#!/usr/bin/env python3
"""Disposable PostgreSQL 16 proof for the S5.2 Tender Details read model."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import perf_counter
import sys
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.endpoints.tenders import get_tender_details, get_tender_documents
from app.models.all_models import User
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


async def seed_user(
    connection: asyncpg.Connection,
    label: str,
    *,
    company_name: str | None,
    is_admin: bool = False,
) -> tuple[UUID, UUID | None]:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',$5,'approved',$6,0)
        """,
        user_id,
        f"s52-{label}-{user_id}",
        f"{label}-{user_id}@s52.invalid",
        label,
        is_admin,
        "admin" if is_admin else "pilot_user",
    )
    if company_name is None:
        return user_id, None
    profile_id = uuid4()
    await connection.execute(
        """
        INSERT INTO company_profiles (
            id,user_id,company_name,pilot_status,approval_status
        ) VALUES ($1,$2,$3,'active_pilot','approved')
        """,
        profile_id,
        user_id,
        company_name,
    )
    return user_id, profile_id


async def seed_tender(
    connection: asyncpg.Connection,
    label: str,
    *,
    source_system: str = "world_bank",
) -> UUID:
    tender_id = uuid4()
    metadata = {
        "contact_person": f"Procurement Contact {label}",
        "email": f"procurement-{label}@example.invalid",
        "submission_method": "Electronic portal",
    }
    await connection.execute(
        """
        INSERT INTO tenders (
            id,external_id,source_system,canonical_source_key,source_url,title,
            description,budget,currency,deadline,buyer,source_metadata_json,
            status,category
        ) VALUES (
            $1,$2,$3,$4,$5,$6,'Local canonical fixture',1000,'USD',
            '2026-09-30T00:00:00Z',$7,$8::jsonb,'OPEN','Services'
        )
        """,
        tender_id,
        f"S52-{label}-{tender_id}",
        source_system,
        f"{source_system}:s52:{label}:{tender_id}",
        f"https://example.invalid/{source_system}/{tender_id}",
        f"S5.2 {label}",
        f"Buyer {label}",
        json.dumps(metadata),
    )
    return tender_id


async def seed_project(connection: asyncpg.Connection, tender_id: UUID) -> UUID:
    project_id = uuid4()
    await connection.execute(
        """
        INSERT INTO projects (
            id,source_system,external_project_id,name,country,project_status,
            enrichment_status
        ) VALUES ($1,'world_bank',$2,'Canonical Project','Uzbekistan','active','queued')
        """,
        project_id,
        f"P-{project_id.hex[:12]}",
    )
    await connection.execute(
        """
        INSERT INTO tender_projects (
            id,tender_id,project_id,linkage_method,source_value,provenance
        ) VALUES ($1,$2,$3,'SOURCE_PROJECT_ID',$4,'{}'::jsonb)
        """,
        uuid4(),
        tender_id,
        project_id,
        f"P-{project_id.hex[:12]}",
    )
    return project_id


async def add_role(connection: asyncpg.Connection, project_id: UUID, index: int) -> None:
    await connection.execute(
        """
        INSERT INTO project_role_assignments (
            id,project_id,source_system,assignment_key,display_name,native_role,
            canonical_role,source_url,provenance,is_current,first_observed_at,
            last_observed_at
        ) VALUES (
            $1,$2,'world_bank',$3,$4,'Task Team Leader','TASK_TEAM_LEADER',$5,
            '{}'::jsonb,true,'2026-08-01T00:00:00Z','2026-08-29T00:00:00Z'
        )
        """,
        uuid4(),
        project_id,
        f"role-{index}",
        f"Project Leader {index}",
        f"https://example.invalid/project/{project_id}",
    )


