#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for Sprint 2.2 analysis versions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.all_models import AnalysisVersion, TenderAnalysis
from app.models.audit import ANALYSIS_OWNERSHIP_OWNED
from app.services.analysis_versions import (
    AnalysisVersionOwnershipError,
    DocumentSnapshotInput,
    append_analysis_version,
    get_latest_analysis_version,
    list_analysis_versions,
)
from scripts import run_s0_3_schema_data_preflight as preflight
from scripts import test_s0_5b4_baseline as support


S2_1_HEAD = "20260827_0001_s2_1_compliance_ownership"
HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


def decoded_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def revision(database: str) -> str:
    connection = await support.database_connection(database)
    try:
        return str(await connection.fetchval("SELECT version_num FROM alembic_version"))
    finally:
        await connection.close()


def legacy_payload(*, document_id: UUID, label: str, with_model: bool) -> dict[str, Any]:
    engine = {
        "extractor_schema_version": "legacy-schema-v5",
        "prompt_schema_version": "legacy-schema-v5",
    }
    if with_model:
        engine["requirement_model_name"] = "historically-persisted-model"
    return {
        "fixture": label,
        "requirements": {"mapped_requirement_uuids": [], "unmapped_custom_requirements": []},
        "evaluation": {"is_compliant": True, "fixture": label},
        "hybrid_compliance": {
            "verdict_status": "COMPLIANT",
            "satisfied_requirements": [
                {
                    "requirement_fingerprint": f"req-{label}",
                    "source_filename": "historical.pdf",
                    "source_page": 4,
                    "exact_quote": "historically persisted evidence",
                }
            ],
        },
        "evidence_validation": {
            "accepted": [
                {
                    "requirement_fingerprint": f"req-{label}",
                    "source_filename": "historical.pdf",
                    "source_page": 4,
                    "exact_quote": "historically persisted evidence",
                    "status": "accepted",
                }
            ]
        },
        "reproducibility_snapshot": {
            "engine_metadata": engine,
            "input_fingerprints": {
                "compiled_text_sha256": "7" * 64,
                "document_order_fingerprint": "8" * 64,
                "document_fingerprints": [
                    {
                        "document_id": str(document_id),
                        "display_name": "historical.pdf",
                        "file_type": "pdf",
                        "file_size": 123,
                        "parsed_text_sha256": "9" * 64,
                    }
                ],
            },
            "requirement_route_summary": [{"requirement_fingerprint": f"req-{label}"}],
        },
        "analysis_status": "completed",
    }


