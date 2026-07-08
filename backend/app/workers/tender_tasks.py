"""
Celery tasks for tender document synchronization and extraction.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import configure_mappers

# Force-load the entire ORM registry into the worker's memory space
import app.models  # This triggers __init__.py to load all models
from app.models.all_models import Tender, TenderDocument, TenderSyncJob, TenderSyncStatus

# Lock the relationships (resolves string references like "TenderAnalysis")
configure_mappers()

from app.core.celery_app import celery_app
from app.core.parser import process_tender_document
from app.core.reproducibility import stable_document_order_key
from app.core.scraper import UzExScraper
from app.core.storage_paths import normalize_storage_path, storage_file_exists
from app.db.session import AsyncSessionLocal, engine
from app.services.tender_sources.base import CanonicalDocument, assert_source_scope
from app.services.giz_document_hydration import hydrate_giz_tender_documents
from app.services.tender_sources.uzex import UzExTenderSource

logger = logging.getLogger(__name__)

DEFAULT_DOCUMENTS_ROOT = Path(__file__).resolve().parents[3] / "data" / "documents"
DOCUMENTS_ROOT = Path(os.getenv("TENDER_DOCUMENTS_ROOT", str(DEFAULT_DOCUMENTS_ROOT)))
MAX_ERROR_MESSAGE_LENGTH = 2000
TRACE_FILE_MARKER_RE = re.compile(r"\[\[FILE:\s*(.+?)\]\]")
TRACE_PAGE_MARKER_RE = re.compile(r"\[\[PAGE\s+(\d+)\]\]")


def _env_float(
    name: str,
    default: float,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        value = float(raw_value)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw_value, default)
        return default

    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


DOWNLOAD_JITTER_MIN_SECONDS = _env_float(
    "TENDER_DOC_DOWNLOAD_JITTER_MIN_SECONDS",
    0.0,
    min_value=0.0,
    max_value=30.0,
)
DOWNLOAD_JITTER_MAX_SECONDS = _env_float(
    "TENDER_DOC_DOWNLOAD_JITTER_MAX_SECONDS",
    0.0,
    min_value=0.0,
    max_value=30.0,
)


def _download_jitter_seconds() -> float:
    if DOWNLOAD_JITTER_MAX_SECONDS <= 0:
        return 0.0

    lower_bound = min(DOWNLOAD_JITTER_MIN_SECONDS, DOWNLOAD_JITTER_MAX_SECONDS)
    upper_bound = max(DOWNLOAD_JITTER_MIN_SECONDS, DOWNLOAD_JITTER_MAX_SECONDS)
    if upper_bound <= lower_bound:
        return upper_bound
    return random.uniform(lower_bound, upper_bound)


def _log_sync_event(level: int, event: str, **fields) -> None:
    safe_fields = {}
    for key, value in fields.items():
        if value is None:
            continue
        safe_fields[key] = str(value)[:500]
    logger.log(level, "tender_docs.%s %s", event, safe_fields)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256_prefix(path: Path) -> str:
    return _file_sha256(path)[:16]


def _disk_probe(path: Path) -> dict[str, int]:
    probe_path = path if path.exists() else path.parent
    usage = shutil.disk_usage(probe_path)
    return {"free": usage.free, "total": usage.total}


def _bounded_progress(value: int) -> int:
    return max(0, min(100, value))


def _bounded_error_message(message: str | None) -> str | None:
    if message is None:
        return None
    normalized = message.strip()
    if not normalized:
        return None
    return normalized[:MAX_ERROR_MESSAGE_LENGTH]


async def _set_sync_job_state(
    db: AsyncSession,
    *,
    job_id: str | None,
    status: TenderSyncStatus | None = None,
    progress: int | None = None,
    error_message: str | None = None,
) -> None:
    if not job_id:
        return

    result = await db.execute(select(TenderSyncJob).where(TenderSyncJob.job_id == job_id))
    sync_job = result.scalar_one_or_none()
    if sync_job is None:
        return

    if status is not None:
        sync_job.status = status

    if progress is not None:
        sync_job.progress = _bounded_progress(progress)

    if error_message is not None:
        sync_job.error_message = _bounded_error_message(error_message)
    elif status is not None and status != TenderSyncStatus.FAILED:
        sync_job.error_message = None


async def _mark_sync_job_failed(
    *,
    job_id: str | None,
    error_message: str,
) -> None:
    if not job_id:
        return

    await _persist_sync_job_state(
        job_id=job_id,
        status=TenderSyncStatus.FAILED,
        progress=100,
        error_message=error_message,
    )


async def _persist_sync_job_state(
    *,
    job_id: str | None,
    status: TenderSyncStatus | None = None,
    progress: int | None = None,
    error_message: str | None = None,
) -> None:
    if not job_id:
        return

    async with AsyncSessionLocal() as sync_db:
        try:
            await _set_sync_job_state(
                sync_db,
                job_id=job_id,
                status=status,
                progress=progress,
                error_message=error_message,
            )
            await sync_db.commit()
        except Exception:
            await sync_db.rollback()
            logger.exception("Failed to persist sync state for job %s", job_id)


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


def _has_real_trace_markers(text: str | None) -> bool:
    normalized = (text or "").strip()
    return bool(
        TRACE_FILE_MARKER_RE.search(normalized)
        and TRACE_PAGE_MARKER_RE.search(normalized)
    )


def _parsed_text_markerless(doc: TenderDocument) -> bool:
    return _parsed_text_present(doc) and not _has_real_trace_markers(doc.parsed_text)


def _marker_counts(text: str | None) -> dict[str, int]:
    normalized = text or ""
    return {
        "length": len(normalized),
        "file_marker_count": normalized.count("[[FILE:"),
        "page_marker_count": normalized.count("[[PAGE"),
    }


def _stored_file_exists(doc: TenderDocument | None) -> bool:
    return bool(doc is not None and storage_file_exists(doc.storage_path))


def _canonical_document_from_scraped(
    doc_data: dict[str, object],
    *,
    source_system: str = "uzex",
) -> CanonicalDocument:
    if source_system != "uzex":
        raise ValueError("UzEx worker only accepts UzEx scraped documents")
    return UzExTenderSource().canonical_document_from_scraped(dict(doc_data))


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


def _reserve_document_download_path(*, tender_id: UUID, filename: str) -> tuple[str, str]:
    tender_dir = DOCUMENTS_ROOT / str(tender_id)
    tender_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = _sanitize_filename(filename)
    stored_name = f"{uuid4().hex}_{safe_filename}"
    final_path = tender_dir / stored_name
    temp_path = tender_dir / f".{stored_name}.part"
    return str(temp_path), str(final_path)


def _finalize_document_download(*, temp_path: str, final_path: str) -> tuple[str, int, str]:
    temp = Path(temp_path)
    final = Path(final_path)
    if not temp.is_file():
        raise OSError(f"Temporary tender document file was not created: {temp}")

    file_size = temp.stat().st_size
    if file_size <= 0:
        raise OSError(f"Downloaded tender document is empty: {temp}")

    sha256_digest = _file_sha256(temp)
    temp.replace(final)
    return str(final), file_size, sha256_digest


def _cleanup_temp_download(temp_path: str) -> None:
    temp = Path(temp_path)
    if temp.exists():
        try:
            temp.unlink()
        except OSError:
            logger.warning("Failed to remove temporary tender document file: %s", temp)


def _document_download_failure_message(
    *,
    scraped_index: int,
    scraped_url: str,
    error: object,
) -> str:
    raw_message = str(error).strip() or type(error).__name__
    return _bounded_error_message(
        f"attachment_index={scraped_index}; url={scraped_url}; error={raw_message}"
    ) or f"attachment_index={scraped_index}; download failed"


def _mark_document_download_failed(
    db: AsyncSession,
    *,
    doc: TenderDocument | None,
    tender_id: UUID,
    scraped_url: str,
    scraped_file_type: str | None,
    scraped_index: int,
    error: object,
) -> tuple[TenderDocument, bool]:
    failure_message = _document_download_failure_message(
        scraped_index=scraped_index,
        scraped_url=scraped_url,
        error=error,
    )
    display_name = _extract_file_name(scraped_url) or "download"
    resolved_file_type = _resolved_file_type(display_name, scraped_file_type)
    created = doc is None

    if doc is None:
        doc = TenderDocument(
            id=uuid4(),
            tender_id=tender_id,
            file_url=scraped_url,
            file_type=resolved_file_type,
        )
        db.add(doc)

    doc.file_url = scraped_url
    doc.file_type = resolved_file_type
    doc.source_document_url = scraped_url
    doc.source_document_type = scraped_file_type or None
    doc.download_status = "failed"
    doc.download_error = failure_message
    doc.storage_path = None
    doc.file_size = None
    doc.mime_type = None
    doc.sha256 = None
    return doc, created


def _document_display_name(doc: TenderDocument | None, fallback: str | None = None) -> str:
    if fallback and fallback.strip():
        return _sanitize_filename(fallback)

    if doc is not None and doc.storage_path:
        resolved_path = normalize_storage_path(doc.storage_path)
        stored_name = resolved_path.name if resolved_path is not None else ""
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

    display_name = _document_display_name(doc, filename)
    # Do not synthesize parser trace markers here. Source verification must be
    # based on markers emitted by the parser/reparse path, not legacy headings.
    return f"[{display_name}]\n{parsed_text}"


def _compiled_text_sort_key(
    doc: TenderDocument,
    filename: str | None = None,
) -> tuple[str, str, int, str, str, str]:
    return stable_document_order_key(
        source_filename=_document_display_name(doc, filename),
        file_type=doc.file_type,
        file_size=doc.file_size,
        parsed_text=doc.parsed_text,
        created_at=getattr(doc, "created_at", None),
        document_id=doc.id,
    )


def _compiled_text_entry(
    doc: TenderDocument,
    filename: str | None = None,
) -> tuple[tuple[str, str, int, str, str, str], str] | None:
    chunk = _compiled_text_chunk(doc, filename)
    if not chunk.strip():
        return None
    return (_compiled_text_sort_key(doc, filename), chunk)


def _store_compiled_text_entry(
    entries_by_identity: dict[
        str,
        tuple[tuple[str, str, int, str, str, str], str],
    ],
    identity: str,
    doc: TenderDocument,
    filename: str | None = None,
    *,
    replace: bool = False,
) -> None:
    entry = _compiled_text_entry(doc, filename)
    if entry is None:
        return
    if replace or identity not in entries_by_identity:
        entries_by_identity[identity] = entry


def _join_compiled_text_entries(
    entries_by_identity: dict[
        str,
        tuple[tuple[str, str, int, str, str, str], str],
    ],
) -> str | None:
    compiled_chunks = [
        text
        for _, text in sorted(entries_by_identity.values(), key=lambda item: item[0])
        if text.strip()
    ]
    return "\n\n".join(compiled_chunks).strip() if compiled_chunks else None


async def _reparse_markerless_stored_document(
    doc: TenderDocument,
    *,
    tender_uuid: UUID,
    job_id: str | None,
) -> bool:
    if not _parsed_text_markerless(doc) or not _stored_file_exists(doc):
        return False

    display_name = _document_display_name(doc)
    storage_path = normalize_storage_path(doc.storage_path)
    if storage_path is None:
        return False
    _log_sync_event(
        logging.INFO,
        "markerless_reparse_start",
        tender_id=tender_uuid,
        job_id=job_id,
        document_id=doc.id,
        display_name=display_name,
    )

    extracted_text = await process_tender_document(
        source=storage_path,
        filename=display_name,
    )
    normalized = extracted_text.strip()
    if not normalized:
        _log_sync_event(
            logging.WARNING,
            "markerless_reparse_empty",
            tender_id=tender_uuid,
            job_id=job_id,
            document_id=doc.id,
            display_name=display_name,
        )
        return False

    doc.parsed_text = normalized
    counts = _marker_counts(normalized)
    _log_sync_event(
        logging.INFO if _has_real_trace_markers(normalized) else logging.WARNING,
        "markerless_reparse_done",
        tender_id=tender_uuid,
        job_id=job_id,
        document_id=doc.id,
        display_name=display_name,
        parsed_chars=counts["length"],
        parsed_file_markers=counts["file_marker_count"],
        parsed_page_markers=counts["page_marker_count"],
    )
    return True


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


async def _process_tender_docs_async(
    tender_uuid: UUID,
    *,
    job_id: str | None = None,
    reparse_markerless: bool = False,
) -> dict[str, int | str]:
    task_started_at = time.monotonic()
    _log_sync_event(
        logging.INFO,
        "task_start",
        tender_id=tender_uuid,
        job_id=job_id,
        reparse_markerless=reparse_markerless,
    )
    try:
        async with AsyncSessionLocal() as db:
            try:
                tender_result = await db.execute(select(Tender).where(Tender.id == tender_uuid))
                tender = tender_result.scalar_one_or_none()
                if tender is None:
                    raise ValueError("Tender not found")
                assert_source_scope("uzex", tender)
                before_compiled_counts = _marker_counts(tender.compiled_master_text)

                await _persist_sync_job_state(
                    job_id=job_id,
                    status=TenderSyncStatus.IN_PROGRESS,
                    progress=5,
                )

                scraper = UzExScraper(headless=True, timeout=30000)
                scrape_started_at = time.monotonic()
                _log_sync_event(
                    logging.INFO,
                    "scrape_start",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    source_system=tender.source_system,
                    external_id=tender.external_id,
                    canonical_source_key=tender.canonical_source_key,
                )
                scraped_doc_payloads = await scraper.scrape_tender_documents(tender.source_url)
                scraped_docs = [
                    _canonical_document_from_scraped(doc_data, source_system="uzex")
                    for doc_data in scraped_doc_payloads
                ]
                _log_sync_event(
                    logging.INFO,
                    "scrape_done",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    elapsed_ms=int((time.monotonic() - scrape_started_at) * 1000),
                    scraped_count=len(scraped_docs),
                )
                if not scraped_docs:
                    _log_sync_event(
                        logging.ERROR,
                        "scrape_zero_documents",
                        tender_id=tender_uuid,
                        job_id=job_id,
                        source_url=tender.source_url,
                    )
                    failure_message = f"UzEx scrape returned zero documents for tender {tender_uuid}"
                    await _mark_sync_job_failed(
                        job_id=job_id,
                        error_message=failure_message,
                    )
                    raise RuntimeError(failure_message)
                await _persist_sync_job_state(
                    job_id=job_id,
                    status=TenderSyncStatus.IN_PROGRESS,
                    progress=15,
                )

                existing_result = await db.execute(
                    select(TenderDocument).where(TenderDocument.tender_id == tender_uuid)
                )
                existing_docs = existing_result.scalars().all()
                _log_sync_event(
                    logging.INFO,
                    "existing_docs_loaded",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    existing_count=len(existing_docs),
                )

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
                reparsed_markerless_count = 0
                parsed_text_by_identity: dict[
                    str,
                    tuple[tuple[str, str, int, str, str, str], str],
                ] = {}
                docs_to_process: list[tuple[TenderDocument | None, str, str, str, int]] = []
                failed_documents: list[dict[str, int | str]] = []

                if reparse_markerless:
                    for existing_doc in existing_docs:
                        if _parsed_text_markerless(existing_doc) and _stored_file_exists(existing_doc):
                            if await _reparse_markerless_stored_document(
                                existing_doc,
                                tender_uuid=tender_uuid,
                                job_id=job_id,
                            ):
                                parsed_count += 1
                                reparsed_markerless_count += 1

                for doc in existing_docs:
                    if _parsed_text_present(doc):
                        _store_compiled_text_entry(
                            parsed_text_by_identity,
                            _document_identity_key(doc.file_url),
                            doc,
                        )

                for scraped_index, canonical_doc in enumerate(scraped_docs):
                    scraped_url = canonical_doc.source_document_url.strip()
                    scraped_file_type = canonical_doc.file_type.strip().lower()
                    if not scraped_url:
                        _log_sync_event(
                            logging.ERROR,
                            "scraped_doc_empty_url",
                            tender_id=tender_uuid,
                            job_id=job_id,
                            scraped_index=scraped_index,
                            source_system=canonical_doc.normalized_source_system,
                        )
                        raise RuntimeError(
                            f"Scraped document at index {scraped_index} has empty file_url"
                        )

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
                        _store_compiled_text_entry(
                            parsed_text_by_identity,
                            _document_identity_key(scraped_url),
                            doc,
                        )
                        continue

                    file_path = _extract_file_path(scraped_url)
                    if not _stored_file_exists(doc) and not file_path:
                        failure = RuntimeError(
                            f"Scraped document at index {scraped_index} has invalid remote path"
                        )
                        failed_doc, created = _mark_document_download_failed(
                            db,
                            doc=doc,
                            tender_id=tender_uuid,
                            scraped_url=scraped_url,
                            scraped_file_type=scraped_file_type,
                            scraped_index=scraped_index,
                            error=failure,
                        )
                        if created:
                            new_count += 1
                        _register_existing_doc(
                            failed_doc,
                            existing_by_url,
                            existing_by_path,
                            existing_by_name,
                        )
                        failed_documents.append(
                            {
                                "index": scraped_index,
                                "url": scraped_url,
                                "error": failed_doc.download_error or str(failure),
                            }
                        )
                        _log_sync_event(
                            logging.ERROR,
                            "scraped_doc_invalid_remote_path",
                            tender_id=tender_uuid,
                            job_id=job_id,
                            scraped_index=scraped_index,
                            document_id=failed_doc.id,
                        )
                        continue

                    docs_to_process.append((doc, scraped_url, file_path, scraped_file_type, scraped_index))

                if not docs_to_process:
                    await _persist_sync_job_state(
                        job_id=job_id,
                        status=TenderSyncStatus.IN_PROGRESS,
                        progress=85,
                    )

                for index, (doc, scraped_url, file_path, scraped_file_type, button_index) in enumerate(docs_to_process):
                    doc_started_at = time.monotonic()
                    _log_sync_event(
                        logging.INFO,
                        "document_start",
                        tender_id=tender_uuid,
                        job_id=job_id,
                        index=index,
                        button_index=button_index,
                        file_type=scraped_file_type,
                        has_existing_doc=doc is not None,
                        stored_file_exists=_stored_file_exists(doc),
                    )
                    if index > 0:
                        delay_seconds = _download_jitter_seconds()
                        if delay_seconds > 0:
                            logger.info(
                                "Applying %.2fs download jitter for tender %s before '%s'",
                                delay_seconds,
                                tender_uuid,
                                scraped_url,
                            )
                            await asyncio.sleep(delay_seconds)

                    try:
                        if doc is not None and _stored_file_exists(doc):
                            local_path = normalize_storage_path(doc.storage_path)
                            if local_path is None:
                                raise FileNotFoundError("Stored document path is empty")
                            display_name = _document_display_name(doc)
                            _log_sync_event(
                                logging.INFO,
                                "existing_storage_reused",
                                tender_id=tender_uuid,
                                job_id=job_id,
                                document_id=doc.id,
                                file_size=local_path.stat().st_size,
                                sha256_prefix=_file_sha256_prefix(local_path),
                            )
                            if not doc.source_document_url:
                                doc.source_document_url = doc.file_url
                            if not doc.source_document_type:
                                doc.source_document_type = doc.file_type
                            if not doc.download_status:
                                doc.download_status = "downloaded"
                            if not doc.mime_type:
                                doc.mime_type = mimetypes.guess_type(display_name)[0]
                            if not doc.sha256:
                                doc.sha256 = await asyncio.to_thread(
                                    _file_sha256,
                                    local_path,
                                )
                            needs_parse = (
                                not _parsed_text_present(doc)
                                or (reparse_markerless and _parsed_text_markerless(doc))
                            )
                            if needs_parse:
                                extracted_text = await process_tender_document(
                                    source=local_path,
                                    filename=display_name,
                                )
                                if extracted_text.strip():
                                    doc.parsed_text = extracted_text.strip()
                                    parsed_count += 1
                                    if reparse_markerless:
                                        reparsed_markerless_count += 1
                                    _log_sync_event(
                                        logging.INFO,
                                        "parse_done",
                                        tender_id=tender_uuid,
                                        job_id=job_id,
                                        document_id=doc.id,
                                        parsed_chars=len(doc.parsed_text),
                                    )

                            if _parsed_text_present(doc):
                                _store_compiled_text_entry(
                                    parsed_text_by_identity,
                                    _document_identity_key(scraped_url),
                                    doc,
                                    display_name,
                                    replace=True,
                                )
                            continue

                        fallback_name = _extract_file_name(scraped_url) or "download"
                        temp_path, final_path = _reserve_document_download_path(
                            tender_id=tender_uuid,
                            filename=fallback_name,
                        )
                        try:
                            downloaded_name = await scraper.download_file_to_path(
                                tender_url=tender.source_url,
                                file_path=file_path,
                                destination_path=temp_path,
                                button_index=button_index,
                            )
                        except Exception:
                            _cleanup_temp_download(temp_path)
                            raise

                        resolved_name = downloaded_name or fallback_name
                        if _sanitize_filename(resolved_name) != _sanitize_filename(fallback_name):
                            final_path = str(
                                Path(temp_path).parent
                                / f"{uuid4().hex}_{_sanitize_filename(resolved_name)}"
                            )

                        storage_path, file_size, sha256_digest = await asyncio.to_thread(
                            _finalize_document_download,
                            temp_path=temp_path,
                            final_path=final_path,
                        )
                        resolved_file_type = _resolved_file_type(
                            resolved_name,
                            scraped_file_type,
                        )
                        mime_type = mimetypes.guess_type(resolved_name)[0]
                        _log_sync_event(
                            logging.INFO,
                            "download_done",
                            tender_id=tender_uuid,
                            job_id=job_id,
                            bytes=file_size,
                            sha256_prefix=sha256_digest[:16],
                            downloaded_name=downloaded_name,
                            resolved_name=resolved_name,
                            elapsed_ms=int((time.monotonic() - doc_started_at) * 1000),
                        )
                        _log_sync_event(
                            logging.INFO,
                            "storage_done",
                            tender_id=tender_uuid,
                            job_id=job_id,
                            file_size=file_size,
                            exists=Path(storage_path).is_file(),
                            disk=_disk_probe(Path(storage_path)),
                        )

                        if doc is None:
                            doc = TenderDocument(
                                id=uuid4(),
                                tender_id=tender_uuid,
                                file_url=scraped_url,
                                file_type=resolved_file_type,
                                source_document_url=scraped_url,
                                source_document_type=scraped_file_type,
                                download_status="downloaded",
                                download_error=None,
                                storage_path=storage_path,
                                file_size=file_size,
                                mime_type=mime_type,
                                sha256=sha256_digest,
                            )
                            db.add(doc)
                            new_count += 1
                        else:
                            doc.file_url = scraped_url
                            doc.file_type = resolved_file_type
                            doc.source_document_url = scraped_url
                            doc.source_document_type = scraped_file_type
                            doc.download_status = "downloaded"
                            doc.download_error = None
                            doc.storage_path = storage_path
                            doc.file_size = file_size
                            doc.mime_type = mime_type
                            doc.sha256 = sha256_digest

                        _register_existing_doc(
                            doc,
                            existing_by_url,
                            existing_by_path,
                            existing_by_name,
                        )

                        needs_parse = (
                            not _parsed_text_present(doc)
                            or (reparse_markerless and _parsed_text_markerless(doc))
                        )
                        if needs_parse:
                            extracted_text = await process_tender_document(
                                source=Path(storage_path),
                                filename=resolved_name,
                            )
                            if extracted_text.strip():
                                doc.parsed_text = extracted_text.strip()
                                parsed_count += 1
                                if reparse_markerless:
                                    reparsed_markerless_count += 1
                                _log_sync_event(
                                    logging.INFO,
                                    "parse_done",
                                    tender_id=tender_uuid,
                                    job_id=job_id,
                                    document_id=doc.id,
                                    parsed_chars=len(doc.parsed_text),
                                )

                        if _parsed_text_present(doc):
                            _store_compiled_text_entry(
                                parsed_text_by_identity,
                                _document_identity_key(scraped_url),
                                doc,
                                resolved_name,
                                replace=True,
                            )
                    except Exception as doc_exc:
                        failed_doc, created = _mark_document_download_failed(
                            db,
                            doc=doc,
                            tender_id=tender_uuid,
                            scraped_url=scraped_url,
                            scraped_file_type=scraped_file_type,
                            scraped_index=button_index,
                            error=doc_exc,
                        )
                        if created:
                            new_count += 1
                        _register_existing_doc(
                            failed_doc,
                            existing_by_url,
                            existing_by_path,
                            existing_by_name,
                        )
                        failed_documents.append(
                            {
                                "index": button_index,
                                "url": scraped_url,
                                "error": failed_doc.download_error or str(doc_exc),
                            }
                        )
                        _log_sync_event(
                            logging.ERROR,
                            "document_failed",
                            tender_id=tender_uuid,
                            job_id=job_id,
                            index=index,
                            button_index=button_index,
                            document_id=failed_doc.id,
                            error_type=type(doc_exc).__name__,
                            error=doc_exc,
                        )
                        logger.exception(
                            "Tender document sync failed for tender_id=%s job_id=%s index=%s",
                            tender_uuid,
                            job_id,
                            index,
                        )
                        continue
                    finally:
                        if docs_to_process:
                            progress = 20 + int(((index + 1) / len(docs_to_process)) * 70)
                            await _persist_sync_job_state(
                                job_id=job_id,
                                status=TenderSyncStatus.IN_PROGRESS,
                                progress=progress,
                            )

                tender.compiled_master_text = _join_compiled_text_entries(
                    parsed_text_by_identity
                )
                after_compiled_counts = _marker_counts(tender.compiled_master_text)

                await db.flush()
                all_docs_result = await db.execute(
                    select(TenderDocument).where(TenderDocument.tender_id == tender_uuid)
                )
                all_docs = all_docs_result.scalars().all()
                total_count = len(all_docs)
                markerless_document_count = sum(
                    1 for doc in all_docs if _parsed_text_markerless(doc)
                )
                markerized_document_count = sum(
                    1 for doc in all_docs if _has_real_trace_markers(doc.parsed_text)
                )
                failed_document_count = sum(
                    1
                    for doc in all_docs
                    if (doc.download_status or "").strip().casefold() == "failed"
                )
                if total_count == 0:
                    _log_sync_event(
                        logging.ERROR,
                        "zero_persisted_documents",
                        tender_id=tender_uuid,
                        job_id=job_id,
                        scraped_count=len(scraped_docs),
                        docs_to_process_count=len(docs_to_process),
                    )
                    failure_message = (
                        f"Tender document sync persisted zero documents for tender {tender_uuid}"
                    )
                    await _mark_sync_job_failed(
                        job_id=job_id,
                        error_message=failure_message,
                    )
                    raise RuntimeError(failure_message)

                await db.commit()
                _log_sync_event(
                    logging.INFO,
                    "compiled_text_rebuilt",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    before_compiled_length=before_compiled_counts["length"],
                    before_compiled_file_markers=before_compiled_counts["file_marker_count"],
                    before_compiled_page_markers=before_compiled_counts["page_marker_count"],
                    after_compiled_length=after_compiled_counts["length"],
                    after_compiled_file_markers=after_compiled_counts["file_marker_count"],
                    after_compiled_page_markers=after_compiled_counts["page_marker_count"],
                    documents_reparsed=reparsed_markerless_count,
                    documents_markerized=markerized_document_count,
                    documents_still_markerless=markerless_document_count,
                    failed_documents_current_run=len(failed_documents),
                    failed_documents_total=failed_document_count,
                )

                if failed_documents:
                    failure_message = (
                        "Document sync incomplete: "
                        f"{len(failed_documents)} of {len(scraped_docs)} discovered attachment(s) "
                        "failed to download or parse."
                    )
                    _log_sync_event(
                        logging.ERROR,
                        "task_partial_failed",
                        tender_id=tender_uuid,
                        job_id=job_id,
                        new_count=new_count,
                        parsed_count=parsed_count,
                        total_count=total_count,
                        failed_count=len(failed_documents),
                        failed_documents=failed_documents,
                        compiled_file_markers=after_compiled_counts["file_marker_count"],
                        compiled_page_markers=after_compiled_counts["page_marker_count"],
                        elapsed_ms=int((time.monotonic() - task_started_at) * 1000),
                    )
                    await _persist_sync_job_state(
                        job_id=job_id,
                        status=TenderSyncStatus.FAILED,
                        progress=100,
                        error_message=failure_message,
                    )
                    return {
                        "status": (
                            "failed"
                            if len(failed_documents) >= len(scraped_docs) and parsed_count == 0
                            else "partial_failed"
                        ),
                        "tender_id": str(tender_uuid),
                        "new_count": new_count,
                        "parsed_count": parsed_count,
                        "failed_count": len(failed_documents),
                        "reparsed_markerless_count": reparsed_markerless_count,
                        "total_count": total_count,
                        "compiled_file_marker_count": after_compiled_counts["file_marker_count"],
                        "compiled_page_marker_count": after_compiled_counts["page_marker_count"],
                        "documents_still_markerless": markerless_document_count,
                        "message": failure_message,
                    }

                await _persist_sync_job_state(
                    job_id=job_id,
                    status=TenderSyncStatus.SUCCESS,
                    progress=100,
                    error_message=None,
                )

                _log_sync_event(
                    logging.INFO,
                    "task_success",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    new_count=new_count,
                    parsed_count=parsed_count,
                    total_count=total_count,
                    reparsed_markerless_count=reparsed_markerless_count,
                    compiled_file_markers=after_compiled_counts["file_marker_count"],
                    compiled_page_markers=after_compiled_counts["page_marker_count"],
                    documents_still_markerless=markerless_document_count,
                    failed_documents_total=failed_document_count,
                    elapsed_ms=int((time.monotonic() - task_started_at) * 1000),
                )

                return {
                    "status": "success",
                    "tender_id": str(tender_uuid),
                    "new_count": new_count,
                    "parsed_count": parsed_count,
                    "reparsed_markerless_count": reparsed_markerless_count,
                    "total_count": total_count,
                    "failed_count": 0,
                    "compiled_file_marker_count": after_compiled_counts["file_marker_count"],
                    "compiled_page_marker_count": after_compiled_counts["page_marker_count"],
                    "documents_still_markerless": markerless_document_count,
                    "message": (
                        f"Synced {new_count} new documents, parsed {parsed_count} documents, "
                        f"reparsed {reparsed_markerless_count} markerless documents, "
                        f"{total_count} total"
                    ),
                }
            except Exception as exc:
                await db.rollback()
                _log_sync_event(
                    logging.ERROR,
                    "task_failed",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    error_type=type(exc).__name__,
                    error=exc,
                    elapsed_ms=int((time.monotonic() - task_started_at) * 1000),
                )
                await _mark_sync_job_failed(
                    job_id=job_id,
                    error_message=str(exc) or "Tender document sync failed.",
                )
                raise
    finally:
        await engine.dispose()


@celery_app.task(bind=True)
def process_tender_docs(
    self,
    tender_id: str,
    job_id: str | None = None,
    reparse_markerless: bool = False,
) -> dict[str, int | str]:
    try:
        tender_uuid = UUID(tender_id)
    except ValueError as exc:
        raise ValueError(f"Invalid tender id: {tender_id}") from exc

    logger.info(
        "Starting tender document sync task for tender %s (job_id=%s, reparse_markerless=%s)",
        tender_id,
        job_id,
        reparse_markerless,
    )
    return asyncio.run(
        _process_tender_docs_async(
            tender_uuid,
            job_id=job_id,
            reparse_markerless=reparse_markerless,
        )
    )


async def _hydrate_giz_documents_async(
    tender_uuid: UUID,
    *,
    job_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    task_started_at = time.monotonic()
    _log_sync_event(
        logging.INFO,
        "giz_hydration_start",
        tender_id=tender_uuid,
        job_id=job_id,
        force=force,
    )
    try:
        async with AsyncSessionLocal() as db:
            try:
                tender_result = await db.execute(select(Tender).where(Tender.id == tender_uuid))
                tender = tender_result.scalar_one_or_none()
                if tender is None:
                    raise ValueError("Tender not found")
                assert_source_scope("giz", tender)

                await _persist_sync_job_state(
                    job_id=job_id,
                    status=TenderSyncStatus.IN_PROGRESS,
                    progress=5,
                )

                async def record_hydration_progress(progress: int) -> None:
                    await _persist_sync_job_state(
                        job_id=job_id,
                        status=TenderSyncStatus.IN_PROGRESS,
                        progress=progress,
                    )

                result = await hydrate_giz_tender_documents(
                    db,
                    tender=tender,
                    force=force,
                    progress_callback=record_hydration_progress,
                )
                await db.flush()
                await db.commit()

                coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
                coverage_status = str(coverage.get("coverage_status") or result.get("status") or "")
                parsed_count = int(result.get("documents_parsed") or 0)
                failed_count = int(result.get("documents_failed") or 0)
                if coverage_status == "failed" or (parsed_count == 0 and failed_count > 0):
                    job_status = TenderSyncStatus.FAILED
                    result_status = "failed"
                    error_message = "GIZ document hydration completed without parsed documents."
                else:
                    job_status = TenderSyncStatus.SUCCESS
                    result_status = coverage_status or "success"
                    error_message = None

                await _persist_sync_job_state(
                    job_id=job_id,
                    status=job_status,
                    progress=100,
                    error_message=error_message,
                )
                result["status"] = result_status
                result["job_id"] = job_id or ""
                result["elapsed_ms"] = int((time.monotonic() - task_started_at) * 1000)
                _log_sync_event(
                    logging.INFO if job_status == TenderSyncStatus.SUCCESS else logging.ERROR,
                    "giz_hydration_done",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    status=result_status,
                    coverage_status=coverage_status,
                    documents_downloaded=result.get("documents_downloaded"),
                    documents_parsed=parsed_count,
                    documents_failed=failed_count,
                    compiled_chars=result.get("compiled_master_text_length"),
                    compiled_file_markers=result.get("compiled_file_marker_count"),
                    compiled_page_markers=result.get("compiled_page_marker_count"),
                    elapsed_ms=result["elapsed_ms"],
                )
                return result
            except Exception as exc:
                await db.rollback()
                _log_sync_event(
                    logging.ERROR,
                    "giz_hydration_failed",
                    tender_id=tender_uuid,
                    job_id=job_id,
                    error_type=type(exc).__name__,
                    error=exc,
                    elapsed_ms=int((time.monotonic() - task_started_at) * 1000),
                )
                await _mark_sync_job_failed(
                    job_id=job_id,
                    error_message=str(exc) or "GIZ document hydration failed.",
                )
                raise
    finally:
        await engine.dispose()


@celery_app.task(bind=True)
def hydrate_giz_documents(
    self,
    tender_id: str,
    job_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    try:
        tender_uuid = UUID(tender_id)
    except ValueError as exc:
        raise ValueError(f"Invalid tender id: {tender_id}") from exc

    logger.info(
        "Starting GIZ document hydration task for tender %s (job_id=%s, force=%s)",
        tender_id,
        job_id,
        force,
    )
    return asyncio.run(
        _hydrate_giz_documents_async(
            tender_uuid,
            job_id=job_id,
            force=force,
        )
    )
