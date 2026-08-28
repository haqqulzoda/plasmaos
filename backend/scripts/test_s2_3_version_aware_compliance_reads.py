#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for Sprint 2.3 version-aware reads."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.all_models import TenderAnalysis
from app.models.audit import (
    ANALYSIS_OWNERSHIP_OWNED,
    AnalysisVersionMutationError,
)
from app.services.analysis_aggregates import get_owned_analysis_parent_for_tender
from app.services.analysis_versions import (
    AnalysisVersionIntegrityError,
    append_analysis_version,
    get_analysis_version,
    get_latest_analysis_version,
    get_versioned_analysis_payload,
    list_analysis_versions,
    require_latest_analysis_version,
    verify_analysis_version_integrity,
)
from scripts import run_s0_3_schema_data_preflight as preflight
from scripts import test_s0_5b4_baseline as support
from scripts import test_s2_2_analysis_version_foundation as s22


HEAD = "20260828_0002_s3_4_admin_audit_hardening"
S2_1_HEAD = "20260827_0001_s2_1_compliance_ownership"


def version_values(fixture: dict, label: str) -> dict:
    values = s22.append_kwargs(fixture, label=label)
    values["result_snapshot"]["label"] = label
    values["result_snapshot"]["evidence_validation"] = {
        "accepted": [{"fixture": f"evidence-{label}"}]
    }
    values["evidence_snapshot"]["evidence_validation"] = deepcopy(
        values["result_snapshot"]["evidence_validation"]
    )
    values["tender_snapshot"]["title"] = f"Tender at {label}"
    values["company_snapshot"]["company_name"] = f"Company at {label}"
    values["input_hash"] = f"{int(label[1:]):064x}"
    return values


