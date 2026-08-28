from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.endpoints.admin import ApprovalActionRequest, disable_user, reject_user
from app.core.access import is_effective_admin
from app.services.account_lifecycle import InvalidAccountLifecycleTransition
from app.services.admin_survivability import (
    ADMIN_SURVIVABILITY_LOCK_KEY,
    ADMIN_SURVIVABILITY_LOCK_NAMESPACE,
    AdminActorAuthorityLost,
    AdminSurvivabilityViolation,
    apply_locked_user_lifecycle_mutation,
)


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"


def make_user(
    state: str = "approved",
    *,
    role: str = "admin",
    legacy_admin: bool = False,
    version: int = 5,
):
    return SimpleNamespace(
        id=uuid4(),
        google_id=f"google-{uuid4()}",
        email=f"{uuid4()}@example.com",
        name="Admin",
        approval_status=state,
        pre_disabled_approval_status=None,
        platform_role=role,
        is_admin=legacy_admin,
        auth_version=version,
        approved_at=None,
        approved_by_user_id=None,
        rejected_at=None,
        rejection_reason=None,
        disabled_at=None,
    )


class ScalarResult:
    def __init__(self, *, users=None, value=None):
        self._users = users or []
        self._value = value

    def scalars(self):
        return SimpleNamespace(all=lambda: self._users)

    def scalar_one(self):
        return self._value


def fake_db(*results):
    return SimpleNamespace(execute=AsyncMock(side_effect=results))


class EffectiveAdminTests(TestCase):
    def test_effective_admin_matches_canonical_backend_authority(self):
        self.assertTrue(is_effective_admin(make_user()))
        self.assertTrue(
            is_effective_admin(make_user(role="pilot_user", legacy_admin=True))
        )
        for state in ("pending", "rejected", "disabled"):
            with self.subTest(state=state):
                self.assertFalse(is_effective_admin(make_user(state)))
        self.assertFalse(is_effective_admin(make_user(role="operator")))
        self.assertFalse(is_effective_admin(make_user(role="pilot_user")))


