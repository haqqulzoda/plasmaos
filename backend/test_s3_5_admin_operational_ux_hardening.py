from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from uuid import uuid4

from app.api.endpoints.admin import (
    AdminAccountItem,
    _admin_account_payload,
    _allowed_account_actions,
    _display_role,
    _restore_target_status,
)


ROOT = Path(__file__).resolve().parent


def make_user(
    *,
    status: str = "approved",
    role: str = "pilot_user",
    is_admin: bool = False,
    previous: str | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        name="Account fixture",
        email=f"{uuid4()}@s35.invalid",
        approval_status=status,
        platform_role=role,
        is_admin=is_admin,
        pre_disabled_approval_status=previous,
        company_profile=None,
        created_at=None,
    )


class AdminOperationalContractTests(TestCase):
    def source(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_backend_owns_the_exact_action_matrix(self):
        actor = make_user(role="admin")
        expected = {
            "pending": ["approve", "reject", "disable"],
            "approved": ["reject", "disable"],
            "rejected": ["approve", "disable"],
            "disabled": ["restore"],
        }
        for status, actions in expected.items():
            with self.subTest(status=status):
                target = make_user(status=status)
                self.assertEqual(
                    _allowed_account_actions(target, current_user=actor),
                    actions,
                )

    def test_operator_capabilities_are_read_only_and_self_guard_uses_id(self):
        operator = make_user(role="operator")
        target = make_user(status="pending")
        self.assertEqual(
            _allowed_account_actions(target, current_user=operator),
            [],
        )

        actor = make_user(role="admin")
        actor.status = "approved"
        actor.approval_status = "approved"
        actor.email = target.email
        self.assertEqual(
            _allowed_account_actions(target, current_user=actor),
            ["approve", "reject", "disable"],
        )
        target.id = actor.id
        self.assertEqual(
            _allowed_account_actions(target, current_user=actor),
            ["approve"],
        )

    def test_restore_preview_is_safe_and_unknown_provenance_fails_closed(self):
        expected = {
            "pending": "pending",
            "approved": "approved",
            "rejected": "rejected",
            None: "pending",
            "invalid": "pending",
        }
        for previous, result in expected.items():
            with self.subTest(previous=previous):
                user = make_user(status="disabled", previous=previous)
                self.assertEqual(_restore_target_status(user), result)
        self.assertIsNone(_restore_target_status(make_user(status="approved")))

    def test_role_display_does_not_override_lifecycle_status(self):
        disabled_admin = make_user(status="disabled", role="admin")
        actor = make_user(role="admin")
        payload = _admin_account_payload(disabled_admin, current_user=actor)
        self.assertEqual(_display_role(disabled_admin), "admin")
        self.assertEqual(payload.role, "admin")
        self.assertEqual(payload.approval_status, "disabled")

    def test_account_contract_exposes_only_operational_fields(self):
        fields = set(AdminAccountItem.model_fields)
        self.assertEqual(
            fields,
            {
                "id",
                "name",
                "email",
                "approval_status",
                "role",
                "is_current_actor",
                "restore_target_status",
                "allowed_actions",
                "company",
                "created_at",
            },
        )
        self.assertNotIn("auth_version", fields)
        self.assertNotIn("pre_disabled_approval_status", fields)
        self.assertNotIn("google_id", fields)

    def test_account_api_is_bounded_filtered_and_deterministic(self):
        admin = self.source("app/api/endpoints/admin.py")
        self.assertIn('@router.get("/accounts"', admin)
        self.assertIn("Depends(require_operator_or_admin)", admin)
        self.assertIn("le=100", admin)
        self.assertIn("User.approval_status", admin)
        self.assertIn("User.platform_role", admin)
        self.assertIn("User.created_at.desc()", admin)
        self.assertIn("User.id.desc()", admin)
        self.assertIn("allowed_actions=_allowed_account_actions", admin)

    def test_ui_uses_only_canonical_action_endpoints(self):
        accounts = self.source("../frontend/app/admin/approvals/page.tsx")
        self.assertIn("/admin/users/${pendingAction.resourceId}/${pendingAction.action}", accounts)
        self.assertNotIn("api.patch", accounts)
        self.assertNotIn("api.put", accounts)
        self.assertNotIn("window.prompt", accounts)
        self.assertIn("account.allowed_actions", accounts)

    def test_no_sprint_35_migration_and_head_remains_sprint_34(self):
        migrations = sorted((ROOT / "alembic/versions").glob("*s3_5*"))
        self.assertEqual(migrations, [])
        s34 = self.source(
            "alembic/versions/20260828_0002_s3_4_admin_audit_hardening.py"
        )
        self.assertIn('revision: str = "20260828_0002_s3_4_admin_audit_hardening"', s34)


if __name__ == "__main__":
    import unittest

    unittest.main()
