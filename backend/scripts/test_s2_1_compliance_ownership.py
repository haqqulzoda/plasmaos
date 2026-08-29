#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for Sprint 2.1 ownership quarantine."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

import asyncpg

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts import run_s0_3_schema_data_preflight as preflight
from scripts import test_s0_5b4_baseline as support


S1_HEAD = "20260826_0002_s1_2_wb_project_enrichment"
HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


async def _revision(database: str) -> str:
    connection = await support.database_connection(database)
    try:
        return str(await connection.fetchval("SELECT version_num FROM alembic_version"))
    finally:
        await connection.close()


async def _seed_s1_database(database: str) -> dict[str, Any]:
    users = {name: uuid4() for name in ("a", "b", "c", "d")}
    profiles = {name: uuid4() for name in ("a", "b", "c", "d")}
    tender_id = uuid4()
    project_id = uuid4()
    tender_project_id = uuid4()
    proposal_id = uuid4()
    recommendation_id = uuid4()
    taxonomy_node_id = uuid4()
    analysis_ids = {
        name: uuid4()
        for name in (
            "valid_a",
            "valid_b",
            "missing_user",
            "missing_profile",
            "mismatched_profile",
            "no_profile",
            "same_name",
            "unique_name",
            "empty",
            "malformed",
        )
    }
    missing_user = uuid4()
    missing_profile = uuid4()

    owners = {
        "valid_a": f"{users['a']}:{profiles['a']}",
        "valid_b": f"{users['b']}:{profiles['b']}",
        "missing_user": f"{missing_user}:{profiles['a']}",
        "missing_profile": f"{users['a']}:{missing_profile}",
        "mismatched_profile": f"{users['a']}:{profiles['b']}",
        "no_profile": f"{users['a']}:no-profile",
        "same_name": "Acme Engineering",
        "unique_name": "Unique Engineering",
        "empty": "",
        "malformed": "malformed:owner:tokens",
    }

    connection = await support.database_connection(database)
    try:
        for key, user_id in users.items():
            await connection.execute(
                """
                INSERT INTO users (
                    id, google_id, email, name, subscription_tier, is_admin,
                    approval_status, platform_role
                ) VALUES ($1, $2, $3, $4, 'SCOUT', false, 'approved', 'pilot_user')
                """,
                user_id,
                f"s21-google-{key}-{user_id}",
                f"s21-{key}-{user_id}@example.test",
                f"S2.1 User {key.upper()}",
            )
        for key, profile_id in profiles.items():
            company_name = (
                "Acme Engineering"
                if key in {"a", "b"}
                else "Unique Engineering"
                if key == "c"
                else "Mismatch Engineering"
            )
            await connection.execute(
                """
                INSERT INTO company_profiles (
                    id, user_id, company_name, pilot_status, approval_status
                ) VALUES ($1, $2, $3, 'active_pilot', 'approved')
                """,
                profile_id,
                users[key],
                company_name,
            )

        await connection.execute(
            """
            INSERT INTO tenders (
                id, external_id, source_url, title, budget, currency, status,
                category, source_system, canonical_source_key, country,
                project_id, source_metadata_json, scrape_status
            ) VALUES ($1, 'S21-WB-1', 'https://example.test/s21',
                      'S2.1 preserved tender', 1000, 'USD', 'OPEN',
                      'World Bank', 'world_bank', 'world_bank:S21-WB-1',
                      'Uzbekistan', 'P-S21', '{"preserved": true}'::json,
                      'success')
            """,
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO projects (
                id, source_system, external_project_id, name, country,
                raw_provenance, created_at, updated_at
            ) VALUES ($1, 'world_bank', 'P-S21', 'Preserved project',
                      'Uzbekistan', '{"preserved": true}'::json, NOW(), NOW())
            """,
            project_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_projects (
                id, tender_id, project_id, linkage_method, source_value,
                provenance, created_at
            ) VALUES ($1, $2, $3, 'SOURCE_PROJECT_ID', 'P-S21',
                      '{"preserved": true}'::json, NOW())
            """,
            tender_project_id,
            tender_id,
            project_id,
        )
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1, $2, $3, 'DRAFT', 75,
                      '{"preserved": true}'::json, 20, true, 'USD')
            """,
            proposal_id,
            users["a"],
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_recommendations (
                id, tender_id, company_profile_id, match_score,
                strategic_rationale, is_dismissed
            ) VALUES ($1, $2, $3, 88, 'preserved', false)
            """,
            recommendation_id,
            tender_id,
            profiles["a"],
        )

        for index, (name, analysis_id) in enumerate(analysis_ids.items()):
            await connection.execute(
                """
                INSERT INTO tender_analyses (
                    id, tender_id, tender_file_name, company_name,
                    raw_extracted_text, analysis_json, content_hash,
                    override_seal, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8,
                          '2026-08-20 10:00:00+00'::timestamptz + ($9 * interval '1 minute'))
                """,
                analysis_id,
                tender_id,
                f"fixture-{name}.pdf",
                owners[name],
                f"immutable extracted text {name}",
                json.dumps({"fixture": name, "evidence": ["preserved"]}),
                f"{index + 1:064x}",
                f"{index + 101:064x}",
                index,
            )

        await connection.execute(
            """
            INSERT INTO taxonomy_nodes (id, category, name, impact_weight, is_fatal)
            VALUES ($1, 'LICENSE', $2, 80, true)
            """,
            taxonomy_node_id,
            f"S2.1 fixture node {taxonomy_node_id}",
        )
        await connection.execute(
            """
            INSERT INTO risk_override_logs (
                id, user_id, tender_id, analysis_id, missing_node_id,
                justification, state_hash, created_at
            ) VALUES ($1, $2, $3, $4, $5, 'preserved override', $6,
                      '2026-08-21 10:00:00+00')
            """,
            uuid4(),
            users["a"],
            tender_id,
            analysis_ids["valid_a"],
            taxonomy_node_id,
            "f" * 64,
        )
        await connection.execute(
            """
            INSERT INTO audit_logs (
                id, analysis_id, user_id, action_type, risk_type, timestamp,
                previous_hash, current_hash
            ) VALUES ($1, $2, $3, 'AUTHORIZE_RISK', 'fixture',
                      '2026-08-21 11:00:00+00', NULL, $4)
            """,
            uuid4(),
            analysis_ids["valid_a"],
            str(users["a"]),
            "e" * 64,
        )
    finally:
        await connection.close()

    return {
        "users": users,
        "profiles": profiles,
        "tender_id": tender_id,
        "project_id": project_id,
        "proposal_id": proposal_id,
        "recommendation_id": recommendation_id,
        "analysis_ids": analysis_ids,
    }


