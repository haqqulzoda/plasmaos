from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.api.endpoints.meta import get_geography_meta
from app.api.endpoints.users import (
    CompanyOnboardingRequest,
    CompanyProfileUpdate,
    _company_profile_response,
)
from app.core.geography import CENTRAL_ASIA_COUNTRIES, REGION_OPTIONS, geography_meta_payload
from app.schemas.vault import CompanyVaultUpdate


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class S22GeographyTests(unittest.TestCase):
    def test_geography_meta_exposes_mvp_regions_and_central_asia_countries(self) -> None:
        payload = geography_meta_payload()

        self.assertEqual(payload["regions"], list(REGION_OPTIONS))
        self.assertEqual(payload["regions"][0], "Central Asia")
        self.assertEqual(
            payload["countries_by_region"]["Central Asia"],
            list(CENTRAL_ASIA_COUNTRIES),
        )
        self.assertEqual(payload["central_asia_countries"], list(CENTRAL_ASIA_COUNTRIES))

        response = asyncio.run(get_geography_meta())
        self.assertEqual(response.regions, list(REGION_OPTIONS))
        self.assertEqual(response.central_asia_countries, list(CENTRAL_ASIA_COUNTRIES))

    def test_company_profile_geography_payloads_normalize_to_canonical_values(self) -> None:
        onboarding = CompanyOnboardingRequest(
            company_name="Plasma Build",
            industry="Construction",
            target_regions=[" central asia ", "CENTRAL ASIA", "europe"],
            target_countries=[" uzbekistan ", "KAZAKHSTAN", "uzbekistan"],
            target_services=["construction"],
            director_name="Ali Pilot",
            phone_contact="+998 90 000 00 00",
            inn="123456789",
        )

        self.assertEqual(onboarding.target_regions, ["Central Asia", "Europe"])
        self.assertEqual(onboarding.target_countries, ["Uzbekistan", "Kazakhstan"])

        update = CompanyProfileUpdate(
            target_regions=["latin america"],
            target_countries=["turkmenistan"],
        )

        self.assertEqual(update.target_regions, ["Latin America"])
        self.assertEqual(update.target_countries, ["Turkmenistan"])

        vault_update = CompanyVaultUpdate(
            target_regions=["north america"],
            target_countries=["tajikistan"],
        )

        self.assertEqual(vault_update.target_regions, ["North America"])
        self.assertEqual(vault_update.target_countries, ["Tajikistan"])

    def test_invalid_regions_and_countries_are_rejected_on_write(self) -> None:
        with self.assertRaises(ValidationError):
            CompanyProfileUpdate(target_regions=["Oceania"])

        with self.assertRaises(ValidationError):
            CompanyProfileUpdate(target_countries=["Brazil"])

        with self.assertRaises(ValidationError):
            CompanyVaultUpdate(target_regions=["Oceania"])

    def test_existing_dirty_profile_values_do_not_break_response(self) -> None:
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
            target_regions=["central asia", "Oceania"],
            target_countries=["uzbekistan", "Brazil"],
            target_services=["construction"],
            notes=None,
            pilot_status="scoped_pilot",
            approval_status="pending",
        )

        response = _company_profile_response(current_user=current_user, profile=profile)

        self.assertEqual(response.target_regions, ["Central Asia"])
        self.assertEqual(response.target_countries, ["Uzbekistan"])

    def test_frontend_uses_shared_geography_options(self) -> None:
        geography = read("../frontend/lib/geography.ts")
        onboarding = read("../frontend/app/dashboard/onboarding/page.tsx")
        settings = read("../frontend/app/dashboard/settings/page.tsx")

        for expected in (
            "Central Asia",
            "Uzbekistan",
            "Kazakhstan",
            "Kyrgyzstan",
            "Tajikistan",
            "Turkmenistan",
        ):
            self.assertIn(expected, geography)

        self.assertIn("useGeographyMeta", onboarding)
        self.assertIn("Select all Central Asia", onboarding)
        self.assertIn("useGeographyMeta", settings)
        self.assertIn("Select all Central Asia", settings)


if __name__ == "__main__":
    unittest.main()
