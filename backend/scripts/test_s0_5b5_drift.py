#!/usr/bin/env python3
"""Disposable PostgreSQL proof for metadata-only S0.5B.5 drift closure."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable
from uuid import uuid4

import asyncpg

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts import bootstrap_database as bootstrap
from scripts import test_s0_5b4_baseline as support


BASELINE = "20260824_0002_s0_4c"
HEAD = "20260828_0002_s3_4_admin_audit_hardening"
CANONICAL_COMMENT = (
    "SHA-256 seal incorporating override state. "
    "Null when no overrides have been applied."
)


async def seed_contract_rows(database: str) -> dict[str, str]:
    user_id = uuid4()
    tender_id = uuid4()
    proposal_id = uuid4()
    analysis_id = uuid4()
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            """
            INSERT INTO users (
                id, subscription_tier, is_admin, google_id, email, name
            ) VALUES ($1, 'SCOUT', false, $2, $3, $4)
            """,
            user_id,
            f"google-{user_id}",
            f"{user_id}@example.test",
            "S0.5B.5 User",
        )
        await connection.execute(
            """
            INSERT INTO tenders (
                id, external_id, source_url, title, budget, currency,
                status, category, source_system, canonical_source_key
            ) VALUES ($1, $2, $3, $4, 1000, 'UZS', 'OPEN', 'Other', 'uzex', $5)
            """,
            tender_id,
            f"S05B5-{tender_id}",
            "https://example.test/tender",
            "S0.5B.5 Tender",
            f"uzex:{tender_id}",
        )
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, final_pdf_url, margin_percent, include_vat, currency
            ) VALUES ($1, $2, $3, 'DRAFT', 73, $4::json, $5, 17.5, true, 'UZS')
            """,
            proposal_id,
            user_id,
            tender_id,
            json.dumps({"preserve": "exact", "nested": {"value": 5}}),
            "https://example.test/proposal.pdf",
        )
        override_seal = "a" * 64
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id, tender_id, tender_file_name, company_name,
                raw_extracted_text, analysis_json, content_hash, override_seal
            ) VALUES ($1, $2, 'requirements.pdf', 'owner-key', 'exact source text',
                      $3::jsonb, $4, $5)
            """,
            analysis_id,
            tender_id,
            json.dumps({"evaluation": {"status": "preserve"}}),
            "b" * 64,
            override_seal,
        )
        return {
            "user_id": str(user_id),
            "tender_id": str(tender_id),
            "proposal_id": str(proposal_id),
            "analysis_id": str(analysis_id),
            "override_seal": override_seal,
        }
    finally:
        await connection.close()


async def business_snapshot(database: str, ids: dict[str, str]) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        proposal = await connection.fetchrow(
            """
            SELECT id::text, user_id::text, tender_id::text, status::text,
                   ai_confidence_score, structured_data::text, final_pdf_url,
                   margin_percent, include_vat, currency, created_at
            FROM proposals WHERE id = $1::uuid
            """,
            ids["proposal_id"],
        )
        analysis = await connection.fetchrow(
            """
            SELECT id::text, tender_id::text, tender_file_name, company_name,
                   raw_extracted_text, analysis_json::text, content_hash,
                   override_seal, created_at
            FROM tender_analyses WHERE id = $1::uuid
            """,
            ids["analysis_id"],
        )
        return {"proposal": dict(proposal), "analysis": dict(analysis)}
    finally:
        await connection.close()


async def physical_contract(database: str) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        constraint = await connection.fetchrow(
            """
            SELECT c.conname, c.contype::text, pg_get_constraintdef(c.oid) AS definition,
                   i.relname AS index_name
            FROM pg_constraint c
            JOIN pg_class i ON i.oid = c.conindid
            WHERE c.conrelid = 'public.proposals'::regclass
              AND c.conname = 'uq_proposals_user_tender'
            """
        )
        comment = await connection.fetchval(
            """
            SELECT col_description('public.tender_analyses'::regclass::oid, a.attnum)
            FROM pg_attribute a
            WHERE a.attrelid = 'public.tender_analyses'::regclass
              AND a.attname = 'override_seal'
            """
        )
        column = await connection.fetchrow(
            """
            SELECT data_type, character_maximum_length, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'tender_analyses'
              AND column_name = 'override_seal'
            """
        )
        return {
            "constraint": dict(constraint) if constraint else None,
            "comment": comment,
            "column": dict(column) if column else None,
        }
    finally:
        await connection.close()


async def assert_duplicate_rejected(database: str, ids: dict[str, str]) -> None:
    connection = await support.database_connection(database)
    try:
        try:
            await connection.execute(
                """
                INSERT INTO proposals (
                    id, user_id, tender_id, status, ai_confidence_score,
                    structured_data, margin_percent, include_vat, currency
                ) VALUES ($1, $2::uuid, $3::uuid, 'COMPLETED', 1,
                          '{"duplicate": true}'::json, 1, false, 'USD')
                """,
                uuid4(),
                ids["user_id"],
                ids["tender_id"],
            )
        except asyncpg.UniqueViolationError as exc:
            assert exc.constraint_name == "uq_proposals_user_tender"
        else:
            raise AssertionError("database accepted duplicate Proposal user+tender")
        assert await connection.fetchval("SELECT count(*) FROM proposals") == 1
    finally:
        await connection.close()


async def assert_clean_check(database: str) -> None:
    result = await asyncio.to_thread(support.alembic, database, "check", success=False)
    diagnostic = result.stdout + result.stderr
    assert result.returncode == 0, diagnostic
    assert "No new upgrade operations detected" in diagnostic
    for forbidden in (
        "uq_proposals_user_tender",
        "override_seal",
        "tender_recommendations",
        "New upgrade operations detected",
    ):
        assert forbidden not in diagnostic


async def fresh_scenario(database: str) -> dict[str, Any]:
    result = await asyncio.to_thread(support.run_bootstrap, database)
    assert result.returncode == 0, result.stderr or result.stdout
    ids = await seed_contract_rows(database)
    await assert_duplicate_rejected(database, ids)
    contract = await physical_contract(database)
    assert contract["constraint"]["definition"] == "UNIQUE (user_id, tender_id)"
    assert contract["constraint"]["index_name"] == "uq_proposals_user_tender"
    assert contract["comment"] == CANONICAL_COMMENT
    assert contract["column"] == {
        "data_type": "character varying",
        "character_maximum_length": 64,
        "is_nullable": "YES",
    }
    await assert_clean_check(database)
    connection = await support.database_connection(database)
    try:
        assert await bootstrap.current_revision(connection) == HEAD
        assert await connection.fetchval("SELECT count(*) FROM tender_recommendations") == 0
    finally:
        await connection.close()
    return {"head": HEAD, "duplicate_rejected": True, "alembic_check": "clean"}


async def existing_upgrade_scenario(database: str) -> dict[str, Any]:
    await support.raw_baseline(database)
    ids = await seed_contract_rows(database)
    before = await business_snapshot(database, ids)
    connection = await support.database_connection(database)
    try:
        before_oids = tuple(
            await connection.fetchrow(
                """
                SELECT 'public.proposals'::regclass::oid AS proposals,
                       'public.tender_analyses'::regclass::oid AS analyses
                """
            )
        )
        assert await bootstrap.current_revision(connection) == BASELINE
    finally:
        await connection.close()

    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    after = await business_snapshot(database, ids)
    assert after == before
    await assert_duplicate_rejected(database, ids)
    await assert_clean_check(database)

    connection = await support.database_connection(database)
    try:
        after_oids = tuple(
            await connection.fetchrow(
                """
                SELECT 'public.proposals'::regclass::oid AS proposals,
                       'public.tender_analyses'::regclass::oid AS analyses
                """
            )
        )
        assert after_oids == before_oids
        assert await bootstrap.current_revision(connection) == HEAD
        assert await connection.fetchval("SELECT count(*) FROM proposals") == 1
        assert await connection.fetchval("SELECT count(*) FROM tender_analyses") == 1
        assert await connection.fetchval(
            "SELECT override_seal FROM tender_analyses WHERE id = $1::uuid",
            ids["analysis_id"],
        ) == ids["override_seal"]
    finally:
        await connection.close()
    return {
        "from": BASELINE,
        "to": HEAD,
        "proposal_rows_preserved": 1,
        "analysis_rows_preserved": 1,
        "tables_not_recreated": True,
        "alembic_check": "clean",
    }


async def with_database(
    label: str,
    scenario: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    database = support.database_name(f"s05b5_{label}")
    await support.create_database(database)
    try:
        return {"scenario": label, "status": "passed", **await scenario(database)}
    finally:
        await support.drop_database(database)


async def main() -> int:
    results: list[dict[str, Any]] = []
    failures = 0
    for label, scenario in (("fresh", fresh_scenario), ("existing_upgrade", existing_upgrade_scenario)):
        try:
            results.append(await with_database(label, scenario))
        except Exception as exc:
            failures += 1
            results.append({"scenario": label, "status": "failed", "error": str(exc)})
    leaks = await support.leaked_databases()
    if leaks:
        failures += 1
    print(json.dumps({"results": results, "leaked_databases": leaks, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
