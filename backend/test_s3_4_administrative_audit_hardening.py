from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import CheckConstraint

from app.models.all_models import AdminActivityEvent, Base
from app.services.admin_activity import (
    ACTION_USER_DISABLED,
    ACTOR_SYSTEM,
    OUTCOME_SUCCESS,
    SOURCE_ADMIN_API,
    record_admin_audit_event,
    user_role_snapshot,
)


ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "alembic/versions/20260828_0002_s3_4_admin_audit_hardening.py"


def make_user(*, role: str = "admin", status: str = "approved"):
    return SimpleNamespace(
        id=uuid4(),
        email=f"{uuid4()}@example.invalid",
        platform_role=role,
        approval_status=status,
        pre_disabled_approval_status=None,
        is_admin=False,
        auth_version=12,
    )


class CanonicalAuditServiceTests(IsolatedAsyncioTestCase):
    async def test_canonical_event_has_snapshots_and_no_live_relationship_dependency(self):
        actor = make_user()
        target = make_user(role="pilot_user")
        db = SimpleNamespace(add=lambda value: setattr(db, "event", value), flush=AsyncMock())
        before = user_role_snapshot(target)
        target.approval_status = "disabled"

        event = await record_admin_audit_event(
            db,
            action=ACTION_USER_DISABLED,
            outcome=OUTCOME_SUCCESS,
            source=SOURCE_ADMIN_API,
            actor_user=actor,
            target_user=target,
            previous_state=before,
            new_state=user_role_snapshot(target),
        )

        self.assertIs(event, db.event)
        self.assertEqual(event.actor_email_snapshot, actor.email)
        self.assertEqual(event.actor_role_snapshot, "admin")
        self.assertEqual(event.target_email, target.email)
        self.assertEqual(event.target_resource_id, str(target.id))
        self.assertNotIn("auth_version", event.previous_state)
        self.assertNotIn("auth_version", event.new_state)
        db.flush.assert_awaited_once()

    async def test_non_user_actor_cannot_impersonate_user(self):
        db = SimpleNamespace(add=lambda _value: None, flush=AsyncMock())
        with self.assertRaisesRegex(ValueError, "cannot impersonate"):
            await record_admin_audit_event(
                db,
                action=ACTION_USER_DISABLED,
                outcome=OUTCOME_SUCCESS,
                source=SOURCE_ADMIN_API,
                actor_user=make_user(),
                actor_type=ACTOR_SYSTEM,
                target_user=make_user(),
            )

    async def test_sensitive_payload_keys_are_rejected_recursively(self):
        db = SimpleNamespace(add=lambda _value: None, flush=AsyncMock())
        with self.assertRaisesRegex(ValueError, "sensitive"):
            await record_admin_audit_event(
                db,
                action=ACTION_USER_DISABLED,
                outcome=OUTCOME_SUCCESS,
                source=SOURCE_ADMIN_API,
                actor_user=make_user(),
                target_user=make_user(),
                metadata={"nested": {"refresh_token": "must-not-land"}},
            )
        db.flush.assert_not_awaited()

    async def test_action_and_outcome_are_controlled(self):
        db = SimpleNamespace(add=lambda _value: None, flush=AsyncMock())
        for action, outcome in (("TYPO", OUTCOME_SUCCESS), (ACTION_USER_DISABLED, "MAYBE")):
            with self.subTest(action=action, outcome=outcome):
                with self.assertRaises(ValueError):
                    await record_admin_audit_event(
                        db,
                        action=action,
                        outcome=outcome,  # type: ignore[arg-type]
                        source=SOURCE_ADMIN_API,
                        actor_user=make_user(),
                        target_user=make_user(),
                    )


class AdministrativeAuditContractTests(TestCase):
    def source(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_orm_is_one_canonical_authority_with_required_indexes(self):
        table = Base.metadata.tables["admin_activity_events"]
        required = {
            "actor_type",
            "actor_email_snapshot",
            "actor_role_snapshot",
            "target_resource_type",
            "target_resource_id",
            "outcome",
            "previous_state",
            "new_state",
            "reason_code",
            "request_id",
            "source",
        }
        self.assertTrue(required <= set(table.c.keys()))
        self.assertIn("ix_admin_activity_events_created_id", {i.name for i in table.indexes})
        checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        self.assertIn("ck_admin_activity_events_outcome_allowed", checks)
        self.assertIs(AdminActivityEvent.__table__, table)

    def test_migration_is_additive_preserves_legacy_rows_and_enforces_append_only(self):
        migration = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('down_revision: Union[str, None] = "20260828_0001', migration)
        self.assertIn("BEFORE UPDATE OR DELETE", migration)
        self.assertIn("admin activity events are append-only", migration)
        self.assertNotIn("UPDATE admin_activity_events SET", migration)
        self.assertNotIn("DELETE FROM admin_activity_events", migration)

    def test_all_known_runtime_writers_use_the_canonical_service(self):
        writers = (
            self.source("app/api/endpoints/admin.py"),
            self.source("app/api/endpoints/auth.py"),
            self.source("app/cli/admin_management.py"),
        )
        for writer in writers:
            self.assertIn("record_admin_audit_event", writer)
            self.assertNotIn("record_admin_activity", writer)
        self.assertNotIn("AdminActivityEvent(", "\n".join(writers))

    def test_admin_api_is_paginated_filtered_deterministic_and_admin_only(self):
        admin = self.source("app/api/endpoints/admin.py")
        self.assertIn('@router.get("/audit-events"', admin)
        self.assertIn("current_user: User = Depends(require_admin)", admin)
        self.assertIn("actor_user_id", admin)
        self.assertIn("target_user_id", admin)
        self.assertIn("AdminActivityEvent.action", admin)
        self.assertIn("AdminActivityEvent.outcome", admin)
        self.assertIn("AdminActivityEvent.created_at.desc()", admin)
        self.assertIn("AdminActivityEvent.id.desc()", admin)
        self.assertIn("le=100", admin)
        self.assertIn("event.metadata_json if event.outcome is not None else None", admin)

    def test_denied_and_failed_events_use_independent_post_rollback_writer(self):
        admin = self.source("app/api/endpoints/admin.py")
        self.assertIn("record_independent_user_audit_event", admin)
        self.assertIn("OUTCOME_DENIED", admin)
        self.assertIn("OUTCOME_FAILED", admin)
        self.assertIn("await db.rollback()", admin)
        service = self.source("app/services/admin_activity.py")
        self.assertIn("AsyncSessionLocal", service)
        self.assertIn("await audit_db.commit()", service)

    def test_preflight_is_aggregate_only_and_never_selects_payloads(self):
        preflight = self.source("scripts/run_s0_3_schema_data_preflight.py")
        self.assertIn("async def admin_audit", preflight)
        self.assertIn("legacy_partial_events", preflight)
        self.assertIn("broken_actor_references", preflight)
        admin_method = preflight.split("async def admin_audit", 1)[1].split(
            "async def referential_integrity", 1
        )[0]
        self.assertNotIn("metadata_json", admin_method)
        self.assertNotIn("previous_state ->", admin_method)


if __name__ == "__main__":
    import unittest

    unittest.main()
