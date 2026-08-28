from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.api.deps import require_approved_user
from app.core.security import create_access_token, get_current_user
from app.services.account_lifecycle import transition_user_account


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"


def make_user(status: str = "approved", *, auth_version: int = 10):
    return SimpleNamespace(
        id=uuid4(),
        google_id="google-id",
        email="pilot@example.com",
        name="Pilot",
        approval_status=status,
        pre_disabled_approval_status=None,
        platform_role="pilot_user",
        is_admin=False,
        auth_version=auth_version,
        approved_at=None,
        approved_by_user_id=None,
        rejected_at=None,
        rejection_reason=None,
        disabled_at=None,
    )


def fake_db(user):
    result = SimpleNamespace(scalar_one_or_none=lambda: user)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


async def authenticate(user, *, version: int | None, nonce: str = "device"):
    payload = {"sub": str(user.id), "nonce": nonce}
    if version is not None:
        payload["auth_version"] = version
    token = create_access_token(payload)
    return await get_current_user(
        credentials=SimpleNamespace(credentials=token),
        db=fake_db(user),
        plasma_api_token=None,
    )


class SessionRevocationTests(IsolatedAsyncioTestCase):
    async def assert_denied(self, user, *, version: int | None, detail: str | None = None):
        with self.assertRaises(HTTPException) as raised:
            await authenticate(user, version=version)
        self.assertEqual(raised.exception.status_code, 401)
        if detail is not None:
            self.assertEqual(raised.exception.detail, detail)

    async def test_exact_version_is_required_even_for_version_zero(self):
        user = make_user(auth_version=0)
        await self.assert_denied(
            user,
            version=None,
            detail="Fresh authentication required",
        )
        self.assertIs(await authenticate(user, version=0), user)

        for invalid_version in ("0", False, 0.5):
            token = create_access_token(
                {"sub": str(user.id), "auth_version": invalid_version}
            )
            with self.subTest(invalid_version=invalid_version):
                with self.assertRaises(HTTPException) as invalid:
                    await get_current_user(
                        credentials=SimpleNamespace(credentials=token),
                        db=fake_db(user),
                        plasma_api_token=None,
                    )
                self.assertEqual(invalid.exception.detail, "Invalid token payload")

        user.auth_version = -1
        await self.assert_denied(
            user,
            version=-1,
            detail="Invalid account security state",
        )

    async def test_disable_and_restore_never_revive_pre_disable_token(self):
        actor = make_user()
        user = make_user(auth_version=20)
        old_version = user.auth_version

        transition_user_account(user, action="disable", actor_user=actor)
        self.assertEqual(user.auth_version, 21)
        await self.assert_denied(user, version=old_version, detail="Account disabled")

        transition_user_account(user, action="restore", actor_user=actor)
        self.assertEqual(user.auth_version, 22)
        await self.assert_denied(
            user,
            version=old_version,
            detail="Fresh authentication required",
        )
        self.assertIs(await authenticate(user, version=22), user)

    async def test_reject_and_approve_each_revoke_old_credentials(self):
        actor = make_user()
        rejected = make_user(auth_version=30)
        transition_user_account(rejected, action="reject", actor_user=actor)
        await self.assert_denied(rejected, version=30, detail="Account rejected")
        await self.assert_denied(rejected, version=31, detail="Account rejected")

        pending = make_user("pending", auth_version=40)
        self.assertIs(await authenticate(pending, version=40), pending)
        with self.assertRaises(HTTPException) as pending_denial:
            await require_approved_user(pending)
        self.assertEqual(pending_denial.exception.status_code, 403)

        transition_user_account(pending, action="approve", actor_user=actor)
        await self.assert_denied(
            pending,
            version=40,
            detail="Fresh authentication required",
        )
        self.assertIs(await authenticate(pending, version=41), pending)

    async def test_all_device_tokens_and_missing_users_fail_closed(self):
        actor = make_user()
        user = make_user(auth_version=50)
        device_tokens = [
            create_access_token(
                {"sub": str(user.id), "auth_version": 50, "nonce": device}
            )
            for device in ("phone", "laptop")
        ]
        transition_user_account(user, action="disable", actor_user=actor)

        for token in device_tokens:
            with self.subTest(token=token[-8:]):
                with self.assertRaises(HTTPException) as raised:
                    await get_current_user(
                        credentials=SimpleNamespace(credentials=token),
                        db=fake_db(user),
                        plasma_api_token=None,
                    )
                self.assertEqual(raised.exception.status_code, 401)

        missing_result = SimpleNamespace(scalar_one_or_none=lambda: None)
        missing_db = SimpleNamespace(execute=AsyncMock(return_value=missing_result))
        token = create_access_token({"sub": str(uuid4()), "auth_version": 0})
        with self.assertRaises(HTTPException) as missing:
            await get_current_user(
                credentials=SimpleNamespace(credentials=token),
                db=missing_db,
                plasma_api_token=None,
            )
        self.assertEqual(missing.exception.detail, "User not found")


class SessionRevocationStaticTests(TestCase):
    def backend(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def frontend(self, relative: str) -> str:
        return (FRONTEND / relative).read_text(encoding="utf-8")

    def test_refresh_and_access_status_have_no_stale_version_bypass(self):
        security_package = self.backend("app/core/security/__init__.py")
        security_mirror = self.backend("app/core/security.py")
        auth = self.backend("app/api/endpoints/auth.py")
        users = self.backend("app/api/endpoints/users.py")

        combined = security_package + security_mirror + auth + users
        self.assertNotIn("get_current_user_allow_stale_auth_version", combined)
        self.assertIn("current_user: User = Depends(get_current_user)", auth)
        self.assertIn("current_user: User = Depends(get_current_user)", users)
        self.assertNotIn("auth_version: int", users)

    def test_browser_cookie_and_authjs_callbacks_revalidate_current_authority(self):
        auth = self.frontend("auth.ts")
        middleware = self.frontend("middleware.ts")
        proxy = self.frontend("lib/documentProxy.ts")

        self.assertIn("await validateAndRotateBackendSession", auth)
        self.assertIn("clearBackendAuthority(token)", auth)
        self.assertIn("BackendSessionRevoked", auth)
        self.assertNotIn("keep existing token", auth)
        self.assertIn("`${backendApiBase}/users/me`", middleware)
        self.assertIn("cache: 'no-store'", middleware)
        self.assertIn("Authorization: `Bearer ${accessToken}`", middleware)
        self.assertIn("const session = await auth();", proxy)
        self.assertIn("Authorization: `Bearer ${accessToken}`", proxy)

    def test_token_issuance_and_role_grants_revoke_atomically(self):
        auth = self.backend("app/api/endpoints/auth.py")
        command = self.backend("app/cli/admin_management.py")
        lifecycle = self.backend("app/services/account_lifecycle.py")

        self.assertIn("if is_rejected_account(user):", auth)
        self.assertLess(auth.index("bump_auth_version(user)"), auth.index("await db.commit()"))
        self.assertIn("account_restore_required", command)
        self.assertLess(command.index("bump_auth_version(user)"), command.index("await db.commit()"))
        self.assertIn("bump_auth_version(user)", lifecycle)

    def test_preflight_reports_only_aggregate_revocation_health(self):
        preflight = self.backend("scripts/run_s0_3_schema_data_preflight.py")
        for marker in (
            'data["credential_revocation"]',
            "null_auth_versions",
            "negative_auth_versions",
            "minimum_auth_version",
            "maximum_auth_version",
        ):
            self.assertIn(marker, preflight)
        self.assertNotIn("access_token", preflight)


if __name__ == "__main__":
    import unittest

    unittest.main()
