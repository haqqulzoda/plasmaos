"""Fast contracts for the World Bank enrichment auto-drain hotfix."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.core.celery_app import celery_app, world_bank_autodrain_interval_seconds
from app.schemas.project import ProjectContextProjectResponse
from app.services.project_enrichment import (
    WORLD_BANK_AUTODRAIN_BATCH_SIZE,
    WORLD_BANK_ENRICHMENT_BATCH_SIZE,
    WORLD_BANK_ENRICHMENT_RETRY_BACKOFF,
)
from app.workers.project_enrichment_tasks import (
    dispatch_world_bank_project_enrichment_backlog_task,
    enrich_world_bank_project_task,
)


ROOT = Path(__file__).resolve().parent
DISPATCH_TASK = (
    "app.workers.project_enrichment_tasks."
    "dispatch_world_bank_project_enrichment_backlog"
)


def _project(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        source_system="world_bank",
        external_project_id="P175588",
        name=None,
        country=None,
        region=None,
        project_status=None,
        approval_date=None,
        closing_date=None,
        borrower=None,
        implementing_agencies=None,
        source_url=None,
        enrichment_status=status,
        last_enriched_at=None,
    )


def test_periodic_dispatcher_is_registered_and_routed() -> None:
    schedule = celery_app.conf.beat_schedule[
        "dispatch-world-bank-project-enrichment-backlog"
    ]
    assert schedule["task"] == DISPATCH_TASK
    assert schedule["schedule"].total_seconds() == world_bank_autodrain_interval_seconds
    assert world_bank_autodrain_interval_seconds >= 60
    assert celery_app.conf.task_routes[DISPATCH_TASK]["queue"] == "celery"
    assert dispatch_world_bank_project_enrichment_backlog_task.name == DISPATCH_TASK


def test_automatic_batch_is_bounded_below_source_rate() -> None:
    assert 1 <= WORLD_BANK_AUTODRAIN_BATCH_SIZE <= 30
    assert WORLD_BANK_AUTODRAIN_BATCH_SIZE <= WORLD_BANK_ENRICHMENT_BATCH_SIZE
    assert enrich_world_bank_project_task.rate_limit == "30/m"
    assert WORLD_BANK_ENRICHMENT_RETRY_BACKOFF.total_seconds() >= 60


def test_terminal_failure_is_not_presented_as_pending() -> None:
    response = ProjectContextProjectResponse.model_validate(_project("failed"))
    assert response.enrichment_status == "failed"
    assert response.source_freshness == "unavailable"


def test_partial_state_remains_visible_and_truthful() -> None:
    project = _project("partial")
    project.name = "Available authoritative name"
    project.last_enriched_at = datetime.now(timezone.utc)
    response = ProjectContextProjectResponse.model_validate(project)
    assert response.name == "Available authoritative name"
    assert response.source_freshness == "incomplete"


def test_production_compose_runs_worker_and_beat() -> None:
    compose = (ROOT.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"app.core.celery_app", "worker"' in compose
    assert '"app.core.celery_app", "beat"' in compose
    assert "WORLD_BANK_AUTODRAIN_INTERVAL_SECONDS" in compose
    assert "WORLD_BANK_AUTODRAIN_BATCH_SIZE" in compose


def test_hotfix_has_no_migration() -> None:
    migration_names = {
        path.name for path in (ROOT / "alembic" / "versions").glob("*.py")
    }
    assert not any(
        "autodrain" in name or "enrichment_retry" in name
        for name in migration_names
    )
