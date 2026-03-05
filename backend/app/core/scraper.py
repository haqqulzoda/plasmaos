"""
Plasma AI - UzEx Tender Scraper

Playwright-based scraper for etender.uzex.uz portal.
Scrapes the main tender list and classifies by keywords.

Note: Uses sync Playwright in a thread executor to avoid Windows async issues.
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

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

ARCHIVE_EXTENSIONS = {"zip", "rar", "7z", "tar", "gz"}


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
        return _looks_like_zip_bytes(file_bytes) or "application/zip" in normalized_content_type

    if extension == "rar":
        return _looks_like_rar_bytes(file_bytes) or "rar" in normalized_content_type

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
            
            # Set up network interceptor to capture download URLs
            def capture_download_request(request):
                url = request.url.lower()
                if any(marker in url for marker in DOWNLOAD_URL_MARKERS):
                    if 'apietender' in url or 'cdn.uzex' in url or '/api/' in url:
                        captured_urls.append(request.url)
                        logger.info(f"[INTERCEPTOR] Captured: {request.url[:80]}...")
            
            page.on("request", capture_download_request)
            
            try:
                logger.info(f"[SCRAPER] Fetching: {source_url}")
                page.goto(source_url, timeout=self.timeout)
                
                # Step 1: Wait for page load
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                    logger.info("[SCRAPER] Page reached networkidle")
                except Exception:
                    logger.warning("[SCRAPER] Networkidle timeout, fallback wait")
                    page.wait_for_timeout(3000)
                
                # Step 2: Find and click ALL "Yuklab olish" (Download) buttons
                download_btns = page.query_selector_all(
                    "a.btn-success, button.btn-success, a:has-text('Yuklab olish'), button:has-text('Yuklab olish')"
                )
                logger.info(f"[BUTTON CLICKER] Found {len(download_btns)} download buttons")
                
                for i, btn in enumerate(download_btns):
                    try:
                        btn_text = (btn.inner_text() or "").strip()[:20]
                        if "Yuklab" in btn_text or "olish" in btn_text.lower():
                            logger.debug(f"[BUTTON CLICKER] Clicking button {i+1}: '{btn_text}'")
                            btn.click()
                            page.wait_for_timeout(1500)  # Wait for network request
                    except Exception as e:
                        logger.debug(f"[BUTTON CLICKER] Button {i+1} click failed: {e}")
                        continue
                
                # Step 3: Also extract any static links with href
                static_links = page.query_selector_all(
                    "a[href*='download'], a[href*='DownloadFile'], a[href$='.pdf'], "
                    "a[href$='.doc'], a[href$='.docx'], a[href$='.xls'], a[href$='.xlsx'], "
                    "a[href$='.zip'], a[href$='.rar'], a[href$='.7z'], a[href$='.tar'], a[href$='.gz']"
                )
                for link in static_links:
                    try:
                        href = link.get_attribute("href")
                        if href and len(href) > 5:
                            captured_urls.append(href)
                    except Exception:
                        continue
                
                # Step 4: Process captured URLs
                logger.info(f"[SCRAPER] Processing {len(captured_urls)} captured URLs")
                
                for url in captured_urls:
                    try:
                        url_lower = url.lower()
                        
                        # Skip noise
                        if any(noise in url_lower for noise in NOISE_PATTERNS):
                            continue
                        
                        # Make absolute URL
                        if url.startswith("//"):
                            url = "https:" + url
                        elif url.startswith("/"):
                            url = self.BASE_URL + url
                        elif not url.startswith("http"):
                            url = self.BASE_URL + "/" + url
                        
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
                
            except Exception as e:
                logger.error(f"[SCRAPER] Failed: {e}")
                if debug:
                    print(f"[ERROR] {e}")
                raise
            
            finally:
                browser.close()
        
        logger.info(f"[SCRAPER] Complete: {len(documents)} documents extracted")
        return documents
    
    def _sync_download_file(self, tender_url: str, file_path: str) -> tuple[bytes, str]:
        """
        Download a file from UzEx.

        Strategy (ordered by reliability for binary files):
        1. Direct HTTP GET to the DownloadFile API URL (fastest, no browser)
        2. Playwright download event (captures browser-triggered saves)
        3. Response interception fallback (legacy, less reliable for archives)
        """
        import httpx
        import os
        import tempfile

        normalized_file_path = _extract_download_path(file_path)
        target_key = _download_target_key(file_path)
        requested_extension = _detect_file_extension(file_path)
        filename = _extract_filename(file_path) or "download"

        if requested_extension not in ARCHIVE_EXTENSIONS and normalized_file_path:
            download_api_url = f"https://apietender.uzex.uz/api/common/DownloadFile?path={normalized_file_path}"
            try:
                logger.info(f"[DOWNLOAD] Strategy 1: Direct HTTP GET -> {download_api_url[:80]}")
                response = httpx.get(download_api_url, timeout=30, follow_redirects=True)
                response_content_type = response.headers.get("content-type", "")
                if response.status_code == 200 and _is_valid_file_payload(
                    response.content,
                    response_content_type,
                    normalized_file_path,
                ):
                    logger.info(f"[DOWNLOAD] Strategy 1 success: {len(response.content)} bytes")
                    return response.content, filename

                logger.warning(
                    "[DOWNLOAD] Strategy 1 rejected payload: HTTP %s, %s bytes, ct=%s",
                    response.status_code,
                    len(response.content),
                    response_content_type,
                )
            except Exception as exc:
                logger.warning(f"[DOWNLOAD] Strategy 1 error: {exc}")
        else:
            logger.info("[DOWNLOAD] Strategy 1 skipped for archive or empty path: %s", file_path)

        file_content = b""

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                accept_downloads=True,
            )
            page = context.new_page()

            captured_files: list[dict] = []

            def capture_file_response(response):
                url_lower = response.url.lower()
                if "downloadfile" in url_lower and response.status == 200:
                    try:
                        body = response.body()
                        content_type = response.headers.get("content-type", "")
                        if _is_valid_file_payload(body, content_type, response.url):
                            captured_files.append(
                                {
                                    "url": response.url,
                                    "body": body,
                                    "content_type": content_type,
                                }
                            )
                            logger.info(
                                f"[DOWNLOAD] Intercepted {len(body)} bytes from {response.url[:60]}"
                            )
                    except Exception as exc:
                        logger.debug(f"[DOWNLOAD] Intercept body failed: {exc}")

            page.on("response", capture_file_response)

            try:
                logger.info(f"[DOWNLOAD] Loading tender page: {tender_url}")
                page.goto(tender_url, timeout=self.timeout)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    page.wait_for_timeout(5000)

                download_btns = page.query_selector_all(
                    "a.btn-success, button.btn-success, a:has-text('Yuklab olish'), "
                    "button:has-text('Yuklab olish'), a[href*='DownloadFile']"
                )
                logger.info(f"[DOWNLOAD] Found {len(download_btns)} download buttons")

                for i, btn in enumerate(download_btns):
                    try:
                        try:
                            with page.expect_download(timeout=10000) as download_info:
                                btn.click()
                            download = download_info.value

                            tmp_path = os.path.join(tempfile.gettempdir(), f"plasma_dl_{i}")
                            download.save_as(tmp_path)
                            with open(tmp_path, "rb") as file_handle:
                                dl_bytes = file_handle.read()
                            os.unlink(tmp_path)

                            suggested = download.suggested_filename or filename

                            if _is_valid_file_payload(dl_bytes, "", suggested):
                                if target_key and _download_target_key(download.url or "") == target_key:
                                    logger.info(
                                        f"[DOWNLOAD] Strategy 2 matched target: {len(dl_bytes)} bytes"
                                    )
                                    browser.close()
                                    return dl_bytes, suggested

                                if not file_content:
                                    file_content = dl_bytes
                                    filename = suggested
                                    logger.info(
                                        f"[DOWNLOAD] Strategy 2 captured: {len(dl_bytes)} bytes ({suggested})"
                                    )

                        except PlaywrightTimeout:
                            btn.click()
                            page.wait_for_timeout(2000)

                        for captured in captured_files:
                            response_key = _download_target_key(captured["url"])
                            if target_key and response_key == target_key:
                                logger.info(
                                    f"[DOWNLOAD] Strategy 3 matched target: {len(captured['body'])} bytes"
                                )
                                browser.close()
                                return captured["body"], _extract_filename(captured["url"]) or filename

                    except Exception as exc:
                        logger.debug(f"[DOWNLOAD] Button {i + 1} processing failed: {exc}")
                        continue

                if file_content and _is_valid_file_payload(file_content, "", filename):
                    logger.info(f"[DOWNLOAD] Using download event capture: {len(file_content)} bytes")
                elif captured_files:
                    file_content = captured_files[0]["body"]
                    filename = _extract_filename(captured_files[0]["url"]) or filename
                    logger.info(
                        f"[DOWNLOAD] Using first intercepted response: {len(file_content)} bytes"
                    )
                else:
                    raise Exception(f"Could not download file: {file_path}")

            finally:
                browser.close()

        return file_content, filename

    async def download_file(self, tender_url: str, file_path: str) -> tuple[bytes, str]:
        """
        Download a file from UzEx tender page.
        
        Args:
            tender_url: URL of the tender detail page
            file_path: The file path from the DownloadFile API
        
        Returns:
            Tuple of (file_bytes, filename)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            partial(self._sync_download_file, tender_url, file_path)
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

