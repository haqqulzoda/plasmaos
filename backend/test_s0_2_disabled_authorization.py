from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException, Response

import app.core.security as runtime_security
from app.api.deps import (
    has_approved_pilot_account_access,
    is_admin_user,
    is_approved_user,
    is_operator_user,
    require_admin,
    require_approved_user,
    require_operator,
)
from app.api.endpoints.admin import (
    ApprovalActionRequest,
    approve_user,
    disable_user,
)
from app.api.endpoints.auth import (
    GoogleAuthRequest,
    _apply_email_bootstrap,
    google_auth_bridge,
    refresh_token,
)
from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_APPROVAL_DISABLED,
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_DISABLED,
    is_disabled_account,
)
from app.core.security import (
    create_access_token,
    get_current_user,
    get_current_user_allow_stale_auth_version,
)


ROOT = Path(__file__).resolve().parent


def make_user(
    *,
    status: str = USER_APPROVAL_APPROVED,
    role: str = PLATFORM_ROLE_PILOT_USER,
    email: str = "pilot@example.com",
    auth_version: int = 4,
    is_admin: bool | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        google_id="google-id",
        email=email,
        name="Pilot User",
        avatar_url=None,
        company_name=None,
        approval_status=status,
        platform_role=role,
        is_admin=(role == PLATFORM_ROLE_ADMIN) if is_admin is None else is_admin,
        auth_version=auth_version,
        subscription_tier=SimpleNamespace(value="scout"),
        approved_at=None,
        approved_by_user_id=None,
        rejected_at=None,
        rejection_reason=None,
        disabled_at=None,
        created_at=None,
    )


