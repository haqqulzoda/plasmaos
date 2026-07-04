import tempfile
import sys
import types
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch


def install_missing_dependency_stubs():
    if find_spec("httpx") is None:
        httpx_stub = types.ModuleType("httpx")
        httpx_stub.TimeoutException = type("TimeoutException", (Exception,), {})
        httpx_stub.TransportError = type("TransportError", (Exception,), {})
        httpx_stub.Timeout = lambda *args, **kwargs: (args, kwargs)
        httpx_stub.stream = None
        sys.modules["httpx"] = httpx_stub

    if find_spec("rarfile") is None:
        rarfile_stub = types.ModuleType("rarfile")
        rarfile_stub.Error = type("RarfileError", (Exception,), {})
        rarfile_stub.RarFile = object
        sys.modules["rarfile"] = rarfile_stub

    if find_spec("playwright") is None:
        playwright_stub = types.ModuleType("playwright")
        sync_api_stub = types.ModuleType("playwright.sync_api")
        sync_api_stub.TimeoutError = type("PlaywrightTimeoutError", (Exception,), {})
        sync_api_stub.sync_playwright = None
        sys.modules["playwright"] = playwright_stub
        sys.modules["playwright.sync_api"] = sync_api_stub

    if find_spec("tenacity") is None:
        tenacity_stub = types.ModuleType("tenacity")
        tenacity_stub.retry = lambda *args, **kwargs: (lambda func: func)
        tenacity_stub.retry_if_exception = lambda *args, **kwargs: None
        tenacity_stub.stop_after_attempt = lambda *args, **kwargs: None
        tenacity_stub.wait_exponential_jitter = lambda *args, **kwargs: None
        tenacity_stub.before_sleep_log = lambda *args, **kwargs: None
        sys.modules["tenacity"] = tenacity_stub


install_missing_dependency_stubs()

from app.core import scraper as scraper_module
from app.core.scraper import UzExScraper, _download_api_path_variants


class MockStreamResponse:
    def __init__(self, status_code, content_type, body):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def iter_bytes(self, chunk_size):
        for index in range(0, len(self._body), chunk_size):
            yield self._body[index : index + chunk_size]


class FakeDownload:
    def __init__(self, body, suggested_filename="fallback.pdf"):
        self._body = body
        self.suggested_filename = suggested_filename

    def save_as(self, path):
        Path(path).write_bytes(self._body)


class FakeDownloadButton:
    def __init__(self, page, download):
        self.page = page
        self.download = download

    def inner_text(self):
        return "Download"

    def get_attribute(self, name):
        return None

    def scroll_into_view_if_needed(self):
        return None

    def click(self, **kwargs):
        self.page.clicked = True
        if "download" in self.page.handlers:
            self.page.handlers["download"](self.download)


class FakeExpectDownload:
    def __init__(self, download):
        self.value = download

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeTenderPage:
    url = "https://etender.uzex.uz/lot/500023"

    def __init__(self, download):
        self.download = download
        self.handlers = {}
        self.clicked = False

    def goto(self, *args, **kwargs):
        return types.SimpleNamespace(status=200)

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def query_selector_all(self, selector):
        return [FakeDownloadButton(self, self.download)]

    def on(self, event, callback):
        self.handlers[event] = callback

    def expect_download(self, **kwargs):
        return FakeExpectDownload(self.download)


class FakeStaticDownloadPage:
    def expect_download(self, **kwargs):
        raise scraper_module.PlaywrightTimeout("static download timed out")

    def close(self):
        return None


class FakeBrowserContext:
    def __init__(self, download):
        self.tender_page = FakeTenderPage(download)
        self._new_page_calls = 0

    def new_page(self):
        self._new_page_calls += 1
        if self._new_page_calls == 1:
            return self.tender_page
        return FakeStaticDownloadPage()


class FakeBrowser:
    def __init__(self, context):
        self.context = context

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        return None


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, **kwargs):
        return self.browser


class FakePlaywright:
    def __init__(self, context):
        self.context = context

    def __enter__(self):
        return types.SimpleNamespace(
            chromium=FakeChromium(FakeBrowser(self.context))
        )

    def __exit__(self, exc_type, exc, traceback):
        return False


