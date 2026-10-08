"""Sprint 13 regression gate for explicit UzEx/GIZ document acquisition."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.api.endpoints import tenders
from app.models.all_models import TenderSyncStatus
from app.services import notifications
from app.services.tender_sources.base import NormalizedTender
from app.services.tender_sources.giz import GizTenderSource


ROOT = Path(__file__).resolve().parent


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_uzex_hunter_and_source_refresh_are_metadata_only() -> None:
    hunter = source("app/workers/hunter_tasks.py")
    endpoint = inspect.getsource(tenders.sync_giz_tenders)
    assert "process_tender_docs" not in hunter
    assert "documents_dispatched" not in hunter
    assert "GIZ source refresh is metadata-only" in endpoint
    assert "hydrate_giz_tender_documents" not in endpoint


def test_shared_command_is_explicit_global_idempotent_and_bounded() -> None:
    command = inspect.getsource(tenders.sync_tender_documents)
    assert '.with_for_update()' in command
    assert "_get_active_sync_job_for_tender" in command
    assert "_get_active_sync_job_for_user_tender" not in command
    assert 'tender.source_system not in {"uzex", "giz"}' in command
    assert "hydrate_giz_documents if" in command
    assert 'queue="heavy_dl_queue"' in command
    assert 'routing_key="heavy_dl_queue"' in command
    assert '"max_retries": 3' in command
    worker = source("app/workers/tender_tasks.py")
    assert 'raise ValueError("Explicit document acquisition job_id is required")' in worker


def test_giz_acquisition_refreshes_official_archive_in_same_session() -> None:
    old_identity = "stable-existing-document-id"
    normalized = NormalizedTender(
        source_system="giz",
        external_id="10034411",
        source_url=(
            "https://ausschreibungen.giz.de/Satellite/public/company/"
            "project/CX/de/overview?0"
        ),
        title="Official GIZ tender",
        source_metadata_json={
            "eproc_project_url": (
                "https://ausschreibungen.giz.de/Satellite/public/company/"
                "project/CX/de/overview?0"
            ),
            "eproc_project_id": "CX",
            "attachments": [
                {
                    "source_document_url": (
                        "https://ausschreibungen.giz.de/Satellite/public/company/"
                        "project/CX/de/archive/expired.zip"
                    ),
                    "external_file_id": old_identity,
                }
            ],
        },
    )
    project_url = normalized.source_url
    documents_url = (
        "https://ausschreibungen.giz.de/Satellite/public/company/"
        "project/CX/de/documents?1"
    )
    archive_url = (
        "https://ausschreibungen.giz.de/Satellite/public/company/"
        "project/CX/de/archive/fresh.zip"
    )
    project_html = f'<a href="{documents_url}">Participation documents</a>'
    documents_html = f"""
        <table><tr><td>terms.pdf</td><td>17.09.2026</td><td>pdf</td><td>20 KB</td></tr></table>
        <a href="{archive_url}">Alle Dokumente als ZIP</a>
    """
    source_adapter = GizTenderSource(source_pages=[])
    calls: list[str] = []

    async def fake_request(_client, _method, url, **_kwargs):
        calls.append(url)
        if url == project_url:
            return SimpleNamespace(url=project_url, content=project_html.encode())
        return SimpleNamespace(url=documents_url, content=documents_html.encode())

    source_adapter._request = fake_request  # type: ignore[method-assign]
    documents, updates = asyncio.run(
        source_adapter.discover_documents_for_acquisition(normalized, client=object())
    )
    assert calls == [project_url, documents_url]
    assert len(documents) == 1
    assert documents[0].source_document_url == archive_url
    assert documents[0].external_file_id == old_identity
    assert updates["participation_documents"][0]["document_name"] == "terms.pdf"


def test_giz_acquisition_does_not_reuse_expired_archive_when_official_link_is_absent() -> None:
    normalized = NormalizedTender(
        source_system="giz",
        external_id="10034411",
        source_url=(
            "https://ausschreibungen.giz.de/Satellite/public/company/"
            "project/CX/de/overview?0"
        ),
        title="Official GIZ tender",
        source_metadata_json={
            "eproc_project_url": (
                "https://ausschreibungen.giz.de/Satellite/public/company/"
                "project/CX/de/overview?0"
            ),
            "attachments": [
                {
                    "source_document_url": (
                        "https://ausschreibungen.giz.de/Satellite/public/company/"
                        "project/CX/de/archive/expired.zip"
                    ),
                    "external_file_id": "stable-existing-document-id",
                }
            ],
        },
    )
    adapter = GizTenderSource(source_pages=[])

    async def fake_request(_client, _method, url, **_kwargs):
        return SimpleNamespace(url=url, content=b"<html><body>No public archive</body></html>")

    adapter._request = fake_request  # type: ignore[method-assign]
    documents, updates = asyncio.run(
        adapter.discover_documents_for_acquisition(normalized, client=object())
    )
    assert documents == []
    assert updates["participation_documents"] == []


def test_progress_mapping_is_truthful_and_has_no_eta() -> None:
    diagnostics = tenders.SyncMarkerDiagnostics(documents_total=3)
    pending = SimpleNamespace(status=TenderSyncStatus.PENDING, progress=0)
    downloading = SimpleNamespace(status=TenderSyncStatus.IN_PROGRESS, progress=30)
    processing = SimpleNamespace(status=TenderSyncStatus.IN_PROGRESS, progress=60)
    assert tenders._sync_acquisition_state(pending, diagnostics) == "QUEUED"
    assert tenders._sync_acquisition_state(downloading, diagnostics) == "DOWNLOADING"
    assert tenders._sync_acquisition_state(processing, diagnostics) == "PROCESSING"
    frontend = source("../frontend/app/dashboard/tenders/[tenderId]/page.tsx")
    assert "attempts < 150" in frontend
    assert "2_000" in frontend
    assert "ETA" not in frontend


def test_ready_partial_failed_notification_contracts_are_job_level() -> None:
    common = {
        "category": "TENDER_ALERT",
        "payload": {
            "tender_id": str(uuid4()),
            "job_id": str(uuid4()),
            "ready_count": 2,
            "total_count": 3,
            "failed_count": 1,
        },
        "dedupe_key": f"document-acquisition:{uuid4()}",
    }
    for event_type, template in (
        ("DOCUMENTS_READY", "notifications.documents_ready"),
        ("DOCUMENTS_PARTIAL", "notifications.documents_partial"),
        ("DOCUMENTS_FAILED", "notifications.documents_failed"),
    ):
        notifications.validate_system_event(
            event_type=event_type,
            template_key=template,
            **common,
        )
    terminal = inspect.getsource(
        __import__(
            "app.workers.tender_tasks", fromlist=["_persist_terminal_acquisition_state"]
        )._persist_terminal_acquisition_state
    )
    assert "stage_document_acquisition_notification" in terminal
    assert "document-acquisition:" in inspect.getsource(
        notifications.stage_document_acquisition_notification
    )


def test_compliance_uses_only_local_processed_documents_and_stays_explicit() -> None:
    analyze = inspect.getsource(tenders.analyze_tender)
    assert "storage_file_exists(document.storage_path)" in analyze
    assert "document.parsed_text.strip()" in analyze
    assert "no locally stored, processed documents ready" in analyze
    workers = source("app/workers/tender_tasks.py")
    assert "analyze_tender" not in workers
    assert "append_analysis_version" not in workers


def test_security_cleanup_and_no_migration_contract() -> None:
    hydration = source("app/services/giz_document_hydration.py")
    connector = source("app/services/tender_sources/giz.py")
    for contract in (
        "_sanitize_filename",
        "_giz_valid_file_signature",
        "GIZ_MAX_ARCHIVE_COMPRESSED_BYTES",
        "_giz_zip_member_rejection_reason",
        "_cleanup_temp_download",
        "_giz_find_duplicate_document_by_sha",
    ):
        assert contract in hydration
    assert "MAX_GIZ_REDIRECTS" in connector
    assert "outside approved giz.de hosts" in connector
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20261009_0001_r3_cv_library_drafts"]