async def add_document(
    connection: asyncpg.Connection,
    tender_id: UUID,
    index: int,
    *,
    public: bool = True,
) -> None:
    source_url = f"https://example.invalid/docs/notice-{index}.pdf" if public else None
    source_type = "PROCUREMENT_NOTICE" if public else None
    await connection.execute(
        """
        INSERT INTO tender_documents (
            id,tender_id,file_url,file_type,source_document_url,
            source_document_type,download_status,file_size,mime_type
        ) VALUES ($1,$2,$3,'pdf',$4,$5,$6,2048,'application/pdf')
        """,
        uuid4(),
        tender_id,
        source_url or f"legacy://unknown/{index}",
        source_url,
        source_type,
        "downloaded" if public else "legacy",
    )


async def seed_private_context(
    connection: asyncpg.Connection,
    *,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
    engagement_status: str | None = None,
    proposal_status: str | None = None,
    compliance_status: str | None = None,
    completeness: str = "COMPLETE",
    version_origin: str = "RUNTIME_ANALYSIS",
    version_count: int = 1,
    zero_version: bool = False,
) -> None:
    if engagement_status:
        await connection.execute(
            """
            INSERT INTO tender_engagements (
                id,user_id,company_profile_id,tender_id,status,origin
            ) VALUES ($1,$2,$3,$4,$5::tender_engagement_status,'MANUAL_SAVE')
            """,
            uuid4(), user_id, profile_id, tender_id, engagement_status,
        )
    if proposal_status:
        await connection.execute(
            """
            INSERT INTO proposals (
                id,user_id,tender_id,status,ai_confidence_score,structured_data,
                margin_percent,include_vat,currency
            ) VALUES ($1,$2,$3,$4::proposal_status,0,'{}'::json,20,true,'USD')
            """,
            uuid4(), user_id, tender_id, proposal_status,
        )
    if compliance_status:
        analysis_id = uuid4()
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id,tender_id,tender_file_name,user_id,company_profile_id,
                ownership_state,company_name,raw_extracted_text,analysis_json,
                content_hash,created_at
            ) VALUES (
                $1,$2,'fixture.pdf',$3,$4,'OWNED','display snapshot','private text',
                '{"parent_mirror":"adversarial"}'::jsonb,$5,NOW()
            )
            """,
            analysis_id, tender_id, user_id, profile_id, "a" * 64,
        )
        if zero_version:
            return
        previous_id = None
        for version_number in range(1, version_count + 1):
            version_id = uuid4()
            result = {
                "hybrid_compliance": {
                    "verdict_status": "COMPLIANT",
                    "failed_count": version_number,
                },
                "coverage_metadata": {"coverage_status": "complete"},
                "requirements": [
                    {
                        "requirement": f"Requirement v{version_number}",
                        "evidence": {
                            "document_name": "notice.pdf",
                            "page": version_number,
                            "section": "Eligibility",
                        },
                    }
                ],
            }
            await connection.execute(
                """
                INSERT INTO analysis_versions (
                    id,analysis_id,version_number,supersedes_version_id,origin,status,
                    provenance_snapshot,tender_snapshot,company_snapshot,
                    result_snapshot,evidence_snapshot,snapshot_completeness,
                    requested_by_user_id,completed_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,
                    $7::jsonb,'{}'::jsonb,$8,$9,NOW()
                )
                """,
                version_id, analysis_id, version_number, previous_id,
                version_origin, compliance_status, json.dumps(result), completeness,
                user_id,
            )
            previous_id = version_id


async def seed_readiness(
    connection: asyncpg.Connection,
    *,
    profile_id: UUID,
    extra_documents: int = 0,
) -> None:
    taxonomy_id = uuid4()
    await connection.execute(
        """
        INSERT INTO taxonomy_nodes (id,category,name,impact_weight,is_fatal)
        VALUES ($1,'CERTIFICATION',$2,10,false)
        """,
        taxonomy_id,
        f"ISO-{taxonomy_id}",
    )
    await connection.execute(
        """
        INSERT INTO company_credentials (
            id,company_profile_id,taxonomy_node_id,value,expiration_date
        ) VALUES ($1,$2,$3,'present','2025-01-01')
        """,
        uuid4(), profile_id, taxonomy_id,
    )
    await connection.execute(
        """
        INSERT INTO certifications (id,company_id,cert_type,issue_date,expiry_date)
        VALUES ($1,$2,'ISO','2020-01-01','2025-01-01')
        """,
        uuid4(), profile_id,
    )
    await connection.execute(
        "INSERT INTO licenses (id,company_id,license_name,is_active) VALUES ($1,$2,'Trade',true)",
        uuid4(), profile_id,
    )
    await connection.execute(
        "INSERT INTO financial_history (id,company_id,year,turnover_uzs) VALUES ($1,$2,2025,1000)",
        uuid4(), profile_id,
    )
    for index in range(extra_documents + 1):
        status = ("available", "missing", "expired", "unknown")[index % 4]
        await connection.execute(
            """
            INSERT INTO readiness_documents (
                id,company_profile_id,document_type,document_name,status,
                optional_file_url
            ) VALUES ($1,$2,'certificate',$3,$4,$5)
            """,
            uuid4(), profile_id, f"Private readiness {index}", status,
            f"private://never-expose/{index}",
        )


async def fingerprint(connection: asyncpg.Connection, tender_id: UUID) -> dict[str, Any]:
    tables = (
        "tenders", "tender_documents", "projects", "tender_projects",
        "project_role_assignments", "tender_analyses", "analysis_versions",
        "company_profiles", "readiness_documents", "tender_engagements", "proposals",
    )
    return {
        "counts": {
            table: int(await connection.fetchval(f"SELECT COUNT(*) FROM {table}"))
            for table in tables
        },
        "tender_dates": tuple(
            await connection.fetchrow(
                "SELECT publication_date,deadline FROM tenders WHERE id=$1", tender_id
            )
        ),
        "engagement_timestamps": [
            tuple(row)
            for row in await connection.fetch(
                "SELECT id,updated_at,status_changed_at FROM tender_engagements ORDER BY id"
            )
        ],
    }


async def call_details(sessions, user_id: UUID, tender_id: UUID):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        statement_count = 0

        def count_statement(*_args):
            nonlocal statement_count
            statement_count += 1

        event.listen(session.sync_session.bind, "before_cursor_execute", count_statement)
        started = perf_counter()
        try:
            response = await get_tender_details(tender_id, user, session)
            elapsed_ms = (perf_counter() - started) * 1000
            assert not session.new and not session.dirty and not session.deleted
        finally:
            event.remove(session.sync_session.bind, "before_cursor_execute", count_statement)
        return response, statement_count, elapsed_ms


async def run_matrix(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert int(await connection.fetchval("SHOW server_version_num")) // 10000 == 16
        user_a, profile_a = await seed_user(
            connection, "owner-a", company_name="Acme Engineering"
        )
        user_b, profile_b = await seed_user(
            connection, "owner-b", company_name="Acme Engineering"
        )
        user_c, profile_c = await seed_user(
            connection, "viewer-c", company_name="Viewer Company"
        )
        admin_id, _ = await seed_user(
            connection, "platform-admin", company_name=None, is_admin=True
        )
        assert profile_a and profile_b and profile_c

        full_tender = await seed_tender(connection, "all-domains")
        project_id = await seed_project(connection, full_tender)
        await add_role(connection, project_id, 0)
        await add_document(connection, full_tender, 0)
        await add_document(connection, full_tender, 999, public=False)
        await seed_readiness(connection, profile_id=profile_a)
        await seed_readiness(connection, profile_id=profile_b)
        await seed_private_context(
            connection, user_id=user_a, profile_id=profile_a, tender_id=full_tender,
            engagement_status="PREPARING", proposal_status="COMPLETED",
            compliance_status="COMPLETED", version_count=2,
        )
        await seed_private_context(
            connection, user_id=user_b, profile_id=profile_b, tender_id=full_tender,
            engagement_status="SAVED", compliance_status="FAILED",
            completeness="PARTIAL", version_origin="LEGACY_BACKFILL",
        )

        tender_only = await seed_tender(connection, "tender-only")
        project_only = await seed_tender(connection, "project-only")
        await seed_project(connection, project_only)
        compliance_only = await seed_tender(connection, "compliance-only")
        await seed_private_context(
            connection, user_id=user_a, profile_id=profile_a,
            tender_id=compliance_only, compliance_status="COMPLETED",
        )
        engagement_only = await seed_tender(connection, "engagement-only")
        await seed_private_context(
            connection, user_id=user_a, profile_id=profile_a,
            tender_id=engagement_only, engagement_status="EVALUATING",
        )
        proposal_only = await seed_tender(connection, "proposal-only")
        await seed_private_context(
            connection, user_id=user_a, profile_id=profile_a,
            tender_id=proposal_only, proposal_status="SUBMITTED",
        )
        zero_version = await seed_tender(connection, "zero-version")
        await seed_private_context(
            connection, user_id=user_a, profile_id=profile_a,
            tender_id=zero_version, compliance_status="COMPLETED", zero_version=True,
        )

        before = await fingerprint(connection, full_tender)
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=12, max_overflow=12)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        initial, initial_queries, _ = await call_details(sessions, user_a, full_tender)
        assert initial.project_context.data is not None
        assert initial.project_context.data.enrichment_state == "queued"
        assert initial.project_leadership.data is not None
        assert initial.project_leadership.data.items[0].display_name == "Project Leader 0"
        assert initial.procurement_contacts.data is not None
        assert initial.procurement_contacts.data.contact_person == "Procurement Contact all-domains"
        assert initial.compliance.data is not None
        assert initial.compliance.data.version_number == 2
        assert initial.compliance.data.decision_label == "COMPLIANT"
        assert initial.requirements.data is not None
        assert initial.requirements.data.items[0].source_type == "ANALYSIS_DERIVED"
        assert initial.pursuit.data is not None
        assert initial.pursuit.data.engagement_status.value == "PREPARING"
        assert initial.bid_preparation.data is not None
        assert initial.bid_preparation.data.proposal_status.value == "COMPLETED"
        assert initial.documents.data is not None
        assert initial.documents.data.omitted_unknown_count == 1
        assert initial.documents.data.download_authorization_separate is True

        connection = await support.database_connection(database)
        try:
            for index in range(1, 10):
                await add_role(connection, project_id, index)
            for index in range(1, 25):
                await add_document(connection, full_tender, index)
            for index in range(1, 21):
                await connection.execute(
                    """
                    INSERT INTO readiness_documents (
                        id,company_profile_id,document_type,document_name,status,
                        optional_file_url
                    ) VALUES ($1,$2,'certificate',$3,$4,$5)
                    """,
                    uuid4(), profile_a, f"Private readiness extra {index}",
                    ("available", "missing", "expired", "unknown")[index % 4],
                    f"private://never-expose/extra/{index}",
                )
        finally:
            await connection.close()

        expanded, expanded_queries, expanded_ms = await call_details(
            sessions, user_a, full_tender
        )
        assert expanded_queries == initial_queries, (initial_queries, expanded_queries)
        assert expanded.project_leadership.data is not None
        assert expanded.project_leadership.data.total_count == 10
        assert expanded.documents.data is not None
        assert expanded.documents.data.visible_total_count == 25
        assert expanded.documents.data.returned_count == 25

        owner_b, _, _ = await call_details(sessions, user_b, full_tender)
        assert owner_b.pursuit.data is not None
        assert owner_b.pursuit.data.engagement_status.value == "SAVED"
        assert owner_b.bid_preparation.state.value == "EMPTY"
        assert owner_b.compliance.state.value == "UNAVAILABLE"
        assert owner_b.compliance.data is not None
        assert owner_b.compliance.data.decision_label == "FAILED"
        assert owner_b.compliance.data.version_origin == "LEGACY_BACKFILL"

        foreign, _, _ = await call_details(sessions, user_c, full_tender)
        assert foreign.compliance.state.value == "EMPTY"
        assert foreign.pursuit.state.value == "EMPTY"
        assert foreign.bid_preparation.state.value == "EMPTY"
        assert foreign.company_readiness.data is not None
        assert foreign.company_readiness.data.readiness_documents_total == 0
        async with sessions() as session:
            foreign_user = await session.scalar(select(User).where(User.id == user_c))
            assert foreign_user is not None
            try:
                await get_tender_documents(full_tender, foreign_user, session)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("details metadata weakened document access")

        admin, _, _ = await call_details(sessions, admin_id, full_tender)
        assert admin.compliance.state.value == "EMPTY"
        assert admin.company_readiness.state.value == "EMPTY"
        assert admin.pursuit.state.value == "EMPTY"
        assert admin.bid_preparation.state.value == "EMPTY"

        proposal_view, _, _ = await call_details(sessions, user_a, proposal_only)
        assert proposal_view.pursuit.state.value == "EMPTY"
        assert proposal_view.bid_preparation.state.value == "AVAILABLE"
        engagement_view, _, _ = await call_details(sessions, user_a, engagement_only)
        assert engagement_view.pursuit.state.value == "AVAILABLE"
        assert engagement_view.bid_preparation.state.value == "EMPTY"
        compliance_view, _, _ = await call_details(sessions, user_a, compliance_only)
        assert compliance_view.compliance.state.value == "AVAILABLE"
        assert compliance_view.pursuit.state.value == "EMPTY"
        assert compliance_view.bid_preparation.state.value == "EMPTY"
        empty_view, _, _ = await call_details(sessions, user_a, tender_only)
        assert empty_view.project_context.state.value == "EMPTY"
        assert empty_view.documents.state.value == "EMPTY"
        zero_view, _, _ = await call_details(sessions, user_a, zero_version)
        assert zero_view.compliance.state.value == "UNAVAILABLE"

        connection = await support.database_connection(database)
        try:
            await connection.execute(
                "UPDATE projects SET enrichment_status='source_unavailable' WHERE id=$1",
                project_id,
            )
        finally:
            await connection.close()
        degraded, _, _ = await call_details(sessions, user_a, full_tender)
        assert degraded.project_context.state.value == "UNAVAILABLE"
        assert degraded.pursuit.state.value == "AVAILABLE"

        repeated, _, _ = await call_details(sessions, user_a, full_tender)
        assert repeated.model_dump(mode="json") == degraded.model_dump(mode="json")

        concurrent = await asyncio.gather(
            *(call_details(sessions, user_a, full_tender) for _ in range(8))
        )
        assert all(
            response.model_dump(mode="json") == degraded.model_dump(mode="json")
            for response, _, _ in concurrent
        )

        async def transition_engagement() -> None:
            mutation_connection = await support.database_connection(database)
            try:
                await mutation_connection.execute(
                    """
                    UPDATE tender_engagements
                    SET status='SUBMITTED',status_changed_at=NOW(),updated_at=NOW()
                    WHERE user_id=$1 AND company_profile_id=$2 AND tender_id=$3
                    """,
                    user_a, profile_a, full_tender,
                )
            finally:
                await mutation_connection.close()

        during_engagement, _ = await asyncio.gather(
            call_details(sessions, user_a, full_tender),
            transition_engagement(),
        )
        engagement_response = during_engagement[0]
        assert engagement_response.pursuit.data is not None
        assert engagement_response.pursuit.data.engagement_status.value in {
            "PREPARING", "SUBMITTED"
        }

        async def append_version() -> None:
            mutation_connection = await support.database_connection(database)
            try:
                analysis_row = await mutation_connection.fetchrow(
                    """
                    SELECT a.id AS analysis_id,v.id AS version_id
                    FROM tender_analyses a
                    JOIN analysis_versions v ON v.analysis_id=a.id
                    WHERE a.user_id=$1 AND a.company_profile_id=$2 AND a.tender_id=$3
                    ORDER BY v.version_number DESC LIMIT 1
                    """,
                    user_a, profile_a, full_tender,
                )
                assert analysis_row is not None
                result = {
                    "hybrid_compliance": {
                        "verdict_status": "REVIEW_REQUIRED", "failed_count": 2
                    },
                    "requirements": [{"requirement": "Concurrent v3"}],
                }
                await mutation_connection.execute(
                    """
                    INSERT INTO analysis_versions (
                        id,analysis_id,version_number,supersedes_version_id,origin,status,
                        provenance_snapshot,tender_snapshot,company_snapshot,
                        result_snapshot,evidence_snapshot,snapshot_completeness,
                        requested_by_user_id,completed_at
                    ) VALUES (
                        $1,$2,3,$3,'RUNTIME_REANALYSIS','NEEDS_REVIEW',
                        '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$4::jsonb,'{}'::jsonb,
                        'PARTIAL',$5,NOW()
                    )
                    """,
                    uuid4(), analysis_row["analysis_id"], analysis_row["version_id"],
                    json.dumps(result), user_a,
                )
            finally:
                await mutation_connection.close()

        during_version, _ = await asyncio.gather(
            call_details(sessions, user_a, full_tender),
            append_version(),
        )
        version_response = during_version[0]
        assert version_response.compliance.data is not None
        assert version_response.compliance.data.version_number in {2, 3}

        connection = await support.database_connection(database)
        try:
            after = await fingerprint(connection, full_tender)
            assert after["tender_dates"] == before["tender_dates"]
            # Only explicit fixture expansion changed counts; repeated reads changed none.
            stable_before = await fingerprint(connection, full_tender)
        finally:
            await connection.close()
        await call_details(sessions, user_a, full_tender)
        connection = await support.database_connection(database)
        try:
            stable_after = await fingerprint(connection, full_tender)
            assert stable_after == stable_before
        finally:
            await connection.close()

        response_bytes = len(
            json.dumps(expanded.model_dump(mode="json"), separators=(",", ":")).encode()
        )
        response_payload = json.dumps(expanded.model_dump(mode="json"))
        for forbidden in (
            "private://", "storage_path", "parsed_text", "analysis_json",
            "result_snapshot", "final_pdf_url", "structured_data",
        ):
            assert forbidden not in response_payload
        preflight_env = support.environment(database)
        preflight = await asyncio.create_subprocess_exec(
            sys.executable,
            "scripts/run_s0_3_schema_data_preflight.py",
            "--compact",
            cwd=BACKEND_DIR,
            env=preflight_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await preflight.communicate()
        assert preflight.returncode == 0, stderr.decode()[-4000:]
        preflight_json = json.loads(stdout)
        composition = preflight_json["tender_details_composition"]
        assert composition["available"] is True
        assert composition["integrity"]["zero_version_analysis_parents"] == 1

        return {
            "postgres_major": 16,
            "head": HEAD,
            "fixture": {
                "documents": 26,
                "public_documents": 25,
                "unknown_documents": 1,
                "project_roles": 10,
                "readiness_documents_for_owner_a": 21,
                "analysis_versions_for_owner_a": 2,
                "same_name_tenants": 2,
                "concurrent_reads": 8,
            },
            "query_count": expanded_queries,
            "query_count_before_expansion": initial_queries,
            "runtime_ms": round(expanded_ms, 3),
            "response_bytes": response_bytes,
            "preflight": composition,
            "read_only_repeatability": True,
            "read_during_engagement_mutation": True,
            "read_during_analysis_version_append": True,
            "document_download_separation": True,
            "tenant_isolation": True,
            "platform_admin_isolation": True,
            "parent_mirror_ignored": True,
        }
    finally:
        await engine.dispose()


async def main() -> None:
    database = support.database_name("s52_details")
    await support.create_database(database)
    try:
        result = await run_matrix(database)
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, (check.stderr or check.stdout)[-4000:]
        current = await asyncio.to_thread(support.alembic, database, "current")
        assert HEAD in current.stdout
        result["alembic_check"] = "clean"
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    asyncio.run(main())
