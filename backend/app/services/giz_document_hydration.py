"""GIZ document hydration, archive extraction, and provenance compilation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable
from urllib.parse import quote, unquote, urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.parser import process_tender_document
from app.core.storage_paths import normalize_storage_path, storage_file_exists
from app.models.all_models import Tender, TenderDocument
from app.services.tender_sources.base import NormalizedTender, assert_source_scope
from app.services.tender_sources.giz import (
    GIZ_USER_AGENT,
    MAX_ARCHIVE_COMPRESSED_BYTES as GIZ_MAX_ARCHIVE_COMPRESSED_BYTES,
    MAX_ARCHIVE_EXTRACTED_BYTES as GIZ_MAX_ARCHIVE_EXTRACTED_BYTES,
    MAX_ARCHIVE_FILE_COUNT as GIZ_MAX_ARCHIVE_FILE_COUNT,
    MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES as GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES,
    MAX_ARCHIVE_NESTING_DEPTH as GIZ_MAX_ARCHIVE_NESTING_DEPTH,
    GizTenderSource,
    _extension_from_url as _giz_extension_from_url,
    _safe_giz_url,
)

logger = logging.getLogger(__name__)

DEFAULT_DOCUMENTS_ROOT = Path(__file__).resolve().parents[3] / "data" / "documents"
DOCUMENTS_ROOT = Path(os.getenv("TENDER_DOCUMENTS_ROOT", str(DEFAULT_DOCUMENTS_ROOT)))

GIZ_PARSEABLE_DOCUMENT_EXTENSIONS = {"pdf", "docx", "txt"}
GIZ_ARCHIVE_DOCUMENT_EXTENSIONS = {"zip"}
GIZ_DANGEROUS_DOCUMENT_EXTENSIONS = {
    "app",
    "bat",
    "bin",
    "cmd",
    "com",
    "cpl",
    "dll",
    "dmg",
    "exe",
    "hta",
    "jar",
    "js",
    "jse",
    "msi",
    "msp",
    "pif",
    "ps1",
    "scr",
    "sh",
    "vbe",
    "vbs",
    "wsf",
}
GIZ_MAX_COMPRESSION_RATIO = 100
_TRACE_FILE_MARKER_RE = re.compile(r"\[\[FILE:\s*([^\]\n]+?)\s*\]\]")

ProgressCallback = Callable[[int], Awaitable[None]]


async def _emit_progress(
    progress_callback: ProgressCallback | None,
    progress: int,
) -> None:
    if progress_callback is not None:
        await progress_callback(progress)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_filename(filename: str) -> str:
    raw_name = Path((filename or "").strip()).name
    if not raw_name:
        return "download.bin"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name)
    return sanitized.strip("._") or "download.bin"


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
            logger.warning("Failed to remove temporary GIZ document file: %s", temp)


def _guess_download_content_type(*, filename: str, file_type: str | None = None) -> str:
    extension = (file_type or Path(filename).suffix.lstrip(".")).lower()
    content_types = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "rtf": "application/rtf",
        "zip": "application/zip",
        "rar": "application/vnd.rar",
        "7z": "application/x-7z-compressed",
        "tar": "application/x-tar",
        "gz": "application/gzip",
        "txt": "text/plain",
    }
    return content_types.get(extension, mimetypes.guess_type(filename)[0] or "application/octet-stream")


def _stored_download_name(storage_path: str) -> str:
    resolved_path = normalize_storage_path(storage_path)
    stored_name = resolved_path.name if resolved_path is not None else ""
    prefix, _, remainder = stored_name.partition("_")
    if len(prefix) == 32 and remainder:
        return remainder
    return stored_name or "document.bin"


def _giz_payload_looks_like_html(file_bytes: bytes) -> bool:
    head = file_bytes[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) or b"<html" in head[:200]


def _giz_archive_limits_payload() -> dict[str, int]:
    return {
        "max_compressed_archive_bytes": GIZ_MAX_ARCHIVE_COMPRESSED_BYTES,
        "max_extracted_bytes": GIZ_MAX_ARCHIVE_EXTRACTED_BYTES,
        "max_file_count": GIZ_MAX_ARCHIVE_FILE_COUNT,
        "max_individual_file_bytes": GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES,
        "max_nesting_depth": GIZ_MAX_ARCHIVE_NESTING_DEPTH,
        "max_compression_ratio": GIZ_MAX_COMPRESSION_RATIO,
    }


def _giz_official_listed_document_count(tender: Tender) -> int:
    metadata = tender.source_metadata_json or {}
    participation_documents = metadata.get("participation_documents")
    if isinstance(participation_documents, list):
        return len(participation_documents)
    attachments = metadata.get("attachments")
    if isinstance(attachments, list):
        return len(attachments)
    return 0


def _giz_inner_source_url(archive_doc: TenderDocument, inner_path: str) -> str:
    base_url = (archive_doc.source_document_url or archive_doc.file_url or "").split("#", 1)[0]
    digest = hashlib.sha256(f"{base_url}|{inner_path}".encode("utf-8")).hexdigest()[:16]
    quoted_path = quote(inner_path, safe="/")
    candidate = f"{base_url}#giz-inner={quoted_path}"
    if len(candidate) <= 1000:
        return candidate
    return f"{base_url}#giz-inner-sha={digest}"


def _giz_file_url_for_source(source_url: str) -> str:
    if len(source_url) <= 500:
        return source_url
    base_url = source_url.split("#", 1)[0]
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
    return f"{base_url[:470]}#giz-inner-sha={digest}"


def _giz_zip_member_name(raw_name: str) -> str | None:
    normalized = raw_name.replace("\\", "/").strip()
    if not normalized or normalized.endswith("/"):
        return None
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return str(path)


def _giz_zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _giz_archive_member_extension(member_name: str) -> str:
    return Path(member_name).suffix.lower().lstrip(".")


def _giz_member_storage_filename(*, archive_name: str, inner_path: str) -> str:
    safe_inner = re.sub(r"[^A-Za-z0-9._-]+", "_", inner_path).strip("._")
    return f"{Path(archive_name).stem}__{safe_inner or Path(inner_path).name}"


def _giz_relabel_parsed_text(parsed_text: str, source_label: str) -> str:
    marker = f"[[FILE: {source_label}]]"
    relabeled = _TRACE_FILE_MARKER_RE.sub(marker, parsed_text)
    if "[[PAGE" not in relabeled:
        relabeled = f"{marker}\n[[PAGE 1]]\n{relabeled.strip()}"
    return relabeled.strip()


async def _giz_upsert_inner_document(
    db: AsyncSession,
    *,
    tender: Tender,
    archive_doc: TenderDocument,
    inner_path: str,
    file_type: str,
    file_size: int | None = None,
) -> TenderDocument:
    assert_source_scope("giz", tender)
    source_url = _giz_inner_source_url(archive_doc, inner_path)
    result = await db.execute(
        select(TenderDocument).where(
            TenderDocument.tender_id == tender.id,
            TenderDocument.source_document_url == source_url,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        doc = TenderDocument(
            tender_id=tender.id,
            file_url=_giz_file_url_for_source(source_url),
            file_type=file_type or "unknown",
            source_document_url=source_url,
            source_document_type=file_type or "unknown",
            external_file_id=hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:32],
            download_status="metadata_only",
            file_size=file_size,
            mime_type=_guess_download_content_type(
                filename=Path(inner_path).name,
                file_type=file_type or None,
            ),
        )
        db.add(doc)
        await db.flush()
    else:
        doc.file_type = file_type or doc.file_type or "unknown"
        doc.source_document_type = file_type or doc.source_document_type
        if file_size is not None:
            doc.file_size = file_size
        if not doc.mime_type:
            doc.mime_type = _guess_download_content_type(
                filename=Path(inner_path).name,
                file_type=file_type or None,
            )
    return doc


async def _giz_find_duplicate_document_by_sha(
    db: AsyncSession,
    *,
    tender: Tender,
    sha256_digest: str,
    excluding_doc_id: UUID,
) -> TenderDocument | None:
    result = await db.execute(
        select(TenderDocument)
        .where(
            TenderDocument.tender_id == tender.id,
            TenderDocument.id != excluding_doc_id,
            TenderDocument.sha256 == sha256_digest,
            TenderDocument.storage_path.is_not(None),
        )
        .order_by(TenderDocument.created_at.asc(), TenderDocument.id.asc())
        .limit(1)
    )
    duplicate = result.scalar_one_or_none()
    if duplicate is not None and storage_file_exists(duplicate.storage_path):
        return duplicate
    return None


def _doc_has_successful_data(doc: TenderDocument) -> bool:
    return bool(
        (doc.parsed_text and doc.parsed_text.strip())
        or storage_file_exists(doc.storage_path)
    )


def _giz_mark_document_failed(
    doc: TenderDocument,
    message: str,
    *,
    preserve_success: bool = True,
) -> None:
    if preserve_success and _doc_has_successful_data(doc):
        doc.download_status = doc.download_status or "downloaded"
        doc.download_error = message[:1000]
        return
    doc.download_status = "failed"
    doc.download_error = message[:1000]


async def _giz_parse_stored_document(
    *,
    doc: TenderDocument,
    source_label: str,
    force: bool = False,
) -> bool:
    previous_error = doc.download_error or ""
    if not force and (doc.download_status or "").casefold() == "failed" and (
        previous_error.startswith("Unsupported GIZ")
        or previous_error.startswith("GIZ document parsed to empty text")
        or previous_error.startswith("GIZ document exceeds the individual")
    ):
        return False
    extension = (doc.file_type or Path(source_label).suffix.lstrip(".")).strip().casefold()
    if extension not in GIZ_PARSEABLE_DOCUMENT_EXTENSIONS:
        _giz_mark_document_failed(
            doc,
            f"Unsupported GIZ document type for parsing: {extension or 'unknown'}.",
            preserve_success=False,
        )
        return False
    local_path = normalize_storage_path(doc.storage_path)
    if local_path is None or not local_path.is_file():
        _giz_mark_document_failed(doc, "GIZ document file is missing from storage.")
        return False
    if local_path.stat().st_size > GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES:
        _giz_mark_document_failed(doc, "GIZ document exceeds the individual file parsing limit.")
        return False
    if not force and doc.parsed_text and doc.parsed_text.strip():
        doc.download_status = "downloaded"
        doc.download_error = None
        return False

    previous_text = doc.parsed_text
    try:
        parsed_text = await process_tender_document(source=local_path, filename=source_label)
    except Exception as exc:
        doc.parsed_text = previous_text
        _giz_mark_document_failed(
            doc,
            f"GIZ document parsing failed: {type(exc).__name__}.",
        )
        return False
    if not parsed_text.strip():
        doc.parsed_text = previous_text
        _giz_mark_document_failed(doc, "GIZ document parsed to empty text.")
        return False

    doc.parsed_text = _giz_relabel_parsed_text(parsed_text, source_label)
    doc.download_status = "downloaded"
    doc.download_error = None
    return True


def _giz_zip_member_rejection_reason(
    info: zipfile.ZipInfo,
    *,
    safe_name: str | None,
    current_depth: int,
) -> str | None:
    if safe_name is None:
        return "Rejected unsafe ZIP member path."
    if _giz_zip_member_is_symlink(info):
        return "Rejected ZIP symlink member."
    extension = _giz_archive_member_extension(safe_name)
    if extension in GIZ_DANGEROUS_DOCUMENT_EXTENSIONS:
        return f"Rejected executable or script member: .{extension}."
    if extension in GIZ_ARCHIVE_DOCUMENT_EXTENSIONS and current_depth >= GIZ_MAX_ARCHIVE_NESTING_DEPTH:
        return "Rejected nested archive beyond the allowed GIZ nesting depth."
    if info.file_size > GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES:
        return "Rejected ZIP member above the GIZ individual file size limit."
    if info.compress_size > 0 and info.file_size / info.compress_size > GIZ_MAX_COMPRESSION_RATIO:
        return "Rejected ZIP member with excessive compression ratio."
    return None


async def _giz_extract_supported_zip_members(
    db: AsyncSession,
    *,
    tender: Tender,
    archive_doc: TenderDocument,
    current_depth: int = 0,
    force: bool = False,
) -> int:
    assert_source_scope("giz", tender)
    parsed_count = 0
    archive_path = normalize_storage_path(archive_doc.storage_path)
    if archive_path is None or not archive_path.is_file():
        _giz_mark_document_failed(archive_doc, "GIZ ZIP archive is missing from storage.")
        return parsed_count
    compressed_size = archive_path.stat().st_size
    if compressed_size > GIZ_MAX_ARCHIVE_COMPRESSED_BYTES:
        _giz_mark_document_failed(archive_doc, "GIZ ZIP archive exceeds the compressed size limit.")
        return parsed_count

    archive_name = Path(archive_doc.source_document_url or archive_doc.file_url or archive_path.name).name
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > GIZ_MAX_ARCHIVE_FILE_COUNT:
                _giz_mark_document_failed(archive_doc, "GIZ ZIP archive exceeds the file count limit.")
                return parsed_count
            total_uncompressed = sum(max(0, info.file_size) for info in infos)
            total_compressed = sum(max(0, info.compress_size) for info in infos)
            if total_uncompressed > GIZ_MAX_ARCHIVE_EXTRACTED_BYTES:
                _giz_mark_document_failed(archive_doc, "GIZ ZIP archive exceeds the extracted size limit.")
                return parsed_count
            if total_compressed > 0 and total_uncompressed / total_compressed > GIZ_MAX_COMPRESSION_RATIO:
                _giz_mark_document_failed(archive_doc, "GIZ ZIP archive has excessive compression ratio.")
                return parsed_count

            for info in infos:
                safe_name = _giz_zip_member_name(info.filename)
                file_type = _giz_archive_member_extension(safe_name or info.filename) or "unknown"
                inner_doc = await _giz_upsert_inner_document(
                    db,
                    tender=tender,
                    archive_doc=archive_doc,
                    inner_path=safe_name or info.filename,
                    file_type=file_type,
                    file_size=max(0, info.file_size),
                )
                rejection_reason = _giz_zip_member_rejection_reason(
                    info,
                    safe_name=safe_name,
                    current_depth=current_depth,
                )
                if rejection_reason:
                    _giz_mark_document_failed(
                        inner_doc,
                        rejection_reason,
                        preserve_success=False,
                    )
                    continue
                if file_type not in GIZ_PARSEABLE_DOCUMENT_EXTENSIONS:
                    _giz_mark_document_failed(
                        inner_doc,
                        f"Unsupported GIZ archive member type for parsing: {file_type}.",
                        preserve_success=False,
                    )
                    continue
                if storage_file_exists(inner_doc.storage_path) and not force:
                    parsed = await _giz_parse_stored_document(
                        doc=inner_doc,
                        source_label=f"{archive_name}!/{safe_name}",
                    )
                    parsed_count += int(parsed)
                    continue

                storage_filename = _giz_member_storage_filename(
                    archive_name=archive_name,
                    inner_path=safe_name,
                )
                temp_path, final_path = _reserve_document_download_path(
                    tender_id=tender.id,
                    filename=storage_filename,
                )
                try:
                    total_written = 0
                    with archive.open(info) as source_handle, Path(temp_path).open("wb") as target_handle:
                        while True:
                            chunk = source_handle.read(1024 * 1024)
                            if not chunk:
                                break
                            total_written += len(chunk)
                            if total_written > GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES:
                                raise ValueError("ZIP member exceeded individual extraction limit")
                            target_handle.write(chunk)
                    storage_path, file_size, sha256_digest = _finalize_document_download(
                        temp_path=temp_path,
                        final_path=final_path,
                    )
                except Exception as exc:
                    _cleanup_temp_download(temp_path)
                    _giz_mark_document_failed(
                        inner_doc,
                        f"GIZ ZIP member extraction failed: {type(exc).__name__}.",
                    )
                    continue

                duplicate = await _giz_find_duplicate_document_by_sha(
                    db,
                    tender=tender,
                    sha256_digest=sha256_digest,
                    excluding_doc_id=inner_doc.id,
                )
                if duplicate is not None:
                    try:
                        Path(storage_path).unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Failed to remove duplicate GIZ extracted file: %s", storage_path)
                    inner_doc.storage_path = duplicate.storage_path
                    inner_doc.file_size = duplicate.file_size
                    inner_doc.mime_type = duplicate.mime_type
                    inner_doc.sha256 = duplicate.sha256
                else:
                    inner_doc.storage_path = storage_path
                    inner_doc.file_size = file_size
                    inner_doc.sha256 = sha256_digest
                    inner_doc.mime_type = _guess_download_content_type(
                        filename=safe_name,
                        file_type=file_type,
                    )
                inner_doc.download_status = "downloaded"
                inner_doc.download_error = None
                parsed = await _giz_parse_stored_document(
                    doc=inner_doc,
                    source_label=f"{archive_name}!/{safe_name}",
                    force=force,
                )
                parsed_count += int(parsed)
    except zipfile.BadZipFile:
        _giz_mark_document_failed(archive_doc, "GIZ ZIP archive is corrupted or unreadable.")
    except Exception as exc:
        _giz_mark_document_failed(
            archive_doc,
            f"GIZ ZIP archive processing failed: {type(exc).__name__}.",
        )
    return parsed_count


async def update_giz_document_coverage(
    db: AsyncSession,
    *,
    tender: Tender,
) -> dict[str, Any]:
    assert_source_scope("giz", tender)
    result = await db.execute(
        select(TenderDocument).where(TenderDocument.tender_id == tender.id)
    )
    docs = result.scalars().all()
    official_count = _giz_official_listed_document_count(tender)
    inner_docs = [
        doc
        for doc in docs
        if "#giz-inner=" in (doc.source_document_url or doc.file_url or "")
        or "#giz-inner-sha=" in (doc.source_document_url or doc.file_url or "")
    ]
    parsed_count = sum(1 for doc in docs if doc.parsed_text and doc.parsed_text.strip())
    unsupported_count = sum(
        1
        for doc in docs
        if "Unsupported GIZ" in (doc.download_error or "")
        or "Rejected executable" in (doc.download_error or "")
        or "Rejected nested archive" in (doc.download_error or "")
    )
    failed_count = sum(
        1
        for doc in docs
        if (doc.download_status or "").casefold() == "failed"
        and "Unsupported GIZ" not in (doc.download_error or "")
    )
    processed_count = parsed_count + unsupported_count + failed_count
    missing_count = max(official_count - processed_count, 0)

    if official_count == 0 and not docs:
        coverage_status = "unavailable"
    elif parsed_count == 0 and (failed_count or unsupported_count or docs):
        coverage_status = "failed"
    elif failed_count or unsupported_count or missing_count:
        coverage_status = "partial"
    else:
        coverage_status = "complete"

    warnings: list[str] = []
    if unsupported_count:
        warnings.append(f"{unsupported_count} GIZ document(s) are unsupported for parsing.")
    if failed_count:
        warnings.append(f"{failed_count} GIZ document(s) failed download, extraction, or parsing.")
    if missing_count:
        warnings.append(f"{missing_count} official GIZ document(s) are not yet parsed.")

    coverage = {
        "coverage_status": coverage_status,
        "official_listed_document_count": official_count,
        "extracted_file_count": len(inner_docs),
        "parsed_file_count": parsed_count,
        "unsupported_file_count": unsupported_count,
        "failed_file_count": failed_count,
        "missing_file_count": missing_count,
        "limits": _giz_archive_limits_payload(),
        "coverage_warnings": warnings,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata = dict(tender.source_metadata_json or {})
    metadata["giz_document_coverage"] = coverage
    tender.source_metadata_json = metadata
    return coverage


def _giz_rejected_payload_content_type(content_type: str | None) -> bool:
    normalized = (content_type or "").split(";", 1)[0].strip().casefold()
    if not normalized:
        return False
    if "html" in normalized:
        return True
    return normalized in {"application/json", "text/json", "text/plain"}


def _giz_valid_file_signature(
    file_bytes: bytes,
    extension: str,
    content_type: str | None,
) -> bool:
    head = file_bytes[:16]
    ext = extension.casefold()
    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if ext == "pdf":
        return file_bytes.lstrip().startswith(b"%PDF") or normalized_type == "application/pdf"
    if ext == "zip":
        return head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if ext in {"docx", "xlsx"}:
        return head.startswith(b"PK\x03\x04")
    if ext in {"doc", "xls"}:
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext == "rtf":
        return file_bytes.lstrip().startswith(b"{\\rtf")
    return normalized_type.startswith("application/")


async def download_giz_document_into_storage(
    *,
    client: httpx.AsyncClient,
    tender: Tender,
    doc: TenderDocument,
    max_bytes: int = GIZ_MAX_ARCHIVE_COMPRESSED_BYTES,
    force: bool = False,
) -> bool:
    assert_source_scope("giz", tender)
    if doc.tender_id != tender.id:
        raise ValueError("GIZ document does not belong to the supplied tender")
    source_url = (doc.source_document_url or doc.file_url or "").strip()
    if "#giz-inner=" in source_url or "#giz-inner-sha=" in source_url:
        return False
    if (doc.download_status or "").strip().casefold() == "access_required":
        return False
    extension = _giz_extension_from_url(source_url)
    if not source_url or not extension or not _safe_giz_url(source_url):
        if not storage_file_exists(doc.storage_path):
            doc.download_status = doc.download_status or "metadata_only"
        return False
    if storage_file_exists(doc.storage_path) and not force:
        doc.download_status = "downloaded"
        doc.download_error = None
        return False

    request_url = source_url.split("#", 1)[0]
    filename = Path(urlparse(request_url).path).name or f"giz-document.{extension}"
    temp_path: str | None = None
    try:
        async with client.stream("GET", request_url) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip()
            content_length = response.headers.get("content-length")
            try:
                declared_length = int(content_length) if content_length else None
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > max_bytes:
                _giz_mark_document_failed(
                    doc,
                    "Public GIZ document exceeds configured download size limit.",
                )
                return False
            if _giz_rejected_payload_content_type(content_type):
                if not _doc_has_successful_data(doc):
                    doc.download_status = "access_required" if "html" in content_type.casefold() else "failed"
                doc.download_error = "Public GIZ document URL returned a page or error payload, not a document file."
                return False

            temp_path, final_path = _reserve_document_download_path(
                tender_id=tender.id,
                filename=filename,
            )
            first_bytes = bytearray()
            total_bytes = 0
            with Path(temp_path).open("wb") as file_handle:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        _cleanup_temp_download(temp_path)
                        _giz_mark_document_failed(
                            doc,
                            "Public GIZ document exceeds configured download size limit.",
                        )
                        return False
                    if len(first_bytes) < 2048:
                        first_bytes.extend(chunk[: 2048 - len(first_bytes)])
                    file_handle.write(chunk)
    except Exception as exc:
        if temp_path:
            _cleanup_temp_download(temp_path)
        _giz_mark_document_failed(
            doc,
            f"GIZ public document download failed: {type(exc).__name__}",
        )
        logger.warning(
            "giz_document_download_failed tender_id=%s doc_id=%s error_type=%s",
            tender.id,
            doc.id,
            type(exc).__name__,
        )
        return False

    file_head = bytes(first_bytes)
    if total_bytes < 32:
        if temp_path:
            _cleanup_temp_download(temp_path)
        _giz_mark_document_failed(doc, "GIZ public document download returned an empty or trivial file.")
        return False
    if _giz_payload_looks_like_html(file_head):
        if temp_path:
            _cleanup_temp_download(temp_path)
        if not _doc_has_successful_data(doc):
            doc.download_status = "access_required"
        doc.download_error = "GIZ public document download returned HTML instead of a document."
        return False
    if not _giz_valid_file_signature(file_head, extension, content_type):
        if temp_path:
            _cleanup_temp_download(temp_path)
        _giz_mark_document_failed(
            doc,
            "GIZ public document download did not match the expected file signature.",
        )
        return False

    storage_path, file_size, sha256_digest = await asyncio.to_thread(
        _finalize_document_download,
        temp_path=temp_path,
        final_path=final_path,
    )
    if not storage_file_exists(storage_path):
        _giz_mark_document_failed(doc, "GIZ public document was written but is not present on disk.")
        return False
    doc.storage_path = storage_path
    doc.file_size = file_size
    doc.mime_type = content_type or doc.mime_type or _guess_download_content_type(
        filename=filename,
        file_type=extension,
    )
    doc.sha256 = sha256_digest
    doc.download_status = "downloaded"
    doc.download_error = None
    return True


async def compile_tender_text_from_documents(
    *,
    db: AsyncSession,
    tender: Tender,
) -> None:
    result = await db.execute(
        select(TenderDocument)
        .where(TenderDocument.tender_id == tender.id)
        .order_by(TenderDocument.source_document_url.asc(), TenderDocument.id.asc())
    )
    docs = result.scalars().all()
    parsed_parts = [doc.parsed_text.strip() for doc in docs if doc.parsed_text and doc.parsed_text.strip()]
    tender.compiled_master_text = "\n\n".join(parsed_parts) if parsed_parts else None


async def process_giz_documents_for_compliance(
    db: AsyncSession,
    *,
    tender: Tender,
    force: bool = False,
) -> dict[str, Any]:
    assert_source_scope("giz", tender)
    result = await db.execute(
        select(TenderDocument)
        .where(TenderDocument.tender_id == tender.id)
        .order_by(TenderDocument.source_document_url.asc(), TenderDocument.id.asc())
    )
    docs = result.scalars().all()
    parsed_count = 0
    for doc in docs:
        source_url = doc.source_document_url or doc.file_url or ""
        if "#giz-inner=" in source_url or "#giz-inner-sha=" in source_url:
            if storage_file_exists(doc.storage_path):
                archive_name = Path(urlparse(source_url.split("#", 1)[0]).path).name
                if "#giz-inner=" in source_url:
                    inner_name = unquote(source_url.split("#giz-inner=", 1)[-1])
                    source_label = f"{archive_name}!/{inner_name}" if archive_name else inner_name
                else:
                    source_label = _stored_download_name(doc.storage_path or "")
                parsed = await _giz_parse_stored_document(
                    doc=doc,
                    source_label=source_label,
                    force=force,
                )
                parsed_count += int(parsed)
            continue
        extension = (doc.file_type or _giz_extension_from_url(source_url) or "").casefold()
        if extension in GIZ_ARCHIVE_DOCUMENT_EXTENSIONS and storage_file_exists(doc.storage_path):
            parsed_count += await _giz_extract_supported_zip_members(
                db,
                tender=tender,
                archive_doc=doc,
                force=force,
            )
        elif storage_file_exists(doc.storage_path):
            display_name = Path(urlparse(source_url).path).name or _stored_download_name(doc.storage_path or "")
            parsed = await _giz_parse_stored_document(
                doc=doc,
                source_label=display_name,
                force=force,
            )
            parsed_count += int(parsed)

    coverage = await update_giz_document_coverage(db, tender=tender)
    await compile_tender_text_from_documents(db=db, tender=tender)
    coverage["parsed_this_run"] = parsed_count
    return coverage


def _normalized_tender_from_giz_row(tender: Tender) -> NormalizedTender:
    assert_source_scope("giz", tender)
    return NormalizedTender(
        source_system="giz",
        external_id=str(tender.external_id),
        source_url=str(tender.source_url),
        title=str(tender.title),
        description=tender.description,
        budget=tender.budget,
        currency=tender.currency,
        country=tender.country,
        region=tender.region,
        sector=tender.sector,
        buyer=tender.buyer,
        procurement_category=tender.procurement_category,
        procurement_method=tender.procurement_method,
        notice_type=tender.notice_type,
        project_id=tender.project_id,
        publication_date=tender.publication_date,
        deadline=tender.deadline,
        status=tender.status,
        category=tender.category,
        source_metadata_json=dict(tender.source_metadata_json or {}),
        scrape_status=tender.scrape_status,
        last_synced_at=tender.last_synced_at,
    )


def _marker_counts(text: str | None) -> dict[str, int]:
    normalized = text or ""
    return {
        "length": len(normalized),
        "file_marker_count": normalized.count("[[FILE:"),
        "page_marker_count": normalized.count("[[PAGE"),
    }


async def hydrate_giz_tender_documents(
    db: AsyncSession,
    *,
    tender: Tender,
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Hydrate one persisted GIZ tender using metadata discovered by the GIZ connector."""
    assert_source_scope("giz", tender)
    before_counts = _marker_counts(tender.compiled_master_text)
    source = GizTenderSource(source_pages=[])
    normalized = _normalized_tender_from_giz_row(tender)
    await _emit_progress(progress_callback, 15)
    documents = await source.discover_documents(normalized)
    upsert_created = 0
    upsert_updated = 0
    if documents:
        upsert_created, upsert_updated = await source.upsert_documents(
            db,
            tender=tender,
            documents=documents,
        )
        await db.flush()

    downloaded_count = 0
    await _emit_progress(progress_callback, 30)
    async with httpx.AsyncClient(
        timeout=source.config.timeout_seconds,
        headers={"User-Agent": GIZ_USER_AGENT},
        follow_redirects=True,
    ) as client:
        docs_result = await db.execute(
            select(TenderDocument)
            .where(TenderDocument.tender_id == tender.id)
            .order_by(TenderDocument.source_document_url.asc(), TenderDocument.id.asc())
        )
        for doc in docs_result.scalars().all():
            downloaded = await download_giz_document_into_storage(
                client=client,
                tender=tender,
                doc=doc,
                max_bytes=GIZ_MAX_ARCHIVE_COMPRESSED_BYTES,
                force=force,
            )
            downloaded_count += int(downloaded)

    await _emit_progress(progress_callback, 60)
    coverage = await process_giz_documents_for_compliance(
        db,
        tender=tender,
        force=force,
    )
    await _emit_progress(progress_callback, 90)
    after_counts = _marker_counts(tender.compiled_master_text)
    docs_result = await db.execute(
        select(TenderDocument).where(TenderDocument.tender_id == tender.id)
    )
    docs = docs_result.scalars().all()
    parsed_documents = sum(1 for doc in docs if doc.parsed_text and doc.parsed_text.strip())
    failed_documents = sum(
        1
        for doc in docs
        if (doc.download_status or "").casefold() == "failed"
    )
    return {
        "status": coverage.get("coverage_status") or "unavailable",
        "source_system": "giz",
        "tender_id": str(tender.id),
        "external_id": tender.external_id,
        "force": force,
        "documents_discovered": len(documents),
        "documents_created": upsert_created,
        "documents_updated": upsert_updated,
        "documents_downloaded": downloaded_count,
        "documents_total": len(docs),
        "documents_parsed": parsed_documents,
        "documents_failed": failed_documents,
        "documents_parsed_this_run": int(coverage.get("parsed_this_run") or 0),
        "coverage": coverage,
        "compiled_master_text_length": after_counts["length"],
        "compiled_file_marker_count": after_counts["file_marker_count"],
        "compiled_page_marker_count": after_counts["page_marker_count"],
        "before_compiled_master_text_length": before_counts["length"],
        "before_compiled_file_marker_count": before_counts["file_marker_count"],
        "before_compiled_page_marker_count": before_counts["page_marker_count"],
    }
