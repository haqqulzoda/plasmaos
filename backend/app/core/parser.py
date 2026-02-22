"""
Phase 1 parser: unpack archives and parse tender technical documents.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from pathlib import Path
from typing import BinaryIO, TypedDict
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

import docx
import fitz
import httpx
import pkgutil

# --- Python 3.14 compatibility shim ---
# pkgutil.find_loader was removed in Python 3.14. pytesseract 0.3.10 still
# relies on it, so we restore it here before importing pytesseract.
if not hasattr(pkgutil, "find_loader"):
    import importlib.util

    def _find_loader_shim(fullname: str):  # type: ignore[return]
        spec = importlib.util.find_spec(fullname)
        return spec.loader if spec is not None else None

    pkgutil.find_loader = _find_loader_shim  # type: ignore[attr-defined]

import pytesseract
import rarfile
from pdf2image import convert_from_bytes
from PIL import Image

logger = logging.getLogger(__name__)

SUPPORTED_DOC_SUFFIXES = {".pdf", ".docx"}
ARCHIVE_SUFFIXES = {".zip", ".rar"}
OCR_MIN_TEXT_LEN = 50
OCR_LANGS = "uzb+rus+eng"


class ExtractedArchiveFile(TypedDict):
    filename: str
    file_bytes: bytes


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_zip(data: bytes) -> bool:
    return data.startswith(b"PK\x03\x04")


def _looks_like_rar(data: bytes) -> bool:
    return data.startswith(b"Rar!\x1a\x07\x00") or data.startswith(b"Rar!\x1a\x07\x01\x00")


def _looks_like_docx(data: bytes) -> bool:
    if not _looks_like_zip(data):
        return False

    try:
        with ZipFile(io.BytesIO(data), "r") as zip_file:
            return "word/document.xml" in zip_file.namelist()
    except BadZipFile:
        return False
    except Exception:
        return False


def _safe_decode_text(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="ignore")


def _parse_extracted_documents(files: list[ExtractedArchiveFile]) -> str:
    parsed_chunks: list[str] = []

    for item in files:
        filename = item["filename"]
        suffix = Path(filename).suffix.lower()

        try:
            if suffix == ".pdf":
                text = parse_pdf(item["file_bytes"], file_path=filename)
            elif suffix == ".docx":
                text = parse_docx(item["file_bytes"])
            else:
                continue
        except Exception as exc:
            logger.error("Failed to parse '%s': %s", filename, exc, exc_info=True)
            continue

        normalized = text.strip()
        if normalized:
            parsed_chunks.append(f"[{filename}]\n{normalized}")

    return "\n\n".join(parsed_chunks).strip()


def _is_safe_archive_member(member_name: str) -> bool:
    member_path = Path(member_name)
    return not member_path.is_absolute() and ".." not in member_path.parts


def _collect_supported_files_from_directory(root_dir: Path) -> list[ExtractedArchiveFile]:
    extracted: list[ExtractedArchiveFile] = []

    for dirpath, _, filenames in os.walk(root_dir):
        current_dir = Path(dirpath)
        for filename in filenames:
            full_path = current_dir / filename
            if full_path.suffix.lower() not in SUPPORTED_DOC_SUFFIXES:
                continue

            relative_name = full_path.relative_to(root_dir).as_posix()
            try:
                file_bytes = full_path.read_bytes()
            except Exception as exc:
                logger.error("Failed to read extracted file '%s': %s", relative_name, exc, exc_info=True)
                continue

            extracted.append({"filename": relative_name, "file_bytes": file_bytes})

    return extracted


def _extract_zip_contents_from_path(archive_path: Path) -> list[ExtractedArchiveFile]:
    with tempfile.TemporaryDirectory(prefix="zip_extract_") as temp_dir:
        extract_root = Path(temp_dir)
        with ZipFile(archive_path, "r") as zip_file:
            for member in zip_file.infolist():
                if member.is_dir():
                    continue
                if not _is_safe_archive_member(member.filename):
                    logger.warning("Skipping unsafe zip member path: %s", member.filename)
                    continue
                try:
                    zip_file.extract(member, path=extract_root)
                except Exception as exc:
                    logger.error("Failed to extract zip member '%s': %s", member.filename, exc, exc_info=True)
                    continue

        return _collect_supported_files_from_directory(extract_root)


def _extract_rar_contents_from_path(archive_path: Path) -> list[ExtractedArchiveFile]:
    with tempfile.TemporaryDirectory(prefix="rar_extract_") as temp_dir:
        extract_root = Path(temp_dir)
        with rarfile.RarFile(archive_path) as rar_archive:
            for member in rar_archive.infolist():
                if member.isdir():
                    continue
                if not _is_safe_archive_member(member.filename):
                    logger.warning("Skipping unsafe rar member path: %s", member.filename)
                    continue
                try:
                    rar_archive.extract(member, path=extract_root)
                except Exception as exc:
                    logger.error("Failed to extract rar member '%s': %s", member.filename, exc, exc_info=True)
                    continue

        return _collect_supported_files_from_directory(extract_root)


def _extract_archive_contents_from_bytes(archive_bytes: bytes, suffix: str) -> list[ExtractedArchiveFile]:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_file.write(archive_bytes)
            temp_path = Path(temp_file.name)
        if suffix == ".zip":
            return _extract_zip_contents_from_path(temp_path)
        return _extract_rar_contents_from_path(temp_path)
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.warning("Failed to remove temporary archive file: %s", temp_path)


def extract_archive_contents(archive_source: bytes | str | Path | BinaryIO) -> list[ExtractedArchiveFile]:
    """
    Extract .pdf/.docx files from a ZIP or RAR archive at any directory depth.

    Returns each file with nested path preserved in `filename`.
    """
    try:
        if isinstance(archive_source, (str, Path)):
            archive_path = Path(archive_source)
            suffix = archive_path.suffix.lower()
            if suffix == ".zip":
                return _extract_zip_contents_from_path(archive_path)
            if suffix == ".rar":
                return _extract_rar_contents_from_path(archive_path)

            try:
                return _extract_zip_contents_from_path(archive_path)
            except BadZipFile:
                return _extract_rar_contents_from_path(archive_path)

        archive_bytes: bytes
        if isinstance(archive_source, (bytes, bytearray)):
            archive_bytes = bytes(archive_source)
        elif hasattr(archive_source, "read"):
            archive_bytes = archive_source.read()
        else:
            logger.error("Unsupported archive source type: %s", type(archive_source))
            return []

        if _looks_like_zip(archive_bytes):
            return _extract_archive_contents_from_bytes(archive_bytes, ".zip")
        if _looks_like_rar(archive_bytes):
            return _extract_archive_contents_from_bytes(archive_bytes, ".rar")

        try:
            return _extract_archive_contents_from_bytes(archive_bytes, ".zip")
        except BadZipFile:
            return _extract_archive_contents_from_bytes(archive_bytes, ".rar")
    except (BadZipFile, rarfile.Error, FileNotFoundError, OSError) as exc:
        logger.error("Archive extraction failed: %s", exc, exc_info=True)
        return []
    except Exception as exc:
        logger.error("Unexpected archive extraction error: %s", exc, exc_info=True)
        return []


def parse_docx(docx_bytes: bytes) -> str:
    """Parse DOCX bytes and return full text."""
    try:
        document = docx.Document(io.BytesIO(docx_bytes))
    except Exception as exc:
        logger.error("DOCX open failed: %s", exc, exc_info=True)
        return ""

    chunks: list[str] = []

    try:
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if text:
                chunks.append(text)

        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    text = cell.text.strip()
                    if text:
                        chunks.append(text)
    except Exception as exc:
        logger.error("DOCX parsing failed: %s", exc, exc_info=True)
        return ""

    return "\n".join(chunks).strip()


def _page_has_visual_content(page: fitz.Page) -> bool:
    try:
        if page.get_images(full=True):
            return True
    except Exception:
        pass

    try:
        if page.get_drawings():
            return True
    except Exception:
        pass

    return False


def _ocr_pdf_page(pdf_bytes: bytes, page_number: int) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="pdf_ocr_page_") as temp_dir:
            image_paths = convert_from_bytes(
                pdf_bytes,
                dpi=300,
                first_page=page_number,
                last_page=page_number,
                fmt="png",
                output_folder=temp_dir,
                paths_only=True,
                thread_count=1,
            )
            if not image_paths:
                return ""

            page_chunks: list[str] = []
            for image_path in image_paths:
                try:
                    with Image.open(image_path) as image:
                        text = pytesseract.image_to_string(image, lang=OCR_LANGS).strip()
                    if text:
                        page_chunks.append(text)
                except Exception as exc:
                    logger.error("OCR image read failed (page %s): %s", page_number, exc, exc_info=True)
                    continue

            return "\n".join(page_chunks).strip()
    except Exception as exc:
        logger.error("OCR conversion failed (page %s): %s", page_number, exc, exc_info=True)
        return ""


def _ocr_entire_pdf(pdf_bytes: bytes) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="pdf_ocr_full_") as temp_dir:
            image_paths = convert_from_bytes(
                pdf_bytes,
                dpi=300,
                fmt="png",
                output_folder=temp_dir,
                paths_only=True,
                thread_count=1,
            )
            if not image_paths:
                return ""

            page_texts: list[str] = []
            for index, image_path in enumerate(image_paths, start=1):
                try:
                    with Image.open(image_path) as image:
                        text = pytesseract.image_to_string(image, lang=OCR_LANGS).strip()
                    if text:
                        page_texts.append(text)
                except Exception as exc:
                    logger.error("OCR failed (fallback page %s): %s", index, exc, exc_info=True)
                    continue

            return "\n\n".join(page_texts).strip()
    except Exception as exc:
        logger.error("Full-document OCR failed: %s", exc, exc_info=True)
        return ""


def parse_pdf(pdf_bytes: bytes, file_path: str = "<bytes>") -> str:
    """
    Parse PDF bytes using native extraction and OCR fallback for scanned pages.
    """
    page_texts: list[str] = []

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
            logger.info("[SONAR] PyMuPDF opened the document successfully.")
            for page_index, page in enumerate(pdf_doc, start=1):
                native_text = ""
                try:
                    native_text = (page.get_text() or "").strip()
                except Exception as exc:
                    logger.error(
                        "Native PDF extraction failed (page %s): %s",
                        page_index,
                        exc,
                        exc_info=True,
                    )

                if len(native_text) >= OCR_MIN_TEXT_LEN:
                    page_texts.append(native_text)
                    continue

                ocr_text = ""
                if native_text or _page_has_visual_content(page):
                    logger.info("[SONAR] Empty text detected. Triggering OCR fallback.")
                    ocr_text = _ocr_pdf_page(pdf_bytes, page_index)

                merged = "\n".join(part for part in (native_text, ocr_text) if part).strip()
                if merged:
                    page_texts.append(merged)
    except Exception as e:
        logger.error(f"[SONAR] EXTRACTION FAILED on {file_path}. Reason: {str(e)}", exc_info=True)
        return _ocr_entire_pdf(pdf_bytes)

    extracted_text = "\n\n".join(page_texts).strip()
    logger.info(f"[SONAR] Extraction complete. Total characters: {len(extracted_text)}")
    return extracted_text


async def process_tender_document(
    source: bytes | str | Path,
    filename: str | None = None,
) -> str:
    """
    Async entry point:
    - accepts URL, local file path, or raw bytes
    - routes to archive extraction or direct parser
    - returns concatenated legally relevant text
    """
    payload: bytes = b""
    inferred_name = filename or ""
    path_source: Path | None = None

    try:
        if isinstance(source, (bytes, bytearray)):
            payload = bytes(source)
        elif isinstance(source, Path):
            path_source = source
            inferred_name = inferred_name or source.name
            payload = source.read_bytes()
        elif isinstance(source, str):
            if _is_url(source):
                inferred_name = inferred_name or Path(urlparse(source).path).name
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(source)
                    response.raise_for_status()
                    payload = response.content
            else:
                path_source = Path(source)
                inferred_name = inferred_name or path_source.name
                payload = path_source.read_bytes()
        else:
            logger.error("Unsupported source type for parser: %s", type(source))
            return ""
    except (httpx.HTTPError, FileNotFoundError, OSError) as exc:
        logger.error("Failed to load source document: %s", exc, exc_info=True)
        return ""
    except Exception as exc:
        logger.error("Unexpected source loading error: %s", exc, exc_info=True)
        return ""

    if not payload:
        return ""

    suffix = Path(inferred_name).suffix.lower()
    is_docx = suffix == ".docx" or _looks_like_docx(payload)
    is_archive = (suffix in ARCHIVE_SUFFIXES or _looks_like_zip(payload) or _looks_like_rar(payload)) and not is_docx

    if is_archive:
        archive_input: bytes | str | Path = path_source if path_source else payload
        extracted_files = await asyncio.to_thread(extract_archive_contents, archive_input)
        return await asyncio.to_thread(_parse_extracted_documents, extracted_files)

    if suffix == ".pdf" or payload.startswith(b"%PDF"):
        source_label = str(path_source) if path_source else inferred_name or "<bytes>"
        return await asyncio.to_thread(parse_pdf, payload, source_label)

    if is_docx:
        return await asyncio.to_thread(parse_docx, payload)

    if suffix == ".txt":
        return _safe_decode_text(payload).strip()

    logger.warning("Unsupported source format for process_tender_document: %s", inferred_name or "<bytes>")
    return ""


def extract_text_from_pdf(file_path: str | Path) -> str:
    """
    Backward-compatible wrapper for existing code paths.
    """
    try:
        path = Path(file_path)
        logger.info(f"[SONAR] Attempting to extract: {file_path} | Size: {os.path.getsize(path)} bytes")
        return parse_pdf(path.read_bytes(), file_path=str(path))
    except Exception as e:
        logger.error(f"[SONAR] EXTRACTION FAILED on {file_path}. Reason: {str(e)}", exc_info=True)
        return ""


def extract_text_from_bytes(file_bytes: bytes, file_type: str) -> str:
    """
    Backward-compatible wrapper for existing code paths.
    """
    normalized = file_type.lower().strip(".")
    try:
        if normalized == "pdf":
            return parse_pdf(file_bytes)
        if normalized in {"doc", "docx"}:
            return parse_docx(file_bytes)
        if normalized == "txt":
            return _safe_decode_text(file_bytes).strip()
        if normalized in {"zip", "rar"}:
            extracted = extract_archive_contents(file_bytes)
            return _parse_extracted_documents(extracted)
    except Exception as exc:
        logger.error("extract_text_from_bytes failed for type '%s': %s", normalized, exc, exc_info=True)
        return ""

    logger.warning("Unsupported file type in extract_text_from_bytes: %s", file_type)
    return ""


def extract_text_from_file(file_path: str | Path) -> str:
    """
    Backward-compatible wrapper for existing code paths.
    """
    path = Path(file_path)
    suffix = path.suffix.lower().strip(".")
    try:
        file_bytes = path.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        logger.error("Failed to read file '%s': %s", file_path, exc, exc_info=True)
        return ""
    except Exception as exc:
        logger.error("Unexpected file read error '%s': %s", file_path, exc, exc_info=True)
        return ""

    return extract_text_from_bytes(file_bytes, suffix)
