"""Real disposable PostgreSQL passivity, ownership and collection budgets."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.endpoints import admin, explorer, proposals, tenders, vault
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.all_models import Tender, TenderDocument, Proposal, User
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
            session.add_all([Proposal(user_id=user_id,tender_id=tender.id,structured_data={}) for tender in corpus])
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
        for module,prefix in [(tenders,"/api/v1/tenders"),(explorer,"/api/v1"),(proposals,"/api/v1/proposals"),(vault,"/api/v1"),(admin,"/api/v1/admin")]:
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
            for table in ("users","company_profiles","tenders","tender_documents","proposals","tender_analyses","analysis_versions","readiness_documents","tender_recommendations","tender_engagements"):
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
            ("readiness","/api/v1/vault/readiness",200,6),
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
                    result = await client.get(url,headers={"Authorization":"Bearer "+(admin_token if label=="approval-queue" else token)})
                    assert result.status_code == expected,(label,result.text[:300])
                    assert len(statements)<=budget,(label,len(statements),budget)
                    evidence.append({"route":label,"status":result.status_code,"queries":len(statements),"budget":budget})
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
                filtered = await client.get("/api/v1/vault/readiness?related_service=IT",headers={"Authorization":"Bearer "+token})
                assert len(filtered.json())==15 and filtered.headers["x-total-count"]=="15"
                for url in ("/api/v1/proposals", "/api/v1/vault/readiness",history,"/api/v1/admin/approval-queue"):
                    result=await client.get(url+"?limit=101",headers={"Authorization":"Bearer "+admin_token})
                    assert result.status_code==422
        after = await fingerprint()
        await connection.close()
        assert before==after
        return {"routes":evidence,"domain_fingerprints_unchanged":True,"source_calls":0,"generation_calls":0}
    finally:
        if engine: await engine.dispose()
        await support.drop_database(database)


def test_real_customer_reads_are_passive_and_collections_bounded(tmp_path):
    result=asyncio.run(scenario(tmp_path))
    output=os.environ.get("PLASMA_READ_PROOF_OUTPUT")
    if output: Path(output).write_text(json.dumps(result,indent=2))
