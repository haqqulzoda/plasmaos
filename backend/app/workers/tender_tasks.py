"""
Celery tasks for tender document synchronization and extraction.
"""

from __future__ import annotations

import asyncio

import logging
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import configure_mappers

# Force-load the entire ORM registry into the worker's memory space
import app.models  # This triggers __init__.py to load all models
from app.models.all_models import Tender, TenderDocument
from app.models.company import CompanyProfile
from app.models.taxonomy import CompanyCredential, TaxonomyNode

# Lock the relationships (resolves string references like "TenderAnalysis")
configure_mappers()

from app.core.celery_app import celery_app
from app.core.parser import process_tender_document
from app.core.scraper import UzExScraper
from app.db.session import AsyncSessionLocal, engine
logger = logging.getLogger(__name__)


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

                for doc in existing_docs:
                    if _parsed_text_present(doc):
                        parsed_text_by_identity.setdefault(
                            _document_identity_key(doc.file_url),
                            doc.parsed_text.strip(),
                        )

                for doc_data in scraped_docs:
                    scraped_url = (doc_data.get("file_url") or "").strip()
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

                    if not doc:
                        new_doc = TenderDocument(
                            id=uuid4(),
                            tender_id=tender_uuid,
                            file_url=scraped_url,
                            file_type=doc_data["file_type"],
                        )
                        db.add(new_doc)
                        doc = new_doc
                        _register_existing_doc(
                            new_doc,
                            existing_by_url,
                            existing_by_path,
                            existing_by_name,
                        )
                        new_count += 1

                    if _parsed_text_present(doc):
                        parsed_text_by_identity.setdefault(
                            _document_identity_key(scraped_url),
                            doc.parsed_text.strip(),
                        )
                        continue

                    file_path = _extract_file_path(scraped_url)
                    try:
                        file_bytes, filename = await scraper.download_file(
                            tender_url=tender.source_url,
                            file_path=file_path,
                        )
                        extracted_text = await process_tender_document(
                            source=file_bytes,
                            filename=filename,
                        )
                        if extracted_text.strip():
                            doc.parsed_text = extracted_text
                            parsed_count += 1
                            parsed_text_by_identity[_document_identity_key(scraped_url)] = (
                                f"[{filename}]\n{extracted_text.strip()}"
                            )
                    except Exception as parse_exc:
                        logger.warning(
                            "Failed to parse tender document '%s' for tender %s: %s",
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
