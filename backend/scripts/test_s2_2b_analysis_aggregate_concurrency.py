#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for Sprint 2.2B aggregate identity."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.all_models import AnalysisVersion, TenderAnalysis
from app.models.audit import ANALYSIS_OWNERSHIP_OWNED
from app.services.analysis_aggregates import resolve_or_create_analysis_aggregate
from app.services.analysis_versions import append_analysis_version
from scripts.report_analysis_aggregate_concurrency import AGGREGATE_AUDIT_SQL
from scripts import test_s0_5b4_baseline as support
from scripts import test_s2_2_analysis_version_foundation as s22


S2_1_HEAD = "20260827_0001_s2_1_compliance_ownership"
HEAD = "20260827_0002_s2_2_analysis_version_foundation"


async def revision(database: str) -> str:
    connection = await support.database_connection(database)
    try:
        return str(await connection.fetchval("SELECT version_num FROM alembic_version"))
    finally:
        await connection.close()


async def add_tender(
    database: str,
    *,
    label: str,
    user_id: UUID | None = None,
) -> tuple[UUID, UUID | None]:
    tender_id = uuid4()
    proposal_id = uuid4() if user_id is not None else None
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            """
            INSERT INTO tenders (
                id, external_id, source_url, title, budget, currency, status,
                category, source_system, canonical_source_key,
                source_metadata_json, scrape_status, compiled_master_text
            ) VALUES (
                $1, $2, $3, $4, 1000, 'USD', 'OPEN', 'Test', 'world_bank',
                $5, '{}'::json, 'success', $6
            )
            """,
            tender_id,
            f"S22B-{label}",
            f"https://example.test/{label}",
            f"Sprint 2.2B {label}",
            f"world_bank:S22B-{label}",
            f"controlled tender text {label}",
        )
        if proposal_id is not None:
            await connection.execute(
                """
                INSERT INTO proposals (
                    id, user_id, tender_id, status, ai_confidence_score,
                    structured_data, margin_percent, include_vat, currency
                ) VALUES (
                    $1, $2, $3, 'DRAFT', 75, '{}'::json, 10, true, 'USD'
                )
                """,
                proposal_id,
                user_id,
                tender_id,
            )
    finally:
        await connection.close()
    return tender_id, proposal_id


def new_parent(
    *,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
    label: str,
    content_hash: str,
) -> TenderAnalysis:
    payload = {
        "analysis_status": "completed",
        "label": label,
        "evaluation": {"is_compliant": True},
        "evidence_validation": {"accepted": []},
    }
    return TenderAnalysis(
        tender_id=tender_id,
        tender_file_name=f"{label}.pdf",
        user_id=user_id,
        company_profile_id=profile_id,
        ownership_state=ANALYSIS_OWNERSHIP_OWNED,
        company_name="Acme Engineering",
        raw_extracted_text=f"text-{label}",
        analysis_json=payload,
        content_hash=content_hash,
    )


def version_values(
    *,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
    label: str,
    content_hash: str,
) -> dict[str, Any]:
    result = {
        "analysis_status": "completed",
        "label": label,
        "evaluation": {"is_compliant": True},
        "evidence_validation": {"accepted": []},
    }
    return {
        "requested_by_user_id": user_id,
        "company_profile_id": profile_id,
        "status": "COMPLETED",
        "analysis_schema_version": "s2.2b-test",
        "model_provider": "controlled",
        "model_name": "controlled-model",
        "model_version": None,
        "prompt_template_version": "s2.2b-test",
        "prompt_template_hash": "d" * 64,
        "provenance_snapshot": {
            "requirement_extractor": {
                "model_name": "controlled-model",
                "prompt_template_hash": "d" * 64,
            }
        },
        "tender_snapshot": {"tender_id": str(tender_id)},
        "company_snapshot": {
            "company_profile_id": str(profile_id),
            "company_name": "Acme Engineering",
        },
        "result_snapshot": result,
        "evidence_snapshot": {"evidence_validation": {"accepted": []}},
        "input_hash": content_hash,
        "documents": [],
        "completed_at": datetime.now(timezone.utc),
    }


