"""
Celery tasks for tender document synchronization and extraction.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import configure_mappers

# Force-load the entire ORM registry into the worker's memory space
import app.models  # This triggers __init__.py to load all models
from app.models.all_models import Tender, TenderDocument

# Lock the relationships (resolves string references like "TenderAnalysis")
configure_mappers()

from app.core.celery_app import celery_app
from app.core.parser import process_tender_document
from app.core.scraper import UzExScraper
from app.db.session import AsyncSessionLocal, engine

logger = logging.getLogger(__name__)

DEFAULT_DOCUMENTS_ROOT = Path(__file__).resolve().parents[3] / "data" / "documents"
DOCUMENTS_ROOT = Path(os.getenv("TENDER_DOCUMENTS_ROOT", str(DEFAULT_DOCUMENTS_ROOT)))


def _extract_file_path(file_url: str) -> str:
    parsed = urlparse(file_url)
    query_path = parse_qs(parsed.query).get("path", [None])[0]
    if query_path:
        return unquote(query_path)
    return file_url


def _normalize_file_path(file_url: str) -> str:
    raw_path = _extract_file_path(file_url).strip()
    if not raw_path:
        return ""

    parsed = urlparse(raw_path)
    if parsed.scheme and parsed.netloc:
        url_path = unquote(parsed.path).strip().lower()
        if url_path in {"/api/common/downloadfile", "/downloadfile"} and parsed.query:
            return ""
        return url_path

    path = parsed.path if parsed.path else raw_path
    return unquote(path).strip().lower()


def _extract_file_name(file_url: str) -> str:
    normalized_path = _normalize_file_path(file_url)
    if not normalized_path:
        return ""
    file_name = normalized_path.rstrip("/").split("/")[-1]
    return file_name if "." in file_name else ""


def _parsed_text_present(doc: TenderDocument) -> bool:
    return bool(doc.parsed_text and doc.parsed_text.strip())


def _stored_file_exists(doc: TenderDocument | None) -> bool:
    if doc is None or not doc.storage_path:
        return False

    try:
        return Path(doc.storage_path).is_file()
    except (OSError, TypeError, ValueError):
        return False


def _sanitize_filename(filename: str) -> str:
    raw_name = Path((filename or "").strip()).name
    if not raw_name:
        return "download.bin"

    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name)
    return sanitized.strip("._") or "download.bin"


def _resolved_file_type(filename: str, file_type: str | None) -> str:
    normalized = (file_type or "").strip().lower().lstrip(".")
    if normalized and normalized != "unknown":
        return normalized

    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix or "unknown"


def _persist_document_bytes(
    *,
    tender_id: UUID,
    filename: str,
    file_bytes: bytes,
) -> tuple[str, int]:
    tender_dir = DOCUMENTS_ROOT / str(tender_id)
    tender_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = _sanitize_filename(filename)
    stored_name = f"{uuid4().hex}_{safe_filename}"
    final_path = tender_dir / stored_name
    temp_path = tender_dir / f".{stored_name}.part"

    try:
        temp_path.write_bytes(file_bytes)
        file_size = temp_path.stat().st_size
        if file_size != len(file_bytes):
            raise OSError(
                f"Persisted size mismatch for '{safe_filename}': "
                f"expected {len(file_bytes)} bytes, wrote {file_size} bytes"
            )
        temp_path.replace(final_path)
        return str(final_path), file_size
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.warning("Failed to remove temporary tender document file: %s", temp_path)


def _document_display_name(doc: TenderDocument | None, fallback: str | None = None) -> str:
    if fallback and fallback.strip():
        return _sanitize_filename(fallback)

    if doc is not None and doc.storage_path:
        stored_name = Path(doc.storage_path).name
        prefix, _, remainder = stored_name.partition("_")
        if len(prefix) == 32 and remainder:
            return remainder
        if stored_name:
            return stored_name

    if doc is not None:
        extracted_name = _extract_file_name(doc.file_url)
        if extracted_name:
            return extracted_name
        if doc.file_type:
            return f"document.{doc.file_type}"

    return "document.bin"


def _compiled_text_chunk(doc: TenderDocument, filename: str | None = None) -> str:
    parsed_text = (doc.parsed_text or "").strip()
    if not parsed_text:
        return ""

    return f"[{_document_display_name(doc, filename)}]\n{parsed_text}"


def _document_identity_key(file_url: str) -> str:
    path_key = _normalize_file_path(file_url)
    if path_key:
        return f"path:{path_key}"

    name_key = _extract_file_name(file_url)
    if name_key:
        return f"name:{name_key}"

    return f"url:{file_url.strip().lower()}"


def _register_existing_doc(
    doc: TenderDocument,
    existing_by_url: dict[str, TenderDocument],
    existing_by_path: dict[str, TenderDocument],
    existing_by_name: dict[str, TenderDocument],
) -> None:
    url_key = (doc.file_url or "").strip()
    path_key = _normalize_file_path(url_key)
    name_key = _extract_file_name(url_key)

    if url_key and url_key not in existing_by_url:
        existing_by_url[url_key] = doc

    if path_key:
        current = existing_by_path.get(path_key)
        if current is None or (not _parsed_text_present(current) and _parsed_text_present(doc)):
            existing_by_path[path_key] = doc

    if name_key:
        current = existing_by_name.get(name_key)
        if current is None or (not _parsed_text_present(current) and _parsed_text_present(doc)):
            existing_by_name[name_key] = doc


async def _process_tender_docs_async(tender_uuid: UUID) -> dict[str, int | str]:
    try:
        async with AsyncSessionLocal() as db:
            try:
                tender_result = await db.execute(select(Tender).where(Tender.id == tender_uuid))
                tender = tender_result.scalar_one_or_none()
                if tender is None:
                    raise ValueError("Tender not found")

                scraper = UzExScraper(headless=True, timeout=30000)
                scraped_docs = await scraper.scrape_tender_documents(tender.source_url)

                existing_result = await db.execute(
                    select(TenderDocument).where(TenderDocument.tender_id == tender_uuid)
                )
                existing_docs = existing_result.scalars().all()

                existing_by_url: dict[str, TenderDocument] = {}
                existing_by_path: dict[str, TenderDocument] = {}
                existing_by_name: dict[str, TenderDocument] = {}

                for existing_doc in existing_docs:
                    _register_existing_doc(
                        existing_doc,
                        existing_by_url,
                        existing_by_path,
                        existing_by_name,
                    )

                new_count = 0
                parsed_count = 0
                parsed_text_by_identity: dict[str, str] = {}
                docs_to_process: list[tuple[TenderDocument | None, str, str, str]] = []

                for doc in existing_docs:
                    if _parsed_text_present(doc):
                        parsed_text_by_identity.setdefault(
                            _document_identity_key(doc.file_url),
                            _compiled_text_chunk(doc),
                        )

                for doc_data in scraped_docs:
                    scraped_url = (doc_data.get("file_url") or "").strip()
                    scraped_file_type = (doc_data.get("file_type") or "").strip().lower()
                    if not scraped_url:
                        logger.warning("Skipping scraped doc with empty file_url for tender %s", tender_uuid)
                        continue

                    path_key = _normalize_file_path(scraped_url)
                    name_key = _extract_file_name(scraped_url)

                    doc = (
                        existing_by_url.get(scraped_url)
                        or (existing_by_path.get(path_key) if path_key else None)
                        or (existing_by_name.get(name_key) if name_key else None)
                    )

                    if doc and doc.file_url != scraped_url:
                        doc.file_url = scraped_url

                    if doc and scraped_file_type and doc.file_type != scraped_file_type:
                        doc.file_type = scraped_file_type

                    if doc and _parsed_text_present(doc) and _stored_file_exists(doc):
                        parsed_text_by_identity.setdefault(
                            _document_identity_key(scraped_url),
                            _compiled_text_chunk(doc),
                        )
                        continue

                    file_path = _extract_file_path(scraped_url)
                    if not _stored_file_exists(doc) and not file_path:
                        logger.warning(
                            "Skipping scraped doc with invalid remote path for tender %s: %s",
                            tender_uuid,
                            scraped_url,
                        )
                        continue

                    docs_to_process.append((doc, scraped_url, file_path, scraped_file_type))

                for index, (doc, scraped_url, file_path, scraped_file_type) in enumerate(docs_to_process):
                    if index > 0:
                        delay_seconds = random.uniform(2.0, 5.0)
                        logger.info(
                            "Applying %.2fs download jitter for tender %s before '%s'",
                            delay_seconds,
                            tender_uuid,
                            scraped_url,
                        )
                        await asyncio.sleep(delay_seconds)

                    try:
                        if doc is not None and _stored_file_exists(doc):
                            local_path = Path(doc.storage_path)
                            display_name = _document_display_name(doc)
                            if not _parsed_text_present(doc):
                                extracted_text = await process_tender_document(
                                    source=local_path,
                                    filename=display_name,
                                )
                                if extracted_text.strip():
                                    doc.parsed_text = extracted_text.strip()
                                    parsed_count += 1

                            if _parsed_text_present(doc):
                                parsed_text_by_identity[_document_identity_key(scraped_url)] = (
                                    _compiled_text_chunk(doc, display_name)
                                )
                            continue

                        file_bytes, downloaded_name = await scraper.download_file(
                            tender_url=tender.source_url,
                            file_path=file_path,
                        )
                        resolved_name = downloaded_name or _extract_file_name(scraped_url) or "download"
                        storage_path, file_size = await asyncio.to_thread(
                            _persist_document_bytes,
                            tender_id=tender_uuid,
                            filename=resolved_name,
                            file_bytes=file_bytes,
                        )

                        if doc is None:
                            doc = TenderDocument(
                                id=uuid4(),
                                tender_id=tender_uuid,
                                file_url=scraped_url,
                                file_type=_resolved_file_type(resolved_name, scraped_file_type),
                                storage_path=storage_path,
                                file_size=file_size,
                            )
                            db.add(doc)
                            new_count += 1
                        else:
                            doc.file_url = scraped_url
                            doc.file_type = _resolved_file_type(resolved_name, scraped_file_type)
                            doc.storage_path = storage_path
                            doc.file_size = file_size

                        _register_existing_doc(
                            doc,
                            existing_by_url,
                            existing_by_path,
                            existing_by_name,
                        )

                        if not _parsed_text_present(doc):
                            extracted_text = await process_tender_document(
                                source=Path(storage_path),
                                filename=resolved_name,
                            )
                            if extracted_text.strip():
                                doc.parsed_text = extracted_text.strip()
                                parsed_count += 1

                        if _parsed_text_present(doc):
                            parsed_text_by_identity[_document_identity_key(scraped_url)] = (
                                _compiled_text_chunk(doc, resolved_name)
                            )
                    except Exception as parse_exc:
                        logger.warning(
                            "Failed to persist/parse tender document '%s' for tender %s: %s",
                            scraped_url,
                            tender_uuid,
                            parse_exc,
                        )

                compiled_chunks = [text for text in parsed_text_by_identity.values() if text.strip()]
                tender.compiled_master_text = (
                    "\n\n".join(compiled_chunks).strip() if compiled_chunks else None
                )

                await db.commit()

                all_docs_result = await db.execute(
                    select(TenderDocument).where(TenderDocument.tender_id == tender_uuid)
                )
                all_docs = all_docs_result.scalars().all()

                return {
                    "status": "success",
                    "tender_id": str(tender_uuid),
                    "new_count": new_count,
                    "parsed_count": parsed_count,
                    "total_count": len(all_docs),
                    "message": (
                        f"Synced {new_count} new documents, parsed {parsed_count} documents, "
                        f"{len(all_docs)} total"
                    ),
                }
            except Exception:
                await db.rollback()
                raise
    finally:
        await engine.dispose()


@celery_app.task(bind=True)
def process_tender_docs(self, tender_id: str) -> dict[str, int | str]:
    try:
        tender_uuid = UUID(tender_id)
    except ValueError as exc:
        raise ValueError(f"Invalid tender id: {tender_id}") from exc

    logger.info("Starting tender document sync task for tender %s", tender_id)
    return asyncio.run(_process_tender_docs_async(tender_uuid))
