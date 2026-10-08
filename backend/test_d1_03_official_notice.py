"""D1-03: system-generated OFFICIAL_NOTICE source documents.

Unit and static checks run anywhere. The database scenarios build disposable
PostgreSQL databases (same harness as the W-series proofs) and never touch the
configured application database.
"""

from __future__ import annotations

import ast
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints import tenders as tenders_endpoint
from app.core.agents.pursuit_analyzer import ExtractedFact, NumericPredicate, VerifiedFact
from app.models.all_models import Tender, TenderDocument, TenderStatus, User
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.pursuit_analysis import AnalysisPackItem, AnalysisRun, PursuitRequirement
from app.schemas.tender_details import DetailsSectionState
from app.schemas.tenancy import PursuitAnalysisStartRequest
from app.services import official_notice as notice
from app.services import pursuit_analysis as analysis_service
from app.services.official_notice import (
    HEADER_OPEN,
    BODY_OPEN,
    OFFICIAL_NOTICE_DISPLAY_NAME,
    OFFICIAL_NOTICE_DOCUMENT_TYPE,
    OFFICIAL_NOTICE_MIN_CHARS,
    build_official_notice_text,
    compose_notice_text,
    notice_body_text,
    notice_text_from_html,
    official_notice_file_url,
    official_notice_sha256,
    sync_official_notices,
)
from app.services.private_documents import build_analysis_pack_candidate
from app.services.pursuit_analysis import (
    AnalysisAdmissionError,
    create_analysis_run,
    get_analysis_run,
    process_analysis_run,
)
from app.services.pursuits import get_or_create_source_pursuit
from app.services.tender_details import compose_tender_details
from app.services.tender_sources.base import (
    CanonicalDocument,
    NormalizedTender,
    persist_document_descriptors,
    persist_tender_batch,
)
from app.services.tender_sources.world_bank import clean_notice_html
from app.workers import tender_tasks
from scripts import backfill_official_notices as backfill_module
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _digest, _seed_w1


BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
P0_HEAD = "20261002_0001_p0_extraction_trust_gate"
HEAD = "20261008_0001_r3_pending_invitations"


def _tender(**overrides) -> Tender:
    values = dict(
        source_system="world_bank", external_id="OP00000001",
        canonical_source_key="world_bank:OP00000001",
        source_url="https://projects.worldbank.org/notice/OP00000001",
        title="Detailed design services", description="x" * 400,
        notice_type="Request for Expression of Interest",
        buyer="Ministry of Energy", country="Mongolia",
        publication_date=datetime(2026, 9, 15, tzinfo=timezone.utc),
        deadline=datetime(2026, 10, 16, 17, 0, tzinfo=timezone.utc),
        budget=0, currency="USD", status=TenderStatus.OPEN, category="Other",
        source_metadata_json=None,
    )
    values.update(overrides)
    return Tender(**values)


# --------------------------------------------------------------------------- #
# Normalization and header composition
# --------------------------------------------------------------------------- #


def test_html_normalization_is_deterministic_for_entities_lists_and_whitespace() -> None:
    source = (
        "<p><strong>NOTICE</strong> &amp; more</p><p>&nbsp;</p>"
        "<p>Budget &lt; 5&nbsp;000 &euro;</p>"
        "<ul><li>First</li><li><p>Second</p></li></ul>"
        "<ol><li>One</li><li>Two</li></ol>"
        "<table><tr><th>A</th><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
        "<script>track()</script>tail<br>line"
    )
    expected = (
        "NOTICE & more\n\nBudget < 5 000 €\n\n- First\n- Second\n\n"
        "1. One\n2. Two\n\nA | B\nC | D\n\ntail\nline"
    )
    assert notice_text_from_html(source) == expected
    assert notice_text_from_html(source) == notice_text_from_html(source)
    assert "track" not in notice_text_from_html(source)


def test_plain_text_keeps_lines_and_only_decodes_terminated_entities() -> None:
    plain = "AT&T  and R&D &amp; more\r\n\r\n\r\nnext   line x​"
    assert notice_text_from_html(plain) == "AT&T and R&D & more\n\nnext line x"
    assert notice_text_from_html(None) == "" and notice_text_from_html("   \n ") == ""
    once = notice_text_from_html(plain)
    assert notice_text_from_html(once) == once


def test_header_block_is_delimited_and_omits_missing_fields() -> None:
    full = compose_notice_text(
        title="Detailed design", reference="OP1", notice_type="REOI",
        buyer="Ministry of Energy", country="Mongolia",
        publication_date=datetime(2026, 9, 15, tzinfo=timezone.utc),
        deadline=datetime(2026, 10, 16, 22, 0, tzinfo=timezone(timedelta(hours=5))),
        source_url="https://example.test/n", body="Body line.",
    )
    assert full == (
        f"{HEADER_OPEN}\nTitle: Detailed design\nReference: OP1\nNotice type: REOI\n"
        "Borrower/client: Ministry of Energy\nCountry: Mongolia\n"
        "Publication date: 2026-09-15\nDeadline: 2026-10-16 17:00 local time (as published)\n"
        f"Source URL: https://example.test/n\n\n{BODY_OPEN}\nBody line."
    )
    sparse = compose_notice_text(
        title=" Only  title ", reference=None, notice_type="  ", buyer="",
        country=None, publication_date=None, deadline=None, source_url=None, body="B",
    )
    assert sparse == f"{HEADER_OPEN}\nTitle: Only title\n\n{BODY_OPEN}\nB"
    for absent in ("Reference", "Notice type", "Borrower", "Country", "Publication", "Deadline", "Source URL"):
        assert absent not in sparse


