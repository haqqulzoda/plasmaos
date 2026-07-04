from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    start = source.index(f"async def {name}")
    next_route = source.find("\n\n@", start + 1)
    if next_route == -1:
        return source[start:]
    return source[start:next_route]


class S24ReadinessAdminTests(unittest.TestCase):
    def test_admin_company_endpoint_is_read_only_and_includes_user_identity(self) -> None:
        admin_source = read("app/api/endpoints/admin.py")
        get_company_block = function_block(admin_source, "get_admin_company_profile")

        self.assertIn('"/companies/{company_profile_id}"', admin_source)
        self.assertIn("response_model=AdminCompanyResponse", admin_source)
        self.assertIn("Depends(require_operator_or_admin)", admin_source)
        self.assertIn("user_name", admin_source)
        self.assertIn("user_email", admin_source)
        self.assertIn("selectinload(CompanyProfile.user)", admin_source)
        self.assertNotIn("CompanyProfile(", get_company_block)

    def test_readiness_vault_ux_supports_labels_filters_and_optional_files(self) -> None:
        readiness_page = read("../frontend/app/dashboard/readiness-vault/page.tsx")
        readiness_helpers = read("../frontend/lib/readiness.ts")

        self.assertIn("DOCUMENT_TYPE_OPTIONS", readiness_helpers)
        self.assertIn("DOCUMENT_STATUS_OPTIONS", readiness_helpers)
        self.assertIn("expiryState", readiness_helpers)
        self.assertIn("Expiring Soon", readiness_helpers)

        for expected in (
            "filters.document_type",
            "filters.status",
            "filters.related_service",
            "filteredDocuments",
            "labelForDocumentType",
            "labelForDocumentStatus",
            "labelForService",
            "labelForExpiryState",
            "optional_file_url: form.optional_file_url || null",
            "api.post<ReadinessDocument>",
            "api.put<ReadinessDocument>",
            "api.delete",
        ):
            self.assertIn(expected, readiness_page)

    def test_company_settings_shows_status_and_clean_target_summary(self) -> None:
        settings_page = read("../frontend/app/dashboard/settings/page.tsx")

        self.assertIn("TargetSummary", settings_page)
        self.assertIn("Approval:", settings_page)
        self.assertIn("Pilot:", settings_page)
        self.assertIn("labelForService", settings_page)
        self.assertIn("CENTRAL_ASIA_REGION", settings_page)

    def test_admin_company_detail_page_is_read_only_and_linked_from_approvals(self) -> None:
        detail_page = read("../frontend/app/admin/companies/[companyProfileId]/page.tsx")
        approvals_page = read("../frontend/app/admin/approvals/page.tsx")

        self.assertIn("AdminCompanyDetailPage", detail_page)
        self.assertIn("api.get<AdminCompany>(`/admin/companies/${companyProfileId}`)", detail_page)
        self.assertIn("api.get<ReadinessDocument[]>(`/admin/companies/${companyProfileId}/readiness`)", detail_page)
        self.assertIn("user_email", detail_page)
        self.assertIn("labelForDocumentType", detail_page)
        self.assertIn("labelForDocumentStatus", detail_page)
        self.assertIn("labelForExpiryState", detail_page)
        self.assertNotIn("api.post", detail_page)
        self.assertNotIn("api.put", detail_page)
        self.assertNotIn("api.delete", detail_page)

        self.assertIn("href={`/admin/companies/${company.id}`}", approvals_page)

    def test_access_boundaries_still_use_existing_guards(self) -> None:
        vault_source = read("app/api/endpoints/vault.py")
        admin_source = read("app/api/endpoints/admin.py")
        admin_layout = read("../frontend/app/admin/layout.tsx")
        get_vault_block = function_block(vault_source, "list_readiness_documents")

        self.assertIn("Depends(require_approved_pilot_access)", get_vault_block)
        self.assertIn("Depends(require_operator_or_admin)", admin_source)
        self.assertIn("isOperatorOrAdmin", admin_layout)
        self.assertIn("router.replace('/dashboard')", admin_layout)
        self.assertNotIn("CompanyProfile(", get_vault_block)


if __name__ == "__main__":
    unittest.main()