class ScraperDownloadVariantsTest(unittest.TestCase):
    def test_download_api_path_variants_for_leading_slash_files_path(self):
        self.assertEqual(
            _download_api_path_variants("/files/a.pdf"),
            ["/files/a.pdf", "files/a.pdf"],
        )

    def test_download_api_path_variants_for_relative_files_path(self):
        self.assertEqual(
            _download_api_path_variants("files/a.pdf"),
            ["files/a.pdf", "/files/a.pdf"],
        )

    def test_download_api_path_variants_for_static_url(self):
        self.assertEqual(
            _download_api_path_variants("https://etender.uzex.uz/files/a.pdf"),
            ["/files/a.pdf", "files/a.pdf"],
        )

    def test_api_trade_file_fields_keep_dom_fallback_order(self):
        self.assertEqual(
            scraper_module.API_TRADE_FILE_PATH_FIELDS[:2],
            ("tech_file_path", "expertise_file_path"),
        )
        self.assertIsInstance(scraper_module.API_TRADE_FILE_PATH_FIELDS, tuple)

    def test_api_post_tries_relative_variant_after_slash_variant_rejection(self):
        calls = []
        pdf_body = b"%PDF-1.4\n" + (b"valid pdf payload\n" * 16)

        def fake_stream(method, url, **kwargs):
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "path": kwargs.get("json", {}).get("path"),
                }
            )
            if kwargs.get("json", {}).get("path") == "/files/a.pdf":
                return MockStreamResponse(
                    500,
                    "application/json",
                    b'{"status":500,"message":"Object reference not set"}',
                )
            return MockStreamResponse(200, "application/pdf", pdf_body)

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "download.pdf"
            scraper = UzExScraper()

            with patch("app.core.scraper.httpx.stream", side_effect=fake_stream), patch(
                "app.core.scraper.sync_playwright",
                side_effect=AssertionError("browser fallback should not be used"),
            ):
                filename = scraper._sync_download_file_to_path(
                    tender_url="https://etender.uzex.uz/lot/482849",
                    file_path="https://etender.uzex.uz/files/a.pdf",
                    destination_path=str(destination),
                )
                downloaded_prefix = destination.read_bytes()[:4]

        self.assertEqual(filename, "a.pdf")
        self.assertEqual([call["path"] for call in calls], ["/files/a.pdf", "files/a.pdf"])
        self.assertEqual(calls[0]["method"], "POST")
        self.assertIn("path=/files/a.pdf", calls[0]["url"])
        self.assertEqual(downloaded_prefix, b"%PDF")

    def test_api_post_rejects_html_response_before_trying_next_variant(self):
        calls = []
        pdf_body = b"%PDF-1.4\n" + (b"valid pdf payload\n" * 16)

        def fake_stream(method, url, **kwargs):
            calls.append(kwargs.get("json", {}).get("path"))
            if kwargs.get("json", {}).get("path") == "/files/html.pdf":
                return MockStreamResponse(
                    200,
                    "text/html; charset=utf-8",
                    b"<html><body>not a document</body></html>",
                )
            return MockStreamResponse(200, "application/pdf", pdf_body)

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "download.pdf"
            scraper = UzExScraper()

            with patch("app.core.scraper.httpx.stream", side_effect=fake_stream), patch(
                "app.core.scraper.sync_playwright",
                side_effect=AssertionError("browser fallback should not be used"),
            ):
                filename = scraper._sync_download_file_to_path(
                    tender_url="https://etender.uzex.uz/lot/500023",
                    file_path="https://etender.uzex.uz/files/html.pdf",
                    destination_path=str(destination),
                )
                downloaded_prefix = destination.read_bytes()[:4]

        self.assertEqual(filename, "html.pdf")
        self.assertEqual(calls, ["/files/html.pdf", "files/html.pdf"])
        self.assertEqual(downloaded_prefix, b"%PDF")

    def test_static_api_and_direct_failure_falls_back_to_dom_button_download(self):
        calls = []
        pdf_body = b"%PDF-1.4\n" + (b"valid dom fallback payload\n" * 16)
        download = FakeDownload(pdf_body, suggested_filename="dom-fallback.pdf")
        fake_context = FakeBrowserContext(download)

        def fake_stream(method, url, **kwargs):
            calls.append(
                {
                    "method": method,
                    "path": kwargs.get("json", {}).get("path"),
                    "url": url,
                }
            )
            if method == "GET":
                return MockStreamResponse(
                    200,
                    "text/html; charset=utf-8",
                    b"<html><body>not a document</body></html>",
                )
            return MockStreamResponse(
                500,
                "application/json",
                b'{"status":500,"message":"No route to host"}',
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "download.pdf"
            scraper = UzExScraper()

            with patch("app.core.scraper.httpx.stream", side_effect=fake_stream), patch(
                "app.core.scraper.sync_playwright",
                return_value=FakePlaywright(fake_context),
            ):
                filename = scraper._sync_download_file_to_path(
                    tender_url="https://etender.uzex.uz/lot/500023",
                    file_path="https://etender.uzex.uz/files/a.pdf",
                    destination_path=str(destination),
                    button_index=0,
                )
                downloaded_prefix = destination.read_bytes()[:4]

        self.assertEqual(filename, "dom-fallback.pdf")
        self.assertTrue(fake_context.tender_page.clicked)
        self.assertEqual(downloaded_prefix, b"%PDF")
        self.assertEqual(
            [call["path"] for call in calls if call["method"] == "POST"],
            ["/files/a.pdf", "files/a.pdf"],
        )
        self.assertEqual([call["method"] for call in calls].count("GET"), 1)


if __name__ == "__main__":
    unittest.main()