@pytest.mark.parametrize(
    "instant",
    [datetime(2026, 10, 16, tzinfo=timezone.utc),
     datetime(2026, 10, 16, 23, 59, 59, 999999, tzinfo=timezone.utc)],
)
def test_deadline_without_a_stated_time_is_not_given_an_invented_clock_time(instant) -> None:
    text_value = compose_notice_text(
        title="t", reference=None, notice_type=None, buyer=None, country=None,
        publication_date=None, deadline=instant, source_url=None, body="b",
    )
    assert "Deadline: 2026-10-16 (date as published; no time stated)" in text_value
    assert "00:00" not in text_value and "23:59" not in text_value


def test_threshold_is_measured_on_the_normalized_description_for_every_source() -> None:
    assert OFFICIAL_NOTICE_MIN_CHARS == 300
    for source in ("world_bank", "adb", "ebrd", "giz", "uzex"):
        base = dict(source_system=source, canonical_source_key=f"{source}:1", external_id="1")
        assert build_official_notice_text(_tender(description="a" * 300, **base)) is not None
        assert build_official_notice_text(_tender(description="a" * 299, **base)) is None
        # Markup and entities do not count towards the threshold.
        assert build_official_notice_text(
            _tender(description="<p>" + "a" * 299 + "&nbsp;</p>", **base)
        ) is None
        assert build_official_notice_text(_tender(description=None, **base)) is None


def test_structured_body_is_used_only_when_raw_html_equals_the_stored_description() -> None:
    raw = (
        "<p><strong>REQUEST</strong>&nbsp;FOR EOI &ndash; &ldquo;Lot 4&rdquo;</p><p>&nbsp;</p>"
        "<p><b>Country:</b> Mongolia</p><p>" + ("Firms shall show experience. " * 12) + "</p>"
        "<ul><li>One</li><li><p>Two</p></li></ul><ol><li>Three</li></ol>"
        "<table><tr><td>A</td><td>B</td></tr></table><script>x()</script>"
    )
    # The stored description is what the real World Bank connector derives from it.
    stored = clean_notice_html(raw)
    assert stored and "\n" not in stored
    eligible, structured = notice_body_text(
        source_system="world_bank", description=stored, source_metadata={"notice_text": raw}
    )
    assert eligible == notice_text_from_html(stored)
    assert structured == notice_text_from_html(raw) != eligible
    assert "\n- One\n- Two\n" in structured and "\n1. Three\n" in structured and "A | B" in structured
    assert "- One" not in eligible and "\n" not in eligible

    # Different content, other sources, or no metadata: the stored description wins.
    _, other = notice_body_text(
        source_system="world_bank", description=stored + " changed",
        source_metadata={"notice_text": raw},
    )
    assert other == stored + " changed"
    for source, metadata in (("uzex", {"notice_text": raw}), ("world_bank", None), ("world_bank", {"notice_text": 5})):
        assert notice_body_text(source_system=source, description=stored, source_metadata=metadata)[1] == stored


def test_file_url_is_a_stable_non_downloadable_identifier() -> None:
    assert official_notice_file_url("world_bank", "OP1") == "official-notice://world_bank/OP1"
    assert official_notice_file_url("uzex", "a b/c") == "official-notice://uzex/a%20b%2Fc"
    long_url = official_notice_file_url("giz", "x" * 900)
    assert len(long_url) <= 500 and long_url.startswith("official-notice://giz/")
    assert long_url == official_notice_file_url("giz", "x" * 900)
    assert "://" in quote("a") + "://" and not long_url.startswith(("http://", "https://"))


