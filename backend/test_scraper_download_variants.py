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


if __name__ == "__main__":
    unittest.main()
