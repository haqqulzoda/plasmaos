"""Bounded, tenant-scoped Proposal PDF intake. No provider calls here."""
import asyncio
import json
import os
import signal
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from redis.asyncio import Redis

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_PDF_BYTES + 1024 * 1024


@asynccontextmanager
async def upload_permit(user_id):
    """Four shared processing slots and one accepted attempt per user/30 seconds."""
    client = Redis.from_url(os.environ.get("AUTH_REPLAY_REDIS_URL", "redis://127.0.0.1:6379/0"),
                             socket_connect_timeout=2, socket_timeout=2)
    owner = str(uuid4())
    slot = None
    try:
        try:
            if not await client.set(f"upload:rate:{user_id}", "1", nx=True, ex=30):
                raise HTTPException(429, detail="Please wait before uploading again")
            for index in range(4):
                key = f"upload:slot:{index}"
                if await client.set(key, owner, nx=True, ex=240):
                    slot = key
                    break
            if slot is None:
                raise HTTPException(429, detail="Upload processing is busy. Please retry")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, detail="Upload processing temporarily unavailable") from None
        yield
    finally:
        if slot:
            try:
                await client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, slot, owner)
            except Exception:
                pass  # Lease expires; do not mask the safe original error.
        await client.aclose()


@asynccontextmanager
async def staged_pdf(file: UploadFile, directory: Path):
    path = None
    try:
        if not file.filename or not file.filename.casefold().endswith(".pdf"):
            raise HTTPException(415, detail="Only PDF files are accepted")
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix="upload-", suffix=".pdf", delete=False) as output:
            path = Path(output.name)
            size = 0
            prefix = b""
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise HTTPException(413, detail="PDF exceeds the 20 MiB limit")
                if not prefix:
                    prefix = chunk[:8]
                output.write(chunk)
        if not prefix.startswith(b"%PDF-"):
            raise HTTPException(415, detail="The file is not a PDF")
        yield path
    finally:
        if path:
            path.unlink(missing_ok=True)
        await file.close()


async def parse_uploaded_pdf(path: Path) -> str:
    """Isolate parser work from the event loop; kill timed-out parsing/OCR children."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.core.upload_parser", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
        if process.returncode or not output.strip():
            raise HTTPException(422, detail="PDF could not be parsed")
        return output.decode("utf-8")
    except TimeoutError:
        raise HTTPException(422, detail="PDF parsing time limit exceeded") from None
    finally:
        if process.returncode is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()


async def analyze_uploaded_pdf(path: Path, company_context: dict) -> dict:
    """Bound provider SDK threads by process lifetime as well as the shared lease."""
    payload = json.dumps(company_context).encode()
    if len(payload) > 64 * 1024:
        raise HTTPException(422, detail="Company context exceeds the processing limit")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.core.upload_model", str(path),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name == "posix",
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(payload), timeout=120)
        if process.returncode:
            raise ValueError("Model failed")
        result = json.loads(output)
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Model failed")
        return result
    except Exception:
        raise HTTPException(502, detail="PDF analysis failed. Please retry") from None
    finally:
        if process.returncode is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()