def test_row_text_hash_is_the_sha256_of_the_stored_text() -> None:
    text_value = build_official_notice_text(_tender())
    assert text_value is not None
    assert official_notice_sha256(text_value) == hashlib.sha256(text_value.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Static boundaries
# --------------------------------------------------------------------------- #


def _source(rel: str) -> str:
    return (BACKEND_DIR / rel).read_text(encoding="utf-8")


def test_only_source_refresh_and_backfill_write_official_notices() -> None:
    callers = []
    for path in list((BACKEND_DIR / "app").rglob("*.py")) + list((BACKEND_DIR / "scripts").glob("*.py")):
        if path.name == "official_notice.py":
            continue
        content = path.read_text(encoding="utf-8")
        if "sync_official_notices" in content:
            callers.append(path.relative_to(BACKEND_DIR).as_posix())
    assert sorted(callers) == [
        "app/services/tender_sources/base.py",
        "scripts/backfill_official_notices.py",
    ]
    persist = _source("app/services/tender_sources/base.py")
    assert persist.count("await sync_official_notices(") == 1
    # The constant that marks the row is only ever written by the shared module.
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        if path.name != "official_notice.py":
            assert 'source_document_type="OFFICIAL_NOTICE"' not in path.read_text(encoding="utf-8")
    assert OFFICIAL_NOTICE_DOCUMENT_TYPE == "OFFICIAL_NOTICE"


def test_notice_builder_reads_only_shared_tender_columns() -> None:
    tree = ast.parse(_source("app/services/official_notice.py"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.")
    }
    # D1-05b: the deadline line reads the source's deadline time basis; both modules are
    # pure configuration/rules and read no tenant or private data.
    assert imported == {"app.models.all_models", "app.core.deadline_truth", "app.services.source_registry"}


def _unguarded_document_selects(rel: str) -> list[str]:
    source = _source(rel)
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select"):
            continue
        names = {n.id for arg in node.args for n in ast.walk(arg) if isinstance(n, ast.Name)}
        if "TenderDocument" not in names:
            continue
        statement = node
        while not isinstance(statement, ast.stmt):
            statement = parents[statement]
        segment = ast.get_source_segment(source, statement) or ""
        if any(token in segment for token in ("not_official_notice", "only_official_notice", "TenderDocument.id ==")):
            continue
        offenders.append(f"{rel}:{node.lineno}")
    return offenders


@pytest.mark.parametrize(
    "rel",
    [
        "app/api/endpoints/tenders.py",
        "app/workers/tender_tasks.py",
        "app/services/giz_document_hydration.py",
        "app/services/tender_details.py",
        "app/services/tender_sources/base.py",
    ],
)
def test_every_tender_document_query_excludes_the_notice_or_fetches_by_primary_key(rel: str) -> None:
    """Acquisition, hydration, download and aggregate queries must skip OFFICIAL_NOTICE rows."""
    assert _unguarded_document_selects(rel) == []


def test_download_endpoint_refuses_notice_rows_before_touching_storage() -> None:
    source = _source("app/api/endpoints/tenders.py")
    refusal = source.index("if is_official_notice(doc):")
    assert refusal < source.index("local_path = normalize_storage_path(doc.storage_path)", refusal - 4000)
    assert source.index("_ensure_tender_access(", source.index("async def download_document")) < refusal


def test_frontend_shows_notice_without_download_and_is_localized() -> None:
    for locale in ("en", "ru", "uz", "ar"):
        details = json.loads((FRONTEND_DIR / "messages" / locale / "tenderDetails.json").read_text(encoding="utf-8"))
        assert all(details["officialNotice"][key].strip() for key in ("title", "help", "openAtSource"))
        pursuits = json.loads((FRONTEND_DIR / "messages" / locale / "pursuits.json").read_text(encoding="utf-8"))
        assert pursuits["roles"]["OFFICIAL_NOTICE"].strip()
        assert pursuits["requirements"]["documentRoles"]["OFFICIAL_NOTICE"].strip()
        assert details["officialNotice"]["title"] == pursuits["roles"]["OFFICIAL_NOTICE"]
    page = (FRONTEND_DIR / "app/dashboard/tenders/[tenderId]/page.tsx").read_text(encoding="utf-8")
    block = page[page.index('className="s143-official-notice"'):page.index('className="s143-table-wrap"')]
    assert 'officialNotice.title' in block and 'officialNotice.openAtSource' in block
    assert "openDocument" not in block and "/download" not in block and "onClick" not in block


# --------------------------------------------------------------------------- #
# Disposable-database scenarios
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _database(label: str, *, seed: bool = True):
    database = support.database_name(label)
    await support.create_database(database)
    engine = None
    try:
        await support.raw_baseline(database)
        ids: dict[str, UUID] = {}
        if seed:
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        engine = create_async_engine(support.target_url(database), pool_size=10)
        yield database, ids, async_sessionmaker(engine, expire_on_commit=False), engine
    finally:
        if engine is not None:
            await engine.dispose()
        await support.drop_database(database)


def _capture(engine) -> list[str]:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _many) -> None:
        statements.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    return statements


def _document_statements(statements: list[str], kinds: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")):
    return [
        item for item in statements
        if "tender_documents" in item.lower() and item.split(" ", 1)[0].upper() in kinds
    ]


def _long_notice(topic: str, sentences: int = 12) -> str:
    body = "".join(
        f"<p>{topic}: firm experience item {n} must be demonstrated with a reference letter.</p>"
        for n in range(sentences)
    )
    return f"<p><strong>REQUEST FOR EXPRESSIONS OF INTEREST</strong></p>{body}<ul><li>Shortlisting criteria A</li><li>Criteria B</li></ul>"


def _normalized(source: str, external_id: str, description: str | None, **overrides) -> NormalizedTender:
    values = dict(
        source_system=source, external_id=external_id,
        source_url=f"https://example.test/{source}/{external_id}",
        title=f"{source} tender {external_id}", description=description, budget=1000.0,
        currency="USD", country="Mongolia", buyer="Ministry", notice_type="REOI",
        publication_date=datetime(2026, 9, 15, tzinfo=timezone.utc),
        deadline=datetime(2026, 12, 1, 9, 30, tzinfo=timezone.utc),
        status=TenderStatus.OPEN, category="Other",
        # Connectors always send their raw payload; NULL metadata reads as "changed"
        # on every refresh (existing behaviour, unrelated to notices).
        source_metadata_json={"id": external_id},
    )
    values.update(overrides)
    return NormalizedTender(**values)


async def _notice_rows(connection) -> dict[UUID, dict]:
    rows = await connection.fetch(
        "SELECT id, tender_id, file_url, file_type, mime_type, sha256, parsed_text, download_status, "
        "storage_path, source_document_url, source_document_type, created_at, xmin::text AS xmin "
        "FROM tender_documents WHERE source_document_type='OFFICIAL_NOTICE'"
    )
    return {row["tender_id"]: dict(row) for row in rows}


def test_migration_is_additive_reversible_drift_free_and_enforces_uniqueness() -> None:
    async def scenario() -> None:
        database = support.database_name("d1_03_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", P0_HEAD)
            connection = await support.database_connection(database)
            try:
                tender_ids = [uuid4(), uuid4()]
                for index, tender_id in enumerate(tender_ids):
                    await connection.execute(
                        "INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,"
                        "budget,currency,status,category) VALUES ($1,$2,'uzex',$3,'https://x.test','t',0,'UZS','OPEN','Other')",
                        tender_id, f"m-{index}", f"uzex:m-{index}",
                    )
                for _ in range(2):  # ordinary attachments may repeat a type freely
                    await connection.execute(
                        "INSERT INTO tender_documents(id,tender_id,file_url,file_type,source_document_type) "
                        "VALUES ($1,$2,$3,'pdf','RFP')", uuid4(), tender_ids[0], f"u-{uuid4()}",
                    )
            finally:
                await connection.close()

            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
                definition = await connection.fetchval(
                    "SELECT indexdef FROM pg_indexes WHERE indexname='uq_tender_documents_official_notice'"
                )
                assert "UNIQUE" in definition and "OFFICIAL_NOTICE" in definition
                insert = (
                    "INSERT INTO tender_documents(id,tender_id,file_url,file_type,source_document_type) "
                    "VALUES ($1,$2,$3,'text/plain','OFFICIAL_NOTICE')"
                )
                await connection.execute(insert, uuid4(), tender_ids[0], "official-notice://uzex/m-0")
                with pytest.raises(Exception, match="uq_tender_documents_official_notice"):
                    await connection.execute(insert, uuid4(), tender_ids[0], "official-notice://uzex/dup")
                await connection.execute(insert, uuid4(), tender_ids[1], "official-notice://uzex/m-1")
                assert await connection.fetchval("SELECT count(*) FROM tender_documents WHERE tender_id=$1", tender_ids[0]) == 3
            finally:
                await connection.close()
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout

            await asyncio.to_thread(support.alembic, database, "downgrade", P0_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == P0_HEAD
                assert await connection.fetchval(
                    "SELECT to_regclass('uq_tender_documents_official_notice')"
                ) is None
                assert await connection.fetchval("SELECT count(*) FROM tender_documents") == 4
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_refresh_hook_is_set_wise_idempotent_race_safe_and_excluded_from_acquisition() -> None:
    async def scenario() -> None:
        async with _database("d1_03_refresh") as (database, ids, sessions, engine):
            statements = _capture(engine)
            worker_engine = create_async_engine(support.target_url(database), pool_size=2)
            worker_sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
            connection = await support.database_connection(database)
            try:
                preserved_before = {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leader", "project_role_assignments", ids["current_leader"]),
                        ("legacy_analysis", "tender_analyses", ids["analysis"]),
                        ("legacy_version", "analysis_versions", ids["analysis_version"]),
                    )
                }

                # ---- create: one document per substantive tender, none for short ones ----
                wb_html = _long_notice("World Bank")
                batch = [
                    _normalized("world_bank", "N-WB", clean_notice_html(wb_html),
                                source_metadata_json={"notice_text": wb_html}),
                    _normalized("uzex", "N-UZ", "Plain uzex notice. " * 30),
                    _normalized("giz", "N-GIZ", "GIZ &amp; partners notice text. " * 20),
                    _normalized("ebrd", "N-SHORT", "too short"),
                    _normalized("adb", "N-NONE", None),
                    # The seeded tender the test user owns: it gains a notice on refresh.
                    _normalized("world_bank", "WB-W2-1", _long_notice("Seeded"), title="W2 Source Tender",
                                source_url="https://example.invalid/w2-source"),
                ]
                statements.clear()
                async with sessions() as db:
                    result = await persist_tender_batch(db, batch)
                    await db.commit()
                assert result.created_count == 5 and result.updated_count == 1
                notice_statements = _document_statements(statements)
                assert [item.split(" ", 1)[0] for item in notice_statements] == ["SELECT", "INSERT"]

                rows = await _notice_rows(connection)
                assert len(rows) == 4
                tenders = {
                    row["external_id"]: row
                    for row in await connection.fetch("SELECT id, external_id, source_url, source_system FROM tenders")
                }
                for external_id in ("N-WB", "N-UZ", "N-GIZ"):
                    tender = tenders[external_id]
                    row = rows[tender["id"]]
                    assert row["file_url"] == f"official-notice://{tender['source_system']}/{external_id}"
                    assert row["file_type"] == "text/plain" and row["mime_type"] == "text/plain"
                    assert row["download_status"] == "processed" and row["storage_path"] is None
                    assert row["source_document_url"] == tender["source_url"]
                    assert row["source_document_type"] == "OFFICIAL_NOTICE"
                    assert row["sha256"] == hashlib.sha256(row["parsed_text"].encode()).hexdigest()
                    assert row["parsed_text"].startswith(HEADER_OPEN) and BODY_OPEN in row["parsed_text"]
                    assert f"Reference: {external_id}" in row["parsed_text"]
                    # D1-05b: the published wall time with its source basis, never "UTC".
                    label = {"world_bank": "local time", "uzex": "Asia/Tashkent time", "giz": "local time"}[tender["source_system"]]
                    assert f"Deadline: 2026-12-01 09:30 {label} (as published)" in row["parsed_text"]
                assert "&amp;" not in rows[tenders["N-GIZ"]["id"]]["parsed_text"]
                wb_text = rows[tenders["N-WB"]["id"]]["parsed_text"]
                assert "\n- Shortlisting criteria A\n- Criteria B" in wb_text  # structure restored from raw HTML

                # ---- set-wise: statement count does not grow with the batch ----
                many = [_normalized("uzex", f"BULK-{n}", f"bulk notice {n} " * 40) for n in range(60)]
                statements.clear()
                async with sessions() as db:
                    await persist_tender_batch(db, many)
                    await db.commit()
                assert [i.split(" ", 1)[0] for i in _document_statements(statements)] == ["SELECT", "INSERT"]
                assert len(await _notice_rows(connection)) == 64

                # ---- unchanged batch: nothing is written ----
                before = await _notice_rows(connection)
                statements.clear()
                async with sessions() as db:
                    again = await persist_tender_batch(db, [*batch, *many])
                    await db.commit()
                assert again.unchanged_count == 66
                assert _document_statements(statements, ("INSERT", "UPDATE", "DELETE")) == []
                after = await _notice_rows(connection)
                assert {k: v["xmin"] for k, v in after.items()} == {k: v["xmin"] for k, v in before.items()}

                # ---- changed text updates in place; neighbours untouched ----
                changed = _long_notice("World Bank amended", 14)
                statements.clear()
                async with sessions() as db:
                    result = await persist_tender_batch(db, [
                        _normalized("world_bank", "N-WB", clean_notice_html(changed),
                                    source_metadata_json={"notice_text": changed}),
                        *batch[1:],
                    ])
                    await db.commit()
                assert result.updated_count == 1
                after2 = await _notice_rows(connection)
                wb_id = tenders["N-WB"]["id"]
                assert len(after2) == 64
                assert after2[wb_id]["id"] == after[wb_id]["id"]
                assert after2[wb_id]["created_at"] == after[wb_id]["created_at"]
                assert after2[wb_id]["sha256"] != after[wb_id]["sha256"]
                assert "amended" in after2[wb_id]["parsed_text"]
                assert after2[wb_id]["sha256"] == hashlib.sha256(after2[wb_id]["parsed_text"].encode()).hexdigest()
                assert all(after2[k]["xmin"] == after[k]["xmin"] for k in after if k != wb_id)
                # A source-owned header field (deadline) is part of the text too.
                async with sessions() as db:
                    await persist_tender_batch(db, [
                        _normalized("uzex", "N-UZ", "Plain uzex notice. " * 30,
                                    deadline=datetime(2026, 12, 2, 9, 30, tzinfo=timezone.utc)),
                    ])
                    await db.commit()
                assert "Deadline: 2026-12-02 09:30 Asia/Tashkent time (as published)" in (await _notice_rows(connection))[tenders["N-UZ"]["id"]]["parsed_text"]
                # A budget-only change is not part of the notice: no notice write.
                statements.clear()
                async with sessions() as db:
                    await persist_tender_batch(db, [_normalized("uzex", "N-UZ", "Plain uzex notice. " * 30,
                                                                deadline=datetime(2026, 12, 2, 9, 30, tzinfo=timezone.utc),
                                                                budget=2222.0)])
                    await db.commit()
                assert _document_statements(statements, ("INSERT", "UPDATE", "DELETE")) == []

                # ---- a missing document is repaired by the next refresh ----
                await connection.execute("DELETE FROM tender_documents WHERE id=$1", after2[wb_id]["id"])
                async with sessions() as db:
                    await persist_tender_batch(db, [
                        _normalized("world_bank", "N-WB", clean_notice_html(changed),
                                    source_metadata_json={"notice_text": changed}),
                    ])
                    await db.commit()
                assert len(await _notice_rows(connection)) == 64

                # ---- concurrent writers never duplicate ----
                for n in range(6):
                    await connection.execute(
                        "INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,description,"
                        "budget,currency,status,category) VALUES ($1,$2,'ebrd',$3,'https://x.test/r','race',$4,0,'EUR','OPEN','Other')",
                        uuid4(), f"RACE-{n}", f"ebrd:RACE-{n}", "race notice text " * 30,
                    )

                async def racer() -> None:
                    async with sessions() as db:
                        tenders_rows = list((await db.scalars(select(Tender).where(Tender.external_id.like("RACE-%")))).all())
                        await sync_official_notices(db, tenders_rows)
                        await db.commit()

                await asyncio.gather(*(racer() for _ in range(8)))
                assert await connection.fetchval(
                    "SELECT count(*) FROM tender_documents d JOIN tenders t ON t.id=d.tender_id "
                    "WHERE d.source_document_type='OFFICIAL_NOTICE' AND t.external_id LIKE 'RACE-%'"
                ) == 6
                assert await connection.fetchval(
                    "SELECT max(c) FROM (SELECT count(*) c FROM tender_documents "
                    "WHERE source_document_type='OFFICIAL_NOTICE' GROUP BY tender_id) s"
                ) == 1

                # ---- an attachment at the tender's own URL never clobbers the notice ----
                async with sessions() as db:
                    tender = await db.get(Tender, tenders["N-UZ"]["id"])
                    outcome = await persist_document_descriptors(
                        db, source_system="uzex", tender=tender,
                        documents=[CanonicalDocument(
                            source_system="uzex", source_document_url=tender.source_url,
                            file_type="pdf", source_document_type="pdf",
                        )],
                    )
                    await db.commit()
                assert outcome.created_count == 1
                rows_now = await _notice_rows(connection)
                assert rows_now[tender.id]["source_document_type"] == "OFFICIAL_NOTICE"
                assert rows_now[tender.id]["file_type"] == "text/plain"
                assert await connection.fetchval(
                    "SELECT count(*) FROM tender_documents WHERE tender_id=$1", tender.id
                ) == 2

                # ---- reads and pursuit commands are passive ----
                await connection.execute(
                    "INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,description,"
                    "budget,currency,status,category) VALUES ($1,'PASSIVE-1','world_bank','world_bank:PASSIVE-1',"
                    "'https://x.test/p','passive',$2,0,'USD','OPEN','Other')",
                    (passive_id := uuid4()), "passive notice text " * 30,
                )
                organization_a = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"])
                statements.clear()
                async with sessions() as db:
                    tender = await db.get(Tender, passive_id)
                    await compose_tender_details(db, tender=tender, user_id=ids["user_a"], procurement_contacts=None)
                    resolution = await get_or_create_source_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a, tender_id=passive_id,
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=resolution.pursuit.id)
                    await db.commit()
                    summary = await tenders_endpoint._batched_tender_summaries(db=db, tender_ids=[passive_id])
                assert candidate.source_documents == [] and summary[passive_id]["document_count"] == 0
                assert _document_statements(statements, ("INSERT", "UPDATE", "DELETE")) == []
                assert await connection.fetchval(
                    "SELECT count(*) FROM tender_documents WHERE tender_id=$1", passive_id) == 0

                # ---- presentation: separate from attachment counts, no download item ----
                async with sessions() as db:
                    wb = await db.get(Tender, wb_id)
                    details = await compose_tender_details(
                        db, tender=wb, user_id=ids["user_a"], procurement_contacts=None)
                section = details.documents
                assert section.state == DetailsSectionState.AVAILABLE
                data = section.data
                assert data.items == [] and data.visible_total_count == 0 and data.omitted_unknown_count == 0
                assert data.acquisition_state == "AVAILABLE_REMOTE" and data.remote_count == 0
                assert data.official_notice is not None
                assert data.official_notice.source_url == tenders["N-WB"]["source_url"]
                assert data.official_notice.character_count == len(
                    (await _notice_rows(connection))[wb_id]["parsed_text"])
                await connection.execute(
                    "INSERT INTO tender_documents(id,tender_id,file_url,file_type,source_document_url,source_document_type,download_status) "
                    "VALUES ($1,$2,'https://x.test/a.pdf','pdf','https://x.test/a.pdf','RFP','metadata_only')", uuid4(), wb_id)
                async with sessions() as db:
                    wb = await db.get(Tender, wb_id)
                    data = (await compose_tender_details(
                        db, tender=wb, user_id=ids["user_a"], procurement_contacts=None)).documents.data
                assert data.visible_total_count == 1 and len(data.items) == 1 and data.remote_count == 1
                assert data.items[0].document_type == "RFP" and data.official_notice is not None

                # ---- legacy document surfaces ignore the notice ----
                seed_id = ids["tender"]
                await connection.execute(
                    "INSERT INTO tender_documents(id,tender_id,file_url,file_type,source_document_url,source_document_type,download_status) "
                    "VALUES ($1,$2,'https://x.test/seed.pdf','pdf','https://x.test/seed.pdf','RFP','metadata_only')", uuid4(), seed_id)
                async with sessions() as db:
                    summaries = await tenders_endpoint._batched_tender_summaries(
                        db=db, tender_ids=[tenders["N-UZ"]["id"], wb_id, seed_id])
                    listed = await tenders_endpoint.get_tender_documents(
                        seed_id, current_user=await db.get(User, ids["user_a"]), db=db)
                assert summaries[wb_id]["document_count"] == 1
                assert summaries[tenders["N-UZ"]["id"]]["document_count"] == 1
                assert summaries[seed_id]["document_count"] == 1
                assert [item.display_name for item in listed] == ["seed.pdf"]

                # ---- download endpoint: clear refusal for the notice, unchanged for files ----
                seed_notice = (await _notice_rows(connection))[seed_id]
                attachment_id = await connection.fetchval(
                    "SELECT id FROM tender_documents WHERE tender_id=$1 AND source_document_type='RFP'", seed_id)
                async with sessions() as db:
                    user = await db.get(User, ids["user_a"])
                    with pytest.raises(HTTPException) as refused:
                        await tenders_endpoint.download_document(seed_notice["id"], current_user=user, db=db)
                    with pytest.raises(HTTPException) as plain:
                        await tenders_endpoint.download_document(attachment_id, current_user=user, db=db)
                assert refused.value.status_code == 404
                assert "official notice text" in refused.value.detail.lower()
                assert "not a downloadable file" in refused.value.detail
                assert plain.value.status_code == 404 and "explicitly sync" in plain.value.detail

                # ---- acquisition workers skip the notice ----
                notice_before = (await _notice_rows(connection))[wb_id]
                tender_tasks_engine, tender_tasks_sessions = tender_tasks.engine, tender_tasks.AsyncSessionLocal
                tender_tasks.engine, tender_tasks.AsyncSessionLocal = worker_engine, worker_sessions
                try:
                    skipped = await tender_tasks._enrich_adb_document_async(
                        notice_before["id"], expected_external_file_id="none",
                        expected_source_url="https://example.test/adb", delivery_id="d1-03")
                finally:
                    tender_tasks.engine, tender_tasks.AsyncSessionLocal = tender_tasks_engine, tender_tasks_sessions
                assert skipped["status"] == "skipped_official_notice"
                assert (await _notice_rows(connection))[wb_id]["xmin"] == notice_before["xmin"]

                # ---- no organization data reaches the shared row ----
                for row in (await _notice_rows(connection)).values():
                    for private_marker in ("Same Name Company", "SAME-TEXT", "same-domain.invalid"):
                        assert private_marker not in row["parsed_text"]

                # ---- World Bank project and leadership rows are byte-identical ----
                preserved_after = {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leader", "project_role_assignments", ids["current_leader"]),
                        ("legacy_analysis", "tender_analyses", ids["analysis"]),
                        ("legacy_version", "analysis_versions", ids["analysis_version"]),
                    )
                }
                assert preserved_after == preserved_before
            finally:
                await connection.close()
                await worker_engine.dispose()

    asyncio.run(scenario())


