"""Real disposable PostgreSQL passivity, ownership and collection budgets."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.endpoints import admin, explorer, my_tenders, proposals, tenders, users, vault
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.all_models import Tender, TenderDocument, Proposal, User
from app.models.engagement import TenderEngagement
from app.models.base import TenderEngagementStatus, TenderEngagementOrigin
from app.models.audit import TenderAnalysis, AnalysisVersion
from app.models.company import ReadinessDocument
from scripts import test_s0_5b4_baseline as support
from scripts.verify_s6_2_unified_explorer_backend import seed_owner


async def scenario(tmp_path):
    # Broad-suite callers use the same loopback restriction as the release CLI.
    assert support.settings.POSTGRES_SERVER in {"localhost","127.0.0.1","::1"}
    database = support.database_name("release_reads")
    await support.create_database(database)
    engine = None
    try:
        bootstrap = await asyncio.to_thread(support.run_bootstrap,database)
        assert bootstrap.returncode == 0, "Disposable bootstrap failed"
        connection = await support.database_connection(database)
        try:
            user_id, profile_id = await seed_owner(connection,"release-owner")
            admin_id, _ = await seed_owner(connection,"release-admin")
            await connection.execute("UPDATE users SET platform_role='admin',is_admin=true WHERE id=$1",admin_id)
        finally:
            await connection.close()
        engine = create_async_engine(support.target_url(database))
        sessions = async_sessionmaker(engine,expire_on_commit=False)
        stored = tmp_path / "stored.pdf"
        stored.write_bytes(b"%PDF-1.4 synthetic local file")
        async with sessions() as session:
            corpus = [Tender(id=uuid4(),external_id=f"release-{i}",source_system="world_bank",canonical_source_key=f"world_bank:release:{i}",source_url="https://example.invalid/notice",title=f"Synthetic Tender {i}",description="Synthetic description",budget=1000,currency="USD",country="Uzbekistan",category="Construction",compiled_master_text="Stored technical text") for i in range(31)]
            session.add_all(corpus)
            await session.flush()
            engagement_rows = [TenderEngagement(user_id=user_id,company_profile_id=profile_id,tender_id=tender.id,status=TenderEngagementStatus.SAVED,origin=TenderEngagementOrigin.MANUAL_SAVE) for tender in corpus]
            session.add_all(engagement_rows)
            artifact_rows = [Proposal(user_id=user_id,tender_id=tender.id,structured_data={}) for tender in corpus]
            session.add_all(artifact_rows)
            session.add_all([ReadinessDocument(company_profile_id=profile_id,document_type="license",document_name=f"License {i:02}",status="available",related_service="IT" if i%2 else "Construction") for i in range(31)])
            session.add_all([User(google_id=f"pending-{i}-{uuid4()}",email=f"pending-{i}@release.invalid",name=f"Pending {i}",approval_status="pending",platform_role="pilot_user") for i in range(31)])
            document = TenderDocument(id=uuid4(),tender_id=corpus[0].id,file_url="https://example.invalid/file.pdf",file_type="pdf",download_status="downloaded",storage_path=str(stored))
            missing = TenderDocument(id=uuid4(),tender_id=corpus[0].id,file_url="https://example.invalid/remote.pdf",file_type="pdf",download_status="metadata_only")
            session.add_all([document,missing])
            analysis = TenderAnalysis(id=uuid4(),tender_id=corpus[0].id,user_id=user_id,company_profile_id=profile_id,ownership_state="OWNED",tender_file_name="fixture.pdf",company_name="Synthetic",raw_extracted_text="Stored text",analysis_json={})
            session.add(analysis)
            await session.flush()
            previous = None
            for number in range(1,32):
                version = AnalysisVersion(id=uuid4(),analysis_id=analysis.id,version_number=number,supersedes_version_id=previous,
                    origin="RUNTIME_ANALYSIS" if number==1 else "RUNTIME_REANALYSIS",status="COMPLETED",analysis_language="en",snapshot_completeness="COMPLETE",
                    tender_snapshot={},company_snapshot={},result_snapshot={"fixture":"x"*100000},evidence_snapshot={},provenance_snapshot={})
                session.add(version)
                await session.flush()
                previous = version.id
            await session.commit()
        app = FastAPI()
        for module,prefix in [(users,"/api/v1/users"),(my_tenders,"/api/v1"),(tenders,"/api/v1/tenders"),(explorer,"/api/v1"),(proposals,"/api/v1/proposals"),(vault,"/api/v1"),(admin,"/api/v1/admin")]:
            app.include_router(module.router,prefix=prefix)
        async def session_dependency():
            async with sessions() as session: yield session
        app.dependency_overrides[get_db] = session_dependency
        statements = []
        def record(conn,cursor,statement,parameters,context,executemany):
            assert not statement.lstrip().upper().startswith(("INSERT","UPDATE","DELETE")), "Passive domain mutation"
            statements.append(statement)
        event.listen(engine.sync_engine,"before_cursor_execute",record)
        connection = await support.database_connection(database)
        async def fingerprint():
            result = {}
            for table in ("users","company_profiles","tenders","tender_documents","proposals","tender_analyses","analysis_versions","analysis_version_document_snapshots","audit_logs","readiness_documents","tender_recommendations","tender_engagements"):
                result[table] = await connection.fetchval(f"SELECT md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'')) FROM {table} t")
            return result
        before = await fingerprint()
        token = create_access_token({"sub":str(user_id),"auth_version":0})
        admin_token = create_access_token({"sub":str(admin_id),"auth_version":0})
        evidence = []
        history = f"/api/v1/tenders/{corpus[0].id}/analyses/{analysis.id}/versions"
        routes = [
            ("legacy-list","/api/v1/tenders?limit=25",200,8),
            ("legacy-detail",f"/api/v1/tenders/{corpus[0].id}",200,8),
            ("details",f"/api/v1/tenders/{corpus[0].id}/details",200,13),
            ("decision",f"/api/v1/tenders/{corpus[0].id}/decision-snapshot",200,7),
            ("documents",f"/api/v1/tenders/{corpus[0].id}/documents",200,6),
            ("stored-download",f"/api/v1/tenders/documents/{document.id}/download",200,8),
            ("missing-download",f"/api/v1/tenders/documents/{missing.id}/download",404,8),
            ("compiled-text",f"/api/v1/tenders/{corpus[0].id}/compiled-text",200,10),
            ("explorer","/api/v1/explorer/tenders?limit=25&view=all",200,8),
            ("proposals","/api/v1/proposals",200,5),
            ("my-tenders","/api/v1/my-tenders",200,8),
            ("readiness","/api/v1/vault/readiness",200,6),
            ("company-profile","/api/v1/users/me/company",200,5),
            ("version-detail",history+"/1",200,9),
            ("history",history,200,7),
            ("latest-analysis",f"/api/v1/tenders/{corpus[0].id}/latest-analysis",200,9),
            ("approval-queue","/api/v1/admin/approval-queue",200,5),
            ("source-status","/api/v1/tenders/sources/refresh-status",200,3),
        ]
        with ExitStack() as spies:
            for attribute in ("_apply_live_uzex_dates","_world_bank_contact_metadata_override","_adb_contact_metadata_override","_uzex_contact_metadata_override","_giz_contact_metadata_override"):
                spies.enter_context(patch.object(tenders,attribute,side_effect=AssertionError("Passive source retrieval")))
            spies.enter_context(patch("app.core.scraper.sync_playwright",side_effect=AssertionError("Passive browser launch")))
            spies.enter_context(patch("requests.sessions.Session.request",side_effect=AssertionError("Passive source HTTP")))
            original_send = httpx.AsyncClient.send
            async def local_send(client,*args,**kwargs):
                assert isinstance(client._transport,httpx.ASGITransport), "Passive external HTTP"
                return await original_send(client,*args,**kwargs)
            spies.enter_context(patch.object(httpx.AsyncClient,"send",local_send))
            spies.enter_context(patch("app.core.ai.analyze_tender_text_async",side_effect=AssertionError("Passive analysis")))
            spies.enter_context(patch("celery.app.base.Celery.send_task",side_effect=AssertionError("Passive dispatch")))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://local.fixture") as client:
                for label,url,expected,budget in routes:
                    statements.clear()
                    filesystem_calls = 0
                    with ExitStack() as filesystem_spies:
                        probes = []
                        if label in {"my-tenders", "proposals", "readiness", "company-profile", "history", "version-detail"}:
                            for target in ("pathlib.Path.is_file", "pathlib.Path.read_bytes", "os.scandir"):
                                probes.append(filesystem_spies.enter_context(patch(target, side_effect=AssertionError("List document filesystem access"))))
                        result = await client.get(url,headers={"Authorization":"Bearer "+(admin_token if label=="approval-queue" else token)})
                        filesystem_calls = sum(probe.call_count for probe in probes)
                    assert result.status_code == expected,(label,result.text[:300])
                    assert len(statements)<=budget,(label,len(statements),budget)
                    evidence.append({"route":label,"status":result.status_code,"queries":len(statements),"budget":budget,"document_filesystem_calls":filesystem_calls if probes else None})
                    if label == "my-tenders":
                        assert len(result.json()["items"]) == 25
                        assert result.json()["total"] == 31
                        second = await client.get(url+"?offset=25",headers={"Authorization":"Bearer "+token})
                        assert len(second.json()["items"]) == 6
                    if label in {"proposals","readiness","history","approval-queue"}:
                        items=result.json()["items"] if label=="approval-queue" else result.json()
                        assert len(items)==25
                        assert result.headers["x-has-more"]=="true"
                        second = await client.get(url+"?offset=25",headers={"Authorization":"Bearer "+(admin_token if label=="approval-queue" else token)})
                        rest=second.json()["items"] if label=="approval-queue" else second.json()
                        assert len(rest)==6 and second.headers["x-has-more"]=="false"
                    if label=="history":
                        version_queries=[query for query in statements if "FROM analysis_versions" in query]
                        assert version_queries
                        assert all("result_snapshot" not in query and "evidence_snapshot" not in query and "analysis_version_document_snapshots" not in query for query in version_queries)
                        assert "x"*1000 not in result.text
                readiness_id = (await client.get("/api/v1/vault/readiness",headers={"Authorization":"Bearer "+token})).json()[0]["id"]
                foreign_headers = {"Authorization":"Bearer "+admin_token}
                foreign_lists = await client.get("/api/v1/my-tenders",headers=foreign_headers)
                assert foreign_lists.json()["items"] == []
                foreign_artifacts = await client.get("/api/v1/proposals",headers=foreign_headers)
                assert foreign_artifacts.json() == []
                foreign_readiness = await client.get("/api/v1/vault/readiness",headers=foreign_headers)
                assert foreign_readiness.json() == []
                foreign_profile = await client.get("/api/v1/users/me/company",headers=foreign_headers)
                assert str(foreign_profile.json()["company_profile_id"]) != str(profile_id)
                for method,url,body in [
                    ("GET",history,None),
                    ("GET",history+"/1",None),
                    ("PUT",f"/api/v1/vault/readiness/{readiness_id}",{"document_name":"Forbidden"}),
                    ("DELETE",f"/api/v1/vault/readiness/{readiness_id}",None),
                    ("GET",f"/api/v1/proposals/{artifact_rows[0].id}",None),
                    ("PUT",f"/api/v1/proposals/{artifact_rows[0].id}",{"our_price":1}),
                    ("POST",f"/api/v1/proposals/{artifact_rows[0].id}/continue",None),
                    ("POST",f"/api/v1/my-tenders/{engagement_rows[0].id}/actions/evaluate",{"expected_status":"SAVED"}),
                ]:
                    denied = await client.request(method,url,headers=foreign_headers,json=body)
                    assert denied.status_code == 404,(method,url,denied.status_code)
                    evidence.append({"route":"foreign-owned-record", "method":method,"status":denied.status_code})
                filtered = await client.get("/api/v1/vault/readiness?related_service=IT",headers={"Authorization":"Bearer "+token})
                assert len(filtered.json())==15 and filtered.headers["x-total-count"]=="15"
                for url in ("/api/v1/proposals", "/api/v1/vault/readiness",history,"/api/v1/admin/approval-queue"):
                    result=await client.get(url+"?limit=101",headers={"Authorization":"Bearer "+admin_token})
                    assert result.status_code==422
        after = await fingerprint()
        assert before==after
        event.remove(engine.sync_engine,"before_cursor_execute",record)
        write_evidence = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://local.fixture") as client:
            headers={"Authorization":"Bearer "+token}
            async def mutate(label,method,url,payload,allowed):
                prior=await fingerprint()
                async with sessions() as session:
                    profile_before=(await session.execute(select(users.CompanyProfile).where(users.CompanyProfile.id==profile_id))).scalar_one()
                    profile_fields_before={column.name:getattr(profile_before,column.name) for column in users.CompanyProfile.__table__.columns}
                response=await client.request(method,url,headers=headers,json=payload)
                assert response.status_code in (200,201,204),(label,response.text)
                current=await fingerprint();changed={table for table in prior if prior[table]!=current[table]}
                assert changed <= set(allowed),(label,changed)
                assert changed,(label,"expected mutation absent")
                if label=="profile-save":
                    async with sessions() as session:
                        row=(await session.execute(select(users.CompanyProfile).where(users.CompanyProfile.id==profile_id))).scalar_one()
                        changed_fields={column.name for column in users.CompanyProfile.__table__.columns if profile_fields_before[column.name]!=getattr(row,column.name)}
                        assert changed_fields <= {"company_name","updated_at"},changed_fields
                write_evidence.append({"action":label,"changed_tables":sorted(changed),"allowed_tables":allowed})
                return response
            with patch("app.core.ai.analyze_tender_text_async",side_effect=AssertionError("Unexpected analysis")), patch("celery.app.base.Celery.send_task",side_effect=AssertionError("Unexpected dispatch")), patch("requests.sessions.Session.request",side_effect=AssertionError("Unexpected source network")):
                await mutate("profile-save","PUT","/api/v1/users/me/company",{"company_name":"Updated owned company"},["company_profiles"])
                await mutate("analysis-default","PATCH","/api/v1/users/me/preferences",{"default_analysis_language":"ru"},["users"])
                created=await mutate("readiness-create","POST","/api/v1/vault/readiness",{"document_type":"license","document_name":"Owned metadata only","status":"available"},["readiness_documents"])
                owned_id=created.json()["id"]
                assert created.json()["optional_file_url"] is None
                await mutate("readiness-edit","PUT",f"/api/v1/vault/readiness/{owned_id}",{"issuer":"Original owned issuer","optional_file_url":"https://example.invalid/owned.pdf"},["readiness_documents"])
                await mutate("readiness-delete","DELETE",f"/api/v1/vault/readiness/{owned_id}",None,["readiness_documents"])
        # Execute the actual HTTP analysis route with deterministic extractor outputs.
        # Only model extraction is substituted; persistence, ownership and versioning are real.
        from app.core.agents.requirement_extractor import RequirementExtractionResult, RequirementExtractionCoverage
        extraction = RequirementExtractionResult(requirements=[],coverage_metadata=RequirementExtractionCoverage(full_text_length=21,max_chunk_chars=10000,chunk_count=1,chunks_processed=1,chunks_failed=0,coverage_status="complete",extractor_mode="fixture"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://local.fixture") as client:
            prior=await fingerprint()
            old_versions=await connection.fetchval("SELECT md5(jsonb_agg(to_jsonb(v) ORDER BY id)::text) FROM analysis_versions v WHERE analysis_id=$1",analysis.id)
            with patch.object(tenders,"extract_requirements_with_coverage",new=AsyncMock(return_value=extraction)), patch.object(tenders,"extract_strategy_intelligence",new=AsyncMock(return_value=None)), patch("requests.sessions.Session.request",side_effect=AssertionError("Unexpected source retrieval")):
                response=await client.post(f"/api/v1/tenders/{corpus[0].id}/analyze?force=true&analysis_language=en",headers={"Authorization":"Bearer "+token})
            assert response.status_code == 200,response.text[:500]
            current=await fingerprint();changed={table for table in prior if prior[table]!=current[table]}
            assert changed <= {"tender_analyses","analysis_versions","analysis_version_document_snapshots"},changed
            assert "analysis_versions" in changed
            assert response.json()["version_number"]==32
            preserved=await connection.fetchval("SELECT md5(jsonb_agg(to_jsonb(v) ORDER BY id)::text) FROM analysis_versions v WHERE analysis_id=$1 AND version_number<=31",analysis.id)
            assert old_versions==preserved,"Historical version mutated"
            write_evidence.append({"action":"explicit-analysis-run-real-route","changed_tables":sorted(changed),"historical_versions_unchanged":True,"new_version":32,"model_extraction":"deterministic test substitute"})
            rejected=await client.post(f"/api/v1/tenders/{corpus[0].id}/analyze?analysis_language=ar",headers={"Authorization":"Bearer "+token})
            assert rejected.status_code==422
        await connection.close()
        return {"routes":evidence,"domain_fingerprints_unchanged":True,"explicit_write_fingerprints":write_evidence,"source_calls":0,"passive_generation_calls":0,"explicit_analysis_runs":1}
    finally:
        if engine: await engine.dispose()
        await support.drop_database(database)


def test_real_customer_reads_are_passive_and_collections_bounded(tmp_path):
    result=asyncio.run(scenario(tmp_path))
    output=os.environ.get("PLASMA_READ_PROOF_OUTPUT")
    if output: Path(output).write_text(json.dumps(result,indent=2))