async def run_existing_database() -> dict:
    database = support.database_name("s23_existing")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        upgrade = await asyncio.to_thread(
            support.alembic, database, "upgrade", S2_1_HEAD
        )
        assert upgrade.returncode == 0, (upgrade.stderr or upgrade.stdout)[-4000:]
        fixture = await s22.seed_s2_1(database)
        upgrade = await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        assert upgrade.returncode == 0, (upgrade.stderr or upgrade.stdout)[-4000:]

        engine = create_async_engine(
            support.target_url(database), pool_size=3, max_overflow=3
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        chosen_parent_id = fixture["analysis_ids"]["owned_a_duplicate"]
        try:
            async with sessions() as session:
                chosen = await get_owned_analysis_parent_for_tender(
                    session,
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                    tender_id=fixture["tender_id"],
                )
                assert chosen is not None and chosen.id == chosen_parent_id

                v2 = await append_analysis_version(
                    session,
                    analysis_id=chosen_parent_id,
                    **version_values(fixture, "v2"),
                )
                v3 = await append_analysis_version(
                    session,
                    analysis_id=chosen_parent_id,
                    **version_values(fixture, "v3"),
                )
                assert (v2.version_number, v3.version_number) == (2, 3)
                await session.commit()

            connection = await support.database_connection(database)
            try:
                await connection.execute(
                    """
                    UPDATE tender_analyses
                    SET analysis_json = '{"label":"mutable-parent-mirror"}'::jsonb,
                        content_hash = $2
                    WHERE id = $1
                    """,
                    chosen_parent_id,
                    "f" * 64,
                )
                await connection.execute(
                    "UPDATE tenders SET title = 'Current tender drift' WHERE id = $1",
                    fixture["tender_id"],
                )
                await connection.execute(
                    "UPDATE company_profiles SET company_name = 'Current company drift' WHERE id = $1",
                    fixture["profiles"]["a"],
                )
                await connection.execute(
                    "UPDATE tender_documents SET parsed_text = 'current document drift' WHERE id = $1",
                    fixture["document_id"],
                )
            finally:
                await connection.close()

            async with sessions() as session:
                latest = await get_latest_analysis_version(
                    session,
                    analysis_id=chosen_parent_id,
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
                assert latest is not None
                assert latest.version_number == 3
                assert latest.result_snapshot["label"] == "v3"
                assert latest.result_snapshot.get("label") != "mutable-parent-mirror"

                history = await list_analysis_versions(
                    session,
                    analysis_id=chosen_parent_id,
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
                assert [item.version_number for item in history] == [1, 2, 3]
                assert history[1].supersedes_version_id == history[0].id
                assert history[2].supersedes_version_id == history[1].id

                specific_v2 = await get_analysis_version(
                    session,
                    analysis_id=chosen_parent_id,
                    version_number=2,
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
                assert specific_v2 is not None
                payload_v2 = get_versioned_analysis_payload(specific_v2)
                assert payload_v2["result_snapshot"]["label"] == "v2"
                assert payload_v2["evidence_snapshot"]["evidence_validation"] == {
                    "accepted": [{"fixture": "evidence-v2"}]
                }
                assert payload_v2["tender_snapshot"]["title"] == "Tender at v2"
                assert payload_v2["company_snapshot"]["company_name"] == "Company at v2"
                assert specific_v2.document_snapshots[0].content_hash == "6" * 64
                assert verify_analysis_version_integrity(specific_v2).overall_status == "VERIFIED"

                denied = await get_analysis_version(
                    session,
                    analysis_id=chosen_parent_id,
                    version_number=2,
                    user_id=fixture["users"]["b"],
                    company_profile_id=fixture["profiles"]["b"],
                )
                assert denied is None
                quarantined = await get_latest_analysis_version(
                    session,
                    analysis_id=fixture["analysis_ids"]["quarantined"],
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
                assert quarantined is None

                older_parent_history = await list_analysis_versions(
                    session,
                    analysis_id=fixture["analysis_ids"]["owned_a"],
                    user_id=fixture["users"]["a"],
                    company_profile_id=fixture["profiles"]["a"],
                )
                assert [item.version_number for item in older_parent_history] == [1]

                detached = get_versioned_analysis_payload(specific_v2)
                detached["result_snapshot"]["label"] = "caller mutation"
                assert specific_v2.result_snapshot["label"] == "v2"
                original_hash = specific_v2.version_hash
                try:
                    specific_v2.result_snapshot = {"label": "ordinary update"}
                except AnalysisVersionMutationError:
                    pass
                else:
                    raise AssertionError("persisted version mutation was allowed")
                specific_v2.__dict__["result_snapshot"] = {
                    "label": "low-level integrity probe"
                }
                mismatch = verify_analysis_version_integrity(specific_v2)
                assert mismatch.overall_status == "MISMATCH"
                assert specific_v2.version_hash == original_hash
                await session.rollback()

            zero_parent_id = uuid4()
            async with sessions() as session:
                session.add(
                    TenderAnalysis(
                        id=zero_parent_id,
                        tender_id=fixture["tender_id"],
                        tender_file_name="zero-version.pdf",
                        user_id=fixture["users"]["a"],
                        company_profile_id=fixture["profiles"]["a"],
                        ownership_state=ANALYSIS_OWNERSHIP_OWNED,
                        company_name="Current company drift",
                        raw_extracted_text="zero-version fixture",
                        analysis_json={"mirror": "must-not-be-authority"},
                        content_hash="0" * 64,
                    )
                )
                await session.commit()
            async with sessions() as session:
                try:
                    await require_latest_analysis_version(
                        session,
                        analysis_id=zero_parent_id,
                        user_id=fixture["users"]["a"],
                        company_profile_id=fixture["profiles"]["a"],
                    )
                except AnalysisVersionIntegrityError:
                    pass
                else:
                    raise AssertionError("zero-version parent used its mutable mirror")
        finally:
            await engine.dispose()

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
        data = report["data"]
        assert data["parent_distribution"]["analyses_with_zero_versions"] == 1
        assert data["multi_parent_owned_logical_keys"] == 1
        assert data["hash_verification"]["hash_mismatches_total"] == 0, data[
            "hash_verification"
        ]
        assert data["hash_verification"]["versions_checked"] == 5

        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, (check.stderr or check.stdout)[-4000:]
        return {
            "head": HEAD,
            "latest_version": 3,
            "separate_parent_histories": [[1], [1, 2, 3]],
            "parent_mirror_ignored": True,
            "snapshot_drift_preserved": True,
            "same_name_cross_tenant_denied": True,
            "quarantined_denied": True,
            "zero_version_anomaly": True,
            "hash_verification": data["hash_verification"],
            "alembic_check": "clean",
        }
    finally:
        await support.drop_database(database)


async def run_fresh_database() -> dict:
    database = support.database_name("s23_fresh")
    await support.create_database(database)
    try:
        result = await asyncio.to_thread(support.run_bootstrap, database)
        assert result.returncode == 0, (result.stderr or result.stdout)[-4000:]
        assert await s22.revision(database) == HEAD
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, (check.stderr or check.stdout)[-4000:]
        return {"head": HEAD, "alembic_check": "clean", "migration_added": False}
    finally:
        await support.drop_database(database)


async def main() -> None:
    payload = {
        "fresh_database": await run_fresh_database(),
        "existing_database": await run_existing_database(),
    }
    import json

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
