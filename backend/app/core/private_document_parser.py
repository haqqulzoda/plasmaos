"""Isolated W3 parser for checked private PDF and DOCX bytes; never uses network AI."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree
from zipfile import ZipFile


MAX_EXTRACTED_CHARACTERS = 5_000_000


def _limit_process() -> None:
    if os.name != "posix":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (110, 110))
    resource.setrlimit(resource.RLIMIT_FSIZE, (30 * 1024**2, 30 * 1024**2))


def _parse_pdf(path: Path) -> dict:
    import pymupdf

    parts: list[str] = []
    partial = False
    ocr_count = 0
    ocr_limit = max(0, min(int(os.getenv("PRIVATE_DOCUMENT_OCR_MAX_PAGES", "25")), 50))
    with pymupdf.open(path) as document:
        if document.is_encrypted or document.needs_pass:
            raise ValueError("encrypted")
        pages = len(document)
        for index, page in enumerate(document):
            text_value = page.get_text("text").strip()
            if not text_value and ocr_count < ocr_limit:
                try:
                    import pytesseract
                    from PIL import Image

                    pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                    image = Image.open(io.BytesIO(pix.tobytes("png")))
                    text_value = pytesseract.image_to_string(
                        image, lang="uzb+rus+eng", timeout=10
                    ).strip()
                    ocr_count += 1
                except Exception:
                    partial = True
            elif not text_value:
                partial = True
            if text_value:
                parts.append(f"[[PAGE {index + 1}]]\n{text_value}")
            if sum(len(part) for part in parts) > MAX_EXTRACTED_CHARACTERS:
                raise ValueError("extracted_text_limit")
    extracted = "\n\n".join(parts).strip()
    if not extracted:
        raise ValueError("no_extractable_text")
    return {
        "text": extracted,
        "page_count": pages,
        "page_count_status": "KNOWN",
        "state": "PARTIAL" if partial else "READY",
        "error_code": "OCR_INCOMPLETE" if partial else None,
        "parser_name": "pymupdf-local-ocr",
    }


def _xml_text(payload: bytes) -> str:
    root = ElementTree.fromstring(payload)
    return " ".join(value.strip() for value in root.itertext() if value.strip())


def _parse_docx(path: Path) -> dict:
    with ZipFile(path) as archive:
        text_value = _xml_text(archive.read("word/document.xml"))
        page_count = None
        if "docProps/app.xml" in archive.namelist():
            try:
                root = ElementTree.fromstring(archive.read("docProps/app.xml"))
                for node in root.iter():
                    if node.tag.rsplit("}", 1)[-1] == "Pages" and node.text:
                        parsed = int(node.text)
                        if parsed > 0:
                            page_count = parsed
                        break
            except (ValueError, ElementTree.ParseError):
                page_count = None
    if not text_value:
        raise ValueError("no_extractable_text")
    if len(text_value) > MAX_EXTRACTED_CHARACTERS:
        raise ValueError("extracted_text_limit")
    return {
        "text": text_value,
        "page_count": page_count,
        "page_count_status": "KNOWN" if page_count else "UNKNOWN",
        "state": "READY" if page_count else "PARTIAL",
        "error_code": None if page_count else "DOCX_PAGE_COUNT_UNKNOWN",
        "parser_name": "docx-openxml",
    }


def main() -> None:
    _limit_process()
    path = Path(sys.argv[1])
    media_type = sys.argv[2]
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        result = _parse_pdf(path) if media_type == "application/pdf" else _parse_docx(path)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