def test_backfill_is_idempotent_reports_per_source_and_only_covers_open_by_default(monkeypatch) -> None:
    async def scenario() -> None:
        async with _database("d1_03_backfill", seed=False) as (database, _ids, sessions, _engine):
            monkeypatch.setattr(backfill_module, "AsyncSessionLocal", sessions)
            connection = await support.database_connection(database)
            try:
                spec = (
                    ("world_bank", "OPEN", 3, "wb notice text " * 40),
                    ("ebrd", "OPEN", 2, "ebrd notice text " * 40),
                    ("giz", "OPEN", 1, "giz notice text " * 40),
                    ("uzex", "OPEN", 2, ""),
                    ("adb", "OPEN", 1, "short"),
                    ("world_bank", "CLOSED", 2, "closed notice text " * 40),
                )
                for source, status_value, count, description in spec:
                    for n in range(count):
                        await connection.execute(
                            "INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,"
                            "description,budget,currency,status,category) VALUES ($1,$2,$3,$4,'https://x.test/b',$5,$6,0,'USD',$7,'Other')",
                            uuid4(), f"{status_value}-{n}", source, f"{source}:{status_value}-{n}",
                            f"{source} {n}", description, status_value,
                        )

                async def run(**kwargs):
                    return await backfill_module.backfill(
                        sources=[], include_closed=False, batch_size=2, **kwargs)

                report = await run(apply=False)
                assert report["mode"] == "report-only"
                assert (await connection.fetchval("SELECT count(*) FROM tender_documents")) == 0
                assert report["sources"]["world_bank"]["created"] == 3
                assert report["sources"]["world_bank"]["with_notice_document_now"] == 0

                report = await run(apply=True)
                assert {s: v["created"] for s, v in report["sources"].items()} == {
                    "world_bank": 3, "ebrd": 2, "giz": 1, "uzex": 0, "adb": 0}
                assert {s: v["with_notice_document_now"] for s, v in report["sources"].items()} == {
                    "world_bank": 3, "ebrd": 2, "giz": 1, "uzex": 0, "adb": 0}
                assert report["sources"]["uzex"]["below_threshold_or_empty"] == 2
                assert report["sources"]["adb"]["below_threshold_or_empty"] == 1
                first = await _notice_rows(connection)
                assert len(first) == 6  # the two CLOSED World Bank tenders are not covered

                report = await run(apply=True)  # re-run: nothing created, nothing rewritten
                assert sum(v["created"] + v["updated"] for v in report["sources"].values()) == 0
                assert sum(v["unchanged"] for v in report["sources"].values()) == 6
                second = await _notice_rows(connection)
                assert {k: v["xmin"] for k, v in second.items()} == {k: v["xmin"] for k, v in first.items()}

                closed = await backfill_module.backfill(
                    apply=True, sources=["world_bank"], include_closed=True, batch_size=200)
                assert closed["sources"]["world_bank"]["created"] == 2
                assert len(await _notice_rows(connection)) == 8
                assert "OPEN" not in backfill_module.render(closed).split("\n")[0]
            finally:
                await connection.close()

    asyncio.run(scenario())
    assert asyncio.run(backfill_module.main(["--apply"])) == 2
    assert asyncio.run(backfill_module.main(["--batch-size", "0"])) == 2


