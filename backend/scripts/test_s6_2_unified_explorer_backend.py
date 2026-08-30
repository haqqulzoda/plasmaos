#!/usr/bin/env python3
"""Disposable PostgreSQL 16 proof for Sprint 6.2 unified Explorer semantics."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.explorer import ExplorerView
from app.services.explorer import ExplorerQuery, list_explorer_tenders
from app.services.recommendations import (
    RecommendationNotFoundError,
    dismiss_recommendation,
    restore_recommendation,
)
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"
TENDER_COUNT = 10_000
RECOMMENDATION_COUNT = 20_000


async def seed_owner(
    connection: asyncpg.Connection,
    label: str,
    *,
    with_profile: bool = True,
) -> tuple[UUID, UUID | None]:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id,google_id,email,name,subscription_tier,is_admin,
            approval_status,platform_role,auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',false,'approved','pilot_user',0)
        """,
        user_id,
        f"s62-{label}-{user_id}",
        f"{label}-{user_id}@s62.invalid",
        label,
    )
    if not with_profile:
        return user_id, None
    profile_id = uuid4()
    await connection.execute(
        """
        INSERT INTO company_profiles (
            id,user_id,company_name,pilot_status,approval_status
        ) VALUES ($1,$2,'Acme Engineering','active_pilot','approved')
        """,
        profile_id,
        user_id,
    )
    return user_id, profile_id


async def seed_scale(
    connection: asyncpg.Connection,
) -> dict[str, Any]:
    user_a, profile_a = await seed_owner(connection, "tenant-a")
    user_b, profile_b = await seed_owner(connection, "tenant-b")
    no_profile_user, _ = await seed_owner(
        connection,
        "no-profile",
        with_profile=False,
    )
    assert profile_a is not None and profile_b is not None

    base_time = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    tender_ids = [uuid4() for _ in range(TENDER_COUNT)]
    tender_rows = []
    for index, tender_id in enumerate(tender_ids):
        source = "world_bank" if index % 2 == 0 else "giz"
        country = "Uzbekistan" if index % 2 == 0 else "Kazakhstan"
        service = "Construction" if index % 2 == 0 else "IT"
        source_status = (
            "CLOSED" if index == 0 else "CANCELLED" if index == 1 else "OPEN"
        )
        tender_rows.append(
            (
                tender_id,
                f"S62-{index:05d}",
                source,
                f"{source}:s62:{index:05d}",
                f"https://example.invalid/s62/{index}",
                f"Scale Tender {index:05d} {service}",
                f"{service} procurement in {country}",
                float(1_000 + index),
                "USD",
                base_time + timedelta(days=30 + index % 30),
                base_time - timedelta(days=index % 60),
                country,
                "Central Asia",
                service,
                f"Buyer {index % 25}",
                service,
                source_status,
                service,
                base_time,
            )
        )
    await connection.copy_records_to_table(
        "tenders",
        records=tender_rows,
        columns=(
            "id",
            "external_id",
            "source_system",
            "canonical_source_key",
            "source_url",
            "title",
            "description",
            "budget",
            "currency",
            "deadline",
            "publication_date",
            "country",
            "region",
            "sector",
            "buyer",
            "procurement_category",
            "status",
            "category",
            "created_at",
        ),
    )

    recommendation_rows = []
    recommendation_ids_a: list[UUID] = []
    recommendation_ids_b: list[UUID] = []
    for index, tender_id in enumerate(tender_ids):
        recommendation_a = uuid4()
        recommendation_b = uuid4()
        recommendation_ids_a.append(recommendation_a)
        recommendation_ids_b.append(recommendation_b)
        recommendation_rows.extend(
            (
                (
                    recommendation_a,
                    tender_id,
                    profile_a,
                    50,
                    f"Tenant A rationale {index} " + ("界" * 300),
                    index % 4 == 0,
                    base_time,
                ),
                (
                    recommendation_b,
                    tender_id,
                    profile_b,
                    43,
                    f"Tenant B rationale {index}",
                    False,
                    base_time,
                ),
            )
        )
    await connection.copy_records_to_table(
        "tender_recommendations",
        records=recommendation_rows,
        columns=(
            "id",
            "tender_id",
            "company_profile_id",
            "match_score",
            "strategic_rationale",
            "is_dismissed",
            "created_at",
        ),
    )

    document_rows = []
    for index in range(200):
        document_rows.append(
            (
                uuid4(),
                tender_ids[index],
                f"https://example.invalid/s62/docs/{index}.pdf",
                "pdf",
                "metadata_only",
                None,
            )
        )
    for index in range(200, 280):
        document_rows.append(
            (
                uuid4(),
                tender_ids[index],
                f"https://example.invalid/s62/docs/{index}.pdf",
                "pdf",
                "downloaded",
                f"/definitely/missing/s62/{index}.pdf",
            )
        )
    await connection.copy_records_to_table(
        "tender_documents",
        records=document_rows,
        columns=(
            "id",
            "tender_id",
            "file_url",
            "file_type",
            "download_status",
            "storage_path",
        ),
    )

    engagement_rows = []
    states = ("SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED")
    engagement_indexes = (2, 3, 5, 6, 7, 9, 10)
    for index, engagement_status in zip(engagement_indexes, states, strict=True):
        engagement_rows.append(
            (
                uuid4(),
                user_a,
                profile_a,
                tender_ids[index],
                engagement_status,
                "MANUAL_SAVE",
                base_time,
                base_time,
                base_time,
            )
        )
    await connection.copy_records_to_table(
        "tender_engagements",
        records=engagement_rows,
        columns=(
            "id",
            "user_id",
            "company_profile_id",
            "tender_id",
            "status",
            "origin",
            "created_at",
            "updated_at",
            "status_changed_at",
        ),
    )
    return {
        "user_a": user_a,
        "profile_a": profile_a,
        "user_b": user_b,
        "profile_b": profile_b,
        "no_profile_user": no_profile_user,
        "tender_ids": tender_ids,
        "recommendation_ids_a": recommendation_ids_a,
    }


