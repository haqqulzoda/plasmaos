from __future__ import annotations

from pathlib import Path
import unittest

from pydantic import ValidationError

from app.api.endpoints.users import CompanyOnboardingRequest


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    start = source.index(f"async def {name}")
    next_route = source.find("\n\n@", start + 1)
    if next_route == -1:
        return source[start:]
    return source[start:next_route]


class CompanyOnboardingTests(unittest.TestCase):
    def test_onboarding_payload_requires_core_company_fields(self) -> None:
        payload = CompanyOnboardingRequest(
            company_name="  Plasma Build  ",
            industry="Construction",
            target_regions=[" Central Asia ", "central asia", "Europe"],
            target_countries=["Uzbekistan"],
            target_services=["construction", "consulting"],
            director_name="Ali Pilot",
            phone_contact="+998 90 000 00 00",
            inn="123456789",
            website=" ",
        )

        self.assertEqual(payload.company_name, "Plasma Build")
        self.assertEqual(payload.target_regions, ["Central Asia", "Europe"])
        self.assertIsNone(payload.website)

        with self.assertRaises(ValidationError):
            CompanyOnboardingRequest(
                company_name="",
                industry="Construction",
                target_regions=[],
                target_countries=["Uzbekistan"],
                target_services=["construction"],
                director_name="Ali Pilot",
                phone_contact="+998 90 000 00 00",
                inn="123456789",
            )

    def test_onboarding_endpoint_is_the_profile_creation_path(self) -> None:
        users_source = read("app/api/endpoints/users.py")
        onboarding_block = function_block(users_source, "submit_company_onboarding")
        legacy_put_block = function_block(users_source, "update_company_profile")
        get_block = function_block(users_source, "get_company_profile")

        self.assertIn('@router.post("/me/company/onboarding"', users_source)
        self.assertIn("CompanyProfile(", onboarding_block)
        self.assertIn("created_by_user_id=current_user.id", onboarding_block)
        self.assertIn("COMPANY_APPROVAL_PENDING", onboarding_block)
        self.assertIn("COMPANY_PILOT_SCOPED", onboarding_block)
        self.assertIn("COMPANY_APPROVAL_APPROVED", onboarding_block)

        self.assertNotIn("CompanyProfile(", legacy_put_block)
        self.assertIn("Company onboarding required", legacy_put_block)
        self.assertNotIn("CompanyProfile(", get_block)

    def test_vault_get_does_not_create_company_profile(self) -> None:
        vault_source = read("app/api/endpoints/vault.py")
        get_block = function_block(vault_source, "get_company_vault")
        load_block = vault_source.split("async def _load_profile_with_children", 1)[1].split(
            "\ndef _to_response",
            1,
        )[0]

        self.assertNotIn("CompanyProfile(", get_block)
        self.assertNotIn("CompanyProfile(", load_block)
        self.assertIn("Company onboarding required", get_block)


if __name__ == "__main__":
    unittest.main()