def fake_user_db(user: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace(scalar_one_or_none=lambda: user)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


async def resolve_user(
    user: SimpleNamespace,
    *,
    token_auth_version: int | None = None,
    allow_stale: bool = False,
) -> SimpleNamespace:
    version = user.auth_version if token_auth_version is None else token_auth_version
    token = create_access_token({"sub": str(user.id), "auth_version": version})
    dependency = (
        get_current_user_allow_stale_auth_version if allow_stale else get_current_user
    )
    return await dependency(
        credentials=SimpleNamespace(credentials=token),
        db=fake_user_db(user),
        plasma_api_token=None,
    )


class DisabledAuthorizationUnitTests(IsolatedAsyncioTestCase):
    async def test_active_ordinary_admin_and_operator_access_is_preserved(self) -> None:
        ordinary = make_user()
        admin = make_user(role=PLATFORM_ROLE_ADMIN)
        operator = make_user(role=PLATFORM_ROLE_OPERATOR)

        self.assertIs(await resolve_user(ordinary), ordinary)
        self.assertIs(await require_approved_user(ordinary), ordinary)
        self.assertIs(await require_admin(admin), admin)
        self.assertIs(await require_operator(operator), operator)
        self.assertTrue(is_approved_user(ordinary))
        self.assertTrue(is_admin_user(admin))
        self.assertTrue(is_operator_user(operator))

    async def test_disabled_ordinary_admin_and_operator_fail_normal_authentication(self) -> None:
        users = (
            make_user(status=USER_APPROVAL_DISABLED),
            make_user(status=USER_APPROVAL_DISABLED, role=PLATFORM_ROLE_ADMIN),
            make_user(status=USER_APPROVAL_DISABLED, role=PLATFORM_ROLE_OPERATOR),
        )

        for user in users:
            with self.subTest(role=user.platform_role):
                with self.assertRaises(HTTPException) as raised:
                    await resolve_user(user)
                self.assertEqual(raised.exception.status_code, 401)
                self.assertEqual(raised.exception.detail, "Account disabled")

    async def test_disabled_privileged_users_fail_direct_role_dependencies(self) -> None:
        disabled_admin = make_user(
            status=USER_APPROVAL_DISABLED,
            role=PLATFORM_ROLE_ADMIN,
        )
        disabled_operator = make_user(
            status=USER_APPROVAL_DISABLED,
            role=PLATFORM_ROLE_OPERATOR,
        )

        with self.assertRaises(HTTPException) as admin_denied:
            await require_admin(disabled_admin)
        self.assertEqual(admin_denied.exception.status_code, 403)
        self.assertFalse(is_admin_user(disabled_admin))

        with self.assertRaises(HTTPException) as operator_denied:
            await require_operator(disabled_operator)
        self.assertEqual(operator_denied.exception.status_code, 403)
        self.assertFalse(is_operator_user(disabled_operator))

        with self.assertRaises(HTTPException):
            await require_approved_user(disabled_admin)

    async def test_disabled_roles_cannot_use_stale_version_refresh_dependency(self) -> None:
        users = (
            make_user(status=USER_APPROVAL_DISABLED),
            make_user(status=USER_APPROVAL_DISABLED, role=PLATFORM_ROLE_ADMIN),
            make_user(status=USER_APPROVAL_DISABLED, role=PLATFORM_ROLE_OPERATOR),
        )

        for user in users:
            with self.subTest(role=user.platform_role):
                with self.assertRaises(HTTPException) as raised:
                    await resolve_user(
                        user,
                        token_auth_version=user.auth_version - 1,
                        allow_stale=True,
                    )
                self.assertEqual(raised.exception.status_code, 401)
                self.assertEqual(raised.exception.detail, "Account disabled")

    async def test_refresh_endpoint_has_its_own_disabled_guard(self) -> None:
        disabled_admin = make_user(
            status=USER_APPROVAL_DISABLED,
            role=PLATFORM_ROLE_ADMIN,
        )
        with self.assertRaises(HTTPException) as raised:
            await refresh_token(
                response=Response(),
                current_user=disabled_admin,
                db=SimpleNamespace(),
            )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_disabled_allowlisted_accounts_are_not_bootstrapped_or_logged_in(self) -> None:
        allowlists = {
            "PLASMA_ADMIN_EMAILS": "admin@example.com",
            "PLASMA_OPERATOR_EMAILS": "operator@example.com",
        }
        with patch.dict(os.environ, allowlists, clear=False):
            for email, role in (
                ("admin@example.com", PLATFORM_ROLE_ADMIN),
                ("operator@example.com", PLATFORM_ROLE_OPERATOR),
            ):
                with self.subTest(email=email):
                    user = make_user(
                        status=USER_APPROVAL_DISABLED,
                        role=role,
                        email=email,
                    )
                    _apply_email_bootstrap(user, email=email)
                    self.assertEqual(user.approval_status, USER_APPROVAL_DISABLED)

                    db = fake_user_db(user)
                    db.add = lambda _value: None
                    db.commit = AsyncMock()
                    db.refresh = AsyncMock()
                    with self.assertRaises(HTTPException) as raised:
                        await google_auth_bridge(
                            payload=GoogleAuthRequest(
                                google_id=user.google_id,
                                email=email,
                                name=user.name,
                            ),
                            response=Response(),
                            db=db,
                        )
                    self.assertEqual(raised.exception.status_code, 403)
                    self.assertEqual(raised.exception.detail, "Account disabled")
                    db.commit.assert_not_awaited()

                    with self.assertRaises(HTTPException):
                        await resolve_user(user, allow_stale=True)

    async def test_disable_bumps_version_and_old_token_remains_invalid_after_restore(self) -> None:
        target = make_user(auth_version=7)
        admin = make_user(role=PLATFORM_ROLE_ADMIN)
        old_token_version = target.auth_version
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

        with (
            patch(
                "app.api.endpoints.admin._get_user_or_404",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "app.api.endpoints.admin.record_admin_activity",
                new=AsyncMock(),
            ),
        ):
            await disable_user(
                user_id=target.id,
                payload=ApprovalActionRequest(reason="Security response"),
                current_user=admin,
                db=db,
            )

        self.assertEqual(target.approval_status, USER_APPROVAL_DISABLED)
        self.assertEqual(target.auth_version, old_token_version + 1)
        self.assertIsNotNone(target.disabled_at)

        with self.assertRaises(HTTPException) as disabled_denial:
            await resolve_user(target, token_auth_version=old_token_version)
        self.assertEqual(disabled_denial.exception.status_code, 401)

        # If an administrator restores status, the pre-disable token is still
        # rejected by the existing auth_version mechanism.
        target.approval_status = USER_APPROVAL_APPROVED
        with self.assertRaises(HTTPException) as stale_denial:
            await resolve_user(target, token_auth_version=old_token_version)
        self.assertEqual(stale_denial.exception.status_code, 401)
        self.assertEqual(stale_denial.exception.detail, "Fresh authentication required")

    async def test_existing_approve_transition_restores_access_with_new_version(self) -> None:
        target = make_user(
            status=USER_APPROVAL_DISABLED,
            role=PLATFORM_ROLE_ADMIN,
            auth_version=9,
        )
        target.disabled_at = SimpleNamespace()
        admin = make_user(role=PLATFORM_ROLE_ADMIN)
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

        with (
            patch(
                "app.api.endpoints.admin._get_user_or_404",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "app.api.endpoints.admin.record_admin_activity",
                new=AsyncMock(),
            ),
        ):
            await approve_user(
                user_id=target.id,
                current_user=admin,
                db=db,
            )

        self.assertEqual(target.approval_status, USER_APPROVAL_APPROVED)
        self.assertEqual(target.auth_version, 10)
        self.assertIsNone(target.disabled_at)
        self.assertIs(await resolve_user(target), target)
        self.assertIs(await require_admin(target), target)

    async def test_company_disable_still_gates_pilots_but_not_active_operator_policy(self) -> None:
        disabled_company = SimpleNamespace(approval_status=COMPANY_APPROVAL_DISABLED)
        approved_company = SimpleNamespace(approval_status=COMPANY_APPROVAL_APPROVED)
        ordinary = make_user()
        active_operator = make_user(role=PLATFORM_ROLE_OPERATOR)
        disabled_operator = make_user(
            status=USER_APPROVAL_DISABLED,
            role=PLATFORM_ROLE_OPERATOR,
        )

        self.assertFalse(has_approved_pilot_account_access(ordinary, disabled_company))
        self.assertTrue(
            has_approved_pilot_account_access(active_operator, disabled_company)
        )
        self.assertFalse(
            has_approved_pilot_account_access(disabled_operator, approved_company)
        )


class DisabledAuthorizationStaticTests(TestCase):
    def test_disabled_status_normalization_is_defensive(self) -> None:
        self.assertTrue(
            is_disabled_account(SimpleNamespace(approval_status=" DISABLED "))
        )
        self.assertFalse(
            is_disabled_account(SimpleNamespace(approval_status="approved"))
        )

    def test_runtime_security_package_and_compatibility_mirror_share_guard(self) -> None:
        self.assertEqual(Path(runtime_security.__file__).name, "__init__.py")
        package_source = (ROOT / "app/core/security/__init__.py").read_text(
            encoding="utf-8"
        )
        mirror_source = (ROOT / "app/core/security.py").read_text(encoding="utf-8")
        self.assertIn("if is_disabled_account(user):", package_source)
        self.assertIn("if is_disabled_account(user):", mirror_source)


if __name__ == "__main__":
    import unittest

    unittest.main()
