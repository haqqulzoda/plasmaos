from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.api.deps import (
    has_approved_pilot_account_access,
    is_admin_user,
    is_approved_user,
    is_operator_user,
)
from app.api.endpoints.auth import _apply_email_bootstrap
from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_DISABLED,
    USER_APPROVAL_PENDING,
    parse_email_allowlist,
)


ROOT = Path(__file__).resolve().parent


def _user(
    *,
    email: str = "pilot@example.com",
    platform_role: str = PLATFORM_ROLE_PILOT_USER,
    approval_status: str = USER_APPROVAL_PENDING,
    is_admin: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email=email,
        platform_role=platform_role,
        approval_status=approval_status,
        is_admin=is_admin,
        approved_at=None,
    )


class AccessFoundationTests(unittest.TestCase):
    def test_parse_email_allowlist_normalizes_commas_spaces_and_case(self) -> None:
        self.assertEqual(
            parse_email_allowlist(" Admin@Example.COM, operator@example.com ,, "),
            {"admin@example.com", "operator@example.com"},
        )

    def test_guard_helpers_classify_canonical_roles(self) -> None:
        admin = _user(
            platform_role=PLATFORM_ROLE_ADMIN,
            approval_status=USER_APPROVAL_APPROVED,
        )
        operator = _user(
            platform_role=PLATFORM_ROLE_OPERATOR,
            approval_status=USER_APPROVAL_APPROVED,
        )
        approved = _user(approval_status=USER_APPROVAL_APPROVED)
        pending = _user()

        self.assertTrue(is_admin_user(admin))
        self.assertTrue(
            is_admin_user(
                _user(is_admin=True, approval_status=USER_APPROVAL_APPROVED)
            )
        )
        self.assertTrue(is_operator_user(admin))
        self.assertTrue(is_operator_user(operator))
        self.assertTrue(is_approved_user(admin))
        self.assertTrue(is_approved_user(operator))
        self.assertTrue(is_approved_user(approved))
        self.assertFalse(is_approved_user(pending))

    def test_operator_email_allowlist_still_grants_operator_access(self) -> None:
        with patch.dict(os.environ, {"PLASMA_OPERATOR_EMAILS": " OPS@Example.com "}, clear=False):
            self.assertFalse(is_operator_user(_user(email="ops@example.com")))
            self.assertTrue(
                is_operator_user(
                    _user(
                        email="ops@example.com",
                        approval_status=USER_APPROVAL_APPROVED,
                    )
                )
            )

    def test_approved_pilot_account_requires_user_and_company_approval(self) -> None:
        approved_user = _user(approval_status=USER_APPROVAL_APPROVED)
        approved_company = SimpleNamespace(approval_status=COMPANY_APPROVAL_APPROVED)
        pending_company = SimpleNamespace(approval_status=USER_APPROVAL_PENDING)

        self.assertTrue(has_approved_pilot_account_access(approved_user, approved_company))
        self.assertFalse(has_approved_pilot_account_access(approved_user, pending_company))
        self.assertFalse(has_approved_pilot_account_access(_user(), approved_company))
        self.assertFalse(
            has_approved_pilot_account_access(
                _user(approval_status=USER_APPROVAL_DISABLED, is_admin=True),
                None,
            )
        )

    def test_auth_bootstrap_promotes_admin_and_operator_allowlists(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PLASMA_ADMIN_EMAILS": "admin@example.com",
                "PLASMA_OPERATOR_EMAILS": "operator@example.com",
            },
            clear=False,
        ):
            admin = _user(email="admin@example.com")
            _apply_email_bootstrap(admin, email=admin.email)
            self.assertEqual(admin.platform_role, PLATFORM_ROLE_ADMIN)
            self.assertEqual(admin.approval_status, USER_APPROVAL_APPROVED)
            self.assertTrue(admin.is_admin)
            self.assertIsNotNone(admin.approved_at)

            operator = _user(email="operator@example.com")
            _apply_email_bootstrap(operator, email=operator.email)
            self.assertEqual(operator.platform_role, PLATFORM_ROLE_OPERATOR)
            self.assertEqual(operator.approval_status, USER_APPROVAL_APPROVED)
            self.assertFalse(operator.is_admin)
            self.assertIsNotNone(operator.approved_at)

            normal = _user(email="new@example.com")
            _apply_email_bootstrap(normal, email=normal.email)
            self.assertEqual(normal.platform_role, PLATFORM_ROLE_PILOT_USER)
            self.assertEqual(normal.approval_status, USER_APPROVAL_PENDING)

            legacy_admin = _user(email="legacy-admin@example.com", is_admin=True)
            _apply_email_bootstrap(legacy_admin, email=legacy_admin.email)
            self.assertEqual(legacy_admin.platform_role, PLATFORM_ROLE_ADMIN)
            self.assertEqual(legacy_admin.approval_status, USER_APPROVAL_APPROVED)

    def test_users_company_get_does_not_create_profile(self) -> None:
        users_source = (ROOT / "app/api/endpoints/users.py").read_text(encoding="utf-8")
        get_block = users_source.split("async def get_company_profile", 1)[1].split(
            "@router.put",
            1,
        )[0]

        self.assertIn("onboarding_required=True", users_source)
        self.assertIn("_get_company_profile", get_block)
        self.assertNotIn("CompanyProfile(", get_block)

    def test_migration_backfills_existing_rows_without_auto_creating_profiles(self) -> None:
        migration = (
            ROOT
            / "alembic/versions/20260624_0001_s1_1_access_foundation.py"
        ).read_text(encoding="utf-8")

        self.assertIn("approval_status = 'approved'", migration)
        self.assertIn("WHEN is_admin IS TRUE THEN 'admin'", migration)
        self.assertIn("created_by_user_id = COALESCE(created_by_user_id, user_id)", migration)
        self.assertNotIn("INSERT INTO company_profiles", migration)


if __name__ == "__main__":
    unittest.main()
