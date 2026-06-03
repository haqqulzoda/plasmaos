"""
Plasma AI - UzEx Tender Scraper

Playwright-based scraper for etender.uzex.uz portal.
Scrapes the main tender list and classifies by keywords.

Note: Uses sync Playwright in a thread executor to avoid Windows async issues.
"""

import asyncio
import html
import io
import json
import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

import httpx
import rarfile
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from zipfile import BadZipFile, ZipFile

logger = logging.getLogger(__name__)

# Thread pool for running sync Playwright
_executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class ScrapedTender:
    """Data class for scraped tender information."""
    external_id: str
    title: str
    budget: float
    currency: str
    region: Optional[str]
    source_url: str
    category: str = "Other"
    deadline: Optional[datetime] = None


# Category classification keywords
CATEGORY_KEYWORDS = {
    "Construction": [
        'tamirlash', "ta'mirlash", 'qurilish', 'remont', 'stroy', 
        'asfalt', 'beton', 'izolyatsiya', 'ремонт', 'строит',
        'quvur', 'труб', 'roof', 'tom', 'deraza', 'gaz'
    ],
    "IT & Tech": [
        'kompyuter', 'printer', 'noutbuk', 'server', 'web', 
        'dastur', 'kartridj', 'monitor', 'komputer', 'computer',
        'texnik', 'программ', 'принтер', 'сервер', 'ўлчаш'
    ],
    "Medical": [
        'dori', 'tibbiy', 'maska', 'shprits', 'aptek', 'farm',
        'медиц', 'аптек', 'лекар', 'shifokor', 'kasalxona'
    ],
    "Office": [
        'qogoz', "qog'oz", 'ruchka', 'mebel', 'parta', 'stul', 
        'kantselyariya', 'канцеляр', 'мебел', 'стол', 'stol'
    ],
}

DOWNLOAD_URL_MARKERS = (
    "downloadfile",
    "download",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
)

KNOWN_FILE_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
}

TRANSIENT_HTTP_STATUS_CODES = {429, 502, 503, 504}
DOCUMENT_ATTRIBUTE_NAMES = (
    "href",
    "onclick",
    "data-url",
    "data-href",
    "data-link",
    "data-path",
    "data-file",
)
API_TRADE_FILE_PATH_FIELDS = {
    "tech_file_path",
    "tech_doc_file_path",
    "contract_proform_file_path",
    "expertise_file_path",
    "add_file_path",
}
API_QUALIFICATION_FIELD_CONTAINERS = {
    "qualification_fields",
    "js_qualification_fields",
}


