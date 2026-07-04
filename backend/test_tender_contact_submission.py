"""Regression checks for tender contact/submission detail fields."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

try:
    from app.api.endpoints import tenders as tender_endpoints
    from app.models.all_models import TenderStatus
    from app.schemas.tender import TenderResponse
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "fastapi",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        tender_endpoints = None
        TenderStatus = None
        TenderResponse = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


def _tender(**overrides):
    values = {
        "id": uuid4(),
        "external_id": "OP00434599",
        "source_system": "world_bank",
        "canonical_source_key": "world_bank:OP00434599",
        "source_url": "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00434599",
        "title": "Package 2: HEM Works",
        "description": "Hydro electro Mechanical Works",
        "budget": 40000000.0,
        "currency": "USD",
        "deadline": datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc),
        "publication_date": datetime(2026, 6, 8, tzinfo=timezone.utc),
        "country": "Liberia",
        "region": "Western And Central Africa",
        "sector": "Renewable Energy Solar",
        "buyer": "Liberia Electricity Corporation",
        "procurement_category": "Works",
        "procurement_method": "Request for Bids",
        "notice_type": "Invitation for Bids",
        "project_id": "P179267",
        "status": TenderStatus.OPEN if TenderStatus is not None else "OPEN",
        "category": "World Bank",
        "created_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
        "source_metadata_json": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class TenderContactSubmissionStaticTests(unittest.TestCase):
    def test_tender_response_does_not_expose_raw_metadata(self) -> None:
        assert TenderResponse is not None

        fields = set(TenderResponse.model_fields)
        self.assertIn("contact_submission", fields)
        self.assertNotIn("source_metadata_json", fields)
        self.assertNotIn("storage_path", fields)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class TenderContactSubmissionBehaviorTests(unittest.TestCase):
    def test_world_bank_contact_submission_is_whitelisted_and_derived(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_metadata_json={
                    "contact_name": "Jane Doe",
                    "contact_address": "1 Energy Way, Monrovia",
                    "submission_method": "Electronic submission",
                    "clarification_deadline": "2026-10-20T12:00:00Z",
                    "document_access_notes": "Bidding documents are linked from the notice.",
                    "notice_text": "Contact Email: jane.doe@example.org Tel: +1 202 555 0199",
                    "internal_path": "/mnt/private/source.json",
                }
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        payload = response.model_dump(mode="json")
        contact = payload["contact_submission"]
        self.assertEqual(contact["buyer_agency"], "Liberia Electricity Corporation")
        self.assertEqual(contact["contact_person"], "Jane Doe")
        self.assertEqual(contact["email"], "jane.doe@example.org")
        self.assertEqual(contact["phone"], "+1 202 555 0199")
        self.assertEqual(contact["address"], "1 Energy Way, Monrovia")
        self.assertEqual(contact["submission_method"], "Electronic submission")
        self.assertEqual(contact["question_deadline"], "2026-10-20T12:00:00Z")
        self.assertNotIn("source_metadata_json", payload)
        self.assertNotIn("/mnt/private", str(payload))

    def test_world_bank_contact_submission_uses_contact_information_fields(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                external_id="OP00454268",
                canonical_source_key="world_bank:OP00454268",
                buyer="MEPSA",
                source_metadata_json={
                    "contact_address": "Republique du Congo",
                    "contact_ctry_name": "Congo, Republic of",
                    "contact_email": "bouckitah@gmail.com",
                    "contact_job_title": "Coordonnateur",
                    "contact_name": "Arsene BOUCKITA",
                    "contact_organization": "MEPSA",
                    "contact_phone_no": "00242055753998",
                },
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.buyer_agency, "MEPSA")
        self.assertEqual(contact.contact_person, "Arsene BOUCKITA (Coordonnateur)")
        self.assertEqual(contact.email, "bouckitah@gmail.com")
        self.assertEqual(contact.phone, "00242055753998")
        self.assertEqual(
            contact.address,
            "Republique du Congo; Congo, Republic of",
        )

    def test_adb_source_info_surfaces_when_contact_is_missing(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_system="adb",
                canonical_source_key="adb:1142361",
                external_id="1142361",
                source_url="https://www.adb.org/node/1142361",
                buyer=None,
                deadline=None,
                category="ADB",
                source_metadata_json={"node_url": "https://www.adb.org/node/1142361"},
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.source_url, "https://www.adb.org/node/1142361")
        self.assertIsNone(contact.contact_person)
        self.assertIsNone(contact.email)
        self.assertIsNone(contact.phone)

    def test_adb_contact_submission_uses_pdf_extracted_metadata(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_system="adb",
                canonical_source_key="adb:1140436",
                external_id="1140436",
                source_url="https://www.adb.org/node/1140436",
                buyer=None,
                deadline=None,
                category="ADB",
                source_metadata_json={
                    "node_url": "https://www.adb.org/node/1140436",
                    "buyer_agency": "Project Administration Group (PAG)",
                    "contact_person": "PAG Manager, Mr. Bobokhon Abdulmajid",
                    "email": "istem.taj@gmail.com",
                    "phone": "(+992) 44 600 4809",
                    "address": "101 Karamov str.; Dushanbe; Tajikistan",
                    "submission_method": "Physical submission to the address specified in the ADB notice",
                    "submission_deadline": "2026-06-30T00:00:00+00:00",
                    "document_access_notes": "Write to the address above requesting the Bidding Documents.",
                },
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.buyer_agency, "Project Administration Group (PAG)")
        self.assertEqual(
            contact.contact_person,
            "PAG Manager, Mr. Bobokhon Abdulmajid",
        )
        self.assertEqual(contact.email, "istem.taj@gmail.com")
        self.assertEqual(contact.phone, "(+992) 44 600 4809")
        self.assertEqual(
            contact.submission_deadline,
            datetime(2026, 6, 30, tzinfo=timezone.utc),
        )

    def test_giz_contact_submission_uses_public_page_metadata(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_system="giz",
                canonical_source_key="giz:7000012992",
                external_id="7000012992",
                source_url="https://www.giz.de/en/regions/africa/south-africa/tenders",
                buyer="GIZ South Africa",
                deadline=datetime(2026, 7, 15, tzinfo=timezone.utc),
                category="GIZ",
                source_metadata_json={
                    "buyer_agency": "GIZ South Africa",
                    "email": "ZA_Quotation@giz.de",
                    "submission_method": "Electronic submission by email and filetransfer.giz.de as specified by GIZ",
                    "procedure_type": "Public tender",
                    "participation_instructions": "Use the GIZ project area for bidder communication.",
                    "document_access_notes": "Public GIZ country-office page includes direct downloadable tender documents.",
                },
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.buyer_agency, "GIZ South Africa")
        self.assertEqual(contact.email, "ZA_Quotation@giz.de")
        self.assertEqual(
            contact.submission_method,
            "Electronic submission by email and filetransfer.giz.de as specified by GIZ",
        )
        self.assertEqual(contact.procedure_type, "Public tender")
        self.assertEqual(
            contact.participation_instructions,
            "Use the GIZ project area for bidder communication.",
        )
        self.assertEqual(contact.source_url, "https://www.giz.de/en/regions/africa/south-africa/tenders")


    def test_ebrd_contact_submission_shows_external_access_required(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_system="ebrd",
                canonical_source_key="ebrd:45376134",
                external_id="45376134",
                source_url="https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=45376255",
                buyer="The Republic of Tajikistan",
                deadline=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
                category="EBRD",
                source_metadata_json={
                    "buyer_agency": "The Republic of Tajikistan",
                    "contact_person": "Ms Amina Karimova",
                    "email": "procurement@example.tj",
                    "phone": "+992 44 123 4567",
                    "address": "Dushanbe, Tajikistan",
                    "submission_method": "Electronic submission through ECEPP where the notice requires a response.",
                    "procedure_type": "Open Tender Single Stage",
                    "participation_instructions": (
                        "Participation documents require ECEPP registration and expressing interest."
                    ),
                    "document_access_notes": (
                        "Participation documents require ECEPP registration; PlasmaOS does not automate ECEPP login."
                    ),
                },
            ),
            summary={
                **tender_endpoints._empty_tender_summary(),
                "document_status": "access_required",
                "document_count": 1,
                "access_required": True,
            },
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.buyer_agency, "The Republic of Tajikistan")
        self.assertEqual(contact.email, "procurement@example.tj")
        self.assertEqual(contact.procedure_type, "Open Tender Single Stage")
        self.assertIn("ECEPP registration", contact.document_access_notes)
        self.assertFalse(response.compliance_analysis_available)
        self.assertIn("metadata-only", response.compliance_unavailable_reason)


    def test_uzex_uses_existing_buyer_source_and_deadline_without_guessing(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_system="uzex",
                canonical_source_key="uzex:488105",
                external_id="488105",
                source_url="https://etender.uzex.uz/lot/488105",
                buyer="Existing UzEx buyer",
                deadline=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
                category="Construction",
                source_metadata_json={"source_route": "/lots/2/"},
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.buyer_agency, "Existing UzEx buyer")
        self.assertEqual(contact.source_url, "https://etender.uzex.uz/lot/488105")
        self.assertEqual(
            contact.submission_deadline,
            datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(contact.contact_person)

    def test_uzex_contact_submission_uses_get_trade_metadata(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(
                source_system="uzex",
                canonical_source_key="uzex:496369",
                external_id="496369",
                source_url="https://etender.uzex.uz/lot/496369",
                buyer=None,
                deadline=None,
                category="Medical",
                source_metadata_json={
                    "buyer_agency": "Ministry Procurement Center",
                    "contact_person": (
                        "Hikmat Usmanov (Director); "
                        "Tolqin Kushimov (Department head)"
                    ),
                    "phone": "977304478",
                    "address": (
                        "17-B Turkiston street; "
                        "Mirzo-Ulugbek district; Tashkent city"
                    ),
                    "submission_method": "Electronic procedure",
                    "submission_deadline": "2026-07-01T20:03:30",
                    "question_deadline": "2026-07-01T20:03:30",
                    "document_access_notes": (
                        "Official tender documents are available from the "
                        "UzEx source notice."
                    ),
                    "contacts": [{"Fullname": "raw field must not leak"}],
                },
            ),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        contact = response.contact_submission
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.buyer_agency, "Ministry Procurement Center")
        self.assertEqual(
            contact.contact_person,
            "Hikmat Usmanov (Director); Tolqin Kushimov (Department head)",
        )
        self.assertEqual(contact.phone, "977304478")
        self.assertEqual(
            contact.address,
            "17-B Turkiston street; Mirzo-Ulugbek district; Tashkent city",
        )
        self.assertEqual(contact.submission_method, "Electronic procedure")
        self.assertEqual(
            contact.submission_deadline,
            datetime(2026, 7, 1, 20, 3, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            contact.question_deadline,
            datetime(2026, 7, 1, 20, 3, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            contact.document_access_notes,
            "Official tender documents are available from the UzEx source notice.",
        )

    def test_internal_document_access_paths_are_not_exposed(self) -> None:
        assert tender_endpoints is not None

        response = tender_endpoints._serialize_tender(
            _tender(source_metadata_json={"document_access_notes": "/var/data/tender.pdf"}),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )

        assert response.contact_submission is not None
        self.assertIsNone(response.contact_submission.document_access_notes)


if __name__ == "__main__":
    unittest.main()