async def persist_analysis(
    sessions: async_sessionmaker,
    *,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
    label: str,
    content_hash: str,
    force: bool = False,
    ready: asyncio.Barrier | None = None,
    fail_before_commit: bool = False,
) -> dict[str, Any]:
    async with sessions() as db:
        if ready is not None:
            await ready.wait()
        candidate = new_parent(
            user_id=user_id,
            profile_id=profile_id,
            tender_id=tender_id,
            label=label,
            content_hash=content_hash,
        )
        resolution = await resolve_or_create_analysis_aggregate(
            db,
            user_id=user_id,
            company_profile_id=profile_id,
            tender_id=tender_id,
            new_parent=candidate,
        )
        parent = resolution.analysis
        if not resolution.created and not force and parent.content_hash == content_hash:
            parent_id = parent.id
            await db.rollback()
            return {
                "analysis_id": parent_id,
                "outcome": "cached",
                "version_number": None,
                "existing_parent_count": resolution.existing_parent_count,
            }
        version = await append_analysis_version(
            db,
            analysis_id=parent.id,
            **version_values(
                user_id=user_id,
                profile_id=profile_id,
                tender_id=tender_id,
                label=label,
                content_hash=content_hash,
            ),
        )
        parent.tender_file_name = f"{label}.pdf"
        parent.company_name = "Acme Engineering"
        parent.raw_extracted_text = f"text-{label}"
        parent.analysis_json = {"analysis_status": "completed", "label": label}
        parent.content_hash = content_hash
        if fail_before_commit:
            await db.rollback()
            raise RuntimeError("controlled persistence failure")
        await db.commit()
        return {
            "analysis_id": parent.id,
            "outcome": "created" if resolution.created else "appended",
            "version_number": version.version_number,
            "existing_parent_count": resolution.existing_parent_count,
        }


async def parent_and_versions(
    sessions: async_sessionmaker,
    *,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
) -> tuple[list[UUID], dict[UUID, list[int]]]:
    async with sessions() as db:
        parents = list(
            (
                await db.execute(
                    select(TenderAnalysis.id)
                    .where(
                        TenderAnalysis.user_id == user_id,
                        TenderAnalysis.company_profile_id == profile_id,
                        TenderAnalysis.tender_id == tender_id,
                        TenderAnalysis.ownership_state == ANALYSIS_OWNERSHIP_OWNED,
                    )
                    .order_by(TenderAnalysis.id)
                )
            ).scalars()
        )
        versions: dict[UUID, list[int]] = {}
        for parent_id in parents:
            versions[parent_id] = list(
                (
                    await db.execute(
                        select(AnalysisVersion.version_number)
                        .where(AnalysisVersion.analysis_id == parent_id)
                        .order_by(AnalysisVersion.version_number)
                    )
                ).scalars()
            )
        return parents, versions


async def historical_snapshot(database: str) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        queries = {
            "parents": """
                SELECT id::text, tender_id::text, user_id::text,
                       company_profile_id::text, ownership_state, company_name,
                       analysis_json::text, content_hash, override_seal, created_at
                FROM tender_analyses ORDER BY id
            """,
            "versions": """
                SELECT id::text, analysis_id::text, version_number,
                       supersedes_version_id::text, result_snapshot::text,
                       evidence_snapshot::text, input_hash, output_hash,
                       evidence_hash, document_set_hash, version_hash
                FROM analysis_versions ORDER BY id
            """,
            "documents": """
                SELECT id::text, analysis_version_id::text,
                       tender_document_id::text, snapshot_metadata::text
                FROM analysis_version_document_snapshots ORDER BY id
            """,
            "overrides": """
                SELECT id::text, analysis_id::text, state_hash, justification
                FROM risk_override_logs ORDER BY id
            """,
            "proposals": """
                SELECT id::text, user_id::text, tender_id::text,
                       structured_data::text FROM proposals ORDER BY id
            """,
            "recommendations": """
                SELECT id::text, tender_id::text, company_profile_id::text,
                       match_score, strategic_rationale
                FROM tender_recommendations ORDER BY id
            """,
            "projects": """
                SELECT id::text, source_system, external_project_id,
                       raw_provenance::text, enrichment_status
                FROM projects ORDER BY id
            """,
            "project_links": """
                SELECT id::text, tender_id::text, project_id::text,
                       linkage_method, source_value, provenance::text
                FROM tender_projects ORDER BY id
            """,
        }
        return {
            name: [tuple(row) for row in await connection.fetch(query)]
            for name, query in queries.items()
        }
    finally:
        await connection.close()


