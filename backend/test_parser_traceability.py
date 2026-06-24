"""
Validation script for parser source traceability markers and OCR bypass.
"""

import os
import unittest
from unittest.mock import patch

from app.core import parser


class FakePage:
    def __init__(self, text: str = "", visual: bool = False):
        self._text = text
        self._visual = visual

    def get_text(self):
        return self._text

    def get_images(self, full=True):
        return [("image",)] if self._visual else []

    def get_drawings(self):
        return []


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(self.pages)


class FakeParagraph:
    def __init__(self, text: str):
        self.text = text


class FakeDocx:
    paragraphs = [FakeParagraph("DOCX paragraph text")]
    tables = []


class ParserTraceabilityTest(unittest.TestCase):
    def test_single_pdf_emits_file_and_page_markers(self):
        pages = [FakePage("Native text long enough for extraction " * 3)]

        with patch("app.core.parser.fitz.open", return_value=FakePdf(pages)):
            text = parser.parse_pdf(b"%PDF-1.4", file_path="/tmp/source.pdf")

        self.assertIn("[[FILE: source.pdf]]", text)
        self.assertIn("[[PAGE 1]]", text)
        self.assertIn("Native text long enough", text)

    def test_archive_txt_member_preserves_filename_and_page_one(self):
        text = parser._parse_extracted_documents(
            [{"filename": "terms.txt", "file_bytes": b"Submit via portal"}]
        )

        self.assertIn("[[FILE: terms.txt]]", text)
        self.assertIn("[[PAGE 1]]", text)
        self.assertIn("Submit via portal", text)

    def test_docx_and_txt_get_page_one_markers(self):
        txt = parser.extract_text_from_bytes(b"Plain tender text", "txt")

        self.assertIn("[[FILE: uploaded_document.txt]]", txt)
        self.assertIn("[[PAGE 1]]", txt)

        with patch("app.core.parser.docx.Document", return_value=FakeDocx()):
            docx = parser.parse_docx(b"fake docx bytes", file_path="legacy.docx")

        self.assertIn("[[FILE: legacy.docx]]", docx)
        self.assertIn("[[PAGE 1]]", docx)
        self.assertIn("DOCX paragraph text", docx)

    def test_legacy_markerless_text_is_wrapped_for_compilation(self):
        repaired = parser.ensure_trace_markers(
            "legacy.docx",
            "Legacy parsed text without provenance.",
        )

        self.assertEqual(
            repaired,
            (
                "[[FILE: legacy.docx]]\n"
                "[[PAGE 1]]\n"
                "Legacy parsed text without provenance."
            ),
        )

    def test_markerized_text_is_not_double_wrapped(self):
        existing = "[[FILE: source.pdf]]\n[[PAGE 4]]\nAlready traceable."

        repaired = parser.ensure_trace_markers("ignored.docx", existing)

        self.assertEqual(repaired, existing)
        self.assertEqual(repaired.count("[[FILE:"), 1)
        self.assertEqual(repaired.count("[[PAGE"), 1)

    def test_demo_ocr_bypass_allows_ocr_past_default_page_cap(self):
        pages = [FakePage("", visual=True) for _ in range(parser.OCR_MAX_PAGES + 1)]

        def fake_ocr(_pdf_bytes, page_number):
            return f"OCR text page {page_number}"

        old_value = os.environ.get(parser.DEMO_OCR_BYPASS_ENV)
        os.environ[parser.DEMO_OCR_BYPASS_ENV] = "true"
        try:
            with patch("app.core.parser.fitz.open", return_value=FakePdf(pages)), patch(
                "app.core.parser._ocr_pdf_page_from_pdf_bytes",
                side_effect=fake_ocr,
            ):
                text = parser.parse_pdf(b"%PDF-1.4", file_path="scan.pdf")
        finally:
            if old_value is None:
                os.environ.pop(parser.DEMO_OCR_BYPASS_ENV, None)
            else:
                os.environ[parser.DEMO_OCR_BYPASS_ENV] = old_value

        self.assertIn(f"[[PAGE {parser.OCR_MAX_PAGES + 1}]]", text)
        self.assertIn(f"OCR text page {parser.OCR_MAX_PAGES + 1}", text)

    def test_ocr_is_skipped_after_enough_native_pdf_text(self):
        pages = [
            FakePage("Native searchable tender text " * 20),
            FakePage("", visual=True),
        ]

        with patch.dict(os.environ, {parser.DEMO_OCR_BYPASS_ENV: ""}), patch(
            "app.core.parser.OCR_SKIP_AFTER_TEXT_CHARS",
            100,
        ), patch(
            "app.core.parser.fitz.open",
            return_value=FakePdf(pages),
        ), patch("app.core.parser._ocr_pdf_page_from_pdf_bytes") as ocr_page:
            text = parser.parse_pdf(b"%PDF-1.4", file_path="mixed.pdf")

        ocr_page.assert_not_called()
        self.assertIn("[[PAGE 1]]", text)
        self.assertIn("Native searchable tender text", text)
        self.assertNotIn("[[PAGE 2]]", text)


if __name__ == "__main__":
    unittest.main()