async def seed_s2_1(database: str) -> dict[str, Any]:
    user_a, user_b = uuid4(), uuid4()
    profile_a, profile_b = uuid4(), uuid4()
    tender_id, document_id, project_id = uuid4(), uuid4(), uuid4()
    analysis_ids = {"owned_a": uuid4(), "owned_a_duplicate": uuid4(), "quarantined": uuid4()}
    proposal_id, recommendation_id, taxonomy_id, override_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    payloads = {
        "owned_a": legacy_payload(document_id=document_id, label="owned-a", with_model=True),
        "owned_a_duplicate": legacy_payload(
            document_id=document_id, label="owned-a-duplicate", with_model=False
        ),
        "quarantined": legacy_payload(
            document_id=document_id, label="quarantined", with_model=False
        ),
    }
    connection = await support.database_connection(database)
    try:
        for key, user_id in (("a", user_a), ("b", user_b)):
            await connection.execute(
                """
                INSERT INTO users (
                    id, google_id, email, name, subscription_tier, is_admin,
                    approval_status, platform_role
                ) VALUES ($1, $2, $3, $4, 'SCOUT', false, 'approved', 'pilot_user')
                """,
                user_id,
                f"s22-google-{key}-{user_id}",
                f"s22-{key}-{user_id}@example.test",
                f"S2.2 User {key.upper()}",
            )
        for user_id, profile_id in ((user_a, profile_a), (user_b, profile_b)):
            await connection.execute(
                """
                INSERT INTO company_profiles (
                    id, user_id, company_name, pilot_status, approval_status
                ) VALUES ($1, $2, 'Same Display Name', 'active_pilot', 'approved')
                """,
                profile_id,
                user_id,
            )
        await connection.execute(
            """
            INSERT INTO tenders (
                id, external_id, source_url, title, buyer, budget, currency,
                status, category, source_system, canonical_source_key, country,
                procurement_method, notice_type, project_id, source_metadata_json,
                scrape_status, compiled_master_text
            ) VALUES (
                $1, 'S22-WB-1', 'https://example.test/tender', 'Historical tender',
                'Historical buyer', 1000, 'USD', 'OPEN', 'World Bank', 'world_bank',
                'world_bank:S22-WB-1', 'Uzbekistan', 'RFB', 'Invitation', 'P-S22',
                '{"preserved": true}'::json, 'success', 'historical compiled text'
            )
            """,
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_documents (
                id, tender_id, file_url, file_type, source_document_url,
                external_file_id, storage_path, file_size, mime_type, sha256,
                parsed_text
            ) VALUES ($1, $2, 'https://example.test/historical.pdf', 'pdf',
                      'https://source.test/historical.pdf', 'source-doc-1',
                      'tenders/historical.pdf', 123, 'application/pdf', $3,
                      'historically parsed text')
            """,
            document_id,
            tender_id,
            "6" * 64,
        )
        await connection.execute(
            """
            INSERT INTO projects (
                id, source_system, external_project_id, name, country,
                raw_provenance, created_at, updated_at
            ) VALUES ($1, 'world_bank', 'P-S22', 'Historical project',
                      'Uzbekistan', '{"preserved": true}'::json, NOW(), NOW())
            """,
            project_id,
        )
        for index, (key, analysis_id) in enumerate(analysis_ids.items()):
            owned = key != "quarantined"
            await connection.execute(
                """
                INSERT INTO tender_analyses (
                    id, tender_id, tender_file_name, user_id, company_profile_id,
                    ownership_state, company_name, raw_extracted_text,
                    analysis_json, content_hash, override_seal, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'Same Display Name', $7,
                          $8::jsonb, $9, $10,
                          '2026-08-20 10:00:00+00'::timestamptz
                            + ($11 * interval '1 minute'))
                """,
                analysis_id,
                tender_id,
                f"historical-{key}.pdf",
                user_a if owned else None,
                profile_a if owned else None,
                "OWNED" if owned else "QUARANTINED_LEGACY",
                f"historical extracted text {key}",
                json.dumps(payloads[key]),
                "a" * 64,
                "b" * 64,
                index,
            )
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1, $2, $3, 'DRAFT', 77, '{"preserved": true}'::json,
                      15, true, 'USD')
            """,
            proposal_id,
            user_a,
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_recommendations (
                id, tender_id, company_profile_id, match_score,
                strategic_rationale, is_dismissed
            ) VALUES ($1, $2, $3, 91, 'preserved recommendation', false)
            """,
            recommendation_id,
            tender_id,
            profile_a,
        )
        await connection.execute(
            """
            INSERT INTO taxonomy_nodes (id, category, name, impact_weight, is_fatal)
            VALUES ($1, 'LICENSE', 'S2.2 fixture node', 80, true)
            """,
            taxonomy_id,
        )
        await connection.execute(
            """
            INSERT INTO risk_override_logs (
                id, user_id, tender_id, analysis_id, missing_node_id,
                justification, state_hash, created_at
            ) VALUES ($1, $2, $3, $4, $5, 'preserved override', $6, NOW())
            """,
            override_id,
            user_a,
            tender_id,
            analysis_ids["owned_a"],
            taxonomy_id,
            "c" * 64,
        )
    finally:
        await connection.close()
    return {
        "users": {"a": user_a, "b": user_b},
        "profiles": {"a": profile_a, "b": profile_b},
        "tender_id": tender_id,
        "document_id": document_id,
        "project_id": project_id,
        "taxonomy_id": taxonomy_id,
        "analysis_ids": analysis_ids,
        "payloads": payloads,
        "artifact_ids": [proposal_id, recommendation_id, override_id],
    }


async def preservation_snapshot(database: str) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        queries = {
            "analyses": """
                SELECT id::text, tender_id::text, tender_file_name,
                       user_id::text, company_profile_id::text, ownership_state,
                       company_name, raw_extracted_text, analysis_json::text,
                       content_hash, override_seal, created_at
                FROM tender_analyses ORDER BY id
            """,
            "overrides": """
                SELECT id::text, user_id::text, tender_id::text, analysis_id::text,
                       missing_node_id::text, justification, state_hash, created_at
                FROM risk_override_logs ORDER BY id
            """,
            "proposals": """
                SELECT id::text, user_id::text, tender_id::text, status::text,
                       structured_data::text, created_at FROM proposals ORDER BY id
            """,
            "recommendations": """
                SELECT id::text, tender_id::text, company_profile_id::text,
                       match_score, strategic_rationale, is_dismissed, created_at
                FROM tender_recommendations ORDER BY id
            """,
            "projects": """
                SELECT id::text, source_system, external_project_id, name, country,
                       raw_provenance::text, enrichment_status, created_at, updated_at
                FROM projects ORDER BY id
            """,
        }
        return {
            name: [tuple(row) for row in await connection.fetch(query)]
            for name, query in queries.items()
        }
    finally:
        await connection.close()


async def verify_legacy_backfill(database: str, fixture: dict[str, Any]) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        rows = await connection.fetch(
            """
            SELECT v.*, a.analysis_json AS parent_json, a.content_hash AS parent_hash,
                   a.company_name, a.created_at AS parent_created_at,
                   a.ownership_state
            FROM analysis_versions v
            JOIN tender_analyses a ON a.id = v.analysis_id
            ORDER BY v.analysis_id
            """
        )
        assert len(rows) == 3
        for row in rows:
            result_snapshot = decoded_json(row["result_snapshot"])
            parent_json = decoded_json(row["parent_json"])
            company_snapshot = decoded_json(row["company_snapshot"])
            tender_snapshot = decoded_json(row["tender_snapshot"])
            evidence_snapshot = decoded_json(row["evidence_snapshot"])
            assert row["id"] == row["analysis_id"]
            assert row["version_number"] == 1
            assert row["supersedes_version_id"] is None
            assert row["origin"] == "LEGACY_BACKFILL"
            assert row["snapshot_completeness"] == "LEGACY_BACKFILL"
            assert result_snapshot == parent_json
            assert row["input_hash"] == row["parent_hash"] == "a" * 64
            assert row["output_hash"] is None
            assert row["evidence_hash"] is None
            assert row["version_hash"] is None
            assert row["pipeline_version"] is None
            assert row["model_provider"] is None
            assert row["prompt_template_hash"] is None
            assert row["requested_by_user_id"] is None
            assert row["created_at"] == row["parent_created_at"]
            assert company_snapshot["company_name"] == row["company_name"]
            assert tender_snapshot["tender_id"] == str(fixture["tender_id"])
            assert evidence_snapshot["evidence_validation"] == parent_json[
                "evidence_validation"
            ]
        missing_model = await connection.fetchrow(
            "SELECT * FROM analysis_versions WHERE analysis_id = $1",
            fixture["analysis_ids"]["owned_a_duplicate"],
        )
        assert missing_model["model_name"] is None
        assert missing_model["model_provider"] is None
        known_model = await connection.fetchrow(
            "SELECT * FROM analysis_versions WHERE analysis_id = $1",
            fixture["analysis_ids"]["owned_a"],
        )
        assert known_model["model_name"] == "historically-persisted-model"
        assert known_model["model_provider"] is None

        document_rows = await connection.fetch(
            "SELECT * FROM analysis_version_document_snapshots ORDER BY analysis_version_id"
        )
        assert len(document_rows) == 3
        assert all(row["content_hash"] == "9" * 64 for row in document_rows)
        assert all(row["source_url"] is None for row in document_rows)
        assert all(row["storage_reference"] is None for row in document_rows)
        assert all(
            decoded_json(row["snapshot_metadata"])["parsed_text_sha256"] == "9" * 64
            for row in document_rows
        )

        # Parent-owned authorization is the only version access predicate.
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM analysis_versions v
            JOIN tender_analyses a ON a.id = v.analysis_id
            WHERE a.user_id = $1 AND a.company_profile_id = $2
              AND a.ownership_state = 'OWNED'
            """,
            fixture["users"]["a"],
            fixture["profiles"]["a"],
        ) == 2
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM analysis_versions v
            JOIN tender_analyses a ON a.id = v.analysis_id
            WHERE a.user_id = $1 AND a.company_profile_id = $2
              AND a.ownership_state = 'OWNED'
            """,
            fixture["users"]["b"],
            fixture["profiles"]["b"],
        ) == 0
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM analysis_versions v
            JOIN tender_analyses a ON a.id = v.analysis_id
            WHERE a.ownership_state = 'QUARANTINED_LEGACY'
            """
        ) == 1
        return {"versions": 3, "document_snapshots": 3, "quarantined_versions": 1}
    finally:
        await connection.close()


