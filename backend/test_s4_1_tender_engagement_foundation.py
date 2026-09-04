"""Sprint 4.1 canonical tender-engagement foundation contracts."""

from __future__ import annotations

from pathlib import Path
import re

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.models.all_models import Base
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.services.tender_engagements import (
    CORRECTION_TRANSITIONS,
    NORMAL_TRANSITIONS,
    transition_is_allowed,
)


BACKEND_DIR = Path(__file__).resolve().parent
MIGRATION = (
    BACKEND_DIR
    / "alembic/versions/20260828_0003_s4_1_tender_engagement_foundation.py"
)
SERVICE = BACKEND_DIR / "app/services/tender_engagements.py"
HEAD = "20260902_0001_s7_2_user_ui_locale"


def source(relative: str) -> str:
    return (BACKEND_DIR / relative).read_text(encoding="utf-8")


def test_model_has_canonical_id_only_identity_and_restrictive_fks() -> None:
    table = Base.metadata.tables["tender_engagements"]
    assert set(table.c.keys()) >= {
        "id",
        "user_id",
        "company_profile_id",
        "tender_id",
        "status",
        "origin",
        "created_at",
        "updated_at",
        "status_changed_at",
    }
    unique = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique["uq_tender_engagements_owner_tender"] == (
        "user_id",
        "company_profile_id",
        "tender_id",
    )
    foreign_keys = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert all(constraint.ondelete == "RESTRICT" for constraint in foreign_keys)
    profile_fk = next(
        constraint
        for constraint in foreign_keys
        if constraint.name == "fk_tender_engagements_profile_user"
    )
    assert tuple(element.target_fullname for element in profile_fk.elements) == (
        "company_profiles.id",
        "company_profiles.user_id",
    )
    assert "company_name" not in table.c


def test_status_and_origin_taxonomies_are_narrow_and_exact() -> None:
    assert {value.value for value in TenderEngagementStatus} == {
        "SAVED",
        "EVALUATING",
        "PREPARING",
        "SUBMITTED",
        "WON",
        "LOST",
        "DISMISSED",
    }
    assert {value.value for value in TenderEngagementOrigin} == {
        "MANUAL_SAVE",
        "MANUAL_EVALUATION",
        "BID_PREPARATION",
        "LEGACY_PROPOSAL",
        "OTHER_EXPLICIT_USER_ACTION",
    }


def test_every_normal_transition_and_rejection_is_deterministic() -> None:
    statuses = set(TenderEngagementStatus)
    for current in statuses:
        for target in statuses:
            expected = target in NORMAL_TRANSITIONS[current]
            assert transition_is_allowed(current, target) is expected
    assert TenderEngagementStatus.PREPARING in NORMAL_TRANSITIONS[
        TenderEngagementStatus.DISMISSED
    ]
    assert not NORMAL_TRANSITIONS[TenderEngagementStatus.WON]
    assert not NORMAL_TRANSITIONS[TenderEngagementStatus.LOST]


def test_corrections_are_explicit_and_narrow() -> None:
    statuses = set(TenderEngagementStatus)
    for current in statuses:
        for target in statuses:
            expected = target in CORRECTION_TRANSITIONS.get(current, frozenset())
            assert transition_is_allowed(current, target, correction=True) is expected
    assert TenderEngagementStatus.PREPARING in CORRECTION_TRANSITIONS[
        TenderEngagementStatus.SUBMITTED
    ]
    assert TenderEngagementStatus.LOST in CORRECTION_TRANSITIONS[
        TenderEngagementStatus.WON
    ]


def test_creation_and_status_mutation_are_database_backed_and_canonical() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    assert ".on_conflict_do_nothing(" in service
    assert 'constraint="uq_tender_engagements_owner_tender"' in service
    assert "CompanyProfile.user_id == user_id" in service
    assert "Tender.id == tender_id" in service
    assert ".with_for_update()" in service
    assert "await db.flush()" in service
    assert "await db.commit()" not in service
    assert "company_name" not in service


def test_migration_is_one_additive_schema_only_head_with_no_backfill() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    migration = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: Union[str, None] = "20260828_0002' in migration
    assert '"tender_engagements"' in migration
    assert "INSERT INTO tender_engagements" not in migration
    assert "UPDATE proposals" not in migration
    assert "DELETE FROM" not in migration
    assert "http" not in migration.casefold()


def test_proposal_compliance_and_hunter_do_not_write_engagement_state() -> None:
    independent_paths = (
        "app/api/endpoints/tenders.py",
        "app/api/endpoints/hunter.py",
        "app/services/compliance_engine.py",
        "app/workers/hunter_tasks.py",
    )
    runtime = "\n".join(source(path) for path in independent_paths)
    assert "TenderEngagement" not in runtime
    assert "mark_submitted" not in runtime
    assert "mark_won" not in runtime
    assert "mark_lost" not in runtime
    proposals = source("app/api/endpoints/proposals.py")
    assert "prepare_bid(" in proposals
    assert "TenderEngagementStatus.SUBMITTED" not in proposals
    assert "engagement.status =" not in proposals


def test_normal_runtime_has_one_engagement_writer_service() -> None:
    runtime_files = list((BACKEND_DIR / "app").rglob("*.py"))
    writers = [
        path
        for path in runtime_files
        if "TenderEngagement(" in path.read_text(encoding="utf-8")
    ]
    assert writers == [BACKEND_DIR / "app/models/engagement.py"]
    for path in runtime_files:
        if path == SERVICE or path.name == "engagement.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"TenderEngagement\.status\s*=(?!=)", text)
        assert ".status = TenderEngagementStatus" not in text


def test_preflight_reports_required_aggregate_health_without_content() -> None:
    preflight = source("scripts/run_s0_3_schema_data_preflight.py")
    block = preflight.split("async def tender_engagement_audit", 1)[1].split(
        "def _legacy_candidate_sql", 1
    )[0]
    for marker in (
        "total_tender_engagements",
        "status_counts",
        "duplicate_logical_keys",
        "invalid_user_profile_relationships",
        "broken_tender_fks",
        "unknown_or_invalid_status",
        "legacy_proposal_candidates",
    ):
        assert marker in block
    for forbidden in ("company_name", "title", "source_url", "analysis_json"):
        assert forbidden not in block


def test_legacy_bids_route_is_owned_proposal_only_without_tender_fallback() -> None:
    page = source("../frontend/app/dashboard/bids/[id]/page.tsx")
    assert "`/proposals/${id}`" in page
    assert "`/dashboard/bid-preparation/${id}`" in page
    assert "api.post" not in page
    assert "tender_id" not in page
