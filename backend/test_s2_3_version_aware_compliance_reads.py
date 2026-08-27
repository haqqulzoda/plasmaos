"""Static and deterministic contracts for Sprint 2.3 read authority."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.core.reproducibility import stable_json_sha256
from app.services.analysis_versions import (
    _version_hash_payload,
    document_set_hash,
    get_versioned_analysis_payload,
    verify_analysis_version_integrity,
)


BACKEND_DIR = Path(__file__).resolve().parent
TENDERS = BACKEND_DIR / "app/api/endpoints/tenders.py"
PROPOSALS = BACKEND_DIR / "app/api/endpoints/proposals.py"
ADMIN = BACKEND_DIR / "app/api/endpoints/admin.py"
VERSIONS = BACKEND_DIR / "app/services/analysis_versions.py"
AGGREGATES = BACKEND_DIR / "app/services/analysis_aggregates.py"
PREFLIGHT = BACKEND_DIR / "scripts/run_s0_3_schema_data_preflight.py"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def version_fixture() -> SimpleNamespace:
    analysis_id = uuid4()
    requested_by = uuid4()
    result = {"analysis_status": "completed", "fixture": "immutable-v1"}
    evidence = {"evidence_validation": {"accepted": [{"fixture": "evidence-v1"}]}}
    provenance = {"requirement_extractor": {"model_name": "model-v1"}}
    tender = {"title": "Tender at v1"}
    company = {"company_name": "Company at v1"}
    output_hash = stable_json_sha256(result)
    evidence_hash = stable_json_sha256(evidence)
    document_hash = document_set_hash([])
    values = {
        "analysis_id": analysis_id,
        "version_number": 1,
        "supersedes_version_id": None,
        "origin": "RUNTIME_ANALYSIS",
        "status": "COMPLETED",
        "analysis_schema_version": "schema-v1",
        "pipeline_version": "pipeline-v1",
        "model_provider": "provider",
        "model_name": "model-v1",
        "model_version": None,
        "prompt_template_version": "prompt-v1",
        "prompt_template_hash": "a" * 64,
        "provenance_snapshot": provenance,
        "tender_snapshot": tender,
        "company_snapshot": company,
        "result_snapshot": result,
        "evidence_snapshot": evidence,
        "input_hash": "b" * 64,
        "output_hash": output_hash,
        "evidence_hash": evidence_hash,
        "document_set_hash": document_hash,
        "snapshot_completeness": "COMPLETE",
        "requested_by_user_id": requested_by,
    }
    hash_values = dict(values)
    hash_values["document_set_hash_value"] = hash_values.pop("document_set_hash")
    values["version_hash"] = stable_json_sha256(
        _version_hash_payload(**hash_values)
    )
    return SimpleNamespace(
        **values,
        id=uuid4(),
        document_snapshots=[],
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


def test_version_payload_is_detached_and_hash_verification_detects_tampering() -> None:
    version = version_fixture()
    original = deepcopy(version.result_snapshot)
    detached = get_versioned_analysis_payload(version)
    detached["result_snapshot"]["fixture"] = "caller mutation"
    assert version.result_snapshot == original
    assert verify_analysis_version_integrity(version).overall_status == "VERIFIED"

    version.result_snapshot = {"fixture": "tampered"}
    integrity = verify_analysis_version_integrity(version)
    assert integrity.overall_status == "MISMATCH"
    assert integrity.output_hash_status == "MISMATCH"
    assert integrity.version_hash_status == "MISMATCH"


def test_missing_legacy_hashes_are_partial_not_fabricated() -> None:
    version = version_fixture()
    version.snapshot_completeness = "LEGACY_BACKFILL"
    version.output_hash = None
    version.version_hash = None
    integrity = verify_analysis_version_integrity(version)
    assert integrity.overall_status == "PARTIAL"
    assert integrity.output_hash_status == "NOT_AVAILABLE"
    assert integrity.version_hash_status == "NOT_AVAILABLE"
    assert set(integrity.missing_fields) == {
        "output_hash",
        "document_set_hash",
        "version_hash",
    }


def test_customer_read_consumers_use_versions_not_parent_mirrors() -> None:
    tenders = source(TENDERS)
    proposals = source(PROPOSALS)
    admin = source(ADMIN)
    assert tenders.count("analysis.analysis_json = analysis_payload") == 1
    assert tenders.count("analysis.content_hash = current_content_hash") == 1
    assert ".analysis_json" not in proposals
    assert ".content_hash" not in proposals
    assert ".analysis_json" not in admin
    assert ".content_hash" not in admin
    assert "latest_analysis_version.result_snapshot" in proposals
    assert "version.result_snapshot" in tenders
    assert "version.evidence_snapshot" in tenders
    assert "version.tender_snapshot" in tenders
    assert "version.company_snapshot" in tenders


def test_version_routes_and_export_are_narrow_and_version_selectable() -> None:
    endpoint = source(TENDERS)
    assert '"/{tender_id}/analyses/{analysis_id}/versions"' in endpoint
    assert '"/{tender_id}/analyses/{analysis_id}/versions/{version_number}"' in endpoint
    assert "version_number: int | None = Query(default=None, ge=1)" in endpoint
    assert "get_owned_analysis_parent_by_id(" in endpoint
    assert "list_analysis_versions(" in endpoint
    assert "get_analysis_version(" in endpoint
    assert "storage_reference=" not in endpoint[
        endpoint.index("def _analysis_version_document(") :
        endpoint.index("def _analysis_version_detail(")
    ]


def test_parent_then_version_selection_and_zero_version_policy_are_explicit() -> None:
    aggregate = source(AGGREGATES)
    versions = source(VERSIONS)
    endpoint = source(TENDERS)
    assert "TenderAnalysis.created_at.desc()" in aggregate
    assert "TenderAnalysis.id.desc()" in aggregate
    assert "AnalysisVersion.version_number.desc()" in versions
    assert "analysis_version_zero_version_anomaly" in versions
    assert "Compliance analysis version history is unavailable." in endpoint
    assert "parent.analysis_json" not in versions
    assert "parent.content_hash" not in versions
    model = source(BACKEND_DIR / "app/models/audit.py")
    assert "AnalysisVersionMutationError" in model
    assert "_reject_persisted_history_mutation" in model


def test_preflight_reports_s2_3_integrity_without_emitting_snapshots() -> None:
    preflight = source(PREFLIGHT)
    for marker in (
        "hash_mismatches_total",
        "hash_not_available",
        "output_hash_mismatches",
        "evidence_hash_mismatches",
        "document_set_hash_mismatches",
        "version_hash_mismatches",
        "multi_parent_owned_logical_keys",
    ):
        assert marker in preflight
    assert '"result_snapshot": result_snapshot' in preflight
    assert "return counts" in preflight


def test_no_version_history_frontend_was_added() -> None:
    changed_contract = "\n".join(
        (source(TENDERS), source(PROPOSALS), source(ADMIN), source(VERSIONS))
    ).casefold()
    assert "restore version" not in changed_contract
    assert "version comparison" not in changed_contract
