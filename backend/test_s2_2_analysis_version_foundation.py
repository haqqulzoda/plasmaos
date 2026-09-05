"""Static and deterministic unit contracts for Sprint 2.2."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.all_models import Base
from app.services.analysis_versions import (
    DocumentSnapshotInput,
    analysis_version_status,
    document_set_hash,
    runtime_snapshot_completeness,
)


BACKEND_DIR = Path(__file__).resolve().parent
MIGRATION = BACKEND_DIR / "alembic/versions/20260827_0002_s2_2_analysis_version_foundation.py"
SERVICE = BACKEND_DIR / "app/services/analysis_versions.py"
ENDPOINT = BACKEND_DIR / "app/api/endpoints/tenders.py"
PREFLIGHT = BACKEND_DIR / "scripts/run_s0_3_schema_data_preflight.py"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_repository_has_one_s2_2_head_with_s2_1_parent() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260904_0001_s8_2_analysis_language"]
    assert (
        script.get_revision("20260827_0002_s2_2_analysis_version_foundation").down_revision
        == "20260827_0001_s2_1_compliance_ownership"
    )


def test_version_and_document_snapshot_schema_contract() -> None:
    version = Base.metadata.tables["analysis_versions"]
    documents = Base.metadata.tables["analysis_version_document_snapshots"]
    assert {
        "analysis_id",
        "version_number",
        "supersedes_version_id",
        "result_snapshot",
        "evidence_snapshot",
        "provenance_snapshot",
        "tender_snapshot",
        "company_snapshot",
        "input_hash",
        "output_hash",
        "evidence_hash",
        "document_set_hash",
        "version_hash",
        "snapshot_completeness",
    } <= set(version.columns.keys())
    assert {
        "analysis_version_id",
        "tender_document_id",
        "source_system",
        "content_hash",
        "storage_reference",
        "snapshot_metadata",
    } <= set(documents.columns.keys())
    constraint_names = {item.name for item in version.constraints}
    assert "uq_analysis_versions_analysis_version_number" in constraint_names
    assert "uq_analysis_versions_supersedes_version_id" in constraint_names
    assert "ck_analysis_versions_not_self_superseding" in constraint_names


def test_migration_is_additive_truthful_and_external_call_free() -> None:
    migration = source(MIGRATION)
    lowered = migration.casefold()
    assert "insert into analysis_versions" in lowered
    assert "from tender_analyses as analysis" in lowered
    assert "'legacy_backfill'" in lowered
    assert "analysis.analysis_json" in lowered
    assert "analysis.content_hash" in lowered
    assert "document_fingerprints" in lowered
    assert "jsonb_typeof" in lowered
    assert "parsed_text_sha256" in lowered
    assert "update tender_analyses" not in lowered
    assert "delete from tender_analyses" not in lowered
    assert "httpx" not in lowered
    assert "google" not in lowered
    assert "gemini" not in lowered
    assert "requirement_extractor" not in lowered


def test_runtime_path_locks_parent_appends_then_updates_compatibility_mirror() -> None:
    service = source(SERVICE)
    endpoint = source(ENDPOINT)
    assert ".with_for_update()" in service
    assert "previous.version_number + 1" in service
    assert "supersedes_version_id = previous.id if previous else None" in service
    assert "UPDATE analysis_versions" not in service.upper()
    append_at = endpoint.index("await append_analysis_version(")
    mirror_at = endpoint.index("analysis.analysis_json = analysis_payload", append_at)
    commit_at = endpoint.index("await session.commit()", mirror_at)
    assert append_at < mirror_at < commit_at
    assert endpoint.count("await append_analysis_version(") == 1


def test_status_and_snapshot_completeness_are_conservative() -> None:
    assert analysis_version_status("completed") == "COMPLETED"
    assert analysis_version_status("needs_review") == "NEEDS_REVIEW"
    assert analysis_version_status("failed") == "FAILED"
    document = DocumentSnapshotInput(
        tender_document_id=uuid4(),
        source_system="world_bank",
        source_document_key="doc-1",
        source_url="https://example.test/doc-1",
        filename="doc.pdf",
        media_type="application/pdf",
        content_hash="a" * 64,
        storage_reference="documents/doc.pdf",
        storage_version=None,
        fetched_at=None,
        observed_at=None,
        snapshot_metadata={"parsed_text_length": 10, "parsed_text_sha256": "b" * 64},
    )
    provenance = {
        "requirement_extractor": {
            "model_name": "configured-model",
            "prompt_template_hash": "c" * 64,
        }
    }
    assert runtime_snapshot_completeness(
        status="COMPLETED",
        input_hash="d" * 64,
        provenance_snapshot=provenance,
        documents=[document],
    ) == "COMPLETE"
    assert runtime_snapshot_completeness(
        status="FAILED",
        input_hash="d" * 64,
        provenance_snapshot=provenance,
        documents=[document],
    ) == "PARTIAL"
    assert runtime_snapshot_completeness(
        status="COMPLETED",
        input_hash="d" * 64,
        provenance_snapshot=provenance,
        documents=[replace(document, content_hash=None, snapshot_metadata={})],
    ) == "PARTIAL"


def test_document_set_hash_is_deterministic_and_input_sensitive() -> None:
    document = DocumentSnapshotInput(
        tender_document_id=uuid4(),
        source_system="giz",
        source_document_key="key",
        source_url=None,
        filename="one.pdf",
        media_type="application/pdf",
        content_hash="1" * 64,
        storage_reference=None,
        storage_version=None,
        fetched_at=None,
        observed_at=None,
        snapshot_metadata={"parsed_text_sha256": "2" * 64},
    )
    assert document_set_hash([document]) == document_set_hash([document])
    assert document_set_hash([document]) != document_set_hash(
        [replace(document, content_hash="3" * 64)]
    )
    second = replace(document, tender_document_id=uuid4(), filename="two.pdf")
    assert document_set_hash([document, second]) == document_set_hash(
        [second, document]
    )


def test_preflight_reports_version_invariants_without_snapshot_content() -> None:
    preflight = source(PREFLIGHT)
    for marker in (
        "analyses_with_zero_versions",
        "analyses_with_one_version",
        "analyses_with_multiple_versions",
        "duplicate_version_number_groups",
        "broken_supersedes_references",
        "quarantined_analyses_with_versions",
        "missing_input_hash",
        "missing_output_hash",
        "missing_document_hash",
    ):
        assert marker in preflight
    # Sprint 2.3 recomputes hashes from snapshots in-memory but returns counts
    # only; the read-only report never includes snapshot payload values.
    assert "hash_mismatches_total" in preflight
    assert '"hash_verification": hash_verification' in preflight