async def fingerprints(connection: asyncpg.Connection) -> dict[str, str]:
    tables = (
        "tenders",
        "tender_recommendations",
        "tender_engagements",
        "proposals",
        "tender_analyses",
        "analysis_versions",
    )
    result: dict[str, str] = {}
    for table in tables:
        result[table] = await connection.fetchval(
            f"SELECT md5(coalesce(string_agg(to_jsonb(t)::text, '' ORDER BY id), '')) FROM {table} t"
        )
    return result


async def timed(coro: Awaitable[Any]) -> tuple[Any, float]:
    started = monotonic()
    value = await coro
    return value, round((monotonic() - started) * 1_000, 2)


async def scenario(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
        seeded = await seed_scale(connection)
        assert await connection.fetchval("SELECT count(*) FROM tenders") == TENDER_COUNT
        assert (
            await connection.fetchval("SELECT count(*) FROM tender_recommendations")
            == RECOMMENDATION_COUNT
        )
        before_reads = await fingerprints(connection)
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=16, max_overflow=8)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_a: UUID = seeded["user_a"]
    user_b: UUID = seeded["user_b"]
    profile_a: UUID = seeded["profile_a"]
    target_recommendation: UUID = seeded["recommendation_ids_a"][2]

    async def read(user_id: UUID, query: ExplorerQuery):
        async with sessions() as session:
            return await list_explorer_tenders(session, user_id=user_id, query=query)

    performance: dict[str, float] = {}
    responses = {}
    for view in ExplorerView:
        response, runtime_ms = await timed(
            read(
                user_a,
                ExplorerQuery(view=view, tender_status="all", limit=25),
            )
        )
        responses[view.value] = response
        performance[view.value] = runtime_ms
        assert response.total == {
            "all": 10_000,
            "recommended": 7_500,
            "dismissed": 2_500,
        }[view.value]
        assert len(response.items) == 25
        assert len({item.tender.id for item in response.items}) == 25
        assert response.total == {
            "all": response.counts.all_tenders,
            "recommended": response.counts.active_recommendations,
            "dismissed": response.counts.dismissed_recommendations,
        }[view.value]

    # All exposes both active and dismissed owned overlay; rationale is bounded.
    all_response = responses["all"]
    assert all(item.recommendation is not None for item in all_response.items)
    assert any(item.recommendation.is_dismissed for item in all_response.items)
    assert max(len(item.recommendation.rationale_summary) for item in all_response.items) == 280
    engaged_response = await read(
        user_a,
        ExplorerQuery(q="Scale Tender 00002", tender_status="all"),
    )
    assert engaged_response.items[0].pursuit is not None

    pursuit_states = set()
    for tender_index in (2, 3, 5, 6, 7, 9, 10):
        coexistence = await read(
            user_a,
            ExplorerQuery(
                view=ExplorerView.RECOMMENDED,
                q=f"Scale Tender {tender_index:05d}",
                tender_status="all",
            ),
        )
        assert coexistence.total == 1
        pursuit_states.add(coexistence.items[0].pursuit.status.value)
    assert pursuit_states == {"SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED"}

    # No-profile discovery remains global while private modes are truthful empties.
    no_profile_all = await read(
        seeded["no_profile_user"],
        ExplorerQuery(view=ExplorerView.ALL, tender_status="all", limit=1),
    )
    no_profile_recommended = await read(
        seeded["no_profile_user"],
        ExplorerQuery(view=ExplorerView.RECOMMENDED, tender_status="all", limit=1),
    )
    assert no_profile_all.total == TENDER_COUNT
    assert no_profile_all.recommendation_availability.value == "PROFILE_REQUIRED"
    assert no_profile_all.items[0].recommendation is None
    assert no_profile_recommended.total == 0 and not no_profile_recommended.items

    # Same-name tenant UUID authority returns only each owner's advisory data.
    tenant_a = await read(
        user_a,
        ExplorerQuery(view=ExplorerView.ALL, q="Scale Tender 00002", tender_status="all"),
    )
    tenant_b = await read(
        user_b,
        ExplorerQuery(view=ExplorerView.ALL, q="Scale Tender 00002", tender_status="all"),
    )
    assert tenant_a.items[0].recommendation.match_score == 50
    assert tenant_a.items[0].recommendation.rationale_summary.startswith("Tenant A")
    assert tenant_b.items[0].recommendation.match_score == 43
    assert tenant_b.items[0].recommendation.rationale_summary.startswith("Tenant B")

    # Filter/count matrix reuses one pre-pagination universe.
    filter_matrix = {
        "search": ExplorerQuery(q="Scale Tender 00999", tender_status="all"),
        "source": ExplorerQuery(source="world_bank", tender_status="all"),
        "source_status": ExplorerQuery(tender_status="closed"),
        "deadline": ExplorerQuery(deadline_from=datetime(2026, 9, 28, tzinfo=timezone.utc), tender_status="all"),
        "document": ExplorerQuery(document_status="metadata_only", tender_status="all"),
        "category_service": ExplorerQuery(service="construction", tender_status="all"),
        "geography": ExplorerQuery(country="Uzbekistan", tender_status="all"),
        "price": ExplorerQuery(price_min=10_999, tender_status="all"),
    }
    matrix_counts: dict[str, int] = {}
    for label, query in filter_matrix.items():
        response = await read(user_a, query)
        assert response.total == response.counts.all_tenders
        assert len(response.items) <= response.total
        matrix_counts[label] = response.total
    assert matrix_counts["search"] == 1
    assert matrix_counts["source"] == 5_000
    assert matrix_counts["source_status"] == 1
    assert matrix_counts["document"] == 200
    assert matrix_counts["category_service"] == 5_000
    assert matrix_counts["geography"] == 5_000
    assert matrix_counts["price"] == 1

    pagination_lengths: dict[int, int] = {}
    for boundary in (1, 24, 25, 26, 99, 100):
        page = await read(
            user_a,
            ExplorerQuery(tender_status="all", limit=boundary),
        )
        assert page.total == TENDER_COUNT
        assert len(page.items) == boundary
        assert len({item.tender.id for item in page.items}) == boundary
        pagination_lengths[boundary] = len(page.items)
    empty_page = await read(
        user_a,
        ExplorerQuery(tender_status="all", limit=25, offset=TENDER_COUNT),
    )
    assert empty_page.total == TENDER_COUNT and not empty_page.items

    files_missing, files_runtime = await timed(
        read(
            user_a,
            ExplorerQuery(
                document_status="files_missing",
                tender_status="all",
                limit=25,
            ),
        )
    )
    performance["files_missing"] = files_runtime
    assert files_missing.total == 80
    assert len(files_missing.items) == 25
    assert all(item.tender.document_status == "files_missing" for item in files_missing.items)

    # Stable equal-score/time ordering across page boundaries.
    page_1 = await read(
        user_a,
        ExplorerQuery(view=ExplorerView.RECOMMENDED, tender_status="all", limit=100, offset=0),
    )
    page_2 = await read(
        user_a,
        ExplorerQuery(view=ExplorerView.RECOMMENDED, tender_status="all", limit=100, offset=100),
    )
    ids = [item.recommendation.recommendation_id for item in page_1.items + page_2.items]
    assert len(ids) == 200 and len(set(ids)) == 200
    assert ids == sorted(ids, key=str)

    # Fixed SQL query counts, independent of returned row count (no N+1).
    query_counts: dict[str, int] = {}
    for view in ExplorerView:
        counter = 0

        def before_cursor_execute(*_args):
            nonlocal counter
            counter += 1

        event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        try:
            await read(
                user_a,
                ExplorerQuery(view=view, tender_status="all", limit=25),
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        query_counts[view.value] = counter
        assert counter == 5
    counter = 0

    def before_files_cursor_execute(*_args):
        nonlocal counter
        counter += 1

    event.listen(engine.sync_engine, "before_cursor_execute", before_files_cursor_execute)
    try:
        await read(
            user_a,
            ExplorerQuery(document_status="files_missing", tender_status="all", limit=25),
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_files_cursor_execute)
    query_counts["files_missing"] = counter
    assert counter == 8

    # Ten concurrent reads return the same stable first page without session reuse.
    concurrent_pages = await asyncio.gather(
        *(
            read(
                user_a,
                ExplorerQuery(view=ExplorerView.RECOMMENDED, tender_status="all", limit=25),
            )
            for _ in range(10)
        )
    )
    reference_ids = [item.tender.id for item in concurrent_pages[0].items]
    assert all([item.tender.id for item in page.items] == reference_ids for page in concurrent_pages)

    connection = await support.database_connection(database)
    try:
        after_passive_reads = await fingerprints(connection)
        assert after_passive_reads == before_reads
    finally:
        await connection.close()

    async def transact(command: Callable[..., Awaitable[Any]], *, user_id: UUID = user_a):
        async with sessions() as session:
            async with session.begin():
                return await command(
                    session,
                    recommendation_id=target_recommendation,
                    user_id=user_id,
                )

    # Foreign UUID knowledge is anti-enumeration not-found.
    try:
        await transact(dismiss_recommendation, user_id=user_b)
    except RecommendationNotFoundError:
        foreign_result = "not_found"
    else:
        raise AssertionError("foreign Recommendation mutation succeeded")

    connection = await support.database_connection(database)
    try:
        immutable_before = await connection.fetchrow(
            """
            SELECT match_score, strategic_rationale, created_at
            FROM tender_recommendations WHERE id=$1
            """,
            target_recommendation,
        )
    finally:
        await connection.close()

    # Same-command and opposing-command races serialize on one row.
    assert not any(
        isinstance(result, Exception)
        for result in await asyncio.gather(
            transact(dismiss_recommendation),
            transact(dismiss_recommendation),
            return_exceptions=True,
        )
    )
    assert not any(
        isinstance(result, Exception)
        for result in await asyncio.gather(
            transact(restore_recommendation),
            transact(restore_recommendation),
            return_exceptions=True,
        )
    )
    opposing = await asyncio.gather(
        transact(dismiss_recommendation),
        transact(restore_recommendation),
        return_exceptions=True,
    )
    assert not any(isinstance(result, Exception) for result in opposing)

    tenant_b_after_a_commands = await read(
        user_b,
        ExplorerQuery(
            view=ExplorerView.RECOMMENDED,
            q="Scale Tender 00002",
            tender_status="all",
        ),
    )
    assert tenant_b_after_a_commands.total == 1
    assert tenant_b_after_a_commands.items[0].recommendation.match_score == 43

    connection = await support.database_connection(database)
    try:
        row = await connection.fetchrow(
            """
            SELECT match_score, strategic_rationale, created_at, is_dismissed
            FROM tender_recommendations WHERE id=$1
            """,
            target_recommendation,
        )
        assert tuple(row[:3]) == tuple(immutable_before)
        assert isinstance(row["is_dismissed"], bool)
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM tender_recommendations WHERE tender_id=$1 AND company_profile_id=$2",
                seeded["tender_ids"][2],
                profile_a,
            )
            == 1
        )
        explain_rows = await connection.fetch(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
            SELECT r.id
            FROM tender_recommendations r
            JOIN tenders t ON t.id = r.tender_id
            WHERE r.company_profile_id=$1 AND r.is_dismissed=false
            ORDER BY r.match_score DESC, r.created_at DESC, r.id ASC
            LIMIT 25
            """,
            profile_a,
        )
        explain = "\n".join(record[0] for record in explain_rows)
        index_names = {
            row["indexname"]
            for row in await connection.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename='tender_recommendations'"
            )
        }
    finally:
        await connection.close()

    # Read during an explicit dismiss sees a valid before/after committed page.
    await transact(restore_recommendation)
    read_result, mutation_result = await asyncio.gather(
        read(
            user_a,
            ExplorerQuery(view=ExplorerView.RECOMMENDED, tender_status="all", limit=100),
        ),
        transact(dismiss_recommendation),
    )
    assert mutation_result.is_dismissed is True
    assert len({item.tender.id for item in read_result.items}) == len(read_result.items)
    assert read_result.total >= len(read_result.items)

    connection = await support.database_connection(database)
    try:
        after_reads_and_commands = await fingerprints(connection)
        # Explicit commands may change only the Recommendation dismissal fingerprint.
        for table in before_reads:
            if table != "tender_recommendations":
                assert after_reads_and_commands[table] == before_reads[table]
        assert await connection.fetchval("SELECT count(*) FROM proposals") == 0
        assert await connection.fetchval("SELECT count(*) FROM tender_analyses") == 0
        assert await connection.fetchval("SELECT count(*) FROM analysis_versions") == 0
        assert await connection.fetchval("SELECT count(*) FROM tender_recommendations") == RECOMMENDATION_COUNT
    finally:
        await connection.close()

    check = await asyncio.to_thread(support.alembic, database, "check", success=False)
    assert check.returncode == 0, check.stderr or check.stdout
    await engine.dispose()
    return {
        "head": HEAD,
        "tenders": TENDER_COUNT,
        "recommendations": RECOMMENDATION_COUNT,
        "totals": {view: response.total for view, response in responses.items()},
        "query_counts": query_counts,
        "pagination_lengths": pagination_lengths,
        "performance_ms": performance,
        "filter_counts": matrix_counts,
        "files_missing": files_missing.total,
        "concurrent_reads": len(concurrent_pages),
        "mutation_concurrency": "serialized",
        "foreign_mutation": foreign_result,
        "explain": explain.splitlines()[:8],
        "recommendation_indexes": sorted(index_names),
        "index_migration": "not justified",
        "alembic_check": "clean",
    }


async def main() -> int:
    database = support.database_name("s62_explorer")
    await support.create_database(database)
    try:
        result = await scenario(database)
        print(json.dumps({"status": "ok", **result}, sort_keys=True))
        return 0
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
