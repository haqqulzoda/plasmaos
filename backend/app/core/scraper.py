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
from typing import Optional

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
                if any(x in url for x in ['downloadfile', 'download', '.pdf', '.doc', '.xls', '.zip']):
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
                static_links = page.query_selector_all("a[href*='download'], a[href$='.pdf'], a[href$='.doc']")
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
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        # Determine file type - PDF or Bust normalization
                        ext = url_lower.split('.')[-1].split('?')[0]  # Handle query strings
                        if ext in ['zip', 'rar', '7z', 'tar']:
                            file_type = "archive"
                        elif ext == 'pdf':
                            file_type = "pdf"
                        elif ext in ['doc', 'docx']:
                            file_type = "word"
                        else:
                            file_type = "unknown"
                        
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
        Download a file from UzEx by navigating to tender page and clicking download.
        
        Uses response interception to capture file bytes from the network layer.
        
        Args:
            tender_url: URL of the tender detail page (e.g., https://etender.uzex.uz/lot/465790)
            file_path: The file path from the DownloadFile API (e.g., /files/2025/12/23/xxx.pdf)
        
        Returns:
            Tuple of (file_bytes, filename)
        """
        file_content = b""
        filename = file_path.split("/")[-1] if file_path else "download"
        captured_files: list[dict] = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = context.new_page()
            
            # Set up response interceptor to capture file bytes
            def capture_file_response(response):
                url_lower = response.url.lower()
                if 'downloadfile' in url_lower and response.status == 200:
                    try:
                        body = response.body()
                        captured_files.append({
                            "url": response.url,
                            "body": body,
                        })
                        logger.info(f"[DOWNLOAD] Captured {len(body)} bytes from {response.url[:60]}...")
                    except Exception as e:
                        logger.debug(f"[DOWNLOAD] Failed to capture response body: {e}")
            
            page.on("response", capture_file_response)
            
            try:
                logger.info(f"[DOWNLOAD] Loading tender page: {tender_url}")
                page.goto(tender_url, timeout=self.timeout)
                page.wait_for_timeout(5000)
                
                # Click download buttons until we find our target file
                download_btns = page.query_selector_all("a.btn-success")
                logger.info(f"[DOWNLOAD] Found {len(download_btns)} download buttons")
                
                for i, btn in enumerate(download_btns):
                    try:
                        btn.click()
                        page.wait_for_timeout(2000)
                        
                        # Check if we captured our target file
                        for cf in captured_files:
                            if file_path in cf["url"]:
                                file_content = cf["body"]
                                logger.info(f"[DOWNLOAD] Found target file: {len(file_content)} bytes")
                                break
                        
                        if file_content:
                            break
                    except Exception as e:
                        logger.debug(f"[DOWNLOAD] Button {i+1} click failed: {e}")
                        continue
                
                # If we didn't find the specific file, return the first captured file
                if not file_content and captured_files:
                    file_content = captured_files[0]["body"]
                    logger.info(f"[DOWNLOAD] Using first captured file: {len(file_content)} bytes")
                
                if not file_content:
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
        Fetch latest tenders from UzEx portal.
        
        Scrapes the main tender list and categorizes by keyword detection.
        
        Args:
            limit: Max tenders to return (default 20)
            
        Returns:
            List of ScrapedTender objects with category assigned.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            partial(self._sync_fetch_all_tenders, limit)
        )


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
