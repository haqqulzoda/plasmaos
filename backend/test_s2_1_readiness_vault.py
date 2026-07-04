from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.api.endpoints.users import _company_profile_response
from app.schemas.vault import ReadinessDocumentCreate


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    start = source.index(f"async def {name}")
    next_route = source.find("\n\n@", start + 1)
    if next_route == -1:
        return source[start:]
    return source[start:next_route]


class S21ReadinessVaultTests(unittest.TestCase):
    def test_readiness_schema_allows_record_without_file(self) -> None:
        payload = ReadinessDocumentCreate(
            document_type="license",
            document_name="Construction license",
            status="available",
            related_service="construction",
        )

        self.assertEqual(payload.document_type, "license")
        self.assertEqual(payload.document_name, "Construction license")
        self.assertIsNone(payload.optional_file_url)

    def test_readiness_model_is_linked_to_company_profile(self) -> None:
        model_source = read("app/models/company.py")
        all_models_source = read("app/models/all_models.py")
        migration = read("alembic/versions/20260629_0001_s2_1_readiness_vault.py")

        self.assertIn('class ReadinessDocument(Base):', model_source)
        self.assertIn('ForeignKey("company_profiles.id", ondelete="CASCADE")', model_source)
        self.assertIn('readiness_documents', migration)
        self.assertIn('company_profile_id', migration)
        self.assertIn('ReadinessDocument', all_models_source)

    def test_readiness_routes_are_crud_and_require_approved_access(self) -> None:
        vault_source = read("app/api/endpoints/vault.py")

        for route in (
            '@router.get("/vault/readiness"',
            '@router.post(\n    "/vault/readiness"',
            '@router.put(\n    "/vault/readiness/{document_id}"',
            '@router.delete("/vault/readiness/{document_id}"',
        ):
            self.assertIn(route, vault_source)

        for function_name in (
            "list_readiness_documents",
            "create_readiness_document",
            "update_readiness_document",
            "delete_readiness_document",
        ):
            block = function_block(vault_source, function_name)
            self.assertIn("Depends(require_approved_pilot_access)", block)
            self.assertNotIn("CompanyProfile(", block)

    def test_company_profile_get_is_auth_only_and_does_not_create_profile(self) -> None:
        users_source = read("app/api/endpoints/users.py")
        get_block = function_block(users_source, "get_company_profile")
        put_block = function_block(users_source, "update_company_profile")

        self.assertIn("@router.get(\"/me/company\"", users_source)
        self.assertIn("Depends(get_current_user)", get_block)
        self.assertNotIn("require_approved_pilot_access", get_block)
        self.assertIn("_get_company_profile", get_block)
        self.assertNotIn("CompanyProfile(", get_block)
        self.assertIn("Depends(require_approved_pilot_access)", put_block)

    def test_pending_user_company_status_responses(self) -> None:
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

        missing = _company_profile_response(current_user=current_user, profile=None)
        self.assertTrue(missing.onboarding_required)
        self.assertIsNone(missing.company_profile_id)

        profile_id = uuid4()
        profile = SimpleNamespace(
            id=profile_id,
            company_name="Pending Company",
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
            target_services=["construction"],
            notes=None,
            pilot_status="scoped_pilot",
            approval_status="pending",
        )

        existing = _company_profile_response(current_user=current_user, profile=profile)
        self.assertFalse(existing.onboarding_required)
        self.assertEqual(existing.company_profile_id, profile_id)
        self.assertEqual(existing.approval_status, "pending")

    def test_admin_operator_can_read_company_and_readiness_data(self) -> None:
        admin_source = read("app/api/endpoints/admin.py")

        self.assertIn('"/companies/{company_profile_id}"', admin_source)
        self.assertIn('"/companies/{company_profile_id}/readiness"', admin_source)
        self.assertIn("Depends(require_operator_or_admin)", admin_source)
        self.assertIn("ReadinessDocumentResponse", admin_source)

    def test_frontend_pages_exist_for_profile_and_readiness_vault(self) -> None:
        settings_page = read("../frontend/app/dashboard/settings/page.tsx")
        readiness_page = read("../frontend/app/dashboard/readiness-vault/page.tsx")
        layout = read("../frontend/app/dashboard/layout.tsx")

        self.assertIn("Company profile", settings_page)
        self.assertIn("Readiness vault", readiness_page)
        self.assertIn("optional_file_url", readiness_page)
        self.assertIn("Company Profile", layout)
        self.assertIn("Readiness Vault", layout)


if __name__ == "__main__":
    unittest.main()
