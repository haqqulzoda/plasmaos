from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import CheckConstraint

from app.api.deps import is_admin_user, is_approved_user, is_operator_user
from app.api.endpoints.admin import ApprovalActionRequest, approve_user, restore_user
from app.api.endpoints.auth import GoogleAuthRequest, _apply_email_bootstrap, google_auth_bridge
from app.core.access import (
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_DISABLED,
    USER_APPROVAL_PENDING,
    USER_APPROVAL_REJECTED,
)
from app.models.all_models import Base
from app.services.account_lifecycle import (
    InvalidAccountLifecycleTransition,
    transition_user_account,
)
from app.services.admin_activity import user_role_snapshot


ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "alembic/versions/20260828_0001_s3_1_admin_account_lifecycle.py"


def make_user(
    state: str,
    *,
    role: str = PLATFORM_ROLE_PILOT_USER,
    email: str = "user@example.com",
    auth_version: int = 3,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        google_id="google-id",
        name="Lifecycle User",
        email=email,
        avatar_url=None,
        approval_status=state,
        pre_disabled_approval_status=None,
        platform_role=role,
        is_admin=role == PLATFORM_ROLE_ADMIN,
        approved_at=None,
        approved_by_user_id=None,
        rejected_at=None,
        rejection_reason=None,
        disabled_at=None,
        auth_version=auth_version,
        subscription_tier=SimpleNamespace(value="scout"),
        created_at=None,
    )


