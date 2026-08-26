from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.endpoints.admin import approve_company
from app.api.endpoints.users import get_access_status
from app.core.security import (
    create_access_token,
    get_current_user,
    get_current_user_allow_stale_auth_version,
)


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"


def make_user(status: str = "pending", role: str = "pilot_user"):
    return SimpleNamespace(
        id=uuid4(),
        google_id="google-id",
        email="pilot@example.com",
        name="Pilot",
        company_name=None,
        approval_status=status,
        platform_role=role,
        is_admin=role == "admin",
        auth_version=4,
        approved_at=None,
        rejection_reason="Review declined" if status in {"rejected", "disabled"} else None,
    )


def make_company(status: str = "pending"):
    return SimpleNamespace(
        id=uuid4(),
        company_name="Pilot Company",
        approval_status=status,
        rejection_reason="Company review declined" if status in {"rejected", "disabled"} else None,
    )


class AccessStatusTests(IsolatedAsyncioTestCase):
    async def access(self, user, company):
        with patch(
            "app.api.endpoints.users._get_company_profile",
            new=AsyncMock(return_value=company),
        ):
            return await get_access_status(current_user=user, db=SimpleNamespace())

    async def test_required_onboarding_and_approval_states(self):
        incomplete = await self.access(make_user(), None)
        self.assertEqual(incomplete.state, "onboarding_incomplete")
        self.assertTrue(incomplete.onboarding_required)

        pending = await self.access(make_user(), make_company())
        self.assertEqual(pending.state, "pending")
        self.assertFalse(pending.access_allowed)

        user_approved = await self.access(make_user("approved"), make_company())
        self.assertEqual(user_approved.state, "user_approved_company_pending")

        company_approved = await self.access(make_user(), make_company("approved"))
        self.assertEqual(company_approved.state, "company_approved_user_pending")

        approved = await self.access(make_user("approved"), make_company("approved"))
        self.assertEqual(approved.state, "approved")
        self.assertTrue(approved.access_allowed)

        rejected = await self.access(make_user("rejected"), make_company())
        self.assertEqual(rejected.state, "rejected")
        self.assertEqual(rejected.rejection_or_disabled_reason, "Review declined")

        disabled = await self.access(make_user(), make_company("disabled"))
        self.assertEqual(disabled.state, "disabled")
        self.assertEqual(
            disabled.rejection_or_disabled_reason,
            "Company review declined",
        )

    async def test_operator_access_does_not_require_company_profile(self):
        access = await self.access(make_user("approved", "operator"), None)
        self.assertTrue(access.access_allowed)
        self.assertEqual(access.state, "approved")

    async def test_stale_auth_version_can_only_use_rotation_dependency(self):
        user = make_user("approved")
        token = create_access_token({"sub": str(user.id), "auth_version": 3})
        credentials = SimpleNamespace(credentials=token)
        result = SimpleNamespace(scalar_one_or_none=lambda: user)
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        with self.assertRaises(HTTPException) as raised:
            await get_current_user(
                credentials=credentials,
                db=db,
                plasma_api_token=None,
            )
        self.assertEqual(raised.exception.status_code, 401)

        resolved = await get_current_user_allow_stale_auth_version(
            credentials=credentials,
            db=db,
            plasma_api_token=None,
        )
        self.assertIs(resolved, user)


class AdminCompanyApprovalTests(IsolatedAsyncioTestCase):
    async def test_company_approval_bumps_user_session_and_records_activity(self):
        target_user = make_user()
        profile = SimpleNamespace(
            id=uuid4(),
            user=target_user,
            user_id=target_user.id,
            company_name="Pilot Company",
            industry="Consulting",
            target_regions=[],
            target_countries=[],
            target_services=[],
            approval_status="pending",
            pilot_status="scoped",
            rejection_reason=None,
            approved_at=None,
            approved_by_user_id=None,
            rejected_at=None,
        )
        admin = make_user("approved", "admin")
        db = SimpleNamespace(
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        activity = AsyncMock()
        with (
            patch(
                "app.api.endpoints.admin._get_company_or_404",
                new=AsyncMock(return_value=profile),
            ),
            patch("app.api.endpoints.admin.record_admin_activity", new=activity),
        ):
            response = await approve_company(
                company_profile_id=profile.id,
                current_user=admin,
                db=db,
            )

        self.assertEqual(response.approval_status, "approved")
        self.assertEqual(target_user.auth_version, 5)
        activity.assert_awaited_once()
        self.assertEqual(activity.await_args.kwargs["action"], "company_approved")


class OnboardingFrontendTests(TestCase):
    def test_pending_and_session_refresh_ux_is_present(self):
        onboarding = (FRONTEND / "app/dashboard/onboarding/page.tsx").read_text()
        pending = (FRONTEND / "app/dashboard/pending-approval/page.tsx").read_text()
        layout = (FRONTEND / "app/dashboard/layout.tsx").read_text()
        auth = (FRONTEND / "auth.ts").read_text()

        self.assertNotIn("window.location.reload", onboarding)
        self.assertIn("Company profile submitted", onboarding)
        self.assertIn("router.replace('/dashboard/pending-approval')", onboarding)
        self.assertIn("Refresh approval status", pending)
        self.assertIn("Access approved", pending)
        self.assertIn("You do not need to submit the form again", pending)
        self.assertIn("'/users/me/access-status'", layout)
        self.assertIn("trigger === 'update'", auth)
        self.assertIn("await update()", onboarding)
