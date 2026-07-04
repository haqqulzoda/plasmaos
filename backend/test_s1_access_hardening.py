from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = ROOT.parent / "frontend"


def read_backend(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_frontend(path: str) -> str:
    return (FRONTEND_ROOT / path).read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    marker = f"async def {name}"
    start = source.index(marker)
    next_func = source.find("\nasync def ", start + len(marker))
    next_route = source.find("\n@router.", start + len(marker))
    candidates = [idx for idx in (next_func, next_route) if idx != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


class S14AccessHardeningTests(unittest.TestCase):
    def test_approved_pilot_dependency_exists(self) -> None:
        deps = read_backend("app/api/deps.py")

        self.assertIn("async def require_approved_pilot_access", deps)
        self.assertIn("has_approved_pilot_account_access(current_user, profile)", deps)
        self.assertIn("select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)", deps)
        self.assertIn("Approved pilot access required", deps)
        self.assertIn("if is_operator_user(current_user):", deps)

    def test_tender_sensitive_routes_require_approved_access(self) -> None:
        tenders = read_backend("app/api/endpoints/tenders.py")

        for name in (
            "analyze_tender",
            "download_document",
            "get_tender_compiled_text",
            "sync_tender_documents",
            "get_sync_status",
            "get_tender_documents",
            "get_latest_analysis",
            "export_compliance_pdf",
            "override_risk",
            "get_risk_overrides",
        ):
            block = function_block(tenders, name)
            self.assertIn(
                "current_user: User = Depends(require_approved_pilot_access)",
                block,
                msg=name,
            )

        documents_block = function_block(tenders, "get_tender_documents")
        self.assertIn("await _ensure_tender_access(", documents_block)
        self.assertIn("allow_operator=True", documents_block)

    def test_vault_company_proposal_and_audit_routes_are_hardened(self) -> None:
        vault = read_backend("app/api/endpoints/vault.py")
        users = read_backend("app/api/endpoints/users.py")
        proposals = read_backend("app/api/endpoints/proposals.py")
        audit = read_backend("app/api/routers/audit.py")
        hunter = read_backend("app/api/endpoints/hunter.py")

        self.assertIn("Depends(require_approved_pilot_access)", vault)
        self.assertIn("async def update_company_profile", users)
        self.assertIn("current_user: User = Depends(require_approved_pilot_access)", users)
        self.assertIn("Depends(require_approved_pilot_access)", proposals)
        self.assertIn("current_user: User = Depends(require_approved_pilot_access)", audit)
        self.assertIn("current_user: User = Depends(require_approved_pilot_access)", hunter)

    def test_admin_activity_and_corpus_health_exist(self) -> None:
        admin = read_backend("app/api/endpoints/admin.py")
        overview = read_frontend("app/admin/page.tsx")

        self.assertIn('"/activity"', admin)
        self.assertIn('"/corpus-health"', admin)
        self.assertIn("AdminActivityResponse", admin)
        self.assertIn("AdminCorpusHealthResponse", admin)
        self.assertIn("dependencies=[Depends(require_operator_or_admin)]", admin)
        self.assertIn("customer_visible_tender_condition(Tender)", admin)
        self.assertIn("uzex_small_scale_tender_condition(Tender)", admin)
        self.assertIn("hidden_legacy_uzex_count", admin)
        self.assertIn("small_uzex_count", admin)

        self.assertIn("api.get<AdminActivity>('/admin/activity')", overview)
        self.assertIn("api.get<AdminCorpusHealth>('/admin/corpus-health')", overview)
        self.assertIn("Pending users", overview)
        self.assertIn("Pending companies", overview)
        self.assertIn("UzEx enterprise visible", overview)
        self.assertIn("World Bank visible", overview)
        self.assertIn("ADB visible", overview)


if __name__ == "__main__":
    unittest.main()