async def add_historical_project_link(database: str, fixture: dict[str, Any]) -> None:
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            """
            INSERT INTO tender_projects (
                id, tender_id, project_id, linkage_method, source_value, provenance
            ) VALUES (
                $1, $2, $3, 'SOURCE_PROJECT_ID', 'P-S22',
                '{"source_field": "tenders.project_id"}'::json
            )
            """,
            uuid4(),
            fixture["tender_id"],
            fixture["project_id"],
        )
    finally:
        await connection.close()


async def aggregate_audit(sessions: async_sessionmaker) -> dict[str, int]:
    async with sessions() as db:
        row = (await db.execute(AGGREGATE_AUDIT_SQL)).mappings().one()
        await db.rollback()
    return {key: int(value or 0) for key, value in row.items()}


async def run_fixture_matrix(
    database: str,
    sessions: async_sessionmaker,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    user_a = fixture["users"]["a"]
    user_b = fixture["users"]["b"]
    profile_a = fixture["profiles"]["a"]
    profile_b = fixture["profiles"]["b"]

    # A, C, D: first write, cached reuse, and forced append.
    basic_tender, _ = await add_tender(database, label="basic")
    first = await persist_analysis(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=basic_tender,
        label="basic-v1",
        content_hash="1" * 64,
    )
    cached = await persist_analysis(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=basic_tender,
        label="basic-cache",
        content_hash="1" * 64,
    )
    forced = await persist_analysis(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=basic_tender,
        label="basic-v2",
        content_hash="1" * 64,
        force=True,
    )
    basic_parents, basic_versions = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=basic_tender,
    )
    assert first["version_number"] == 1
    assert cached["outcome"] == "cached"
    assert forced["version_number"] == 2
    assert len(basic_parents) == 1
    assert basic_versions[basic_parents[0]] == [1, 2]

    # B: two separate transactions racing on the zero-parent path.
    first_race_tender, _ = await add_tender(database, label="first-race")
    barrier = asyncio.Barrier(2)
    first_race = await asyncio.gather(
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=first_race_tender,
            label="first-race-a",
            content_hash="2" * 64,
            ready=barrier,
        ),
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=first_race_tender,
            label="first-race-b",
            content_hash="2" * 64,
            ready=barrier,
        ),
    )
    race_parents, race_versions = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=first_race_tender,
    )
    assert len(race_parents) == 1
    assert race_versions[race_parents[0]] == [1]
    assert {item["outcome"] for item in first_race} == {"created", "cached"}

    # E: existing parent plus concurrent forced reanalysis remains v2/v3.
    reanalysis_tender, _ = await add_tender(database, label="reanalysis-race")
    await persist_analysis(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=reanalysis_tender,
        label="reanalysis-v1",
        content_hash="3" * 64,
    )
    barrier = asyncio.Barrier(2)
    reanalysis = await asyncio.gather(
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=reanalysis_tender,
            label="reanalysis-a",
            content_hash="4" * 64,
            force=True,
            ready=barrier,
        ),
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=reanalysis_tender,
            label="reanalysis-b",
            content_hash="5" * 64,
            force=True,
            ready=barrier,
        ),
    )
    re_parents, re_versions = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=reanalysis_tender,
    )
    assert len(re_parents) == 1
    assert re_versions[re_parents[0]] == [1, 2, 3]
    assert sorted(item["version_number"] for item in reanalysis) == [2, 3]

    # F: a first request and content-changing forced request cannot fork.
    mixed_tender, _ = await add_tender(database, label="mixed-race")
    barrier = asyncio.Barrier(2)
    mixed = await asyncio.gather(
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=mixed_tender,
            label="mixed-first",
            content_hash="6" * 64,
            ready=barrier,
        ),
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=mixed_tender,
            label="mixed-forced",
            content_hash="7" * 64,
            force=True,
            ready=barrier,
        ),
    )
    mixed_parents, mixed_versions = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=mixed_tender,
    )
    assert len(mixed_parents) == 1
    assert mixed_versions[mixed_parents[0]] == [1, 2]
    assert sorted(item["version_number"] for item in mixed) == [1, 2]

    # G: Proposal drafting is a read-only consumer racing a direct creation.
    proposal_tender, proposal_id = await add_tender(
        database,
        label="proposal-race",
        user_id=user_a,
    )

    async def proposal_compliance_read() -> UUID | None:
        async with sessions() as db:
            return await db.scalar(
                select(TenderAnalysis.id)
                .where(
                    TenderAnalysis.tender_id == proposal_tender,
                    TenderAnalysis.user_id == user_a,
                    TenderAnalysis.company_profile_id == profile_a,
                    TenderAnalysis.ownership_state == ANALYSIS_OWNERSHIP_OWNED,
                )
                .limit(1)
            )

    await asyncio.gather(
        persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=proposal_tender,
            label="proposal-direct",
            content_hash="8" * 64,
        ),
        proposal_compliance_read(),
    )
    proposal_parents, _ = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=proposal_tender,
    )
    assert proposal_id is not None
    assert len(proposal_parents) == 1

    # H, I: identical display names isolate by IDs; quarantine cannot block B.
    await persist_analysis(
        sessions,
        user_id=user_b,
        profile_id=profile_b,
        tender_id=fixture["tender_id"],
        label="same-name-tenant-b",
        content_hash="a" * 64,
    )
    tenant_b_parents, _ = await parent_and_versions(
        sessions,
        user_id=user_b,
        profile_id=profile_b,
        tender_id=fixture["tender_id"],
    )
    assert len(tenant_b_parents) == 1
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM tender_analyses
            WHERE tender_id = $1 AND ownership_state = 'QUARANTINED_LEGACY'
            """,
            fixture["tender_id"],
        ) == 1
    finally:
        await connection.close()

    # J, L: duplicate historical parents/hashes stay; runtime adds no third.
    before_historical = await historical_snapshot(database)
    historical_result = await persist_analysis(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=fixture["tender_id"],
        label="historical-runtime",
        content_hash="a" * 64,
    )
    historical_parents, _ = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=fixture["tender_id"],
    )
    assert len(historical_parents) == 2
    assert historical_result["outcome"] == "cached"
    assert historical_result["existing_parent_count"] == 2
    after_historical = await historical_snapshot(database)
    assert before_historical == after_historical

    # K: rollback releases the transaction lock and removes parent plus v1.
    rollback_tender, _ = await add_tender(database, label="rollback")
    try:
        await persist_analysis(
            sessions,
            user_id=user_a,
            profile_id=profile_a,
            tender_id=rollback_tender,
            label="rollback-failed",
            content_hash="9" * 64,
            fail_before_commit=True,
        )
    except RuntimeError as exc:
        assert str(exc) == "controlled persistence failure"
    else:
        raise AssertionError("controlled failed creator unexpectedly committed")
    failed_parents, failed_versions = await parent_and_versions(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=rollback_tender,
    )
    assert failed_parents == []
    assert failed_versions == {}
    retry = await persist_analysis(
        sessions,
        user_id=user_a,
        profile_id=profile_a,
        tender_id=rollback_tender,
        label="rollback-retry",
        content_hash="9" * 64,
    )
    assert retry["outcome"] == "created"
    assert retry["version_number"] == 1

    return {
        "A_first": "one_parent_v1",
        "B_concurrent_first": {
            "parents": 1,
            "versions": [1],
            "outcomes": sorted(item["outcome"] for item in first_race),
        },
        "C_cached": "reused_no_new_version",
        "D_forced": "same_parent_v2",
        "E_concurrent_reanalysis": [1, 2, 3],
        "F_first_forced_race": [1, 2],
        "G_proposal_direct": "one_parent",
        "H_same_name_tenants": "separate_id_scopes",
        "I_quarantine": "did_not_block_owned_parent",
        "J_historical_duplicates": "two_preserved_no_third",
        "K_rollback_retry": "rollback_clean_retry_v1",
        "L_equal_hashes": "no_merge",
    }


async def fresh_database_scenario() -> dict[str, Any]:
    database = support.database_name("s22b_fresh")
    await support.create_database(database)
    try:
        result = await asyncio.to_thread(support.run_bootstrap, database)
        assert result.returncode == 0, result.stderr or result.stdout
        assert await revision(database) == HEAD
        connection = await support.database_connection(database)
        try:
            assert (
                await connection.fetchval("SELECT COUNT(*) FROM tender_analyses")
                == 0
            )
            assert (
                await connection.fetchval("SELECT COUNT(*) FROM analysis_versions")
                == 0
            )
        finally:
            await connection.close()
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, check.stderr or check.stdout
        return {"head": HEAD, "business_rows": 0, "alembic_check": "clean"}
    finally:
        await support.drop_database(database)


async def existing_database_scenario() -> dict[str, Any]:
    database = support.database_name("s22b_existing")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", S2_1_HEAD)
        fixture = await s22.seed_s2_1(database)
        await add_historical_project_link(database, fixture)
        await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        assert await revision(database) == HEAD
        before_code_cutover = await historical_snapshot(database)
        repeated = await asyncio.to_thread(support.alembic, database, "upgrade", "head")
        assert repeated.returncode == 0, repeated.stderr or repeated.stdout
        after_code_cutover = await historical_snapshot(database)
        assert before_code_cutover == after_code_cutover

        engine = create_async_engine(
            support.target_url(database),
            pool_size=8,
            max_overflow=8,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            initial_audit = await aggregate_audit(sessions)
            assert initial_audit == {
                "total_tender_analyses": 3,
                "distinct_logical_aggregate_keys": 2,
                "keys_with_one_parent": 1,
                "keys_with_multiple_parents": 1,
                "max_parents_per_key": 2,
                "owned_logical_aggregate_keys": 1,
                "owned_single_parent_keys": 0,
                "owned_multi_parent_keys": 1,
                "quarantined_keys": 1,
                "quarantined_multi_parent_keys": 0,
                "invalid_canonical_keys": 0,
            }
            matrix = await run_fixture_matrix(database, sessions, fixture)
            final_audit = await aggregate_audit(sessions)
            assert final_audit["invalid_canonical_keys"] == 0
        finally:
            await engine.dispose()

        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, check.stderr or check.stdout
        return {
            "head": HEAD,
            "migration": "none",
            "historical_before_code_cutover_preserved": True,
            "controlled_historical_audit": initial_audit,
            "fixture_matrix": matrix,
            "final_invalid_canonical_keys": final_audit["invalid_canonical_keys"],
            "alembic_check": "clean",
        }
    finally:
        await support.drop_database(database)


async def main() -> int:
    results: dict[str, Any] = {}
    failures = 0
    for label, scenario in (
        ("fresh", fresh_database_scenario),
        ("existing", existing_database_scenario),
    ):
        try:
            results[label] = {"status": "passed", **await scenario()}
        except Exception as exc:
            failures += 1
            results[label] = {"status": "failed", "error": repr(exc)}
    leaked = await support.leaked_databases()
    if leaked:
        failures += 1
    print(
        json.dumps(
            {"results": results, "leaked_databases": leaked, "failures": failures},
            indent=2,
            default=str,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
