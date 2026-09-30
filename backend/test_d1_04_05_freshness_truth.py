"""D1-04 scheduled refresh, D1-04b hidden ADB, D1-05 budgets, D1-05b deadline time truth,
D1-05c open-status truth.

Unit checks run anywhere. The database scenario builds one disposable PostgreSQL database
(the W-series harness) and never touches the configured application database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, literal_column, select, text

from app.api.endpoints import admin as admin_endpoint
from app.api.endpoints import pursuits as pursuits_endpoint
from app.api.endpoints import tenders as tenders_endpoint
from app.core import deadline_truth as truth
from app.core.budget_display import budget_is_published, not_published_label
from app.core.tender_actionability import is_tender_actionable
from app.models.all_models import SourceRefreshJob, Tender, TenderStatus
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.schemas.explorer import ExplorerView
from app.schemas.tender import TenderResponse
from app.services import source_refresh_schedule as schedule
from app.services.explorer import ExplorerQuery, list_explorer_tenders
from app.services.my_tenders import MyTendersQuery, list_my_tenders
from app.services.official_notice import compose_notice_text
from app.services.pursuits import get_or_create_source_pursuit
from app.services.source_refresh_activity import source_catalog, source_refresh_status
from app.services.source_registry import (
    SOURCE_REGISTRY,
    DateOnlyMarker,
    DeadlineTimeBasis,
    customer_hidden_source_keys,
)
from app.services.tender_sources.uzex_scope import customer_visible_tender_condition
from app.workers import source_refresh_tasks
from test_d1_03_official_notice import _database

BACKEND_DIR = Path(__file__).resolve().parent
UTC = timezone.utc


# ---- D1-04 schedule --------------------------------------------------------------------------


def test_default_schedule_covers_the_visible_sources_and_empty_disables() -> None:
    parsed = schedule.parse_source_refresh_schedule(schedule.DEFAULT_SOURCE_REFRESH_SCHEDULE)
    assert parsed == {
        "world_bank": timedelta(hours=6), "uzex": timedelta(hours=6),
        "ebrd": timedelta(hours=24), "giz": timedelta(hours=24),
    }
    assert schedule.configured_source_refresh_schedule({}) == parsed  # unset -> default
    assert schedule.configured_source_refresh_schedule({"SOURCE_REFRESH_SCHEDULE": ""}) == {}
    assert schedule.configured_source_refresh_schedule({"SOURCE_REFRESH_SCHEDULE": "  "}) == {}
    assert schedule.parse_source_refresh_schedule(" World_Bank=30m , giz=2d ") == {
        "world_bank": timedelta(minutes=30), "giz": timedelta(days=2),
    }


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("adb=6h", "hidden source 'adb'"),
        ("sam_gov=6h", "unknown source 'sam_gov'"),
        ("world_bank=6", "is not <source>=<N>m|h|d"),
        ("world_bank=6w", "is not <source>=<N>m|h|d"),
        ("world_bank=0h", "is not <source>=<N>m|h|d"),
        ("world_bank=-6h", "is not <source>=<N>m|h|d"),
        ("world_bank=10m", "below 15 minutes"),
        ("world_bank=6h,world_bank=1h", "lists 'world_bank' twice"),
        ("world_bank=6h,,giz=1d", "is not <source>=<N>m|h|d"),
    ],
)
def test_schedule_parsing_is_strict(raw: str, message: str) -> None:
    with pytest.raises(schedule.SourceRefreshScheduleError, match=message):
        schedule.parse_source_refresh_schedule(raw)


def test_beat_has_one_entry_per_scheduled_visible_source_and_none_for_hidden() -> None:
    entries = schedule.build_beat_schedule(schedule.parse_source_refresh_schedule(schedule.DEFAULT_SOURCE_REFRESH_SCHEDULE))
    assert sorted(entries) == [f"scheduled-source-refresh-{key}" for key in ("ebrd", "giz", "uzex", "world_bank")]
    for key, entry in entries.items():
        assert entry["task"] == "app.workers.source_refresh_tasks.dispatch_scheduled_source_refresh"
        assert entry["args"] == (key.removeprefix("scheduled-source-refresh-"),)
        assert entry["schedule"] == timedelta(seconds=schedule.DEFAULT_TICK_SECONDS)
        assert entry["options"]["queue"] == "celery"
    from app.core.celery_app import celery_app

    configured = {name for name in celery_app.conf.beat_schedule if name.startswith("scheduled-source-refresh-")}
    assert configured == set(schedule.build_beat_schedule(schedule.configured_source_refresh_schedule()))
    assert "scheduled-source-refresh-adb" not in celery_app.conf.beat_schedule
    # The pre-existing sweeps are untouched.
    assert "dispatch-pursuit-analysis-work" in celery_app.conf.beat_schedule


def test_invalid_schedule_fails_the_celery_app_at_startup() -> None:
    with pytest.raises(schedule.SourceRefreshScheduleError):
        schedule.configured_source_refresh_schedule({"SOURCE_REFRESH_SCHEDULE": "world_bank=6h,nosuch=1h"})
    celery_source = " ".join((BACKEND_DIR / "app/core/celery_app.py").read_text(encoding="utf-8").split())
    # Evaluated at module import (not inside a task), so worker, Beat and API refuse to start.
    assert (
        "celery_app.conf.beat_schedule.update( build_beat_schedule( configured_source_refresh_schedule(),"
        in celery_source
    )


def test_due_and_stale_thresholds() -> None:
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    cadence = timedelta(hours=6)
    assert schedule.refresh_is_due(last_attempt_at=None, cadence=cadence, now=now)
    assert not schedule.refresh_is_due(last_attempt_at=now - timedelta(hours=5, minutes=59), cadence=cadence, now=now)
    assert schedule.refresh_is_due(last_attempt_at=now - cadence, cadence=cadence, now=now)
    assert schedule.is_stale(last_success_at=None, cadence=cadence, now=now) is True
    assert schedule.is_stale(last_success_at=now - timedelta(hours=12), cadence=cadence, now=now) is False
    assert schedule.is_stale(last_success_at=now - timedelta(hours=12, seconds=1), cadence=cadence, now=now) is True
    assert schedule.is_stale(last_success_at=now - timedelta(days=9), cadence=None, now=now) is None


def test_scheduled_jobs_reuse_the_durable_request_path_with_the_system_origin() -> None:
    worker = (BACKEND_DIR / "app/workers/source_refresh_tasks.py").read_text(encoding="utf-8")
    dispatcher = worker.split("async def dispatch_scheduled_refresh", 1)[1]
    assert "_request_source_refresh(" in dispatcher and "SourceRefreshJob(" not in dispatcher
    assert "trigger_kind=SOURCE_REFRESH_TRIGGER_SCHEDULED" in dispatcher
    assert "current_user=None" in dispatcher and "force=False" in dispatcher
    migration = (BACKEND_DIR / "alembic/versions/20260831_0001_sr2_2_refresh_leases.py").read_text(encoding="utf-8")
    assert "'customer', 'operator', 'scheduled'" in migration  # existing column already allows it


# ---- D1-04b hidden ADB --------------------------------------------------------------------------


def test_adb_is_hidden_from_customers_but_stays_operator_visible() -> None:
    adb = SOURCE_REGISTRY["adb"]
    assert adb.customer_visible is False and adb.operator_visible is True
    assert customer_hidden_source_keys() == ("adb",)
    assert "adb" not in {item.source_system for item in source_catalog()}
    sql = str(customer_visible_tender_condition(Tender).compile(compile_kwargs={"literal_binds": True}))
    assert "NOT IN ('adb')" in sql


# ---- D1-05 budgets ------------------------------------------------------------------------------


def test_unpublished_budgets_are_never_rendered_as_amounts_in_exports() -> None:
    for value in (None, 0, 0.0, -1, "0", "x", float("nan"), float("inf")):
        assert budget_is_published(value) is False, value
    assert budget_is_published(1500) is True
    assert not_published_label("ru") == "Не опубликован" and not_published_label("xx") == "Not published"
    from app.api.endpoints.proposals import _source_budget_text

    assert _source_budget_text(SimpleNamespace(budget=0, currency="UZS")) == "E'lon qilinmagan (Not published)"
    assert _source_budget_text(SimpleNamespace(budget=2500000, currency="UZS")) == "2,500,000 UZS"
    pdf = (BACKEND_DIR / "app/core/pdf_generator.py").read_text(encoding="utf-8")
    assert "if not budget_is_published(tender_budget):" in pdf
    proposals = (BACKEND_DIR / "app/api/endpoints/proposals.py").read_text(encoding="utf-8")
    assert "{tender.budget:,.0f} {tender.currency}\"]" not in proposals
    assert proposals.count("_source_budget_text(tender)") == 2


def test_quick_proposal_pdf_prints_not_published_for_a_zero_budget() -> None:
    from app.core import pdf_generator

    captured: list[str] = []
    original = pdf_generator.Paragraph

    def spy(text_value, *args, **kwargs):
        captured.append(str(text_value))
        return original(text_value, *args, **kwargs)

    pdf_generator.Paragraph = spy
    try:
        pdf_generator.generate_quick_proposal_pdf(
            company_name="c", director_name="d", address="a", tender_title="t", tender_budget=0,
            currency="UZS", ai_summary="s", items=[], delivery_days=1,
        )
    finally:
        pdf_generator.Paragraph = original
    budget_lines = [line for line in captured if "Бюджет тендера" in line]
    assert budget_lines == ["<b>Бюджет тендера:</b> Не опубликован"]


# ---- D1-05b deadline time truth -----------------------------------------------------------------


def test_deadline_time_basis_is_recorded_for_every_connector() -> None:
    expected = {
        "world_bank": (DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED, None, DateOnlyMarker.END_OF_DAY),
        "uzex": (DeadlineTimeBasis.EXPLICIT_TZ, "Asia/Tashkent", None),
        "ebrd": (DeadlineTimeBasis.EXPLICIT_TZ, "Europe/London", DateOnlyMarker.MIDNIGHT),
        "giz": (DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED, None, DateOnlyMarker.MIDNIGHT),
        "adb": (DeadlineTimeBasis.DATE_ONLY, None, DateOnlyMarker.MIDNIGHT),
    }
    assert set(SOURCE_REGISTRY) == set(expected)
    for key, (basis, zone, marker) in expected.items():
        definition = SOURCE_REGISTRY[key]
        assert (definition.deadline_time_basis, definition.deadline_timezone, definition.deadline_date_only_marker) == (
            basis, zone, marker,
        ), key
    audit = (BACKEND_DIR.parent / "docs/audits/d1/d1-05-deadline-open-truth.md").read_text(encoding="utf-8")
    for key in expected:
        assert f"`{key}`" in audit


@pytest.mark.parametrize(
    ("source", "stored", "basis", "zone", "published", "effective"),
    [
        # borrower-local 17:00, zone unknown -> earliest instant: 17:00 at UTC+14
        ("world_bank", datetime(2026, 10, 16, 17, 0, tzinfo=UTC), "SOURCE_LOCAL_UNSPECIFIED", None,
         "2026-10-16T17:00", datetime(2026, 10, 16, 3, 0, tzinfo=UTC)),
        # parse_world_bank_deadline stores time.max for a date without a time
        ("world_bank", datetime(2026, 10, 16, 23, 59, 59, 999999, tzinfo=UTC), "DATE_ONLY", None,
         "2026-10-16", datetime(2026, 10, 16, 10, 0, tzinfo=UTC)),
        # Tashkent wall time (UTC+5, no DST)
        ("uzex", datetime(2026, 9, 29, 8, 17, 30, tzinfo=UTC), "EXPLICIT_TZ", "Asia/Tashkent",
         "2026-09-29T08:17", datetime(2026, 9, 29, 3, 17, 30, tzinfo=UTC)),
        ("uzex", datetime(2026, 9, 29, 0, 0, tzinfo=UTC), "EXPLICIT_TZ", "Asia/Tashkent",
         "2026-09-29T00:00", datetime(2026, 9, 28, 19, 0, tzinfo=UTC)),
        # UK time: BST in August, GMT in December
        ("ebrd", datetime(2026, 8, 17, 10, 0, tzinfo=UTC), "EXPLICIT_TZ", "Europe/London",
         "2026-08-17T10:00", datetime(2026, 8, 17, 9, 0, tzinfo=UTC)),
        ("ebrd", datetime(2026, 12, 17, 10, 0, tzinfo=UTC), "EXPLICIT_TZ", "Europe/London",
         "2026-12-17T10:00", datetime(2026, 12, 17, 10, 0, tzinfo=UTC)),
        ("ebrd", datetime(2026, 8, 17, 0, 0, tzinfo=UTC), "DATE_ONLY", "Europe/London",
         "2026-08-17", datetime(2026, 8, 17, 23, 0, tzinfo=UTC)),
        ("giz", datetime(2026, 10, 1, 12, 0, tzinfo=UTC), "SOURCE_LOCAL_UNSPECIFIED", None,
         "2026-10-01T12:00", datetime(2026, 9, 30, 22, 0, tzinfo=UTC)),
        ("giz", datetime(2026, 10, 1, 0, 0, tzinfo=UTC), "DATE_ONLY", None,
         "2026-10-01", datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),
        ("adb", datetime(2026, 10, 1, 0, 0, tzinfo=UTC), "DATE_ONLY", None,
         "2026-10-01", datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),
        ("unknown_source", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "SOURCE_LOCAL_UNSPECIFIED", None,
         "2026-10-01T09:00", datetime(2026, 9, 30, 19, 0, tzinfo=UTC)),
    ],
)
def test_published_wall_time_and_conservative_effective_instant(source, stored, basis, zone, published, effective) -> None:
    result = truth.deadline_time(source, stored)
    assert (result.basis.value, result.timezone, result.published_local, result.effective_at) == (
        basis, zone, published, effective,
    )
    # With a time of day, the effective instant is never later than any real reading of the
    # wall time (UTC-12 is the latest zone); a date-only deadline runs to the end of that day.
    if basis != "DATE_ONLY":
        assert result.effective_at <= stored + timedelta(hours=12)
    else:
        assert result.effective_at <= stored + timedelta(days=1)


def test_derived_status_closes_only_open_or_unknown_rows_with_a_passed_deadline() -> None:
    now = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    wall = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)  # effective 03:00 UTC: passed at 10:00
    assert truth.derived_status("OPEN", "world_bank", wall, now=now) == (TenderStatus.CLOSED, "DEADLINE_PASSED")
    assert truth.derived_status(TenderStatus.UNKNOWN, "world_bank", wall, now=now) == (TenderStatus.CLOSED, "DEADLINE_PASSED")
    assert truth.derived_status("OPEN", "world_bank", wall, now=datetime(2026, 10, 16, 2, tzinfo=UTC)) == (TenderStatus.OPEN, None)
    assert truth.derived_status("OPEN", "world_bank", None, now=now) == (TenderStatus.OPEN, None)
    assert truth.derived_status("CANCELLED", "world_bank", wall, now=now) == (TenderStatus.CANCELLED, None)
    assert truth.derived_status("CLOSED", "world_bank", None, now=now) == (TenderStatus.CLOSED, None)
    assert truth.derived_status("garbage", "world_bank", None, now=now) == (TenderStatus.UNKNOWN, None)
    tender = SimpleNamespace(status=TenderStatus.OPEN, source_system="world_bank", deadline=wall)
    assert is_tender_actionable(tender, now=now) is False
    assert is_tender_actionable(tender, now=datetime(2026, 10, 16, 2, tzinfo=UTC)) is True
    assert is_tender_actionable("OPEN") is True


def test_notice_header_prints_the_deadline_as_published_with_its_label() -> None:
    def deadline_line(source: str | None, value: datetime) -> str:
        text_value = compose_notice_text(
            title="t", reference=None, notice_type=None, buyer=None, country=None,
            publication_date=None, deadline=value, source_url=None, body="b", source_system=source,
        )
        return next(line for line in text_value.split("\n") if line.startswith("Deadline"))

    at_five_pm = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)
    assert deadline_line("world_bank", at_five_pm) == "Deadline: 2026-10-16 17:00 local time (as published)"
    assert deadline_line("giz", at_five_pm) == "Deadline: 2026-10-16 17:00 local time (as published)"
    assert deadline_line("uzex", at_five_pm) == "Deadline: 2026-10-16 17:00 Asia/Tashkent time (as published)"
    assert deadline_line("ebrd", at_five_pm) == "Deadline: 2026-10-16 17:00 Europe/London time (as published)"
    assert deadline_line("world_bank", datetime(2026, 10, 16, 23, 59, 59, 999999, tzinfo=UTC)) == (
        "Deadline: 2026-10-16 (date as published; no time stated)"
    )
    for line in (deadline_line(source, at_five_pm) for source in ("world_bank", "uzex", "ebrd", "giz")):
        assert " UTC" not in line


def test_decision_snapshot_urgency_counts_down_to_the_effective_instant() -> None:
    now = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    payload = SimpleNamespace(
        id=uuid4(), source_system="world_bank", country=None, region=None,
        deadline=datetime(2026, 10, 16, 17, 0, tzinfo=UTC),
        deadline_effective_at=datetime(2026, 10, 16, 3, 0, tzinfo=UTC),
        price_amount=None, price_currency=None, price_display=None, document_status="metadata_only",
        document_count=0, downloadable_document_count=0, missing_file_document_count=0,
        parsed_document_count=0, contact_submission=None, compliance_analysis_available=False,
        source_url=None, sector=None, category="Other", procurement_category=None,
    )
    competitors = SimpleNamespace(groups=[])
    snapshot = tenders_endpoint._decision_snapshot_response(payload, competitor_intelligence=competitors, now=now)
    assert snapshot.deadline_urgency == "expired"  # the wall time (17:00) would still say "urgent"


def test_tender_reads_expose_the_truth_fields() -> None:
    for name in ("source_status", "status_reason", "deadline_time_basis", "deadline_timezone",
                 "deadline_published_local", "deadline_effective_at"):
        assert name in TenderResponse.model_fields
    from app.schemas.engagement import MyTenderListItem
    from app.schemas.explorer import ExplorerTenderSummary
    from app.schemas.tenancy import PursuitResponse

    assert "deadline_time_basis" in ExplorerTenderSummary.model_fields
    assert "deadline_time_basis" in MyTenderListItem.model_fields
    assert {"source_tender_status", "source_deadline_time_basis", "source_deadline_effective_at"} <= set(PursuitResponse.model_fields)


# ---- database scenario --------------------------------------------------------------------------


def _writes(engine) -> list[str]:
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    return statements


def test_every_customer_surface_derives_open_status_and_hides_adb_on_postgres(monkeypatch) -> None:
    published: list[str] = []
    monkeypatch.setattr(tenders_endpoint, "_publish_source_refresh_job", lambda job: published.append(str(job.id)))

    async def scenario() -> None:
        async with _database("d1_04_05_truth") as (database, ids, sessions, engine):
            now = datetime.now(UTC)
            rows = {
                # world_bank wall time 5 h ahead -> effective 9 h ago: closed
                "WB-PASSED": ("world_bank", "OPEN", now + timedelta(hours=5), None),
                "WB-OPEN": ("world_bank", "OPEN", now + timedelta(hours=30), None),
                # Tashkent wall time 3 h ahead of UTC now -> 2 h ago: closed
                "UZ-PASSED": ("uzex", "OPEN", now + timedelta(hours=3), {"uzex_type_id": 2}),
                "EBRD-PASSED": ("ebrd", "OPEN", now - timedelta(days=1), None),
                "GIZ-NO-DEADLINE": ("giz", "OPEN", None, None),
                "WB-STORED-CLOSED": ("world_bank", "CLOSED", now + timedelta(days=5), None),
                "ADB-FUTURE": ("adb", "OPEN", now + timedelta(days=10), None),
            }
            tender_ids = {}
            async with sessions() as db:
                for external_id, (source, status_value, deadline, metadata) in rows.items():
                    tender = Tender(
                        source_system=source, external_id=external_id, canonical_source_key=f"{source}:{external_id}",
                        source_url=f"https://example.test/{external_id}", title=f"D105TRUTH {external_id}",
                        description="d", budget=0, currency="USD", status=TenderStatus(status_value),
                        category="Other", deadline=deadline, source_metadata_json=metadata,
                        country="Mongolia",
                    )
                    db.add(tender)
                    await db.flush()
                    tender_ids[external_id] = tender.id
                await db.commit()

            # SQL and Python agree on every row's effective instant.
            async with sessions() as db:
                result = await db.execute(
                    select(Tender.id, Tender.source_system, Tender.deadline, truth.effective_deadline_sql(Tender))
                    .where(Tender.id.in_(tender_ids.values()))
                )
                for tender_id, source, deadline, effective in result.all():
                    assert effective == truth.effective_deadline(source, deadline), (source, deadline)
                # A date-only and an explicit-zone row, directly.
                for source, stored in (
                    ("world_bank", datetime(2026, 10, 16, 23, 59, 59, 999999, tzinfo=UTC)),
                    ("ebrd", datetime(2026, 8, 17, 0, 0, tzinfo=UTC)),
                    ("giz", datetime(2026, 10, 1, 0, 0, tzinfo=UTC)),
                    ("uzex", datetime(2026, 9, 29, 8, 17, 30, tzinfo=UTC)),
                ):
                    probe = SimpleNamespace(
                        source_system=literal_column(f"'{source}'::varchar"),
                        deadline=literal_column(f"TIMESTAMPTZ '{stored.isoformat()}'"),
                    )
                    value = await db.scalar(select(truth.effective_deadline_sql(probe)))
                    assert value == truth.effective_deadline(source, stored), source

            connection = await __import__("scripts.test_s0_5b4_baseline", fromlist=["x"]).database_connection(database)
            try:
                profile = ids["profile_a"]
                organization = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", profile)
                membership = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization, ids["user_a"])
                # "Matches your profile" (D1-08) is computed from the profile's targets.
                await connection.execute(
                    "UPDATE company_profiles SET target_countries='[\"Mongolia\"]'::json WHERE id=$1", profile)
            finally:
                await connection.close()

            writes = _writes(engine)
            user = SimpleNamespace(id=ids["user_a"])
            async with sessions() as db:
                # Explorer default view, counts and filters.
                default = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(q="D105TRUTH", limit=50))
                assert {item.tender.external_id for item in default.items} == {"WB-OPEN", "GIZ-NO-DEADLINE"}
                assert default.counts.all_tenders == 2
                assert all(item.tender.status == TenderStatus.OPEN for item in default.items)
                closed = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(q="D105TRUTH", tender_status="closed", limit=50))
                by_id = {item.tender.external_id: item.tender for item in closed.items}
                assert set(by_id) == {"WB-PASSED", "UZ-PASSED", "EBRD-PASSED", "WB-STORED-CLOSED"}
                assert by_id["WB-PASSED"].status_reason == "DEADLINE_PASSED"
                assert by_id["WB-PASSED"].source_status == TenderStatus.OPEN
                assert by_id["WB-PASSED"].deadline_time_basis == "SOURCE_LOCAL_UNSPECIFIED"
                assert by_id["UZ-PASSED"].deadline_timezone == "Asia/Tashkent"
                assert by_id["WB-STORED-CLOSED"].status_reason is None
                expired = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    q="D105TRUTH", tender_status="all", deadline_status="expired", limit=50))
                assert {item.tender.external_id for item in expired.items} == {"WB-PASSED", "UZ-PASSED", "EBRD-PASSED"}
                everything = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(q="D105TRUTH", tender_status="all", limit=50))
                assert "ADB-FUTURE" not in {item.tender.external_id for item in everything.items}  # D1-04b
                assert everything.counts.all_tenders == 6
                # "Matches your profile": only open tenders by derived status. WB-PASSED's
                # stored wall time is still ahead but its effective deadline has passed.
                recommended = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="D105TRUTH", limit=50))
                assert {item.tender.external_id for item in recommended.items} == {"WB-OPEN", "GIZ-NO-DEADLINE"}
                assert recommended.counts.active_recommendations == 2

                # Tender reads (Tender Details header, notification destinations).
                read = await tenders_endpoint.get_tender(tender_ids["WB-PASSED"], current_user=user, db=db)
                assert (read.status, read.status_reason, read.source_status) == (TenderStatus.CLOSED, "DEADLINE_PASSED", TenderStatus.OPEN)
                assert read.deadline_effective_at == read.deadline - timedelta(hours=14)
                for endpoint in (tenders_endpoint.get_tender, tenders_endpoint.get_tender_details):
                    with pytest.raises(HTTPException) as hidden:
                        await endpoint(tender_ids["ADB-FUTURE"], current_user=user, db=db)
                    assert (hidden.value.status_code, hidden.value.detail) == (404, tenders_endpoint.TENDER_SOURCE_UNAVAILABLE_DETAIL)
                with pytest.raises(HTTPException) as missing:
                    await tenders_endpoint.get_tender(uuid4(), current_user=user, db=db)
                assert missing.value.detail == "Tender not found"
            assert not {verb for verb in writes if verb in {"INSERT", "UPDATE", "DELETE"}}, writes  # passive GETs

            # My Tenders and pursuit reads.
            async with sessions() as db:
                for external_id in ("WB-PASSED", "WB-OPEN"):
                    await get_or_create_source_pursuit(
                        db, organization_id=organization, actor_user_id=ids["user_a"], actor_membership_id=membership,
                        tender_id=tender_ids[external_id], stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                await db.commit()
            writes.clear()
            async with sessions() as db:
                mine = await list_my_tenders(db, user_id=ids["user_a"], company_profile_id=profile, query=MyTendersQuery(search="D105TRUTH"))
                statuses = {item.tender_title: (item.tender_status, item.status_reason) for item in mine.items}
                assert statuses["D105TRUTH WB-PASSED"] == (TenderStatus.CLOSED, "DEADLINE_PASSED")
                assert statuses["D105TRUTH WB-OPEN"] == (TenderStatus.OPEN, None)
                only_open = await list_my_tenders(db, user_id=ids["user_a"], company_profile_id=profile,
                                                  query=MyTendersQuery(search="D105TRUTH", tender_status=TenderStatus.OPEN))
                assert [item.tender_title for item in only_open.items] == ["D105TRUTH WB-OPEN"]
                pursuit_rows = (await db.execute(
                    text("SELECT id FROM organization_pursuits WHERE source_tender_id = :t"), {"t": tender_ids["WB-PASSED"]}
                )).scalars().all()
                from app.models.tenancy import OrganizationPursuit

                pursuit = await db.get(OrganizationPursuit, pursuit_rows[0])
                tender = await db.get(Tender, tender_ids["WB-PASSED"])
                response = pursuits_endpoint._response(pursuit, tender)
                assert (response.source_tender_status, response.source_tender_status_reason) == ("CLOSED", "DEADLINE_PASSED")
                assert response.source_deadline_time_basis == "SOURCE_LOCAL_UNSPECIFIED"
            assert not {verb for verb in writes if verb in {"INSERT", "UPDATE", "DELETE"}}, writes

            # Admin still sees ADB.
            async with sessions() as db:
                health = await admin_endpoint.get_admin_corpus_health(db=db)
                assert health.adb_visible_count == 0 and health.adb_total_count >= 1
                assert health.customer_hidden_sources == ["adb"]

            # Scheduled refresh: dispatch, no overlap, due check, hidden source, system origin.
            async with sessions() as db:
                cadence = timedelta(hours=6)
                first = await source_refresh_tasks.dispatch_scheduled_refresh(db, "world_bank", cadence=cadence)
                assert first["outcome"] == "dispatched" and published == [first["job_id"]]
                job = (await db.execute(select(SourceRefreshJob).where(SourceRefreshJob.source_system == "world_bank"))).scalars().one()
                assert (job.trigger_kind, job.requested_by_user_id, job.status) == ("scheduled", None, "queued")
                second = await source_refresh_tasks.dispatch_scheduled_refresh(db, "world_bank", cadence=cadence)
                assert second["outcome"] == "skipped_active" and len(published) == 1
                job.status, job.lease_owner = "running", uuid4()
                job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=3)
                await db.commit()
                assert (await source_refresh_tasks.dispatch_scheduled_refresh(db, "world_bank", cadence=cadence))["outcome"] == "skipped_active"
                job.status, job.lease_owner, job.lease_expires_at = "completed", None, None
                job.completed_at = datetime.now(UTC)
                await db.commit()
                assert (await source_refresh_tasks.dispatch_scheduled_refresh(db, "world_bank", cadence=cadence))["outcome"] == "not_due"
                job.created_at = datetime.now(UTC) - timedelta(hours=7)
                job.completed_at = datetime.now(UTC) - timedelta(hours=13)
                await db.commit()
                # Staleness: last success 13 h ago > 2 x 6 h.
                status_items = {item.source_system: item for item in await source_refresh_status(db)}
                assert "adb" not in status_items
                assert status_items["world_bank"].stale is True
                assert status_items["world_bank"].scheduled_cadence_seconds == 6 * 3600
                third = await source_refresh_tasks.dispatch_scheduled_refresh(db, "world_bank", cadence=cadence)
                assert third["outcome"] == "dispatched" and len(published) == 2
                hidden = await source_refresh_tasks.dispatch_scheduled_refresh(db, "adb", cadence=cadence)
                assert hidden["outcome"] == "skipped_hidden" and len(published) == 2

    asyncio.run(scenario())


# ---- Step 0 (d): analysis_smoke --live guard ------------------------------------------------------


def _fake_api(monkeypatch, routes: dict):
    from scripts import analysis_smoke

    calls: list[tuple[str, str]] = []

    def call(self, method, path, payload=None):  # noqa: ARG001
        calls.append((method, path))
        for (route_method, prefix), response in routes.items():
            if method == route_method and path.startswith(prefix):
                return response(payload) if callable(response) else response
        return 404, {"detail": "not routed"}

    monkeypatch.setattr(analysis_smoke.Api, "call", call)
    return analysis_smoke, calls


ORG = "11111111-1111-1111-1111-111111111111"
MEMBERSHIP = "22222222-2222-2222-2222-222222222222"


def _live_args(analysis_smoke, **overrides):
    argv = ["--live", "--api-base", "http://api.test/api/v1", "--org-id", ORG, "--org-name", "Plasma Smoke Test Org",
            "--tender-id", "33333333-3333-3333-3333-333333333333", "--poll-seconds", "0"]
    for key, value in overrides.items():
        argv += [f"--{key}", str(value)]
    parser_args = analysis_smoke.argparse.ArgumentParser()
    return argv, parser_args


@pytest.mark.parametrize(
    ("organizations", "members", "message"),
    [
        ([{"organization_id": ORG, "display_name": "Plasma Smoke Test Org", "membership_id": MEMBERSHIP},
          {"organization_id": "x", "display_name": "Customer", "membership_id": "y"}], [], "belongs to 2 organizations"),
        ([{"organization_id": ORG, "display_name": "A Customer Ltd", "membership_id": MEMBERSHIP}], [], "display name does not equal"),
        ([{"organization_id": "other", "display_name": "Plasma Smoke Test Org", "membership_id": MEMBERSHIP}], [], "--org-id is not"),
        ([{"organization_id": ORG, "display_name": "Plasma Smoke Test Org", "membership_id": MEMBERSHIP}],
         [{"membership_id": MEMBERSHIP, "state": "ACTIVE"}, {"membership_id": "another", "state": "ACTIVE"}],
         "exactly one active member"),
    ],
)
def test_live_smoke_refuses_anything_but_a_dedicated_single_member_test_org(monkeypatch, capsys, organizations, members, message) -> None:
    analysis_smoke, calls = _fake_api(monkeypatch, {
        ("GET", "/organizations/"): (200, members),
        ("GET", "/organizations"): (200, organizations),
    })
    argv, _ = _live_args(analysis_smoke)
    exit_code = analysis_smoke.live(analysis_smoke_args(analysis_smoke, argv), {"ANALYSIS_SMOKE_TOKEN": "t"})
    assert exit_code == 1 and message in capsys.readouterr().out
    assert all(method == "GET" for method, _path in calls)  # nothing was written


def analysis_smoke_args(analysis_smoke, argv):
    captured = {}
    original = analysis_smoke.live

    def grab(args, environ=None):  # noqa: ARG001
        captured["args"] = args
        return 0

    analysis_smoke.live = grab
    try:
        analysis_smoke.main(argv)
    finally:
        analysis_smoke.live = original
    return captured["args"]


def test_live_smoke_needs_a_token_from_the_environment(capsys) -> None:
    from scripts import analysis_smoke

    args = analysis_smoke_args(analysis_smoke, _live_args(analysis_smoke)[0])
    assert analysis_smoke.live(args, {}) == 2
    assert "ANALYSIS_SMOKE_TOKEN" in capsys.readouterr().err


def test_live_smoke_runs_one_notice_analysis_and_checks_the_gate(monkeypatch, capsys) -> None:
    started = []
    completed = {
        "status": "COMPLETED", "quality_state": "READY_FOR_REVIEW", "model_name": "gemini-3.8-flash",
        "pipeline_version": "pursuit_analysis_pipeline_d1_v3", "failure_stage": None, "gaps": [], "positions": [],
        "requirements": [{"source_locator": {"context_origin": "MODEL_VERBATIM"}}] * 6,
    }
    analysis_smoke, calls = _fake_api(monkeypatch, {
        ("GET", "/organizations/"): (200, [{"membership_id": MEMBERSHIP, "state": "ACTIVE"}]),
        ("GET", "/organizations"): (200, [{"organization_id": ORG, "display_name": "Plasma Smoke Test Org", "membership_id": MEMBERSHIP}]),
        ("POST", "/pursuits/source"): (201, {"pursuit_id": "p1"}),
        ("GET", "/pursuits/p1/analysis-pack-candidate"): (200, {"candidate_sha256": "a" * 64, "source_documents": [
            {"role": "OFFICIAL_SOURCE", "parse_ready": True, "tender_document_id": "doc-attachment"},
            {"role": "OFFICIAL_NOTICE", "parse_ready": True, "tender_document_id": "doc-notice"},
        ]}),
        ("POST", "/pursuits/p1/analysis-runs"): lambda payload: (started.append(payload) or (202, {"analysis_run_id": "r1"})),
        ("GET", "/pursuits/p1/analysis-runs/r1"): (200, completed),
    })
    args = analysis_smoke_args(analysis_smoke, _live_args(analysis_smoke)[0])
    assert analysis_smoke.live(args, {"ANALYSIS_SMOKE_TOKEN": "secret-token"}) == 0
    output = capsys.readouterr().out
    assert "live analysis smoke: OK" in output and "secret-token" not in output
    assert started[0]["source_document_ids"] == ["doc-notice"] and started[0]["private_version_ids"] == []
    writes = [(method, path) for method, path in calls if method == "POST"]
    assert writes == [("POST", "/pursuits/source"), ("POST", "/pursuits/p1/analysis-runs")]
    completed["requirements"] = completed["requirements"][:4]
    assert analysis_smoke.live(args, {"ANALYSIS_SMOKE_TOKEN": "t"}) == 1
    assert "4 requirements < 5" in capsys.readouterr().out
