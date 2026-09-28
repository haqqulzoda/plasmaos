"""Fail-closed private upload validation, opaque storage, and ClamAV scanning."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import socket
import struct
import tempfile
import unicodedata
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

import pymupdf
from fastapi import UploadFile

from app.core.config import settings


MAX_PRIVATE_FILE_BYTES = 25 * 1024 * 1024
MAX_PRIVATE_PACK_BYTES = 150 * 1024 * 1024
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCX_ENTRY_BYTES = 25 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_PRIVATE_MEDIA_TYPES = {".pdf": PDF_MEDIA_TYPE, ".docx": DOCX_MEDIA_TYPE}


class PrivateUploadError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int = 422):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class MalwareScanError(RuntimeError):
    pass


class MalwareDetectedError(MalwareScanError):
    pass


def private_storage_root() -> Path:
    root = Path(settings.PRIVATE_DOCUMENT_STORAGE_ROOT).expanduser().resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def resolve_private_storage_key(storage_key: str) -> Path:
    if not storage_key or storage_key.startswith(("/", "\\")):
        raise PrivateUploadError("PRIVATE_STORAGE_KEY_INVALID", "Stored document is unavailable", 404)
    key = PurePosixPath(storage_key)
    if any(part in {"", ".", ".."} for part in key.parts):
        raise PrivateUploadError("PRIVATE_STORAGE_KEY_INVALID", "Stored document is unavailable", 404)
    root = private_storage_root()
    path = (root / Path(*key.parts)).resolve()
    if root != path and root not in path.parents:
        raise PrivateUploadError("PRIVATE_STORAGE_KEY_INVALID", "Stored document is unavailable", 404)
    return path


def opaque_storage_key(*, organization_id: UUID, pursuit_id: UUID, version_id: UUID) -> str:
    # UUID directories contain no customer filename or source text.
    return f"objects/{organization_id.hex}/{pursuit_id.hex}/{version_id.hex}.bin"


def safe_display_filename(filename: str | None, suffix: str) -> str:
    raw = unicodedata.normalize("NFKC", Path(filename or f"document{suffix}").name)
    raw = "".join(ch for ch in raw if ch.isprintable() and ch not in "/\\\x00")
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    if not raw:
        raw = f"document{suffix}"
    if not raw.casefold().endswith(suffix):
        raw = f"{raw}{suffix}"
    stem = raw[: 255 - len(suffix)].removesuffix(suffix).strip(" .") or "document"
    return f"{stem}{suffix}"


def _reject_html_polyglot(prefix: bytes) -> None:
    lowered = prefix[:8192].lower().lstrip()
    if any(marker in lowered for marker in (b"<!doctype html", b"<html", b"<script", b"javascript:")):
        raise PrivateUploadError(
            "PRIVATE_DOCUMENT_POLYGLOT", "HTML or active content is not accepted"
        )


def _validate_pdf(path: Path) -> None:
    prefix = path.read_bytes()[:8192]
    _reject_html_polyglot(prefix)
    if not prefix.startswith(b"%PDF-"):
        raise PrivateUploadError("PRIVATE_DOCUMENT_SIGNATURE", "File signature does not match PDF")
    try:
        with pymupdf.open(path) as document:
            if document.is_encrypted or document.needs_pass:
                raise PrivateUploadError(
                    "PRIVATE_DOCUMENT_ENCRYPTED",
                    "Remove the PDF password or encryption and upload it again",
                )
            if len(document) < 1:
                raise PrivateUploadError("PRIVATE_DOCUMENT_EMPTY", "PDF contains no pages")
    except PrivateUploadError:
        raise
    except Exception:
        raise PrivateUploadError("PRIVATE_DOCUMENT_INVALID", "PDF could not be opened safely") from None


def _validate_docx(path: Path) -> None:
    with path.open("rb") as stream:
        prefix = stream.read(8192)
    _reject_html_polyglot(prefix)
    if not prefix.startswith(b"PK\x03\x04"):
        raise PrivateUploadError("PRIVATE_DOCUMENT_SIGNATURE", "File signature does not match DOCX")
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = {item.filename for item in entries}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise PrivateUploadError("PRIVATE_DOCUMENT_SIGNATURE", "File is not a valid DOCX document")
            if len(entries) > MAX_DOCX_ENTRIES:
                raise PrivateUploadError("PRIVATE_DOCUMENT_DOCX_BOMB", "DOCX contains too many entries")
            total = 0
            for item in entries:
                normalized = PurePosixPath(item.filename)
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise PrivateUploadError("PRIVATE_DOCUMENT_DOCX_PATH", "DOCX contains an unsafe entry")
                lowered = item.filename.casefold()
                if (
                    "vbaproject" in lowered
                    or "/activex/" in lowered
                    or "/embeddings/" in lowered
                    or lowered.endswith((".bin", ".exe", ".dll", ".js", ".html", ".htm"))
                ):
                    raise PrivateUploadError("PRIVATE_DOCUMENT_ACTIVE_CONTENT", "DOCX active content is not accepted")
                total += item.file_size
                if item.file_size > MAX_DOCX_ENTRY_BYTES or total > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise PrivateUploadError("PRIVATE_DOCUMENT_DOCX_BOMB", "DOCX expands beyond the safety limit")
                if item.compress_size == 0 and item.file_size:
                    raise PrivateUploadError("PRIVATE_DOCUMENT_DOCX_BOMB", "DOCX entry has an unsafe compression ratio")
                if item.compress_size and item.file_size / item.compress_size > MAX_DOCX_COMPRESSION_RATIO:
                    raise PrivateUploadError("PRIVATE_DOCUMENT_DOCX_BOMB", "DOCX entry has an unsafe compression ratio")
    except PrivateUploadError:
        raise
    except BadZipFile:
        raise PrivateUploadError("PRIVATE_DOCUMENT_INVALID", "DOCX could not be opened safely") from None


async def stage_private_upload(upload: UploadFile, directory: Path) -> tuple[Path, str, str, int, str]:
    original = upload.filename or ""
    suffix = Path(original).suffix.casefold()
    expected_media = ALLOWED_PRIVATE_MEDIA_TYPES.get(suffix)
    if expected_media is None:
        raise PrivateUploadError("PRIVATE_DOCUMENT_TYPE", "Only PDF and DOCX files are accepted", 415)
    declared_media = (upload.content_type or "").split(";", 1)[0].strip().casefold()
    if declared_media != expected_media:
        raise PrivateUploadError(
            "PRIVATE_DOCUMENT_MIME", "Declared media type does not match the file extension", 415
        )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    target: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix="incoming-", suffix=".bin", delete=False) as stream:
            target = Path(stream.name)
            while chunk := await upload.read(64 * 1024):
                size += len(chunk)
                if size > MAX_PRIVATE_FILE_BYTES:
                    raise PrivateUploadError(
                        "PRIVATE_DOCUMENT_TOO_LARGE", "Each file must be 25 MiB or smaller", 413
                    )
                digest.update(chunk)
                stream.write(chunk)
        if size == 0:
            raise PrivateUploadError("PRIVATE_DOCUMENT_EMPTY", "Empty files are not accepted")
        if suffix == ".pdf":
            _validate_pdf(target)
        else:
            _validate_docx(target)
        return target, original[:255], safe_display_filename(original, suffix), size, digest.hexdigest()
    except Exception:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def commit_staged_file(staged_path: Path, storage_key: str) -> Path:
    target = resolve_private_storage_key(storage_key)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        raise PrivateUploadError("PRIVATE_STORAGE_CONFLICT", "Stored document identity already exists", 409)
    os.replace(staged_path, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def scan_with_clamav(path: Path) -> str:
    """Scan one bounded file with ClamAV INSTREAM; unavailable is a hard failure."""
    timeout = max(1, min(settings.PRIVATE_DOCUMENT_SCAN_TIMEOUT_SECONDS, 120))
    try:
        with socket.create_connection(
            (settings.PRIVATE_DOCUMENT_SCAN_HOST, settings.PRIVATE_DOCUMENT_SCAN_PORT),
            timeout=timeout,
        ) as connection:
            connection.settimeout(timeout)
            connection.sendall(b"zINSTREAM\0")
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    connection.sendall(struct.pack(">I", len(chunk)))
                    connection.sendall(chunk)
            connection.sendall(struct.pack(">I", 0))
            response = connection.recv(4096).decode("utf-8", "replace").strip("\0\r\n ")
    except Exception as exc:
        raise MalwareScanError("Malware scanning is temporarily unavailable") from exc
    if response.endswith(" OK"):
        return response
    if " FOUND" in response:
        raise MalwareDetectedError("The file failed malware screening")
    raise MalwareScanError("Malware scanning returned an invalid response")
