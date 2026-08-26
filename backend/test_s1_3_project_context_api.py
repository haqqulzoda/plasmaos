"""Sprint 1.3 Tender-scoped Project Context API contracts."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.deps import require_approved_pilot_access
from app.api.endpoints.tenders import get_tender_project_context
from app.schemas.project import ProjectContextProjectResponse


ROOT = Path(__file__).resolve().parent
NOW = datetime.now(timezone.utc)


def _role(**overrides):
    values = {
        "id": uuid4(),
        "source_system": "world_bank",
        "display_name": "Jane Doe",
        "native_role": "Task Manager",
        "canonical_role": "PROJECT_TASK_MANAGER",
        "email": None,
        "phone": None,
        "source_url": "https://projects.worldbank.org/en/projects-operations/project-detail/P179267",
        "is_current": True,
        "first_observed_at": NOW - timedelta(days=30),
        "last_observed_at": NOW,
        "ended_at": None,
        "provenance": {"raw_source_value": "Jane Doe"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _project(**overrides):
    values = {
        "id": uuid4(),
        "source_system": "world_bank",
        "external_project_id": "P179267",
        "name": "Regional Emergency Solar Power Intervention Project",
        "country": "Liberia",
        "region": "Western and Central Africa",
        "project_status": "Active",
        "approval_date": date(2022, 12, 20),
        "closing_date": date(2027, 6, 30),
        "borrower": "Republic of Liberia",
        "implementing_agencies": ["Liberia Electricity Corporation"],
        "source_url": "https://projects.worldbank.org/en/projects-operations/project-detail/P179267",
        "enrichment_status": "successful",
        "last_enriched_at": NOW,
        "enrichment_failure_class": None,
        "raw_provenance": {"world_bank_project_enrichment": {"secret": "not public"}},
        "role_assignments": [_role()],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _context(project):
    result = SimpleNamespace(scalar_one_or_none=lambda: project)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    return await get_tender_project_context(
        uuid4(),
        _current_user=SimpleNamespace(id=uuid4()),
        db=db,
    )


def test_tender_without_project_returns_omittable_null_context() -> None:
    assert asyncio.run(_context(None)) is None


def test_linked_project_exposes_canonical_external_and_internal_identity() -> None:
    project = _project(enrichment_status="never_attempted", last_enriched_at=None)
    response = asyncio.run(_context(project))
    assert response is not None
    assert response.project.id == project.id
    assert response.project.external_project_id == "P179267"
    assert response.project.source_freshness == "pending"


def test_enriched_project_exposes_whitelisted_metadata_and_source() -> None:
    response = asyncio.run(_context(_project()))
    assert response is not None
    assert response.project.status == "Active"
    assert response.project.approval_date == date(2022, 12, 20)
    assert response.project.implementing_agencies == [
        "Liberia Electricity Corporation"
    ]
    assert response.project.source_freshness == "fresh"


def test_sparse_project_serializes_missing_fields_as_null_without_fabrication() -> None:
    response = asyncio.run(
        _context(
            _project(
                name=None,
                country=None,
                region=None,
                borrower=None,
                implementing_agencies=None,
            )
        )
    )
    assert response is not None
    assert response.project.name is None
    assert response.project.borrower is None
    assert response.project.implementing_agencies is None


def test_current_and_historical_roles_are_separate_and_deterministic() -> None:
    historical = _role(
        display_name="Previous Lead",
        is_current=False,
        ended_at=NOW - timedelta(days=2),
        last_observed_at=NOW - timedelta(days=2),
    )
    current = _role(display_name="Current Lead")
    response = asyncio.run(
        _context(_project(role_assignments=[historical, current]))
    )
    assert response is not None
    assert [role.display_name for role in response.current_roles] == ["Current Lead"]
    assert [role.display_name for role in response.historical_roles] == [
        "Previous Lead"
    ]
    assert response.historical_roles[0].ended_at is not None


def test_teamleadname_remains_other_project_role_without_contact_inference() -> None:
    response = asyncio.run(
        _context(
            _project(
                role_assignments=[
                    _role(
                        display_name="Published Team Member",
                        native_role="teamleadname",
                        canonical_role="OTHER_PROJECT_ROLE",
                    )
                ]
            )
        )
    )
    assert response is not None
    role = response.current_roles[0]
    assert role.canonical_role == "OTHER_PROJECT_ROLE"
    assert role.native_role == "teamleadname"
    assert role.email is None and role.phone is None


def test_failure_state_is_safe_and_raw_provenance_is_not_exposed() -> None:
    response = asyncio.run(
        _context(
            _project(
                enrichment_status="source_unavailable",
                last_enriched_at=NOW - timedelta(days=2),
            )
        )
    )
    assert response is not None
    payload = response.model_dump(mode="json")
    assert payload["project"]["source_freshness"] == "unavailable"
    assert "raw_provenance" not in payload["project"]
    assert "enrichment_failure_class" not in payload["project"]
    assert "provenance" not in payload["current_roles"][0]
    assert payload["project"]["source_url"].startswith("https://projects.worldbank.org/")


def test_stale_success_is_serialized_truthfully() -> None:
    project = ProjectContextProjectResponse.model_validate(
        _project(last_enriched_at=NOW - timedelta(days=8))
    )
    assert project.enrichment_status == "stale"
    assert project.source_freshness == "stale"


def test_endpoint_is_approved_access_guarded_and_uses_canonical_link_query() -> None:
    source = (ROOT / "app/api/endpoints/tenders.py").read_text(encoding="utf-8")
    block = source.split('"/{tender_id}/project"', 1)[1].split(
        "async def _build_tender_competitor_intelligence", 1
    )[0]
    assert "Depends(require_approved_pilot_access)" in block
    assert "customer_visible_tender_condition(Tender)" in block
    assert ".join(TenderProject" in block
    assert "selectinload(Project.role_assignments)" in block
    assert "CanonicalContact" not in block


def test_disabled_user_cannot_pass_project_endpoint_access_dependency() -> None:
    disabled_user = SimpleNamespace(
        id=uuid4(),
        email="disabled@example.test",
        is_admin=True,
        platform_role="admin",
        approval_status="disabled",
        disabled_at=NOW,
    )
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_approved_pilot_access(disabled_user, db))
    assert exc_info.value.status_code == 403


def test_project_status_and_dates_are_independent_of_tender_actionability() -> None:
    source = (ROOT / "app/api/endpoints/tenders.py").read_text(encoding="utf-8")
    block = source.split('"/{tender_id}/project"', 1)[1].split(
        "async def _build_tender_competitor_intelligence", 1
    )[0]
    assert "TenderStatus" not in block
    assert "actionable_tender_condition" not in block
    assert "Proposal(" not in block