def runtime_documents(fixture: dict[str, Any]) -> list[DocumentSnapshotInput]:
    return [
        DocumentSnapshotInput(
            tender_document_id=fixture["document_id"],
            source_system="world_bank",
            source_document_key="source-doc-1",
            source_url="https://source.test/historical.pdf",
            filename="historical.pdf",
            media_type="application/pdf",
            content_hash="6" * 64,
            storage_reference="tenders/historical.pdf",
            storage_version=None,
            fetched_at=None,
            observed_at=None,
            snapshot_metadata={
                "parsed_text_length": 24,
                "parsed_text_sha256": "9" * 64,
            },
        )
    ]


def append_kwargs(fixture: dict[str, Any], *, label: str) -> dict[str, Any]:
    result = {
        "analysis_status": "completed",
        "label": label,
        "hybrid_compliance": {"verdict_status": "COMPLIANT"},
        "evidence_validation": {"accepted": [{"quote": "runtime evidence"}]},
        "reproducibility_snapshot": {"requirement_route_summary": []},
    }
    return {
        "requested_by_user_id": fixture["users"]["a"],
        "company_profile_id": fixture["profiles"]["a"],
        "status": "COMPLETED",
        "analysis_schema_version": "runtime-schema-v1",
        "model_provider": "google",
        "model_name": "runtime-configured-model",
        "model_version": None,
        "prompt_template_version": "runtime-schema-v1",
        "prompt_template_hash": "d" * 64,
        "provenance_snapshot": {
            "requirement_extractor": {
                "model_provider": "google",
                "model_name": "runtime-configured-model",
                "prompt_template_hash": "d" * 64,
            }
        },
        "tender_snapshot": {
            "tender_id": str(fixture["tender_id"]),
            "title": "Historical tender",
        },
        "company_snapshot": {
            "company_profile_id": str(fixture["profiles"]["a"]),
            "company_name": "Same Display Name",
            "vault": {"licenses": [{"license_name": "Runtime license"}]},
        },
        "result_snapshot": result,
        "evidence_snapshot": {
            "evidence_validation": result["evidence_validation"],
            "hybrid_compliance": result["hybrid_compliance"],
        },
        "input_hash": "e" * 64,
        "documents": runtime_documents(fixture),
    }