class AccountLifecycleServiceTests(TestCase):
    def setUp(self) -> None:
        self.actor = make_user(USER_APPROVAL_APPROVED, role=PLATFORM_ROLE_ADMIN)
        self.now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    def transition(self, user: SimpleNamespace, action: str, reason: str | None = None):
        return transition_user_account(
            user,
            action=action,  # type: ignore[arg-type]
            actor_user=self.actor,
            reason=reason,
            occurred_at=self.now,
        )

    def test_explicit_allowed_transition_matrix(self) -> None:
        expected = {
            (USER_APPROVAL_PENDING, "approve"): USER_APPROVAL_APPROVED,
            (USER_APPROVAL_PENDING, "reject"): USER_APPROVAL_REJECTED,
            (USER_APPROVAL_PENDING, "disable"): USER_APPROVAL_DISABLED,
            (USER_APPROVAL_APPROVED, "reject"): USER_APPROVAL_REJECTED,
            (USER_APPROVAL_APPROVED, "disable"): USER_APPROVAL_DISABLED,
            (USER_APPROVAL_REJECTED, "approve"): USER_APPROVAL_APPROVED,
            (USER_APPROVAL_REJECTED, "disable"): USER_APPROVAL_DISABLED,
        }
        for (source, action), destination in expected.items():
            with self.subTest(source=source, action=action):
                user = make_user(source)
                transition = self.transition(user, action)
                self.assertEqual(user.approval_status, destination)
                self.assertEqual(transition.previous_state, source)
                self.assertEqual(transition.new_state, destination)
                self.assertEqual(user.auth_version, 4)

    def test_invalid_transitions_are_strict_and_do_not_mutate(self) -> None:
        invalid = (
            (USER_APPROVAL_APPROVED, "approve"),
            (USER_APPROVAL_REJECTED, "reject"),
            (USER_APPROVAL_DISABLED, "approve"),
            (USER_APPROVAL_DISABLED, "reject"),
            (USER_APPROVAL_DISABLED, "disable"),
            (USER_APPROVAL_PENDING, "restore"),
            (USER_APPROVAL_APPROVED, "restore"),
            (USER_APPROVAL_REJECTED, "restore"),
        )
        for source, action in invalid:
            with self.subTest(source=source, action=action):
                user = make_user(source)
                with self.assertRaises(InvalidAccountLifecycleTransition):
                    self.transition(user, action)
                self.assertEqual(user.approval_status, source)
                self.assertEqual(user.auth_version, 3)

    def test_restore_matrix_preserves_each_known_prior_state(self) -> None:
        for prior in (
            USER_APPROVAL_PENDING,
            USER_APPROVAL_APPROVED,
            USER_APPROVAL_REJECTED,
        ):
            with self.subTest(prior=prior):
                user = make_user(prior, auth_version=7)
                if prior == USER_APPROVAL_REJECTED:
                    user.rejected_at = self.now
                    user.rejection_reason = "Policy decision"
                self.transition(user, "disable")
                self.assertEqual(user.approval_status, USER_APPROVAL_DISABLED)
                self.assertEqual(user.pre_disabled_approval_status, prior)
                self.assertEqual(user.auth_version, 8)

                restored = self.transition(user, "restore")
                self.assertEqual(restored.new_state, prior)
                self.assertEqual(user.approval_status, prior)
                self.assertIsNone(user.pre_disabled_approval_status)
                self.assertIsNone(user.disabled_at)
                self.assertEqual(user.auth_version, 9)
                if prior == USER_APPROVAL_REJECTED:
                    self.assertEqual(user.rejection_reason, "Policy decision")

    def test_unknown_prior_state_restores_conservatively_to_pending(self) -> None:
        user = make_user(USER_APPROVAL_DISABLED, auth_version=11)
        user.disabled_at = self.now
        transition = self.transition(user, "restore")

        self.assertEqual(transition.new_state, USER_APPROVAL_PENDING)
        self.assertEqual(user.approval_status, USER_APPROVAL_PENDING)
        self.assertEqual(user.auth_version, 12)
        self.assertFalse(is_approved_user(user))

    def test_disable_and_reject_remain_distinct(self) -> None:
        rejected = make_user(USER_APPROVAL_APPROVED)
        self.transition(rejected, "reject", "Not approved")
        self.assertEqual(rejected.approval_status, USER_APPROVAL_REJECTED)
        self.assertIsNotNone(rejected.rejected_at)
        self.assertIsNone(rejected.disabled_at)

        disabled = make_user(USER_APPROVAL_APPROVED)
        self.transition(disabled, "disable", "Suspended")
        self.assertEqual(disabled.approval_status, USER_APPROVAL_DISABLED)
        self.assertEqual(
            disabled.pre_disabled_approval_status,
            USER_APPROVAL_APPROVED,
        )
        self.assertIsNotNone(disabled.disabled_at)
        self.assertIsNone(disabled.rejected_at)

    def test_pending_rejected_and_disabled_roles_never_override_lifecycle(self) -> None:
        for state in (
            USER_APPROVAL_PENDING,
            USER_APPROVAL_REJECTED,
            USER_APPROVAL_DISABLED,
        ):
            for role in (
                PLATFORM_ROLE_PILOT_USER,
                PLATFORM_ROLE_ADMIN,
                PLATFORM_ROLE_OPERATOR,
            ):
                with self.subTest(state=state, role=role):
                    user = make_user(state, role=role)
                    self.assertFalse(is_admin_user(user))
                    self.assertFalse(is_operator_user(user))
                    self.assertFalse(is_approved_user(user))

    def test_allowlist_does_not_override_rejection_or_disable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PLASMA_ADMIN_EMAILS": "admin@example.com",
                "PLASMA_OPERATOR_EMAILS": "operator@example.com",
            },
            clear=False,
        ):
            for state in (USER_APPROVAL_REJECTED, USER_APPROVAL_DISABLED):
                for email in ("admin@example.com", "operator@example.com"):
                    with self.subTest(state=state, email=email):
                        user = make_user(state, email=email)
                        _apply_email_bootstrap(user, email=email)
                        self.assertEqual(user.approval_status, state)
                        self.assertEqual(user.platform_role, PLATFORM_ROLE_PILOT_USER)