class LockedMutationTests(IsolatedAsyncioTestCase):
    async def test_api_maps_self_action_denials_to_409_without_commit(self):
        actor = make_user()
        db = SimpleNamespace(
            commit=AsyncMock(),
            refresh=AsyncMock(),
            rollback=AsyncMock(),
        )
        for endpoint, arguments in (
            (
                disable_user,
                {"payload": ApprovalActionRequest(reason="self")},
            ),
            (
                reject_user,
                {"payload": ApprovalActionRequest(reason="self")},
            ),
        ):
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    patch(
                        "app.api.endpoints.admin.apply_locked_user_lifecycle_mutation",
                        new=AsyncMock(
                            side_effect=AdminSurvivabilityViolation("Self-action prohibited")
                        ),
                    ),
                    patch(
                        "app.api.endpoints.admin.record_independent_user_audit_event",
                        new=AsyncMock(),
                    ),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await endpoint(
                            user_id=actor.id,
                            current_user=actor,
                            db=db,
                            **arguments,
                        )
                self.assertEqual(raised.exception.status_code, 409)
        db.commit.assert_not_awaited()

    async def test_self_disable_and_self_reject_are_separate_hard_denials(self):
        for action in ("disable", "reject"):
            actor = make_user()
            db = fake_db(ScalarResult(), ScalarResult(users=[actor]))
            with self.subTest(action=action):
                with self.assertRaises(AdminSurvivabilityViolation) as raised:
                    await apply_locked_user_lifecycle_mutation(
                        db,
                        actor_user_id=actor.id,
                        target_user_id=actor.id,
                        action=action,
                    )
                self.assertEqual(raised.exception.reason_code, "SELF_ACTION_PROHIBITED")
                self.assertEqual(actor.approval_status, "approved")
                self.assertEqual(actor.auth_version, 5)
                self.assertIsNone(actor.pre_disabled_approval_status)

    async def test_non_last_admin_target_can_be_disabled(self):
        actor = make_user()
        target = make_user(version=8)
        db = fake_db(
            ScalarResult(),
            ScalarResult(users=[actor, target]),
            ScalarResult(value=2),
        )
        mutation = await apply_locked_user_lifecycle_mutation(
            db,
            actor_user_id=actor.id,
            target_user_id=target.id,
            action="disable",
            reason="Security response",
        )
        self.assertEqual(mutation.transition.previous_state, "approved")
        self.assertEqual(target.approval_status, "disabled")
        self.assertEqual(target.pre_disabled_approval_status, "approved")
        self.assertEqual(target.auth_version, 9)

    async def test_last_admin_guard_does_not_count_inactive_admin_like_rows(self):
        actor = make_user()
        target = make_user()
        inactive = (
            make_user("disabled"),
            make_user("rejected"),
            make_user("pending"),
        )
        self.assertTrue(all(not is_effective_admin(user) for user in inactive))
        db = fake_db(
            ScalarResult(),
            ScalarResult(users=[actor, target]),
            ScalarResult(value=1),
        )
        with self.assertRaises(AdminSurvivabilityViolation) as raised:
            await apply_locked_user_lifecycle_mutation(
                db,
                actor_user_id=actor.id,
                target_user_id=target.id,
                action="reject",
            )
        self.assertEqual(raised.exception.reason_code, "LAST_EFFECTIVE_ADMIN")
        self.assertEqual(target.approval_status, "approved")
        self.assertEqual(target.auth_version, 5)

    async def test_actor_and_target_are_revalidated_under_lock(self):
        stale_actor = make_user("disabled")
        target = make_user()
        db = fake_db(ScalarResult(), ScalarResult(users=[stale_actor, target]))
        with self.assertRaises(AdminActorAuthorityLost):
            await apply_locked_user_lifecycle_mutation(
                db,
                actor_user_id=stale_actor.id,
                target_user_id=target.id,
                action="disable",
            )
        self.assertEqual(target.approval_status, "approved")

        actor = make_user()
        already_disabled = make_user("disabled")
        db = fake_db(ScalarResult(), ScalarResult(users=[actor, already_disabled]))
        with self.assertRaises(InvalidAccountLifecycleTransition):
            await apply_locked_user_lifecycle_mutation(
                db,
                actor_user_id=actor.id,
                target_user_id=already_disabled.id,
                action="disable",
            )
        self.assertEqual(already_disabled.auth_version, 5)

    async def test_restore_unknown_provenance_is_pending_not_effective(self):
        actor = make_user()
        target = make_user("disabled", version=10)
        db = fake_db(ScalarResult(), ScalarResult(users=[actor, target]))
        mutation = await apply_locked_user_lifecycle_mutation(
            db,
            actor_user_id=actor.id,
            target_user_id=target.id,
            action="restore",
        )
        self.assertEqual(mutation.target.approval_status, "pending")
        self.assertEqual(mutation.target.auth_version, 11)
        self.assertFalse(is_effective_admin(mutation.target))


class SurvivabilityStaticTests(TestCase):
    def source(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_lock_is_postgresql_transaction_scoped_and_dedicated(self):
        service = self.source("app/services/admin_survivability.py")
        self.assertIn("pg_advisory_xact_lock", service)
        self.assertIn("populate_existing=True", service)
        self.assertIn("with_for_update()", service)
        self.assertNotIn("threading", service)
        self.assertNotEqual(ADMIN_SURVIVABILITY_LOCK_NAMESPACE, 0)
        self.assertNotEqual(ADMIN_SURVIVABILITY_LOCK_KEY, 0)

    def test_all_runtime_user_lifecycle_routes_use_locked_service(self):
        admin = self.source("app/api/endpoints/admin.py")
        self.assertIn("apply_locked_user_lifecycle_mutation", admin)
        self.assertNotIn("transition_user_account(", admin)
        self.assertIn("AdminActorAuthorityLost", admin)
        self.assertIn("AdminSurvivabilityViolation", admin)

    def test_no_runtime_role_revocation_endpoint_exists(self):
        runtime = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "app/api").rglob("*.py")
        )
        for route in ("/revoke-admin", "/demote", "/revoke-operator"):
            self.assertNotIn(route, runtime)

    def test_preflight_and_frontend_surface_safety_without_leaking_counts(self):
        preflight = self.source("scripts/run_s0_3_schema_data_preflight.py")
        frontend = (FRONTEND / "app/admin/approvals/page.tsx").read_text(
            encoding="utf-8"
        )
        for marker in (
            "admin_survivability",
            "effective_admins",
            "disabled_admin_role_users",
            "rejected_admin_role_users",
            "pending_admin_role_users",
            "zero_effective_admins",
        ):
            self.assertIn(marker, preflight)
        self.assertIn("Administrators cannot reject themselves", frontend)
        self.assertIn("Administrators cannot disable themselves", frontend)
        self.assertNotIn("effective_admins", frontend)


if __name__ == "__main__":
    import unittest

    unittest.main()
