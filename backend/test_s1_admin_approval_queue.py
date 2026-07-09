from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = ROOT.parent / "frontend"


def read_backend(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_frontend(path: str) -> str:
    return (FRONTEND_ROOT / path).read_text(encoding="utf-8")


class AdminApprovalQueueTests(unittest.TestCase):
    def test_backend_admin_approval_routes_exist_and_are_guarded(self) -> None:
        source = read_backend("app/api/endpoints/admin.py")

        self.assertIn('"/approval-queue"', source)
        self.assertIn("Depends(require_operator_or_admin)", source)

        for route in (
            '"/users/{user_id}/approve"',
            '"/users/{user_id}/reject"',
            '"/users/{user_id}/disable"',
            '"/companies/{company_profile_id}/approve"',
            '"/companies/{company_profile_id}/reject"',
            '"/companies/{company_profile_id}/disable"',
        ):
            self.assertIn(route, source)

        self.assertIn("current_user: User = Depends(require_admin)", source)
        self.assertIn("USER_APPROVAL_APPROVED", source)
        self.assertIn("USER_APPROVAL_REJECTED", source)
        self.assertIn("USER_APPROVAL_DISABLED", source)
        self.assertIn("COMPANY_APPROVAL_APPROVED", source)
        self.assertIn("COMPANY_APPROVAL_REJECTED", source)
        self.assertIn("COMPANY_APPROVAL_DISABLED", source)
        self.assertIn("approved_by_user_id = current_user.id", source)
        self.assertIn("rejection_reason = _clean_reason(payload.reason)", source)

    def test_admin_pages_and_pilot_route_block_exist(self) -> None:
        dashboard_layout = read_frontend("app/dashboard/layout.tsx")
        admin_layout = read_frontend("app/admin/layout.tsx")
        admin_page = read_frontend("app/admin/page.tsx")
        approvals_page = read_frontend("app/admin/approvals/page.tsx")
        legacy_admin_page = read_frontend("app/dashboard/admin/page.tsx")
        legacy_approvals_page = read_frontend("app/dashboard/admin/approvals/page.tsx")
        middleware = read_frontend("middleware.ts")

        self.assertIn("Admin Console", admin_layout)
        self.assertIn("'/admin'", admin_layout)
        self.assertIn("'/admin/approvals'", admin_layout)
        self.assertIn("role === 'operator'", admin_layout)
        self.assertIn("session?.approval_status === 'approved'", admin_layout)
        self.assertIn("router.replace('/dashboard')", admin_layout)
        self.assertIn("Admin Console", dashboard_layout)
        self.assertNotIn("name: 'Admin'", dashboard_layout)
        self.assertIn("'/admin/:path*'", middleware)

        self.assertIn("Open approval queue", admin_page)
        self.assertIn('href="/admin/approvals"', admin_page)
        self.assertIn("api.get<QueueResponse>('/admin/approval-queue')", approvals_page)
        self.assertIn("without signing out", approvals_page)
        self.assertIn("Only admins can change approval status", approvals_page)
        self.assertIn("redirect('/admin')", legacy_admin_page)
        self.assertIn("redirect('/admin/approvals')", legacy_approvals_page)

        for endpoint in (
            "/admin/users/${item.user.id}/approve",
            "/admin/users/${item.user.id}/reject",
            "/admin/users/${item.user.id}/disable",
            "/admin/companies/${company.id}/approve",
            "/admin/companies/${company.id}/reject",
            "/admin/companies/${company.id}/disable",
        ):
            self.assertIn(endpoint, approvals_page)

        self.assertIn('action="company_approved"', read_backend("app/api/endpoints/admin.py"))
        self.assertIn('action="company_rejected"', read_backend("app/api/endpoints/admin.py"))
        self.assertIn('action="company_disabled"', read_backend("app/api/endpoints/admin.py"))


if __name__ == "__main__":
    unittest.main()
