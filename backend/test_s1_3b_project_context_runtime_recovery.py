"""Sprint 1.3B runtime-recovery contracts for Project Context."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.api.endpoints.tenders import get_tender_project_context
from app.schemas.project import ProjectContextProjectResponse
from app.services.project_enrichment import (
    ProjectEnrichmentDispatchResult,
    WORLD_BANK_ENRICHMENT_STATUS_PRIORITY,
)
from scripts import enqueue_world_bank_project_enrichment as reconciliation


ROOT = Path(__file__).resolve().parent
EXPECTED_HEAD = "20260902_0001_s7_2_user_ui_locale"


class _Session:
    def __init__(self) -> None:
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def _args(*, apply: bool, limit: int = 5, confirm: str = "") -> argparse.Namespace:
    return argparse.Namespace(apply=apply, limit=limit, confirm=confirm)


def _project(**overrides):
    values = {
        "id": uuid4(),
        "source_system": "world_bank",
        "external_project_id": "P171305",
        "name": None,
        "country": "India",
        "region": None,
        "project_status": None,
        "approval_date": None,
        "closing_date": None,
        "borrower": None,
        "implementing_agencies": None,
        "source_url": None,
        "enrichment_status": "never_attempted",
        "last_enriched_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_existing_world_bank_tender_backfill_creates_project_and_link() -> None:
    migration = (
        ROOT / "alembic/versions/20260826_0001_s1_1_project_foundation.py"
    ).read_text(encoding="utf-8")
    assert "_backfill_world_bank_projects" in migration
    assert "INSERT INTO projects" in migration
    assert "INSERT INTO tender_projects" in migration
    assert "ON CONFLICT (tender_id) DO NOTHING" in migration
    assert "BTRIM(project_id) ~ '^P[0-9]{6}$'" in migration


def test_existing_project_can_be_reconciled_without_tender_ingestion() -> None:
    session = _Session()
    project_id = uuid4()
    with (
        patch.object(reconciliation, "AsyncSessionLocal", return_value=session),
        patch.object(
            reconciliation,
            "claim_world_bank_projects_for_enrichment",
            new=AsyncMock(return_value=[project_id]),
        ) as claim,
    ):
        result = asyncio.run(reconciliation.run(_args(apply=False)))
    assert result == {
        "mode": "dry_run",
        "limit": 5,
        "eligible_in_batch": 1,
        "database_mutated": False,
    }
    claim.assert_awaited_once_with(session, limit=5)
    session.rollback.assert_awaited_once()


def test_operator_reconciliation_is_bounded_idempotent_orchestration() -> None:
    session = _Session()
    dispatch = AsyncMock(
        side_effect=[
            ProjectEnrichmentDispatchResult(claimed=2, enqueued=2, dispatch_failed=0),
            ProjectEnrichmentDispatchResult(claimed=0, enqueued=0, dispatch_failed=0),
        ]
    )
    args = _args(
        apply=True,
        limit=2,
        confirm=reconciliation.CONFIRMATION,
    )
    with (
        patch.object(reconciliation, "AsyncSessionLocal", return_value=session),
        patch.object(
            reconciliation,
            "enqueue_world_bank_project_enrichment_batch",
            new=dispatch,
        ),
    ):
        first = asyncio.run(reconciliation.run(args))
        second = asyncio.run(reconciliation.run(args))
    assert first["enqueued"] == 2
    assert second["claimed"] == 0
    assert dispatch.await_count == 2


def test_operator_command_requires_exact_apply_confirmation_and_batch_bound() -> None:
    with pytest.raises(ValueError, match="confirmation must be exactly"):
        asyncio.run(reconciliation.run(_args(apply=True, confirm="wrong")))
    with pytest.raises(ValueError, match="limit must be between"):
        asyncio.run(reconciliation.run(_args(apply=False, limit=51)))


def test_reconciliation_prioritizes_untouched_projects_over_known_failures() -> None:
    assert (
        WORLD_BANK_ENRICHMENT_STATUS_PRIORITY["never_attempted"]
        < WORLD_BANK_ENRICHMENT_STATUS_PRIORITY["failed"]
    )
    service = (ROOT / "app/services/project_enrichment.py").read_text(
        encoding="utf-8"
    )
    assert "case(" in service
    assert 'predicates["never_attempted"]' in service


def test_linked_not_enriched_project_identity_is_pending_not_unavailable() -> None:
    response = ProjectContextProjectResponse.model_validate(_project())
    assert response.external_project_id == "P171305"
    assert response.enrichment_status == "never_attempted"
    assert response.source_freshness == "pending"


def test_enrichment_failure_preserves_known_project_identity() -> None:
    response = ProjectContextProjectResponse.model_validate(
        _project(
            enrichment_status="source_unavailable",
            last_enriched_at=datetime.now(timezone.utc),
        )
    )
    assert response.external_project_id == "P171305"
    assert response.source_freshness == "unavailable"


def test_true_project_endpoint_failure_is_not_collapsed_to_null() -> None:
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("database down")))
    with pytest.raises(RuntimeError, match="database down"):
        asyncio.run(
            get_tender_project_context(
                uuid4(),
                _current_user=SimpleNamespace(id=uuid4()),
                db=db,
            )
        )


def test_no_project_is_successful_null() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    response = asyncio.run(
        get_tender_project_context(
            uuid4(),
            _current_user=SimpleNamespace(id=uuid4()),
            db=db,
        )
    )
    assert response is None


def test_recovery_adds_no_migration_and_reuses_sprint_1_2_worker() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_HEAD]
    command = (
        ROOT / "scripts/enqueue_world_bank_project_enrichment.py"
    ).read_text(encoding="utf-8")
    assert "enqueue_world_bank_project_enrichment_batch" in command
    assert "WorldBankProjectsClient" not in command
    assert "httpx" not in command