async def _preservation_snapshot(database: str) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        analyses = await connection.fetch(
            """
            SELECT id::text, tender_id::text, tender_file_name, company_name,
                   raw_extracted_text, analysis_json::text, content_hash,
                   override_seal, created_at
            FROM tender_analyses ORDER BY id
            """
        )
        artifact_queries = {
            "audit_logs": """
                SELECT id::text, analysis_id::text, user_id, action_type,
                       risk_type, timestamp, previous_hash, current_hash
                FROM audit_logs ORDER BY id
            """,
            "risk_override_logs": """
                SELECT id::text, user_id::text, tender_id::text,
                       analysis_id::text, missing_node_id::text, justification,
                       state_hash, created_at
                FROM risk_override_logs ORDER BY id
            """,
            "proposals": """
                SELECT id::text, user_id::text, tender_id::text, status::text,
                       ai_confidence_score, structured_data::text,
                       margin_percent, include_vat, currency, created_at
                FROM proposals ORDER BY id
            """,
            "tender_recommendations": """
                SELECT id::text, tender_id::text, company_profile_id::text,
                       match_score, strategic_rationale, is_dismissed, created_at
                FROM tender_recommendations ORDER BY id
            """,
            "projects": """
                SELECT id::text, source_system, external_project_id, name,
                       country, raw_provenance::text, created_at, updated_at,
                       enrichment_status
                FROM projects ORDER BY id
            """,
            "tender_projects": """
                SELECT id::text, tender_id::text, project_id::text,
                       linkage_method, source_value, provenance::text, created_at
                FROM tender_projects ORDER BY id
            """,
        }
        artifacts = {
            name: [tuple(row) for row in await connection.fetch(query)]
            for name, query in artifact_queries.items()
        }
        return {
            "analyses": [tuple(row) for row in analyses],
            "artifacts": artifacts,
        }
    finally:
        await connection.close()