class AccountLifecycleEndpointTests(IsolatedAsyncioTestCase):
    @staticmethod
    def locked_apply(target, actor):
        async def apply(_db=None, **kwargs):
            before = user_role_snapshot(target)
            transition = transition_user_account(
                target,
                action=kwargs["action"],
                actor_user=actor,
                reason=kwargs.get("reason"),
            )
            return SimpleNamespace(
                actor=actor,
                target=target,
                before=before,
                transition=transition,
            )

        return apply

    async def test_google_login_denies_rejected_account_token_issuance(self) -> None:
        target = make_user(
            USER_APPROVAL_REJECTED,
            email="admin@example.com",
        )
        user_result = SimpleNamespace(scalar_one_or_none=lambda: target)
        no_profile_result = SimpleNamespace(scalar_one_or_none=lambda: None)
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=(user_result, no_profile_result)),
            commit=AsyncMock(),
            refresh=AsyncMock(),
            add=lambda _value: None,
        )

        with patch.dict(
            os.environ,
            {"PLASMA_ADMIN_EMAILS": "admin@example.com"},
            clear=False,
        ):
            with self.assertRaises(HTTPException) as raised:
                await google_auth_bridge(
                    GoogleAuthRequest(
                        google_id=target.google_id,
                        email=target.email,
                        name=target.name,
                    ),
                    Response(),
                    db,
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(target.approval_status, USER_APPROVAL_REJECTED)
        self.assertEqual(target.platform_role, PLATFORM_ROLE_PILOT_USER)
        db.commit.assert_not_awaited()

    async def test_direct_approve_of_disabled_user_returns_409(self) -> None:
        target = make_user(USER_APPROVAL_DISABLED)
        target.pre_disabled_approval_status = USER_APPROVAL_APPROVED
        actor = make_user(USER_APPROVAL_APPROVED, role=PLATFORM_ROLE_ADMIN)
        db = SimpleNamespace(rollback=AsyncMock())

        with (
            patch(
                "app.api.endpoints.admin.apply_locked_user_lifecycle_mutation",
                new=self.locked_apply(target, actor),
            ),
            patch(
                "app.api.endpoints.admin.record_independent_user_audit_event",
                new=AsyncMock(),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await approve_user(target.id, actor, db)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(target.approval_status, USER_APPROVAL_DISABLED)

    async def test_restore_endpoint_records_transition_context(self) -> None:
        target = make_user(USER_APPROVAL_DISABLED)
        target.pre_disabled_approval_status = USER_APPROVAL_REJECTED
        actor = make_user(USER_APPROVAL_APPROVED, role=PLATFORM_ROLE_ADMIN)
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
        audit = AsyncMock()
        with (
            patch(
                "app.api.endpoints.admin.apply_locked_user_lifecycle_mutation",
                new=self.locked_apply(target, actor),
            ),
            patch("app.api.endpoints.admin.record_admin_audit_event", new=audit),
        ):
            response = await restore_user(
                target.id,
                ApprovalActionRequest(reason="Reviewed"),
                db,
                actor,
            )

        self.assertEqual(response.approval_status, USER_APPROVAL_REJECTED)
        self.assertEqual(audit.await_args.kwargs["action"], "USER_RESTORED")
        self.assertEqual(
            audit.await_args.kwargs["previous_state"]["approval_status"],
            USER_APPROVAL_DISABLED,
        )
        self.assertEqual(
            audit.await_args.kwargs["new_state"]["approval_status"],
            USER_APPROVAL_REJECTED,
        )


class AccountLifecycleSchemaTests(TestCase):
    def test_orm_declares_canonical_and_pre_disable_constraints(self) -> None:
        users = Base.metadata.tables["users"]
        self.assertIn("approval_status", users.c)
        self.assertIn("pre_disabled_approval_status", users.c)
        constraints = {
            constraint.name: str(constraint.sqltext)
            for constraint in users.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn("ck_users_approval_status_allowed", constraints)
        self.assertIn("ck_users_pre_disabled_approval_status_allowed", constraints)
        self.assertIn("approval_status = 'disabled'", constraints["ck_users_pre_disabled_approval_status_allowed"])

    def test_additive_migration_preserves_unknown_history(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('op.add_column(\n        "users"', source)
        self.assertIn('"pre_disabled_approval_status"', source)
        self.assertIn("Existing disabled accounts receive NULL", source)
        self.assertNotIn("UPDATE users", source)
        self.assertNotIn("DELETE FROM users", source)
        self.assertNotIn("INSERT INTO users", source)


if __name__ == "__main__":
    import unittest

    unittest.main()