async def verify_runtime(database: str, fixture: dict[str, Any]) -> dict[str, Any]:
    engine = create_async_engine(support.target_url(database), pool_size=5, max_overflow=5)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    runtime_analysis_id = uuid4()
    failed_atomic_id = uuid4()
    try:
        # New analysis compatibility parent plus v1 are committed together.
        async with sessions() as session:
            parent = TenderAnalysis(
                id=runtime_analysis_id,
                tender_id=fixture["tender_id"],
                tender_file_name="runtime.pdf",
                user_id=fixture["users"]["a"],
                company_profile_id=fixture["profiles"]["a"],
                ownership_state=ANALYSIS_OWNERSHIP_OWNED,
                company_name="Same Display Name",
                raw_extracted_text="runtime text",
                analysis_json={"label": "runtime-v1"},
                content_hash="e" * 64,
            )
            session.add(parent)
            await session.flush()
            v1 = await append_analysis_version(
                session, analysis_id=runtime_analysis_id, **append_kwargs(fixture, label="v1")
            )
            parent.analysis_json = deepcopy(v1.result_snapshot)
            await session.commit()
            assert v1.version_number == 1

        # Owner-aware internal reads deny same-name other tenant and quarantine.
        async with sessions() as session:
            assert (
                await get_latest_analysis_version(
                    session,
                    analysis_id=runtime_analysis_id,
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
            ) is not None
            assert (
                await get_latest_analysis_version(
                    session,
                    analysis_id=runtime_analysis_id,
                    user_id=fixture["users"]["b"],
                    company_profile_id=fixture["profiles"]["b"],
                )
            ) is None
            assert (
                await get_latest_analysis_version(
                    session,
                    analysis_id=fixture["analysis_ids"]["quarantined"],
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
            ) is None

        for denied_analysis_id, denied_user, denied_profile in (
            (
                runtime_analysis_id,
                fixture["users"]["b"],
                fixture["profiles"]["b"],
            ),
            (
                fixture["analysis_ids"]["quarantined"],
                fixture["users"]["a"],
                fixture["profiles"]["a"],
            ),
        ):
            async with sessions() as session:
                denied = append_kwargs(fixture, label="denied")
                denied["requested_by_user_id"] = denied_user
                denied["company_profile_id"] = denied_profile
                try:
                    await append_analysis_version(
                        session,
                        analysis_id=denied_analysis_id,
                        **denied,
                    )
                except AnalysisVersionOwnershipError:
                    await session.rollback()
                else:
                    raise AssertionError("cross-tenant/quarantined append was allowed")

        # Two real PostgreSQL transactions serialize on the parent row and
        # allocate unique v2/v3 lineage even with the same input hash.
        async def concurrent_append(label: str) -> tuple[int, UUID | None]:
            async with sessions() as session:
                version = await append_analysis_version(
                    session,
                    analysis_id=runtime_analysis_id,
                    **append_kwargs(fixture, label=label),
                )
                await session.commit()
                return version.version_number, version.supersedes_version_id

        concurrent = await asyncio.gather(
            concurrent_append("concurrent-a"),
            concurrent_append("concurrent-b"),
        )
        assert sorted(number for number, _ in concurrent) == [2, 3]

        async with sessions() as session:
            versions = await list_analysis_versions(
                session,
                analysis_id=runtime_analysis_id,
                user_id=fixture["users"]["a"],
                company_profile_id=fixture["profiles"]["a"],
            )
            assert [item.version_number for item in versions] == [1, 2, 3]
            assert versions[0].supersedes_version_id is None
            assert versions[1].supersedes_version_id == versions[0].id
            assert versions[2].supersedes_version_id == versions[1].id
            assert len({item.input_hash for item in versions}) == 1
            assert all(item.output_hash and item.evidence_hash for item in versions)
            assert all(item.document_set_hash and item.version_hash for item in versions)
            assert all(item.snapshot_completeness == "COMPLETE" for item in versions)
            immutable_v1 = {
                "result": deepcopy(versions[0].result_snapshot),
                "evidence": deepcopy(versions[0].evidence_snapshot),
                "company": deepcopy(versions[0].company_snapshot),
                "tender": deepcopy(versions[0].tender_snapshot),
                "hash": versions[0].version_hash,
            }

        # Live metadata and the compatibility parent may change; v1 does not.
        connection = await support.database_connection(database)
        try:
            await connection.execute(
                "UPDATE tenders SET title = 'Changed live tender' WHERE id = $1",
                fixture["tender_id"],
            )
            await connection.execute(
                "UPDATE company_profiles SET company_name = 'Changed live company' WHERE id = $1",
                fixture["profiles"]["a"],
            )
            await connection.execute(
                "UPDATE tender_documents SET parsed_text = 'changed live document' WHERE id = $1",
                fixture["document_id"],
            )
            await connection.execute(
                "UPDATE tender_analyses SET analysis_json = '{\"mirror\": \"changed\"}'::jsonb WHERE id = $1",
                runtime_analysis_id,
            )
            await connection.execute(
                """
                INSERT INTO risk_override_logs (
                    id, user_id, tender_id, analysis_id, missing_node_id,
                    justification, state_hash, created_at
                ) VALUES ($1, $2, $3, $4, $5, 'post-version override', $6, NOW())
                """,
                uuid4(),
                fixture["users"]["a"],
                fixture["tender_id"],
                runtime_analysis_id,
                fixture["taxonomy_id"],
                "f" * 64,
            )
            await connection.execute(
                "UPDATE tender_analyses SET override_seal = $2 WHERE id = $1",
                runtime_analysis_id,
                "f" * 64,
            )
        finally:
            await connection.close()
        async with sessions() as session:
            v1_again = await session.scalar(
                select(AnalysisVersion).where(
                    AnalysisVersion.analysis_id == runtime_analysis_id,
                    AnalysisVersion.version_number == 1,
                )
            )
            assert v1_again is not None
            assert immutable_v1 == {
                "result": v1_again.result_snapshot,
                "evidence": v1_again.evidence_snapshot,
                "company": v1_again.company_snapshot,
                "tender": v1_again.tender_snapshot,
                "hash": v1_again.version_hash,
            }

        # Rollback proves no successful parent can be left without its v1.
        async with sessions() as session:
            parent = TenderAnalysis(
                id=failed_atomic_id,
                tender_id=fixture["tender_id"],
                tender_file_name="rollback.pdf",
                user_id=fixture["users"]["a"],
                company_profile_id=fixture["profiles"]["a"],
                ownership_state=ANALYSIS_OWNERSHIP_OWNED,
                company_name="Changed live company",
                raw_extracted_text="rollback text",
                analysis_json={"label": "rollback"},
                content_hash="e" * 64,
            )
            session.add(parent)
            await session.flush()
            await append_analysis_version(
                session, analysis_id=failed_atomic_id, **append_kwargs(fixture, label="rollback")
            )
            await session.rollback()
        connection = await support.database_connection(database)
        try:
            assert await connection.fetchval(
                "SELECT COUNT(*) FROM tender_analyses WHERE id = $1", failed_atomic_id
            ) == 0
            assert await connection.fetchval(
                "SELECT COUNT(*) FROM analysis_versions WHERE analysis_id = $1", failed_atomic_id
            ) == 0
        finally:
            await connection.close()

        return {
            "new_parent_versions": 3,
            "concurrent_numbers": sorted(number for number, _ in concurrent),
            "same_input_versions_retained": True,
            "snapshots_immutable_after_live_mutation": True,
            "risk_override_separate": True,
            "atomic_rollback": True,
        }
    finally:
        await engine.dispose()


async def fresh_database_scenario() -> dict[str, Any]:
    database = support.database_name("s22_fresh")
    await support.create_database(database)
    try:
        result = await asyncio.to_thread(support.run_bootstrap, database)
        if result.returncode:
            raise AssertionError((result.stderr or result.stdout)[-4000:])
        assert await revision(database) == HEAD
        connection = await support.database_connection(database)
        try:
            assert await connection.fetchval("SELECT COUNT(*) FROM tender_analyses") == 0
            assert await connection.fetchval("SELECT COUNT(*) FROM analysis_versions") == 0
            assert await connection.fetchval(
                "SELECT COUNT(*) FROM analysis_version_document_snapshots"
            ) == 0
        finally:
            await connection.close()
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0
        return {"head": HEAD, "business_rows": 0, "alembic_check": "clean"}
    finally:
        await support.drop_database(database)


async def existing_database_scenario() -> dict[str, Any]:
    database = support.database_name("s22_existing")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", S2_1_HEAD)
        fixture = await seed_s2_1(database)
        before = await preservation_snapshot(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        assert await revision(database) == HEAD
        after = await preservation_snapshot(database)
        assert after == before
        legacy = await verify_legacy_backfill(database, fixture)
        runtime = await verify_runtime(database, fixture)

        connection = await support.database_connection(database)
        transaction = connection.transaction(readonly=True)
        await transaction.start()
        try:
            runner = preflight.ReadOnlyPreflight(connection, timeout=30.0)
            await runner.load_catalog()
            report = await runner.analysis_version_audit()
        finally:
            await transaction.rollback()
            await connection.close()
        distribution = report["data"]["parent_distribution"]
        integrity = report["data"]["version_integrity"]
        duplicates = report["data"]["duplicate_version_numbers"]
        assert distribution == {
            "total_tender_analyses": 4,
            "analyses_with_zero_versions": 0,
            "analyses_with_one_version": 3,
            "analyses_with_multiple_versions": 1,
        }
        assert integrity["total_analysis_versions"] == 6
        assert integrity["version_parent_orphans"] == 0
        assert integrity["broken_supersedes_references"] == 0
        assert integrity["quarantined_analyses_with_versions"] == 1
        assert duplicates["duplicate_version_number_groups"] == 0
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0
        return {
            "head": HEAD,
            "legacy": legacy,
            "runtime": runtime,
            "preflight": {
                "distribution": distribution,
                "integrity": integrity,
                "duplicate_versions": duplicates,
            },
            "legacy_source_and_related_artifacts_unchanged": True,
            "alembic_check": "clean",
        }
    finally:
        await support.drop_database(database)


async def set_based_load_scenario() -> dict[str, Any]:
    """Exercise the network-free INSERT...SELECT backfill above expected local scale."""
    database = support.database_name("s22_load")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", S2_1_HEAD)
        fixture = await seed_s2_1(database)
        connection = await support.database_connection(database)
        try:
            rows = [
                (
                    uuid4(),
                    fixture["tender_id"],
                    f"load-{index}.pdf",
                    f"load text {index}",
                    json.dumps({"fixture": index, "analysis_status": "completed"}),
                    f"{index:064x}",
                )
                for index in range(1000)
            ]
            await connection.executemany(
                """
                INSERT INTO tender_analyses (
                    id, tender_id, tender_file_name, ownership_state,
                    company_name, raw_extracted_text, analysis_json, content_hash
                ) VALUES ($1, $2, $3, 'QUARANTINED_LEGACY', 'load fixture',
                          $4, $5::jsonb, $6)
                """,
                rows,
            )
        finally:
            await connection.close()
        started = monotonic()
        await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        elapsed = monotonic() - started
        connection = await support.database_connection(database)
        try:
            analyses = await connection.fetchval("SELECT COUNT(*) FROM tender_analyses")
            versions = await connection.fetchval("SELECT COUNT(*) FROM analysis_versions")
            assert analyses == versions == 1003
            assert await connection.fetchval(
                """
                SELECT COUNT(*) FROM tender_analyses a
                LEFT JOIN analysis_versions v
                  ON v.analysis_id = a.id AND v.version_number = 1
                WHERE v.id IS NULL
                """
            ) == 0
        finally:
            await connection.close()
        return {
            "historical_analyses": analyses,
            "backfilled_versions": versions,
            "elapsed_seconds": round(elapsed, 3),
            "missing_v1": 0,
        }
    finally:
        await support.drop_database(database)


async def main() -> int:
    results = {
        "fresh_database": await fresh_database_scenario(),
        "existing_database": await existing_database_scenario(),
        "set_based_load": await set_based_load_scenario(),
    }
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