class TransientPortalError(Exception):
    """Retryable UzEx/network failure."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _is_transient_exception(exc: BaseException) -> bool:
    if isinstance(exc, (PlaywrightTimeout, httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, TransientPortalError):
        return exc.status_code is None or exc.status_code in TRANSIENT_HTTP_STATUS_CODES
    return False
DOWNLOAD_CANDIDATE_PATTERN = re.compile(
    r"""(?ix)
    (?:
        https?://[^\s"'<>]+?downloadfile\?path=[^\s"'<>]+
        |https?://[^\s"'<>]+\.(?:pdf|docx?|xlsx?|zip|rar|7z|tar|gz)\b[^\s"'<>]*
        |/api/common/downloadfile\?path=[^\s"'<>]+
        |api/common/downloadfile\?path=[^\s"'<>]+
        |/downloadfile\?path=[^\s"'<>]+
        |downloadfile\?path=[^\s"'<>]+
        |/files/[^\s"'<>]+\.(?:pdf|docx?|xlsx?|zip|rar|7z|tar|gz)\b[^\s"'<>]*
        |files/[^\s"'<>]+\.(?:pdf|docx?|xlsx?|zip|rar|7z|tar|gz)\b[^\s"'<>]*
    )
    """
)
DOWNLOAD_TRIGGER_SELECTOR = (
    "a.btn-success, button.btn-success, a[href*='DownloadFile'], "
    "button[onclick*='DownloadFile'], [onclick*='DownloadFile'], "
    "[data-url*='DownloadFile'], [data-href*='DownloadFile'], "
    "a:has-text('Yuklab olish'), button:has-text('Yuklab olish'), "
    "a:has-text('Download'), button:has-text('Download'), "
    "a:has-text('Скачать'), button:has-text('Скачать')"
)


def _extract_download_path(url_or_path: str) -> str:
    raw_value = (url_or_path or "").strip()
    if not raw_value:
        return ""

    parsed = urlparse(raw_value)
    query_path = parse_qs(parsed.query).get("path", [None])[0]
    if query_path:
        return unquote(query_path).strip()

    if parsed.scheme and parsed.netloc:
        return unquote(parsed.path).strip()

    return unquote(parsed.path or raw_value).strip()


def _download_api_path_variants(url_or_path: str) -> list[str]:
    download_path = _extract_download_path(url_or_path)
    if not download_path:
        return []

    variants: list[str] = []

    def add_variant(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    add_variant(download_path)
    normalized = download_path.lstrip("/")
    normalized_lower = normalized.lower()
    if normalized_lower.startswith(("files/", "tender/user-files/")):
        if download_path.startswith("/"):
            add_variant(normalized)
        else:
            add_variant(f"/{download_path}")

    return variants


def _download_target_key(url_or_path: str) -> str:
    return _extract_download_path(url_or_path).lower()


def _extract_filename(url_or_path: str) -> str:
    download_path = _extract_download_path(url_or_path)
    if not download_path:
        return ""
    return Path(download_path).name


def _detect_file_extension(url_or_path: str) -> str:
    filename = _extract_filename(url_or_path)
    if not filename:
        return ""
    return Path(filename).suffix.lower().lstrip(".")


def _detect_scraped_file_type(url_or_path: str) -> str:
    extension = _detect_file_extension(url_or_path)
    return extension if extension in KNOWN_FILE_EXTENSIONS else "unknown"


def _looks_like_html_response(file_bytes: bytes, content_type: str) -> bool:
    normalized_content_type = (content_type or "").lower()
    if "html" in normalized_content_type:
        return True

    prefix = file_bytes[:512].lstrip().lower()
    return (
        prefix.startswith(b"<!doctype html")
        or prefix.startswith(b"<html")
        or prefix.startswith(b"<body")
    )


def _looks_like_pdf_bytes(file_bytes: bytes) -> bool:
    return file_bytes.startswith(b"%PDF")


def _looks_like_zip_bytes(file_bytes: bytes) -> bool:
    return file_bytes.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _looks_like_rar_bytes(file_bytes: bytes) -> bool:
    return file_bytes.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))


def _normalize_embedded_text(value: str) -> str:
    normalized = html.unescape(value or "")
    return (
        normalized.replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u003A", ":")
        .replace("\\u0026", "&")
    )


def _extract_download_candidates_from_text(value: str) -> list[str]:
    cleaned = _normalize_embedded_text(value)
    if not cleaned:
        return []

    candidates: list[str] = []
    for match in DOWNLOAD_CANDIDATE_PATTERN.findall(cleaned):
        candidate = match.strip().strip("\"'`()[]{}")
        if candidate:
            candidates.append(candidate)
    return candidates


def _extract_download_candidates_from_element(element) -> list[str]:
    candidates: list[str] = []
    for attr_name in DOCUMENT_ATTRIBUTE_NAMES:
        try:
            attr_value = element.get_attribute(attr_name)
        except Exception:
            attr_value = None
        if not attr_value:
            continue
        candidates.extend(_extract_download_candidates_from_text(attr_value))
        if any(marker in attr_value.lower() for marker in DOWNLOAD_URL_MARKERS):
            candidates.append(attr_value)
    return candidates


def _json_load_if_possible(value):
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value

    try:
        return json.loads(stripped)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _case_insensitive_get(mapping: dict, key: str):
    normalized_key = key.lower()
    for existing_key, value in mapping.items():
        if str(existing_key).lower() == normalized_key:
            return value
    return None


def _extract_lot_id(source_url: str) -> str:
    parsed = urlparse(source_url or "")
    match = re.search(r"/lot/(\d+)", parsed.path or source_url or "")
    return match.group(1) if match else ""


def _is_api_document_path(value: str) -> bool:
    candidate = (value or "").strip()
    if not candidate:
        return False

    normalized_candidate = _normalize_embedded_text(candidate).strip().lower()
    if not _detect_file_extension(normalized_candidate):
        return False

    return (
        normalized_candidate.startswith("/files/")
        or normalized_candidate.startswith("files/")
        or normalized_candidate.startswith("/tender/user-files/")
        or normalized_candidate.startswith("tender/user-files/")
    )


def _normalize_download_candidate(value: str, *, portal_base_url: str) -> str:
    candidate = _normalize_embedded_text(value).strip().strip("\"'`()[]{}")
    if not candidate:
        return ""

    candidate_lower = candidate.lower()
    if candidate.startswith("//"):
        return f"https:{candidate}"
    if candidate_lower.startswith(("http://", "https://")):
        return candidate
    if "downloadfile?path=" in candidate_lower:
        if candidate.startswith("/api/"):
            return f"https://apietender.uzex.uz{candidate}"
        if candidate.startswith("api/"):
            return f"https://apietender.uzex.uz/{candidate}"
        if candidate.startswith("/"):
            return f"https://apietender.uzex.uz/api/common{candidate}"
        return f"https://apietender.uzex.uz/api/common/{candidate.lstrip('/')}"
    if candidate.startswith("/"):
        return f"{portal_base_url}{candidate}"
    return f"{portal_base_url.rstrip('/')}/{candidate.lstrip('/')}"


def _archive_has_file_members(file_bytes: bytes, extension: str) -> bool:
    if extension == "zip" or _looks_like_zip_bytes(file_bytes):
        try:
            with ZipFile(io.BytesIO(file_bytes), "r") as archive:
                return any(
                    not member.is_dir() and Path(member.filename.replace("\\", "/")).name
                    for member in archive.infolist()
                )
        except (BadZipFile, OSError):
            return False

    if extension == "rar" or _looks_like_rar_bytes(file_bytes):
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".rar", delete=False) as temp_file:
                temp_file.write(file_bytes)
                temp_path = temp_file.name

            with rarfile.RarFile(temp_path) as archive:
                return any(
                    not member.isdir() and Path(member.filename.replace("\\", "/")).name
                    for member in archive.infolist()
                )
        except (rarfile.Error, FileNotFoundError, OSError):
            return False
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    logger.warning("Failed to remove temporary rar validation file: %s", temp_path)

    return False


def _archive_path_has_file_members(file_path: str, extension: str) -> bool:
    if extension == "zip":
        try:
            with ZipFile(file_path, "r") as archive:
                return any(
                    not member.is_dir() and Path(member.filename.replace("\\", "/")).name
                    for member in archive.infolist()
                )
        except (BadZipFile, OSError):
            return False

    if extension == "rar":
        try:
            with rarfile.RarFile(file_path) as archive:
                return any(
                    not member.isdir() and Path(member.filename.replace("\\", "/")).name
                    for member in archive.infolist()
                )
        except (rarfile.Error, FileNotFoundError, OSError):
            return False

    return False


def _read_prefix(file_path: str, size: int = 512) -> bytes:
    try:
        with open(file_path, "rb") as file_handle:
            return file_handle.read(size)
    except OSError:
        return b""


def _download_candidate_matches_target(
    *,
    target_key: str,
    requested_name: str,
    candidate_url: str,
    candidate_name: str,
) -> bool:
    normalized_requested_name = requested_name.strip().lower()
    normalized_candidate_name = candidate_name.strip().lower()

    if target_key and _download_target_key(candidate_url) == target_key:
        return True

    if normalized_requested_name and normalized_candidate_name == normalized_requested_name:
        return True

    candidate_url_name = _extract_filename(candidate_url).strip().lower()
    return bool(normalized_requested_name and candidate_url_name == normalized_requested_name)


def _is_valid_file_payload(file_bytes: bytes, content_type: str, file_path: str) -> bool:
    if not file_bytes or len(file_bytes) <= 100:
        return False

    if _looks_like_html_response(file_bytes, content_type):
        return False

    extension = _detect_file_extension(file_path)
    normalized_content_type = (content_type or "").lower()

    if extension == "pdf":
        return _looks_like_pdf_bytes(file_bytes) or "application/pdf" in normalized_content_type

    if extension == "zip":
        is_zip_payload = (
            _looks_like_zip_bytes(file_bytes)
            or "application/zip" in normalized_content_type
            or "octet-stream" in normalized_content_type
        )
        return is_zip_payload and _archive_has_file_members(file_bytes, "zip")

    if extension == "rar":
        is_rar_payload = (
            _looks_like_rar_bytes(file_bytes)
            or "rar" in normalized_content_type
            or "octet-stream" in normalized_content_type
        )
        return is_rar_payload and _archive_has_file_members(file_bytes, "rar")

    return True


def _is_valid_file_path_payload(local_path: str, content_type: str, file_path: str) -> bool:
    try:
        file_size = os.path.getsize(local_path)
    except OSError:
        return False

    if file_size <= 100:
        return False

    normalized_content_type = (content_type or "").lower()
    prefix = _read_prefix(local_path)
    if "html" in normalized_content_type:
        return False
    if prefix.lstrip().lower().startswith((b"<!doctype html", b"<html", b"<body")):
        return False

    extension = _detect_file_extension(file_path)

    if extension == "pdf":
        return prefix.startswith(b"%PDF") or "application/pdf" in normalized_content_type

    if extension == "zip":
        is_zip_payload = (
            prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
            or "application/zip" in normalized_content_type
            or "octet-stream" in normalized_content_type
        )
        return is_zip_payload and _archive_path_has_file_members(local_path, "zip")

    if extension == "rar":
        is_rar_payload = (
            prefix.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
            or "rar" in normalized_content_type
            or "octet-stream" in normalized_content_type
        )
        return is_rar_payload and _archive_path_has_file_members(local_path, "rar")

    return True


def detect_category(title: str) -> str:
    """Detect tender category based on keywords in the title."""
    title_lower = title.lower()
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in title_lower:
                return category
    
    return "Other"


class UzExScraper:
    """
    Scraper for etender.uzex.uz portal.
    
    Scrapes all tenders from the main page and categorizes by keywords.
    """
    
    BASE_URL = "https://etender.uzex.uz"
    LOTS_URL = "https://etender.uzex.uz/lots/2/0"
    
    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
    
    def _parse_budget(self, budget_text: str) -> tuple[float, str]:
        """Parse budget string like '450 000 000 UZS' to (450000000.0, 'UZS')."""
        cleaned = budget_text.strip()
        parts = cleaned.split()
        currency = "UZS"
        
        if parts and parts[-1].isalpha():
            currency = parts[-1].upper()
            parts = parts[:-1]
        
        number_str = "".join(parts).replace(" ", "").replace(",", "")
        
        try:
            budget = float(number_str)
        except ValueError:
            budget = 0.0
        
        return budget, currency
    
    def _parse_deadline(self, deadline_text: str) -> Optional[datetime]:
        """Parse deadline string to datetime."""
        formats = [
            "%d.%m.%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%d.%m.%Y %H:%M",
            "%d-%m-%Y %H:%M",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(deadline_text.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        
        return None
    
    def _extract_region(self, lines: list[str]) -> Optional[str]:
        """Extract region from address lines."""
        region_names = {
            # Uzbek
            'toshkent': 'Tashkent',
            'tashkent': 'Tashkent', 
            'samarqand': 'Samarkand',
            'buxoro': 'Bukhara',
            'fargona': 'Fergana',
            'andijon': 'Andijan',
            'namangan': 'Namangan',
            'xorazm': 'Khorezm',
            'surxondaryo': 'Surkhandarya',
            'qashqadaryo': 'Kashkadarya',
            'jizzax': 'Jizzakh',
            'sirdaryo': 'Sirdarya',
            'navoiy': 'Navoi',
            'qoraqalpog': 'Karakalpakstan',
            # Russian
            'ташкент': 'Tashkent',
            'хорезм': 'Khorezm',
            'ургенч': 'Khorezm',
            'самарканд': 'Samarkand',
            'бухар': 'Bukhara',
            'ферган': 'Fergana',
            'андижан': 'Andijan',
            'наманган': 'Namangan',
            'сурхандар': 'Surkhandarya',
            'кашкадар': 'Kashkadarya',
            'джизак': 'Jizzakh',
            'сырдар': 'Sirdarya',
            'навои': 'Navoi',
            'каракалпак': 'Karakalpakstan',
            # Districts/areas in Russian
            'алмазар': 'Tashkent',
            'чиланзар': 'Tashkent',
            'юнусабад': 'Tashkent',
            'мирзо улугбек': 'Tashkent',
            'яккасарай': 'Tashkent',
            'мирабад': 'Tashkent',
            'шайхантахур': 'Tashkent',
            'сергели': 'Tashkent',
            'бектемир': 'Tashkent',
            'бостанлык': 'Tashkent Region',
            'чирчик': 'Tashkent Region',
        }
        
        for line in lines:
            line_lower = line.lower()
            for kw, name in region_names.items():
                if kw in line_lower:
                    return name
        return None
    
    def _extract_deadline(self, lines: list[str]) -> Optional[datetime]:
        """Extract deadline from lines."""
        deadline_keywords = ['tugash sanasi', 'deadline', 'muddati', 'срок']
        
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in deadline_keywords):
                # Try same line
                date_match = re.search(r'(\d{2}[-./]\d{2}[-./]\d{4}(?:\s+\d{2}:\d{2})?)', line)
                if date_match:
                    return self._parse_deadline(date_match.group(1))
                # Try next line
                if i + 1 < len(lines):
                    date_match = re.search(r'(\d{2}[-./]\d{2}[-./]\d{4}(?:\s+\d{2}:\d{2})?)', lines[i + 1])
                    if date_match:
                        return self._parse_deadline(date_match.group(1))
        return None

    def _sync_scrape_documents_from_api(self, source_url: str) -> list[dict]:
        lot_id = _extract_lot_id(source_url)
        if not lot_id:
            logger.info("[SCRAPER] api_get_trade_start skipped: no lot id in %s", source_url)
            return []

        trade_api_url = f"https://apietender.uzex.uz/api/common/GetTrade/{lot_id}/0"
        documents: list[dict] = []
        seen_urls: set[str] = set()

        def add_document(raw_path, source_field: str) -> None:
            if not isinstance(raw_path, str) or not _is_api_document_path(raw_path):
                return

            file_url = _normalize_download_candidate(
                raw_path,
                portal_base_url=self.BASE_URL,
            )
            if not file_url:
                return

            dedupe_key = _download_target_key(file_url) or file_url.lower()
            if dedupe_key in seen_urls:
                return
            seen_urls.add(dedupe_key)

            file_type = _detect_scraped_file_type(file_url)
            documents.append(
                {
                    "file_url": file_url,
                    "file_type": file_type,
                }
            )
            logger.info(
                "[SCRAPER] api_document_found lot_id=%s source_field=%s file_type=%s path=%s",
                lot_id,
                source_field,
                file_type,
                file_url,
            )

        def walk_payload(value, path: str = "") -> None:
            parsed_value = _json_load_if_possible(value)

            if isinstance(parsed_value, dict):
                for field_name in API_TRADE_FILE_PATH_FIELDS:
                    add_document(
                        _case_insensitive_get(parsed_value, field_name),
                        field_name if not path else f"{path}.{field_name}",
                    )

                for container_name in API_QUALIFICATION_FIELD_CONTAINERS:
                    container_value = _json_load_if_possible(
                        _case_insensitive_get(parsed_value, container_name)
                    )
                    if isinstance(container_value, list):
                        for index, item in enumerate(container_value):
                            item = _json_load_if_possible(item)
                            if isinstance(item, dict):
                                add_document(
                                    _case_insensitive_get(item, "file_path"),
                                    f"{container_name}[{index}].file_path",
                                )

                for key, child_value in parsed_value.items():
                    child_path = str(key) if not path else f"{path}.{key}"
                    if isinstance(child_value, (dict, list)):
                        walk_payload(child_value, child_path)
                        continue

                    decoded_child = _json_load_if_possible(child_value)
                    if isinstance(decoded_child, (dict, list)):
                        walk_payload(decoded_child, child_path)

            elif isinstance(parsed_value, list):
                for index, item in enumerate(parsed_value):
                    walk_payload(item, f"{path}[{index}]")

        logger.info("[SCRAPER] api_get_trade_start lot_id=%s url=%s", lot_id, trade_api_url)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, read=60.0),
                follow_redirects=True,
            ) as client:
                response = client.get(
                    trade_api_url,
                    headers={
                        "Accept": "application/json",
                        "Referer": source_url,
                    },
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning(
                "[SCRAPER] api_get_trade_error lot_id=%s error=%s; falling back to DOM",
                lot_id,
                exc,
            )
            return []

        content_type = response.headers.get("content-type", "")
        logger.info(
            "[SCRAPER] api_get_trade_done lot_id=%s status=%s content_type=%s bytes=%s",
            lot_id,
            response.status_code,
            content_type,
            len(response.content),
        )

        if response.status_code in TRANSIENT_HTTP_STATUS_CODES:
            logger.warning(
                "[SCRAPER] api_get_trade_transient lot_id=%s status=%s; falling back to DOM",
                lot_id,
                response.status_code,
            )
            return []

        if response.status_code != 200:
            logger.warning(
                "[SCRAPER] api_get_trade_rejected lot_id=%s status=%s; falling back to DOM",
                lot_id,
                response.status_code,
            )
            return []

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning(
                "[SCRAPER] api_get_trade_invalid_json lot_id=%s error=%s; falling back to DOM",
                lot_id,
                exc,
            )
            return []

        if isinstance(payload, dict):
            logger.info(
                "[SCRAPER] api_get_trade_keys lot_id=%s key_count=%s",
                lot_id,
                len(payload),
            )
        walk_payload(payload)

        logger.info(
            "[SCRAPER] api_extract_done lot_id=%s total_count=%s",
            lot_id,
            len(documents),
        )
        return documents
    
    def _sync_fetch_all_tenders(self, limit: int = 20) -> list[ScrapedTender]:
        """
        Scrape all tenders from the main lots page.
        Categories are detected by keyword matching on titles.
        """
        tenders: list[ScrapedTender] = []
        seen_ids: set[str] = set()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            
            try:
                logger.info(f"Navigating to {self.LOTS_URL}")
                page.goto(self.LOTS_URL, timeout=self.timeout)
                page.wait_for_load_state("networkidle", timeout=10000)
                
                # Find all unique lot links
                lot_links = page.query_selector_all("a[href*='/lot/']")
                logger.info(f"Found {len(lot_links)} lot links")
                
                # Get full card content for parsing
                card = page.query_selector("div.card")
                full_text = card.inner_text() if card else ""
                lines = [l.strip() for l in full_text.split('\n') if l.strip()]
                
                # Process unique lot IDs
                current_idx = 0
                for link in lot_links:
                    if len(tenders) >= limit:
                        break
                        
                    try:
                        href = link.get_attribute("href") or ""
                        lot_match = re.search(r'/lot/(\d+)', href)
                        if not lot_match:
                            continue
                        
                        lot_id = lot_match.group(1)
                        
                        # Skip if already processed
                        if lot_id in seen_ids:
                            continue
                        seen_ids.add(lot_id)
                        
                        # Find this lot's section in the text (lot_id is at end of full lot number)
                        lot_section_lines = []
                        for i, line in enumerate(lines):
                            # Match lot ID at end of full lot number (e.g., ...467165)
                            if line.endswith(lot_id) or f"{lot_id}" in line:
                                start = i
                                end = min(len(lines), i + 12)
                                lot_section_lines = lines[start:end]
                                break
                        
                        if not lot_section_lines:
                            continue  # Skip if no section found
                        
                        # Extract title - skip header lines, find descriptive content
                        title = f"Tender #{lot_id}"
                        skip_words = ['Lot', 'UZS', 'Batafsil', 'Toifa', 'narx', 'sanasi', 'Boshlang']
                        for line in lot_section_lines[1:]:  # Skip the first line (lot number)
                            # Skip short lines and lines with known headers
                            if len(line) > 20 and not any(sw in line for sw in skip_words):
                                title = line[:200]
                                break
                        
                        # Detect category from title
                        category = detect_category(title)
                        
                        # Budget - check for UZS, USD, EUR
                        budget = 0.0
                        currency = "UZS"
                        currency_keywords = ['UZS', 'USD', 'EUR', 'сум', 'доллар', 'евро']
                        for line in lot_section_lines:
                            if any(kw in line.upper() for kw in ['UZS', 'USD', 'EUR']) or any(kw in line.lower() for kw in ['сум', 'доллар', 'евро']):
                                budget, currency = self._parse_budget(line)
                                if budget > 0:
                                    break
                        
                        # Region & Deadline
                        region = self._extract_region(lot_section_lines)
                        deadline = self._extract_deadline(lot_section_lines)
                        
                        source_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                        
                        tender = ScrapedTender(
                            external_id=lot_id,
                            title=title,
                            budget=budget,
                            currency=currency,
                            region=region,
                            source_url=source_url,
                            category=category,
                            deadline=deadline,
                        )
                        tenders.append(tender)
                        logger.info(f"[{category}] {lot_id}: {title[:40]}...")
                        
                    except Exception as e:
                        logger.warning(f"Failed to parse lot: {e}")
                        continue
                    
            except Exception as e:
                logger.error(f"Scraping error: {e}")
                raise
            
            finally:
                browser.close()
        
        logger.info(f"Scraped {len(tenders)} unique tenders")
        return tenders
    
    def _sync_scrape_documents(self, source_url: str, debug: bool = False) -> list[dict]:
        """
        Scrape document links from a tender detail page.
        
        Strategy (Button Clicker + Network Interceptor):
        1. Navigate & wait for page load
        2. Set up network interceptor for download URLs
        3. Click ALL "Yuklab olish" buttons to trigger API calls
        4. Capture download URLs from network traffic
        
        Args:
            source_url: URL of the tender detail page
            debug: If True, dump page info on zero results
        
        Returns list of dicts with file_url and file_type.
        """
        api_documents = self._sync_scrape_documents_from_api(source_url)
        if api_documents:
            logger.info("[SCRAPER] Complete: %s documents extracted via API", len(api_documents))
            return api_documents

        logger.info("[SCRAPER] dom_fallback_start url=%s", source_url)
        documents: list[dict] = []
        seen_urls: set[str] = set()
        captured_urls: list[str] = []
        
        # Noise patterns to exclude
        NOISE_PATTERNS = [
            'manual', 'help', 'instruction', 'qollanma',
            '/assets/file/', 'e-tender-buyurtmachi', 'e-tender-postavshik',
        ]
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            popup_urls: list[str] = []
            
            # Set up network interceptor to capture download URLs
            def capture_download_request(request):
                url = request.url.lower()
                if any(marker in url for marker in DOWNLOAD_URL_MARKERS):
                    captured_urls.append(request.url)
                    logger.info(f"[INTERCEPTOR] Captured: {request.url[:80]}...")
            
            page.on("request", capture_download_request)

            def capture_popup(popup):
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                try:
                    popup_url = popup.url
                except Exception:
                    popup_url = ""
                if popup_url:
                    popup_urls.append(popup_url)
                    captured_urls.append(popup_url)
                    logger.info("[POPUP] Captured: %s", popup_url[:120])
                try:
                    popup.close()
                except Exception:
                    pass

            page.on("popup", capture_popup)
            
            try:
                logger.info(f"[SCRAPER] Fetching: {source_url}")
                nav_response = None
                for nav_attempt in range(2):
                    try:
                        nav_timeout = self.timeout if nav_attempt == 0 else 60000
                        nav_response = page.goto(source_url, timeout=nav_timeout)
                        break
                    except Exception as nav_exc:
                        if nav_attempt == 0 and "timeout" in str(nav_exc).lower():
                            logger.warning(
                                "[SCRAPER] Navigation timed out (%sms), retrying in 5s…",
                                self.timeout,
                            )
                            page.wait_for_timeout(5000)
                            continue
                        raise
                nav_status = nav_response.status if nav_response is not None else None
                if nav_status in TRANSIENT_HTTP_STATUS_CODES:
                    raise TransientPortalError(
                        f"UzEx tender page returned retryable HTTP {nav_status}",
                        status_code=nav_status,
                    )
                
                # Step 1: Wait for page load
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                    logger.info("[SCRAPER] Page reached networkidle")
                except Exception:
                    logger.warning("[SCRAPER] Networkidle timeout, fallback wait")
                    page.wait_for_timeout(3000)
                
                # Step 2: Find and click ALL "Yuklab olish" (Download) buttons
                download_btns = page.query_selector_all(DOWNLOAD_TRIGGER_SELECTOR)
                button_samples = []
                for sample_btn in download_btns[:5]:
                    try:
                        button_samples.append(
                            {
                                "text": ((sample_btn.inner_text() or "").strip()[:80]),
                                "href": sample_btn.get_attribute("href"),
                                "onclick": sample_btn.get_attribute("onclick"),
                                "data_url": sample_btn.get_attribute("data-url"),
                                "data_href": sample_btn.get_attribute("data-href"),
                            }
                        )
                    except Exception:
                        continue
                logger.info(
                    "[SCRAPER] DOM extraction summary url=%s final_url=%s status=%s title=%s buttons=%s samples=%s",
                    source_url,
                    page.url,
                    nav_status,
                    page.title() or "",
                    len(download_btns),
                    button_samples,
                )
                
                for i, btn in enumerate(download_btns):
                    try:
                        btn_text = (btn.inner_text() or "").strip()[:20]
                        btn_marker = " ".join(
                            filter(
                                None,
                                [
                                    btn_text,
                                    btn.get_attribute("href") or "",
                                    btn.get_attribute("onclick") or "",
                                    btn.get_attribute("data-url") or "",
                                    btn.get_attribute("data-href") or "",
                                ],
                            )
                        ).lower()
                        if (
                            "yuklab" in btn_marker
                            or "olish" in btn_marker
                            or "download" in btn_marker
                            or "downloadfile" in btn_marker
                        ):
                            pre_click_count = len(captured_urls)
                            logger.info(
                                "[BUTTON CLICKER] Clicking button %s/%s: '%s'",
                                i + 1,
                                len(download_btns),
                                btn_text,
                            )
                            try:
                                btn.scroll_into_view_if_needed()
                            except Exception:
                                pass
                            attr_candidates = _extract_download_candidates_from_element(btn)
                            if attr_candidates:
                                captured_urls.extend(attr_candidates)
                                logger.info(
                                    "[BUTTON CLICKER] Button %s exposed %s attribute URL candidate(s)",
                                    i + 1,
                                    len(attr_candidates),
                                )
                            if not btn.is_visible():
                                logger.info(
                                    "[BUTTON CLICKER] Button %s skipped because it is hidden",
                                    i + 1,
                                )
                                continue
                            btn.click(force=True, timeout=5000, no_wait_after=True)
                            # ── Throttle: give the server time to generate the
                            # dynamic download URL before clicking the next button.
                            # Without this, Button N+1's click aborts Button N's
                            # in-flight URL generation request.
                            page.wait_for_timeout(3000)
                            post_click_count = len(captured_urls)
                            logger.info(
                                "[BUTTON CLICKER] Button %s captured %s new URL(s) (total: %s)",
                                i + 1,
                                post_click_count - pre_click_count,
                                post_click_count,
                            )
                    except Exception as e:
                        fallback_candidates = _extract_download_candidates_from_element(btn)
                        if fallback_candidates:
                            captured_urls.extend(fallback_candidates)
                            logger.warning(
                                "[BUTTON CLICKER] Button %s click failed, recovered %s URL candidate(s) from attributes: %s",
                                i + 1,
                                len(fallback_candidates),
                                e,
                            )
                            continue
                        logger.warning("[BUTTON CLICKER] Button %s click failed without URL fallback: %s", i + 1, e)
                        continue
                
                # Step 3: Also extract any static links with href
                static_links = page.query_selector_all(
                    "a[href*='download'], a[href*='DownloadFile'], a[href$='.pdf'], "
                    "a[href$='.doc'], a[href$='.docx'], a[href$='.xls'], a[href$='.xlsx'], "
                    "a[href$='.zip'], a[href$='.rar'], a[href$='.7z'], a[href$='.tar'], a[href$='.gz']"
                )
                logger.info("[SCRAPER] Static download link candidates: %s", len(static_links))
                for link in static_links:
                    try:
                        href = link.get_attribute("href")
                        if href and len(href) > 5:
                            captured_urls.append(href)
                    except Exception:
                        continue

                attribute_elements = page.query_selector_all(
                    "a[href], button[onclick], [onclick], [data-url], [data-href], [data-link], [data-path], [data-file]"
                )
                attribute_candidate_count = 0
                for element in attribute_elements:
                    for attr_name in DOCUMENT_ATTRIBUTE_NAMES:
                        try:
                            attr_value = element.get_attribute(attr_name)
                        except Exception:
                            attr_value = None
                        if not attr_value:
                            continue
                        extracted_candidates = _extract_download_candidates_from_text(attr_value)
                        attribute_candidate_count += len(extracted_candidates)
                        captured_urls.extend(extracted_candidates)

                try:
                    html_candidates = _extract_download_candidates_from_text(page.content())
                    captured_urls.extend(html_candidates)
                except Exception as exc:
                    html_candidates = []
                    logger.debug("[SCRAPER] Could not extract candidates from page HTML: %s", exc)
                
                # Step 4: Process captured URLs
                logger.info(
                    "[SCRAPER] Processing %s captured URLs (network/static/attrs/html totals: captured=%s static=%s attrs=%s html=%s)",
                    len(captured_urls),
                    len(captured_urls),
                    len(static_links),
                    attribute_candidate_count,
                    len(html_candidates),
                )
                if popup_urls:
                    logger.info("[SCRAPER] Popup URL candidates captured: %s", popup_urls[:10])
                
                for url in captured_urls:
                    try:
                        url_lower = url.lower()
                        
                        # Skip noise
                        if any(noise in url_lower for noise in NOISE_PATTERNS):
                            continue
                        
                        url = _normalize_download_candidate(url, portal_base_url=self.BASE_URL)
                        if not url:
                            continue
                        
                        # Skip duplicates
                        dedupe_key = _download_target_key(url) or url.lower()
                        if dedupe_key in seen_urls:
                            continue
                        seen_urls.add(dedupe_key)
                        
                        file_type = _detect_scraped_file_type(url)
                        
                        documents.append({
                            "file_url": url,
                            "file_type": file_type,
                        })
                        logger.info(f"[SCRAPER] Found: {file_type} - {url[:70]}...")
                        
                    except Exception as e:
                        logger.debug(f"[SCRAPER] URL processing error: {e}")
                        continue
                
                # Debug dump if no documents
                if len(documents) == 0 and debug:
                    page_title = page.title() or "Unknown"
                    logger.info(f"[DEBUG] Zero documents. Title: {page_title}")
                    print(f"[DEBUG] Page: {source_url}")
                    print(f"[DEBUG] Title: {page_title}")
                    print(f"[DEBUG] Captured URLs: {captured_urls}")
                elif len(documents) == 0:
                    logger.error(
                        "[SCRAPER] Zero documents extracted url=%s final_url=%s title=%s buttons=%s captured_urls=%s",
                        source_url,
                        page.url,
                        page.title() or "",
                        len(download_btns),
                        captured_urls[:10],
                    )
                
            except Exception as e:
                logger.error(f"[SCRAPER] Failed: {e}")
                if debug:
                    print(f"[ERROR] {e}")
                raise
            
            finally:
                browser.close()
        
        logger.info(f"[SCRAPER] Complete: {len(documents)} documents extracted")
        return documents
    
    def _sync_download_file_to_path(
        self,
        tender_url: str,
        file_path: str,
        destination_path: str,
        button_index: int = 0,
    ) -> str:
        """
        Download a file from UzEx directly to disk.

        This mirrors _sync_download_file but avoids carrying large PDFs/archives
        through worker memory before the database row is committed.
        """
        normalized_file_path = _extract_download_path(file_path)
        filename = _extract_filename(file_path) or "download"
        api_path_variants = _download_api_path_variants(file_path)
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        parsed_file_path = urlparse(file_path)
        normalized_static_url = _normalize_download_candidate(
            file_path,
            portal_base_url=self.BASE_URL,
        )
        normalized_file_root = normalized_file_path.lower().lstrip("/")
        is_concrete_static_file = (
            bool(normalized_file_path)
            and normalized_file_root.startswith(("files/", "tender/user-files/"))
            and _detect_file_extension(normalized_file_path) in KNOWN_FILE_EXTENSIONS
        )

        def remove_invalid_download() -> None:
            try:
                if destination.exists():
                    destination.unlink()
            except OSError:
                logger.warning("[DOWNLOAD] Failed to remove invalid partial file: %s", destination)

        def stream_url_to_destination(candidate_url: str, label: str) -> str:
            normalized_url = _normalize_download_candidate(
                candidate_url,
                portal_base_url=self.BASE_URL,
            )
            if not normalized_url:
                return ""

            normalized_lower = normalized_url.lower()
            if not any(marker in normalized_lower for marker in DOWNLOAD_URL_MARKERS):
                logger.info("[DOWNLOAD] %s URL ignored because it is not a download candidate: %s", label, normalized_url)
                return ""

            logger.info("[DOWNLOAD] %s stream fallback -> %s", label, normalized_url[:160])
            try:
                with httpx.stream(
                    "GET",
                    normalized_url,
                    timeout=httpx.Timeout(60.0, read=180.0),
                    follow_redirects=True,
                ) as response:
                    response_content_type = response.headers.get("content-type", "")
                    if response.status_code in TRANSIENT_HTTP_STATUS_CODES:
                        raise TransientPortalError(
                            f"UzEx fallback URL returned retryable HTTP {response.status_code}",
                            status_code=response.status_code,
                        )

                    with destination.open("wb") as file_handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            if chunk:
                                file_handle.write(chunk)

                    validation_name = (
                        normalized_url if _detect_file_extension(normalized_url) else file_path
                    )
                    file_size = destination.stat().st_size if destination.exists() else 0
                    if response.status_code == 200 and _is_valid_file_path_payload(
                        str(destination),
                        response_content_type,
                        validation_name,
                    ):
                        resolved_name = _extract_filename(normalized_url) or filename
                        logger.info(
                            "[DOWNLOAD] %s stream fallback success: %s bytes, ct=%s, name=%s",
                            label,
                            file_size,
                            response_content_type,
                            resolved_name,
                        )
                        return resolved_name

                    logger.warning(
                        "[DOWNLOAD] %s stream fallback rejected payload: HTTP %s, %s bytes, ct=%s",
                        label,
                        response.status_code,
                        file_size,
                        response_content_type,
                    )
                    remove_invalid_download()
                    return ""
            except (httpx.TimeoutException, httpx.TransportError, TransientPortalError):
                remove_invalid_download()
                raise
            except Exception as exc:
                remove_invalid_download()
                logger.warning("[DOWNLOAD] %s stream fallback error: %s", label, exc)
                return ""

        def api_post_to_destination() -> str:
            if not api_path_variants:
                logger.info("[DOWNLOAD] Strategy 1 POST skipped for empty path: %s", file_path)
                return ""

            for variant_index, api_file_path in enumerate(api_path_variants, start=1):
                encoded_file_path = quote(api_file_path, safe="/")
                download_api_url = (
                    "https://apietender.uzex.uz/api/common/DownloadFile"
                    f"?path={encoded_file_path}"
                )
                logger.info("[DOWNLOAD] Strategy 1 POST stream -> %s", download_api_url[:160])
                try:
                    with httpx.stream(
                        "POST",
                        download_api_url,
                        json={"path": api_file_path},
                        headers={
                            "Referer": tender_url,
                            "Origin": self.BASE_URL,
                            "Content-Type": "application/json",
                        },
                        timeout=httpx.Timeout(60.0, read=180.0),
                        follow_redirects=True,
                    ) as response:
                        response_content_type = response.headers.get("content-type", "")
                        if response.status_code in TRANSIENT_HTTP_STATUS_CODES:
                            raise TransientPortalError(
                                f"UzEx download API returned retryable HTTP {response.status_code}",
                                status_code=response.status_code,
                            )

                        with destination.open("wb") as file_handle:
                            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                                if chunk:
                                    file_handle.write(chunk)

                        file_size = destination.stat().st_size if destination.exists() else 0
                        if response.status_code == 200 and _is_valid_file_path_payload(
                            str(destination),
                            response_content_type,
                            api_file_path,
                        ):
                            logger.info(
                                "[DOWNLOAD] Strategy 1 POST stream success: %s bytes ct=%s path=%s api_path=%s",
                                file_size,
                                response_content_type,
                                destination,
                                api_file_path,
                            )
                            return filename

                        logger.warning(
                            "[DOWNLOAD] Strategy 1 POST stream rejected payload: HTTP %s, %s bytes, ct=%s api_path=%s variant=%s/%s",
                            response.status_code,
                            file_size,
                            response_content_type,
                            api_file_path,
                            variant_index,
                            len(api_path_variants),
                        )
                        remove_invalid_download()
                except (httpx.TimeoutException, httpx.TransportError):
                    remove_invalid_download()
                    raise
                except TransientPortalError:
                    remove_invalid_download()
                    raise
                except Exception as exc:
                    remove_invalid_download()
                    logger.warning(
                        "[DOWNLOAD] Strategy 1 POST stream error for api_path=%s variant=%s/%s: %s",
                        api_file_path,
                        variant_index,
                        len(api_path_variants),
                        exc,
                    )

            return ""

        def browser_goto_download_to_destination(context, candidate_url: str, label: str) -> str:
            normalized_url = _normalize_download_candidate(
                candidate_url,
                portal_base_url=self.BASE_URL,
            )
            if not normalized_url:
                return ""

            normalized_lower = normalized_url.lower()
            if not any(marker in normalized_lower for marker in DOWNLOAD_URL_MARKERS):
                return ""

            logger.info("[DOWNLOAD] %s browser navigation download -> %s", label, normalized_url[:160])
            file_page = context.new_page()
            try:
                with file_page.expect_download(timeout=45000) as download_info:
                    try:
                        file_page.goto(
                            normalized_url,
                            timeout=45000,
                            wait_until="domcontentloaded",
                            referer=tender_url,
                        )
                    except Exception as goto_exc:
                        if "net::ERR_ABORTED" not in str(goto_exc):
                            raise
                        logger.info(
                            "[DOWNLOAD] %s browser navigation aborted after download event: %s",
                            label,
                            goto_exc,
                        )
                download = download_info.value
                download.save_as(str(destination))
                suggested = download.suggested_filename or _extract_filename(normalized_url) or filename
                validation_name = (
                    suggested
                    if _detect_file_extension(suggested)
                    else normalized_url
                    if _detect_file_extension(normalized_url)
                    else file_path
                )
                file_size = destination.stat().st_size if destination.exists() else 0
                if _is_valid_file_path_payload(
                    str(destination),
                    "",
                    validation_name,
                ):
                    logger.info(
                        "[DOWNLOAD] %s browser navigation download success: %s bytes, name=%s",
                        label,
                        file_size,
                        suggested,
                    )
                    return suggested

                logger.warning(
                    "[DOWNLOAD] %s browser navigation download rejected payload: %s bytes, name=%s",
                    label,
                    file_size,
                    validation_name,
                )
                remove_invalid_download()
                return ""
            except PlaywrightTimeout as exc:
                remove_invalid_download()
                logger.warning("[DOWNLOAD] %s browser navigation download timed out: %s", label, exc)
                return ""
            except TransientPortalError:
                remove_invalid_download()
                raise
            except Exception as exc:
                remove_invalid_download()
                logger.warning("[DOWNLOAD] %s browser navigation download error: %s", label, exc)
                return ""
            finally:
                try:
                    file_page.close()
                except Exception:
                    pass

        resolved_name = api_post_to_destination()
        if resolved_name:
            return resolved_name

        # Strategy 2: Playwright download saved directly to target path.
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                accept_downloads=True,
            )
            page = context.new_page()

            try:
                logger.info("[DOWNLOAD] Loading tender page for disk download: %s", tender_url)
                nav_response = None
                for nav_attempt in range(2):
                    try:
                        nav_timeout = self.timeout if nav_attempt == 0 else 60000
                        nav_response = page.goto(tender_url, timeout=nav_timeout)
                        break
                    except Exception as nav_exc:
                        if nav_attempt == 0 and "timeout" in str(nav_exc).lower():
                            logger.warning(
                                "[DOWNLOAD] Navigation timed out (%sms), retrying in 5s",
                                self.timeout,
                            )
                            page.wait_for_timeout(5000)
                            continue
                        raise

                nav_status = nav_response.status if nav_response is not None else None
                if nav_status in TRANSIENT_HTTP_STATUS_CODES:
                    raise TransientPortalError(
                        f"UzEx tender page returned retryable HTTP {nav_status}",
                        status_code=nav_status,
                    )

                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    page.wait_for_timeout(5000)

                if is_concrete_static_file:
                    resolved_name = browser_goto_download_to_destination(
                        context,
                        normalized_static_url,
                        "static-file-url",
                    )
                    if resolved_name:
                        return resolved_name

                    raise Exception(
                        "UzEx direct document URL download failed after API POST and browser navigation "
                        f"fallback: {normalized_static_url}"
                    )

                if parsed_file_path.scheme in {"http", "https"} and parsed_file_path.netloc:
                    resolved_name = stream_url_to_destination(file_path, "non-static-url")
                    if resolved_name:
                        return resolved_name

                download_btns = page.query_selector_all(DOWNLOAD_TRIGGER_SELECTOR)
                button_samples = []
                for sample_btn in download_btns[:5]:
                    try:
                        button_samples.append(
                            {
                                "text": ((sample_btn.inner_text() or "").strip()[:80]),
                                "href": sample_btn.get_attribute("href"),
                                "onclick": sample_btn.get_attribute("onclick"),
                                "data_url": sample_btn.get_attribute("data-url"),
                                "data_href": sample_btn.get_attribute("data-href"),
                            }
                        )
                    except Exception:
                        continue
                logger.info(
                    "[DOWNLOAD] DOM summary final_url=%s status=%s buttons=%s target_index=%s samples=%s",
                    page.url,
                    nav_status,
                    len(download_btns),
                    button_index,
                    button_samples,
                )

                if button_index >= len(download_btns):
                    raise Exception(
                        f"Button index {button_index} out of bounds for "
                        f"{len(download_btns)} buttons on {tender_url}"
                    )

                target_btn = download_btns[button_index]
                try:
                    target_btn.scroll_into_view_if_needed()
                except Exception:
                    pass

                fallback_candidates = _extract_download_candidates_from_element(target_btn)
                popup_urls: list[str] = []
                download_events: list = []

                def capture_popup(popup):
                    try:
                        popup.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    try:
                        popup_url = popup.url
                    except Exception:
                        popup_url = ""
                    if popup_url:
                        popup_urls.append(popup_url)
                        logger.info("[DOWNLOAD] Popup captured for button %s: %s", button_index, popup_url[:160])
                    try:
                        popup.close()
                    except Exception:
                        pass

                def capture_download(download):
                    download_events.append(download)
                    logger.info(
                        "[DOWNLOAD] Browser download event captured for button %s: %s",
                        button_index,
                        download.suggested_filename,
                    )

                page.on("popup", capture_popup)
                page.on("download", capture_download)

                try:
                    target_btn.click(force=True, timeout=90000, no_wait_after=True)
                except Exception as click_exc:
                    logger.warning(
                        "[DOWNLOAD] Button %s click failed, trying %s attribute fallback URL(s): %s",
                        button_index,
                        len(fallback_candidates),
                        click_exc,
                    )
                    for candidate in fallback_candidates:
                        resolved_name = stream_url_to_destination(candidate, "button-attribute")
                        if resolved_name:
                            return resolved_name
                    raise

                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    while popup_urls:
                        popup_url = popup_urls.pop(0)
                        resolved_name = stream_url_to_destination(popup_url, "popup")
                        if resolved_name:
                            return resolved_name

                    while download_events:
                        download = download_events.pop(0)
                        download.save_as(str(destination))
                        suggested = download.suggested_filename or filename
                        validation_name = suggested if _detect_file_extension(suggested) else file_path
                        file_size = destination.stat().st_size if destination.exists() else 0

                        if not _is_valid_file_path_payload(str(destination), "", validation_name):
                            remove_invalid_download()
                            raise Exception(
                                f"Browser download event returned invalid payload: "
                                f"{file_size} bytes ({validation_name})"
                            )

                        logger.info(
                            "[DOWNLOAD] Browser download disk success at index %s: %s bytes, name=%s path=%s",
                            button_index,
                            file_size,
                            suggested,
                            destination,
                        )
                        return suggested

                    page.wait_for_timeout(500)

                logger.warning(
                    "[DOWNLOAD] Button %s produced no browser download/popup after 90000ms; trying %s attribute fallback URL(s)",
                    button_index,
                    len(fallback_candidates),
                )
                for candidate in fallback_candidates:
                    resolved_name = stream_url_to_destination(candidate, "button-attribute-timeout")
                    if resolved_name:
                        return resolved_name

                raise PlaywrightTimeout(
                    f"Timed out after 90000ms waiting for download or popup from button {button_index}"
                )

            finally:
                browser.close()

    def _sync_download_file(
        self, tender_url: str, file_path: str, button_index: int = 0
    ) -> tuple[bytes, str]:
        """
        Compatibility wrapper for API callers that still need bytes.

        The actual UzEx transfer is disk-first; this method only reads the
        completed temp file back into memory for the HTTP response path.
        """
        tmp_path = os.path.join(tempfile.gettempdir(), f"plasma_dl_{uuid4().hex}")
        try:
            suggested = self._sync_download_file_to_path(
                tender_url=tender_url,
                file_path=file_path,
                destination_path=tmp_path,
                button_index=button_index,
            )
            with open(tmp_path, "rb") as file_handle:
                return file_handle.read(), suggested
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    logger.warning("[DOWNLOAD] Failed to remove compatibility temp file: %s", tmp_path)

    @retry(
        retry=retry_if_exception(_is_transient_exception),
        wait=wait_exponential_jitter(initial=2, max=60),
        stop=stop_after_attempt(4),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def download_file(
        self, tender_url: str, file_path: str, button_index: int = 0
    ) -> tuple[bytes, str]:
        """
        Download a file from UzEx tender page.
        
        Args:
            tender_url: URL of the tender detail page
            file_path: The file path from the DownloadFile API
            button_index: Spatial index of the download button in DOM order
        
        Returns:
            Tuple of (file_bytes, filename)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            partial(self._sync_download_file, tender_url, file_path, button_index)
        )

    @retry(
        retry=retry_if_exception(_is_transient_exception),
        wait=wait_exponential_jitter(initial=2, max=60),
        stop=stop_after_attempt(4),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def download_file_to_path(
        self,
        tender_url: str,
        file_path: str,
        destination_path: str,
        button_index: int = 0,
    ) -> str:
        """
        Download a file from UzEx tender page directly to disk.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            partial(
                self._sync_download_file_to_path,
                tender_url,
                file_path,
                destination_path,
                button_index,
            ),
        )
    
    @retry(
        retry=retry_if_exception(_is_transient_exception),
        wait=wait_exponential_jitter(initial=2, max=60),
        stop=stop_after_attempt(4),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def scrape_tender_documents(self, source_url: str) -> list[dict]:
        """
        Scrape document links from a tender detail page.
        
        Args:
            source_url: URL of the tender detail page
            
        Returns:
            List of dicts with file_url and file_type
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            partial(self._sync_scrape_documents, source_url)
        )
    
    async def fetch_latest_tenders(self, limit: int = 20) -> list[ScrapedTender]:
        """
        Fetch latest tenders from UzEx portal via direct API call.
        
        Uses the discovered JSON API at apietender.uzex.uz instead of 
        Playwright browser scraping, making it reliable in Docker.
        
        Args:
            limit: Max tenders to return (default 20)
            
        Returns:
            List of ScrapedTender objects with category assigned.
        """
        import httpx
        
        API_URL = "https://apietender.uzex.uz/api/common/TradeList"
        
        # Region name mapping (Russian -> English)
        REGION_MAP = {
            'ташкент': 'Tashkent',
            'навои': 'Navoi',
            'самарканд': 'Samarkand',
            'бухар': 'Bukhara',
            'ферган': 'Fergana',
            'андижан': 'Andijan',
            'наманган': 'Namangan',
            'хорезм': 'Khorezm',
            'сурхандар': 'Surkhandarya',
            'кашкадар': 'Kashkadarya',
            'джизак': 'Jizzakh',
            'сырдар': 'Sirdarya',
            'каракалпак': 'Karakalpakstan',
        }
        
        tenders: list[ScrapedTender] = []
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    API_URL,
                    json={"TypeId": 2, "From": 1, "To": limit, "System_Id": 0},
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                lots = response.json()
            
            logger.info(f"[API] Received {len(lots)} lots from TradeList API")
            
            for lot in lots:
                try:
                    lot_id = str(lot.get("id", ""))
                    title = lot.get("name", "").strip()
                    cost = float(lot.get("cost", 0) or 0)
                    currency = lot.get("currency_codeabc", "UZS") or "UZS"
                    
                    # Parse deadline
                    deadline = None
                    end_date_str = lot.get("end_date")
                    if end_date_str:
                        try:
                            deadline = datetime.fromisoformat(end_date_str).replace(tzinfo=timezone.utc)
                        except (ValueError, TypeError):
                            pass
                    
                    # Map region from Russian to English
                    region_raw = lot.get("region_name", "") or ""
                    region = None
                    for ru_key, en_name in REGION_MAP.items():
                        if ru_key in region_raw.lower():
                            region = en_name
                            break
                    if not region and region_raw:
                        region = region_raw  # Keep original if no mapping found
                    
                    # Detect category from title
                    category = detect_category(title)
                    
                    source_url = f"{self.BASE_URL}/lot/{lot_id}"
                    
                    tender = ScrapedTender(
                        external_id=lot_id,
                        title=title,
                        budget=cost,
                        currency=currency,
                        region=region,
                        source_url=source_url,
                        category=category,
                        deadline=deadline,
                    )
                    tenders.append(tender)
                    logger.info(f"[API] [{category}] {lot_id}: {title[:50]}...")
                    
                except Exception as e:
                    logger.warning(f"[API] Failed to parse lot: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"[API] TradeList fetch failed: {e}")
            raise
        
        logger.info(f"[API] Processed {len(tenders)} tenders")
        return tenders


def test_scraper():
    """Test the scraper."""
    scraper = UzExScraper(headless=True)
    tenders = scraper._sync_fetch_all_tenders(limit=15)
    
    print(f"\n{'='*60}")
    print(f"Total: {len(tenders)} tenders")
    print('='*60)
    
    # Group by category
    by_cat: dict[str, list] = {}
    for t in tenders:
        by_cat.setdefault(t.category, []).append(t)
    
    for cat, items in sorted(by_cat.items()):
        print(f"\n=== {cat} ({len(items)}) ===")
        for t in items[:3]:
            print(f"  {t.external_id}: {t.title[:50]}...")


if __name__ == "__main__":
    test_scraper()