def test_pack_candidate_seals_the_notice_and_sealed_packs_stay_immutable(monkeypatch) -> None:
    async def scenario() -> None:
        async with _database("d1_03_pack") as (database, ids, sessions, engine):
            connection = await support.database_connection(database)
            try:
                organization_a = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"])

                criterion = "Interested firms must demonstrate at least three similar assignments."
                original_html = f"<p>REQUEST FOR EXPRESSIONS OF INTEREST</p><p>{criterion}</p>" + _long_notice("Original")
                # The seeded tender is short; a source refresh gives it a substantive notice.
                async with sessions() as db:
                    await persist_tender_batch(db, [NormalizedTender(
                        source_system="world_bank", external_id="WB-W2-1",
                        source_url="https://example.invalid/w2-source", title="W2 Source Tender",
                        description=clean_notice_html(original_html), budget=125000.0, currency="USD",
                        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), status=TenderStatus.OPEN,
                        category="Services", notice_type="Request for Expression of Interest",
                        buyer="Ministry of Energy, Mongolia", country="Mongolia",
                        source_metadata_json={"contact_name": "Procurement Contact", "teamleadname": "Literal Leader",
                                              "notice_text": original_html},
                    )])
                    await db.commit()
                notice_row = (await _notice_rows(connection))[ids["tender"]]

                async with sessions() as db:
                    pursuit = (await get_or_create_source_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a, tender_id=ids["tender"],
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )).pursuit
                    candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=pursuit.id)
                    assert len(candidate.source_documents) == 1 and candidate.private_versions == []
                    item = candidate.source_documents[0]
                    assert item.tender_document_id == notice_row["id"]
                    assert item.display_name == OFFICIAL_NOTICE_DISPLAY_NAME == "Official notice text"
                    assert item.role == "OFFICIAL_NOTICE" and item.file_type == "text/plain"
                    assert item.parse_ready and candidate.parse_ready
                    assert item.page_count_known is False and candidate.page_count_total is None
                    assert item.source_url == "https://example.invalid/w2-source"
                    assert item.extracted_character_count == len(notice_row["parsed_text"])
                    assert item.content_sha256 == notice_row["sha256"]

                    # A no-op refresh leaves the candidate hash alone.
                    async with sessions() as other:
                        await persist_tender_batch(other, [NormalizedTender(
                            source_system="world_bank", external_id="WB-W2-1",
                            source_url="https://example.invalid/w2-source", title="W2 Source Tender",
                            description=clean_notice_html(original_html), budget=125000.0, currency="USD",
                            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), status=TenderStatus.OPEN,
                            category="Services", notice_type="Request for Expression of Interest",
                            buyer="Ministry of Energy, Mongolia", country="Mongolia",
                            source_metadata_json={"contact_name": "Procurement Contact", "teamleadname": "Literal Leader",
                                                  "notice_text": original_html},
                        )])
                        await other.commit()
                    repeat = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=pursuit.id)
                    assert repeat.candidate_sha256 == candidate.candidate_sha256

                    started = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                            source_document_ids=[item.tender_document_id]),
                    )
                    assert started.page_count_known is False
                    sealed = await db.scalar(select(AnalysisPackItem).where(
                        AnalysisPackItem.pack_id == started.analysis_pack_id))
                    assert sealed is not None
                    assert sealed.analyzed_text == notice_row["parsed_text"]
                    assert sealed.provenance == "SHARED_SOURCE" and sealed.role == "OFFICIAL_NOTICE"
                    assert sealed.locator_type == "PARAGRAPH" and sealed.page_count_known is False
                    sealed_text, sealed_id = sealed.analyzed_text, sealed.id
                    # The real connector stores the notice on one line; the raw HTML in
                    # its payload restores paragraphs and lists for the sealed text.
                    assert "\n- Shortlisting criteria A\n- Criteria B" in sealed_text
                    assert "\n\n" in sealed_text.split(BODY_OPEN, 1)[1]

                    async def extracted(sealed_items, language):
                        pack_item = sealed_items[0]
                        start = pack_item.text.index(criterion)
                        return [VerifiedFact(pack_item.pack_item_id, ExtractedFact(
                            kind="CORPORATE_REQUIREMENT", original_quote=criterion,
                            normalized_text="At least three similar assignments", category="EXPERIENCE",
                            requirement_type="CORPORATE_EXPERIENCE", stage_scope="ELIGIBILITY",
                            distinction="MANDATORY",
                            predicate=NumericPredicate(operator=">=", threshold=3, unit="assignments"),
                            confidence=0.9,
                        ), start, start + len(criterion), None, 2)]

                    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
                    await process_analysis_run(db, started.analysis_run_id, worker_id="d1-03-worker")
                    run = await db.get(AnalysisRun, started.analysis_run_id)
                    assert run is not None and run.status == "COMPLETED"
                    requirement = await db.scalar(select(PursuitRequirement).where(
                        PursuitRequirement.analysis_run_id == started.analysis_run_id))
                    assert requirement is not None and requirement.original_quote == criterion
                    fresh = await get_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, run_id=started.analysis_run_id)
                    assert fresh is not None and fresh.inputs_changed is False

                # The source amends the notice: shared row updates, the sealed copy does not.
                amended_html = original_html + "<p>Addendum 1: the submission date is extended.</p>"
                async with sessions() as db:
                    await persist_tender_batch(db, [NormalizedTender(
                        source_system="world_bank", external_id="WB-W2-1",
                        source_url="https://example.invalid/w2-source", title="W2 Source Tender",
                        description=clean_notice_html(amended_html), budget=125000.0, currency="USD",
                        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), status=TenderStatus.OPEN,
                        category="Services", notice_type="Request for Expression of Interest",
                        buyer="Ministry of Energy, Mongolia", country="Mongolia",
                        source_metadata_json={"notice_text": amended_html},
                    )])
                    await db.commit()
                amended_row = (await _notice_rows(connection))[ids["tender"]]
                assert amended_row["id"] == notice_row["id"] and amended_row["sha256"] != notice_row["sha256"]
                assert "Addendum 1" in amended_row["parsed_text"]

                async with sessions() as db:
                    still = await db.get(AnalysisPackItem, sealed_id)
                    assert still is not None and still.analyzed_text == sealed_text
                    assert "Addendum 1" not in still.analyzed_text
                    stale = await get_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, run_id=started.analysis_run_id)
                    assert stale is not None and stale.inputs_changed is True
                    assert "differ" in (stale.stale_reason or "")
                    newer = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=pursuit.id)
                    assert newer.candidate_sha256 != candidate.candidate_sha256
                    assert newer.source_documents[0].content_sha256 == amended_row["sha256"]
                    with pytest.raises(AnalysisAdmissionError, match="changed after review"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                                source_document_ids=[item.tender_document_id]),
                        )
                    rerun = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=newer.candidate_sha256, analysis_language="en",
                            source_document_ids=[item.tender_document_id]),
                    )
                    reseal = await db.scalar(select(AnalysisPackItem).where(
                        AnalysisPackItem.pack_id == rerun.analysis_pack_id))
                    assert reseal is not None and "Addendum 1" in reseal.analyzed_text
                    assert await db.scalar(select(func.count(AnalysisPackItem.id)).where(
                        AnalysisPackItem.tender_document_id == notice_row["id"])) == 2
                # Sealed packs restrict deletion of the shared row they were built from.
                with pytest.raises(Exception, match="(?i)foreign key|restrict|violates"):
                    await connection.execute("DELETE FROM tender_documents WHERE id=$1", notice_row["id"])
            finally:
                await connection.close()

    asyncio.run(scenario())
