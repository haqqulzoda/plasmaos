"""Deterministic Sprint 1.2 World Bank Project enrichment contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.all_models import Base, Project
from app.schemas.project import ProjectResponse, ProjectRoleAssignmentResponse
from app.services.project_enrichment import (
    effective_project_enrichment_status,
    project_role_assignment_key,
)
from app.services.tender_sources.base import CanonicalContact
from app.services.world_bank_projects import (
    CO_TASK_TEAM_LEADER,
    OTHER_PROJECT_ROLE,
    PROJECT_TASK_MANAGER,
    TASK_TEAM_LEADER,
    WorldBankProjectIdentityMismatch,
    WorldBankProjectSourceError,
    WorldBankProjectsClient,
    canonical_project_role,
    normalize_world_bank_project_record,
)


BACKEND_DIR = Path(__file__).resolve().parent
HEAD = "20260828_0003_s4_1_tender_engagement_foundation"
MIGRATION_PATH = BACKEND_DIR / "alembic/versions/20260826_0002_s1_2_wb_project_enrichment.py"
OBSERVED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def project_fixture(**overrides):
    record = {
        "id": "P179267",
        "project_name": "Regional Emergency Solar Power Intervention Project",
        "countryshortname": "Western and Central Africa",
        "regionname": "Western and Central Africa",
        "projectstatusdisplay": "Active",
        "boardapprovaldate": "2022-12-20T00:00:00Z",
        "closingdate": "6/30/2027 12:00:00 AM",
        "borrower": "Republic of Liberia",
        "impagency": "Liberia Electricity Corporation (LEC)",
        "teamleadname": "Anshul Rana,Kagaba Paul Mukiibi",
        "p2a_updated_date": "2022-12-21 00:00:00.0",
        "url": "https://projects.worldbank.org/en/projects-operations/project-detail/P179267",
        "totalcommamt": "311,000,000",
        "sector": [{"Name": "Renewable Energy Solar"}],
    }
    record.update(overrides)
    return record


def test_official_project_record_normalizes_authoritative_metadata() -> None:
    snapshot = normalize_world_bank_project_record(
        "P179267",
        project_fixture(),
        retrieved_at=OBSERVED_AT,
    )
    assert snapshot.external_project_id == "P179267"
    assert snapshot.name == "Regional Emergency Solar Power Intervention Project"
    assert snapshot.country == "Western and Central Africa"
    assert snapshot.region == "Western and Central Africa"
    assert snapshot.project_status == "Active"
    assert snapshot.approval_date.isoformat() == "2022-12-20"
    assert snapshot.closing_date.isoformat() == "2027-06-30"
    assert snapshot.borrower == "Republic of Liberia"
    assert snapshot.implementing_agencies == ["Liberia Electricity Corporation (LEC)"]
    assert snapshot.roles_complete
    assert [role.display_name for role in snapshot.roles] == [
        "Anshul Rana",
        "Kagaba Paul Mukiibi",
    ]


def test_projects_api_teamlead_field_is_not_mislabeled_ttl() -> None:
    snapshot = normalize_world_bank_project_record(
        "P179267", project_fixture(), retrieved_at=OBSERVED_AT
    )
    assert all(role.native_role == "teamleadname" for role in snapshot.roles)
    assert all(role.canonical_role == OTHER_PROJECT_ROLE for role in snapshot.roles)
    assert all(role.email is None and role.phone is None for role in snapshot.roles)


def test_native_role_mapping_preserves_task_manager_distinction() -> None:
    assert canonical_project_role("Task Team Leader") == TASK_TEAM_LEADER
    assert canonical_project_role("Co-Task Team Leader") == CO_TASK_TEAM_LEADER
    assert canonical_project_role("Task Manager") == PROJECT_TASK_MANAGER
    assert canonical_project_role("Team Leader") == OTHER_PROJECT_ROLE
    assert canonical_project_role("Unmapped Official Role") == OTHER_PROJECT_ROLE


def test_wrong_returned_project_identity_is_rejected() -> None:
    with pytest.raises(WorldBankProjectIdentityMismatch):
        normalize_world_bank_project_record(
            "P179267",
            project_fixture(id="P123456"),
            retrieved_at=OBSERVED_AT,
        )


def test_missing_leadership_field_is_partial_not_an_empty_roster() -> None:
    record = project_fixture()
    del record["teamleadname"]
    snapshot = normalize_world_bank_project_record(
        "P179267", record, retrieved_at=OBSERVED_AT
    )
    assert not snapshot.roles_complete
    assert snapshot.roles == ()


def test_assignment_identity_is_project_scoped_and_exact() -> None:
    first = project_role_assignment_key(
        external_project_id="P179267",
        source_system="world_bank",
        native_role="Task Team Leader",
        display_name="Jane Doe",
        source_person_id=None,
    )
    repeated = project_role_assignment_key(
        external_project_id="P179267",
        source_system="world_bank",
        native_role="Task Team Leader",
        display_name="Jane Doe",
        source_person_id=None,
    )
    other_project = project_role_assignment_key(
        external_project_id="P123456",
        source_system="world_bank",
        native_role="Task Team Leader",
        display_name="Jane Doe",
        source_person_id=None,
    )
    case_variant = project_role_assignment_key(
        external_project_id="P179267",
        source_system="world_bank",
        native_role="Task Team Leader",
        display_name="JANE DOE",
        source_person_id=None,
    )
    assert first == repeated
    assert first != other_project
    assert first != case_variant


def test_role_provenance_is_structured_and_complete() -> None:
    role = normalize_world_bank_project_record(
        "P179267", project_fixture(), retrieved_at=OBSERVED_AT
    ).roles[0]
    assert {
        "source_system",
        "source_endpoint",
        "source_url",
        "external_project_id",
        "source_field",
        "native_role",
        "raw_source_value",
        "source_value",
        "retrieved_at",
        "source_update_time",
        "source_record_identifier",
    }.issubset(role.provenance)


def test_procurement_contact_is_a_separate_non_role_contract() -> None:
    contact = CanonicalContact(
        source_system="world_bank",
        name="Anshul Rana",
        email="procurement@example.test",
    )
    role = normalize_world_bank_project_record(
        "P179267", project_fixture(teamleadname="Anshul Rana"), retrieved_at=OBSERVED_AT
    ).roles[0]
    assert not hasattr(contact, "canonical_role")
    assert role.email is None
    assert role.provenance["source_field"] == "teamleadname"


def test_role_schema_labels_domain_as_project_leadership() -> None:
    assert ProjectRoleAssignmentResponse.model_fields["role_type"].default == (
        "PROJECT_LEADERSHIP"
    )


def test_successful_project_older_than_freshness_window_is_stale() -> None:
    project = Project(
        source_system="world_bank",
        external_project_id="P179267",
        enrichment_status="successful",
        last_enriched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert effective_project_enrichment_status(
        project,
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
    ) == "stale"


def test_project_response_exposes_expired_success_as_stale() -> None:
    response = ProjectResponse.model_validate(
        {
            "id": uuid4(),
            "source_system": "world_bank",
            "external_project_id": "P179267",
            "enrichment_status": "successful",
            "last_enriched_at": datetime.now(timezone.utc) - timedelta(days=8),
        }
    )

    assert response.enrichment_status == "stale"


def test_orm_uniqueness_and_allowed_role_contract() -> None:
    table = Base.metadata.tables["project_role_assignments"]
    unique = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_project_role_assignments_identity"
    )
    assert tuple(column.name for column in unique.columns) == (
        "project_id",
        "source_system",
        "assignment_key",
    )
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    role_check = checks["ck_project_role_assignments_canonical_role_allowed"]
    assert "PROJECT_TASK_MANAGER" in role_check
    assert "TASK_TEAM_LEADER" in role_check


def test_migration_is_additive_network_free_single_head() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == (
        "20260828_0002_s3_4_admin_audit_hardening"
    )
    assert script.get_revision(
        "20260827_0001_s2_1_compliance_ownership"
    ).down_revision == "20260826_0002_s1_2_wb_project_enrichment"
    assert script.get_revision("20260826_0002_s1_2_wb_project_enrichment").down_revision == (
        "20260826_0001_s1_1_project_foundation"
    )
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "urllib" not in source
    assert "import requests" not in source
    assert "INSERT INTO project_role_assignments" not in source


class _FakeHttpClient:
    def __init__(self, response: httpx.Response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, *_args, **_kwargs):
        return self.response


def test_source_http_retry_classification_is_bounded() -> None:
    request = httpx.Request("GET", "https://search.worldbank.org/api/v2/projects")
    retryable_response = httpx.Response(429, request=request)
    with patch(
        "app.services.world_bank_projects.httpx.AsyncClient",
        return_value=_FakeHttpClient(retryable_response),
    ):
        with pytest.raises(WorldBankProjectSourceError) as retryable:
            asyncio.run(WorldBankProjectsClient().fetch_project("P179267"))
    assert retryable.value.retryable
    assert retryable.value.status == "source_unavailable"

    permanent_response = httpx.Response(404, request=request)
    with patch(
        "app.services.world_bank_projects.httpx.AsyncClient",
        return_value=_FakeHttpClient(permanent_response),
    ):
        with pytest.raises(WorldBankProjectSourceError) as permanent:
            asyncio.run(WorldBankProjectsClient().fetch_project("P179267"))
    assert not permanent.value.retryable
    assert permanent.value.status == "failed"


def test_celery_enrichment_task_is_rate_and_retry_bounded() -> None:
    from app.workers.project_enrichment_tasks import enrich_world_bank_project_task

    assert enrich_world_bank_project_task.max_retries == 3
    assert enrich_world_bank_project_task.rate_limit == "30/m"
    assert enrich_world_bank_project_task.soft_time_limit == 60
    assert enrich_world_bank_project_task.time_limit == 90
