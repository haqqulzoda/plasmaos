"""Regression tests for targeted GIZ document hydration."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

try:
    import fitz

    from app.models.all_models import TenderDocument
    from app.services import giz_document_hydration
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "celery",
        "fastapi",
        "fitz",
        "google",
        "httpx",
        "playwright",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        HAS_BACKEND_DEPS = False
        TenderDocument = None
        giz_document_hydration = None
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


ROOT = Path(__file__).resolve().parent


class _FakeResult:
    def __init__(self, value=None, values=None):
        self.value = value
        self.values = values if values is not None else ([] if value is None else [value])

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.values


class _FakeGizDocumentSession:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.added = []

    async def execute(self, statement):
        values = {}

        def visit(criterion) -> None:
            clauses = getattr(criterion, "clauses", None)
            if clauses is not None:
                for clause in clauses:
                    visit(clause)
                return

            left = str(getattr(criterion, "left", ""))
            right = getattr(criterion, "right", None)
            value = getattr(right, "value", None)
            if left.endswith("tender_id"):
                values["tender_id"] = value
            elif left.endswith("source_document_url"):
                values["source_document_url"] = value
            elif left.endswith("sha256"):
                values["sha256"] = value

        for criterion in getattr(statement, "_where_criteria", ()):
            visit(criterion)

        matching_docs = [
            doc
            for doc in self.docs
            if values.get("tender_id") is None or doc.tender_id == values["tender_id"]
        ]
        if values.get("source_document_url"):
            for doc in matching_docs:
                if doc.source_document_url == values["source_document_url"]:
                    return _FakeResult(value=doc)
            return _FakeResult()
        if values.get("sha256"):
            for doc in matching_docs:
                if doc.sha256 == values["sha256"]:
                    return _FakeResult(value=doc)
            return _FakeResult()
        return _FakeResult(values=matching_docs)

    def add(self, doc):
        self.docs.append(doc)
        self.added.append(doc)

    async def flush(self):
        return None


def _giz_tender(tender_id):
    return SimpleNamespace(
        id=tender_id,
        source_system="giz",
        external_id="10034411",
        canonical_source_key="giz:10034411",
        source_metadata_json={
            "attachments": [
                {
                    "source_document_url": "https://www.giz.de/sites/default/files/archive.zip",
                    "source_document_type": "zip",
                }
            ]
        },
    )


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class GizHydrationWorkerTests(unittest.TestCase):
    def test_giz_hydration_rejects_uzex_tender_scope(self) -> None:
        assert giz_document_hydration is not None

        tender = SimpleNamespace(
            id=uuid4(),
            source_system="uzex",
            canonical_source_key="uzex:10034411",
        )

        with self.assertRaises(ValueError):
            asyncio.run(
                giz_document_hydration.hydrate_giz_tender_documents(
                    _FakeGizDocumentSession(),
                    tender=tender,
                )
            )

    def test_direct_pdf_parse_adds_file_and_page_provenance(self) -> None:
        assert TenderDocument is not None
        assert giz_document_hydration is not None

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "direct.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72, 72), "GIZ direct PDF eligibility text.")
            pdf.save(pdf_path)
            pdf.close()
            doc = TenderDocument(
                id=uuid4(),
                tender_id=uuid4(),
                file_url="https://www.giz.de/sites/default/files/direct.pdf",
                file_type="pdf",
                source_document_url="https://www.giz.de/sites/default/files/direct.pdf",
                download_status="downloaded",
                storage_path=str(pdf_path),
            )

            parsed = asyncio.run(
                giz_document_hydration._giz_parse_stored_document(
                    doc=doc,
                    source_label="direct.pdf",
                    force=True,
                )
            )

        self.assertTrue(parsed)
        self.assertIn("[[FILE: direct.pdf]]", doc.parsed_text)
        self.assertIn("[[PAGE 1]]", doc.parsed_text)

    def test_archive_hydration_extracts_inner_document_and_is_idempotent(self) -> None:
        assert TenderDocument is not None
        assert giz_document_hydration is not None

        tender_id = uuid4()
        tender = _giz_tender(tender_id)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            previous_root = giz_document_hydration.DOCUMENTS_ROOT
            giz_document_hydration.DOCUMENTS_ROOT = tmp_path / "documents"
            try:
                archive_path = tmp_path / "archive.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr(
                        "forms/spec.txt",
                        "Eligibility: bidder must provide audited financial statements.",
                    )
                archive_doc = TenderDocument(
                    id=uuid4(),
                    tender_id=tender_id,
                    file_url="https://www.giz.de/sites/default/files/archive.zip",
                    file_type="zip",
                    source_document_url="https://www.giz.de/sites/default/files/archive.zip",
                    download_status="downloaded",
                    storage_path=str(archive_path),
                )
                db = _FakeGizDocumentSession([archive_doc])

                parsed_first = asyncio.run(
                    giz_document_hydration._giz_extract_supported_zip_members(
                        db,
                        tender=tender,
                        archive_doc=archive_doc,
                    )
                )
                parsed_second = asyncio.run(
                    giz_document_hydration._giz_extract_supported_zip_members(
                        db,
                        tender=tender,
                        archive_doc=archive_doc,
                    )
                )
                coverage = asyncio.run(
                    giz_document_hydration.update_giz_document_coverage(
                        db,
                        tender=tender,
                    )
                )
            finally:
                giz_document_hydration.DOCUMENTS_ROOT = previous_root

        inner_docs = [
            doc
            for doc in db.docs
            if "#giz-inner=" in (doc.source_document_url or "")
        ]
        self.assertEqual(len(inner_docs), 1)
        self.assertEqual(parsed_first, 1)
        self.assertEqual(parsed_second, 0)
        self.assertIn("[[FILE: archive.zip!/forms/spec.txt]]", inner_docs[0].parsed_text)
        self.assertIn("[[PAGE 1]]", inner_docs[0].parsed_text)
        self.assertEqual(coverage["coverage_status"], "complete")
        self.assertEqual(coverage["extracted_file_count"], 1)
        self.assertEqual(coverage["parsed_file_count"], 1)


if __name__ == "__main__":
    unittest.main()
