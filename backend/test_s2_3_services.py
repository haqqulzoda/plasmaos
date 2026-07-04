from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.api.endpoints.meta import get_services_meta
from app.api.endpoints.users import (
    CompanyOnboardingRequest,
    CompanyProfileUpdate,
    _company_profile_response,
)
from app.core.services import TARGET_SERVICE_LABELS, TARGET_SERVICE_VALUES, services_meta_payload
from app.schemas.vault import CompanyVaultUpdate, ReadinessDocumentCreate, ReadinessDocumentUpdate


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class S23ServiceTests(unittest.TestCase):
    def test_service_meta_exposes_values_and_clean_labels(self) -> None:
        payload = services_meta_payload()

        self.assertEqual(
            [item["value"] for item in payload],
            list(TARGET_SERVICE_VALUES),
        )
        self.assertEqual(
            [item["label"] for item in payload],
            [TARGET_SERVICE_LABELS[value] for value in TARGET_SERVICE_VALUES],
        )

        response = asyncio.run(get_services_meta())
        self.assertEqual(response[0].value, "construction")
        self.assertEqual(response[0].label, "Construction")
        self.assertIn(
            ("industrial services", "Industrial Services"),
            [(item.value, item.label) for item in response],
        )

    def test_company_target_services_normalize_to_canonical_values(self) -> None:
        onboarding = CompanyOnboardingRequest(
            company_name="Plasma Build",
            industry="Construction",
            target_regions=["Central Asia"],
            target_countries=["Uzbekistan"],
            target_services=["Construction", "construction", "Industrial Services", "it"],
            director_name="Ali Pilot",
            phone_contact="+998 90 000 00 00",
            inn="123456789",
        )

        self.assertEqual(
            onboarding.target_services,
            ["construction", "industrial services", "IT"],
        )

        update = CompanyProfileUpdate(
            target_services=["Equipment Supply", "Medical"],
        )
        self.assertEqual(update.target_services, ["equipment supply", "medical"])

        vault_update = CompanyVaultUpdate(
            target_services=["Consulting", "Other", "consulting"],
        )
        self.assertEqual(vault_update.target_services, ["consulting", "other"])

    def test_invalid_company_target_services_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CompanyProfileUpdate(target_services=["legal"])

        with self.assertRaises(ValidationError):
            CompanyVaultUpdate(target_services=["logistics"])

    def test_readiness_related_service_uses_same_taxonomy(self) -> None:
        create = ReadinessDocumentCreate(
            document_type="license",
            document_name="Construction license",
            status="available",
            related_service="Industrial Services",
        )
        self.assertEqual(create.related_service, "industrial services")

        update = ReadinessDocumentUpdate(related_service="Construction")
        self.assertEqual(update.related_service, "construction")

        empty_update = ReadinessDocumentUpdate(related_service=" ")
        self.assertIsNone(empty_update.related_service)

        with self.assertRaises(ValidationError):
            ReadinessDocumentCreate(
                document_type="license",
                document_name="Construction license",
                status="available",
                related_service="legal",
            )

    def test_existing_dirty_profile_services_do_not_break_response(self) -> None:
        current_user = SimpleNamespace(
            company_name=None,
            director_name=None,
            address=None,
            phone_contact=None,
            bank_name=None,
            mfo=None,
            account_number=None,
            inn=None,
        )
        profile = SimpleNamespace(
            id=uuid4(),
            company_name="Legacy Company",
            director_name=None,
            address=None,
            phone_contact=None,
            bank_name=None,
            mfo=None,
            account_number=None,
            inn="123456789",
            industry="construction",
            website=None,
            target_regions=["Central Asia"],
            target_countries=["Uzbekistan"],
            target_services=["Construction", "legal"],
            notes=None,
            pilot_status="scoped_pilot",
            approval_status="pending",
        )

        response = _company_profile_response(current_user=current_user, profile=profile)

        self.assertEqual(response.target_services, ["construction"])

    def test_frontend_uses_shared_service_metadata(self) -> None:
        services = read("../frontend/lib/services.ts")
        onboarding = read("../frontend/app/dashboard/onboarding/page.tsx")
        settings = read("../frontend/app/dashboard/settings/page.tsx")
        readiness = read("../frontend/app/dashboard/readiness-vault/page.tsx")

        for expected in (
            "Construction",
            "Medical",
            "IT",
            "Industrial Services",
            "Equipment Supply",
        ):
            self.assertIn(expected, services)

        self.assertIn("useServiceMeta", onboarding)
        self.assertIn("service.label", onboarding)
        self.assertIn("useServiceMeta", settings)
        self.assertIn("useServiceMeta", readiness)
        self.assertIn("labelForService", readiness)


if __name__ == "__main__":
    unittest.main()