async def _verify_existing_upgrade(database: str, ids: dict[str, Any]) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        rows = await connection.fetch(
            """
            SELECT id, user_id, company_profile_id, ownership_state
            FROM tender_analyses
            """
        )
        classified = {row["id"]: row for row in rows}
        for key in ("valid_a", "valid_b"):
            row = classified[ids["analysis_ids"][key]]
            assert row["ownership_state"] == "OWNED"
            owner_key = "a" if key == "valid_a" else "b"
            assert row["user_id"] == ids["users"][owner_key]
            assert row["company_profile_id"] == ids["profiles"][owner_key]
        for key in (
            "missing_user",
            "missing_profile",
            "mismatched_profile",
            "no_profile",
            "same_name",
            "unique_name",
            "empty",
            "malformed",
        ):
            row = classified[ids["analysis_ids"][key]]
            assert row["ownership_state"] == "QUARANTINED_LEGACY"
            assert row["user_id"] is None
            assert row["company_profile_id"] is None

        counts = dict(
            await connection.fetchrow(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE ownership_state = 'OWNED') AS owned,
                       COUNT(*) FILTER (
                         WHERE ownership_state = 'QUARANTINED_LEGACY'
                       ) AS quarantined
                FROM tender_analyses
                """
            )
        )
        assert counts == {"total": 10, "owned": 2, "quarantined": 8}

        # Customer predicates cannot cross tenants or claim either same-name row.
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM tender_analyses
            WHERE user_id = $1 AND company_profile_id = $2
              AND ownership_state = 'OWNED'
            """,
            ids["users"]["a"],
            ids["profiles"]["a"],
        ) == 1
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM tender_analyses
            WHERE id = $1 AND user_id = $2 AND company_profile_id = $3
              AND ownership_state = 'OWNED'
            """,
            ids["analysis_ids"]["valid_b"],
            ids["users"]["a"],
            ids["profiles"]["a"],
        ) == 0
        for key in ("same_name", "unique_name"):
            assert await connection.fetchval(
                """
                SELECT COUNT(*) FROM tender_analyses
                WHERE id = $1 AND user_id = $2 AND company_profile_id = $3
                  AND ownership_state = 'OWNED'
                """,
                ids["analysis_ids"][key],
                ids["users"]["a"],
                ids["profiles"]["a"],
            ) == 0

        # Old code can roll through the additive schema only by creating a
        # quarantined row; it can never create customer-visible ownership.
        old_code_id = uuid4()
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id, tender_id, tender_file_name, company_name,
                raw_extracted_text, analysis_json
            ) VALUES ($1, $2, 'rolling.pdf', 'Acme Engineering',
                      'rolling old code', '{}'::jsonb)
            """,
            old_code_id,
            ids["tender_id"],
        )
        rolling = await connection.fetchrow(
            """
            SELECT user_id, company_profile_id, ownership_state
            FROM tender_analyses WHERE id = $1
            """,
            old_code_id,
        )
        assert tuple(rolling) == (None, None, "QUARANTINED_LEGACY")

        rejected = False
        try:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO tender_analyses (
                        id, tender_id, tender_file_name, company_name,
                        raw_extracted_text, analysis_json, ownership_state
                    ) VALUES ($1, $2, 'invalid.pdf', 'metadata', 'invalid',
                              '{}'::jsonb, 'OWNED')
                    """,
                    uuid4(),
                    ids["tender_id"],
                )
        except asyncpg.CheckViolationError:
            rejected = True
        assert rejected

        schema = await connection.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE column_name IN (
                'user_id', 'company_profile_id', 'ownership_state'
              )) AS ownership_columns,
              (SELECT COUNT(*) FROM pg_indexes
               WHERE tablename = 'tender_analyses'
                 AND indexname IN (
                   'ix_tender_analyses_user_id',
                   'ix_tender_analyses_company_profile_id'
                 )) AS ownership_indexes,
              (SELECT COUNT(*) FROM pg_constraint
               WHERE conrelid = 'tender_analyses'::regclass
                 AND conname IN (
                   'tender_analyses_user_id_fkey',
                   'tender_analyses_company_profile_id_fkey',
                   'ck_tender_analyses_ownership_tuple'
                 )) AS ownership_constraints
            FROM information_schema.columns
            WHERE table_name = 'tender_analyses'
            """
        )
        assert tuple(schema) == (3, 2, 3)

        transaction = connection.transaction(readonly=True)
        await transaction.start()
        try:
            runner = preflight.ReadOnlyPreflight(connection, timeout=30.0)
            await runner.load_catalog()
            report = await runner.analysis_audit()
        finally:
            await transaction.rollback()
        canonical = report["data"]["canonical_ownership"]
        assert canonical == {
            "total_analyses": 11,
            "owned": 2,
            "quarantined": 9,
            "invalid_fk": 0,
            "user_profile_mismatch": 0,
            "invalid_ownership_tuple": 0,
            "quarantined_encoded_remnants": 4,
            "quarantined_legacy_name_or_malformed_remnants": 4,
        }
        return {**counts, "preflight": canonical}
    finally:
        await connection.close()


async def _fresh_database_scenario() -> dict[str, Any]:
    database = support.database_name("s21_fresh")
    await support.create_database(database)
    try:
        result = await asyncio.to_thread(support.run_bootstrap, database)
        if result.returncode:
            raise AssertionError((result.stderr or result.stdout)[-4000:])
        assert await _revision(database) == HEAD
        connection = await support.database_connection(database)
        try:
            assert await connection.fetchval("SELECT COUNT(*) FROM tender_analyses") == 0
        finally:
            await connection.close()
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0
        return {"head": HEAD, "analyses": 0, "alembic_check": "clean"}
    finally:
        await support.drop_database(database)


async def _existing_database_scenario() -> dict[str, Any]:
    database = support.database_name("s21_existing")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", S1_HEAD)
        ids = await _seed_s1_database(database)
        before = await _preservation_snapshot(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        assert await _revision(database) == HEAD
        counts = await _verify_existing_upgrade(database, ids)
        after = await _preservation_snapshot(database)
        # Ignore only the rolling-compatibility row added after migration.
        before_by_id = {row[0]: row for row in before["analyses"]}
        after_by_id = {row[0]: row for row in after["analyses"]}
        assert {key: after_by_id[key] for key in before_by_id} == before_by_id
        assert after["artifacts"] == before["artifacts"]
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0
        return {
            "head": HEAD,
            "fixture_counts": counts,
            "historical_rows_preserved": len(before["analyses"]),
            "related_artifacts_preserved": True,
            "alembic_check": "clean",
        }
    finally:
        await support.drop_database(database)


async def main() -> int:
    results = {
        "fresh_database": await _fresh_database_scenario(),
        "existing_database": await _existing_database_scenario(),
    }
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
