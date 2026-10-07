"""INT-4: scripts/eoi_smoke.py (stdlib-only EOI smoke in the dedicated smoke organization)."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND / "scripts"))

import analysis_smoke  # noqa: E402
import eoi_smoke  # noqa: E402

ORG = "11111111-1111-1111-1111-111111111111"
DOCX = b"PK\x03\x04" + b"x" * 2_000
PDF = b"%PDF-1.4" + b"y" * 2_000


class FakeApi(analysis_smoke.Api):
    """The smoke organization's API: one completed analysis; drafts appear only on POST."""

    def __init__(self, *, organizations: int = 1, members: int = 1, passive: bool = True, pdf: bytes = PDF):
        super().__init__("http://api.invalid/api/v1", "token", ORG)
        self.organizations, self.members, self.passive, self.pdf = organizations, members, passive, pdf
        self.references: list[dict] = []
        self.drafts: list[dict] = []
        self.writes: list[tuple[str, str]] = []

    def call(self, method, path, payload=None):
        if method != "GET":
            self.writes.append((method, path))
        if path == "/organizations":
            return 200, [{"organization_id": ORG, "display_name": "Plasma Smoke Test", "membership_id": "m1"}] * self.organizations
        if path == f"/organizations/{ORG}/members":
            return 200, [{"membership_id": f"m{n + 1}", "state": "ACTIVE"} for n in range(self.members)]
        if path == "/candidates/self-firm":
            return (200, {"firm_id": "f1", "project_references": list(self.references)}) if method == "GET" or self.references is not None else (404, {})
        if path == "/candidates/firms/f1/project-references" and method == "POST":
            created = {"reference_id": f"r{len(self.references) + 1}", "project_name": payload["project_name"]}
            self.references.append(created)
            return 201, created
        if path == "/pursuits?limit=50":
            return 200, {"items": [{"pursuit_id": "p-upload", "origin": "UPLOAD"}, {"pursuit_id": "p1", "origin": "SOURCE"}]}
        if path == "/pursuits/p1/analysis-runs/latest":
            return 200, {"analysis_run_id": "run1", "status": "COMPLETED", "completed_at": "2026-10-07T00:00:00Z"}
        if path == "/pursuits/p1/eoi-drafts" and method == "GET":
            return 200, list(self.drafts)
        if path.startswith("/pursuits/p1/eoi/suggestions"):
            if not self.passive:
                self.drafts.append({"draft_id": "unexpected"})
            return 200, {"criteria": [{"requirement_id": "c1"}], "notes": [], "defaults": {"addressee_organization": "Ministry"}}
        if path == "/pursuits/p1/eoi-drafts" and method == "POST":
            assert payload["language"] == "en" and payload["own_reference_ids"] == ["r1", "r2"]
            draft = {"draft_id": "d1", "version": 1, "summary": {"criteria_total": 1}, "artifacts": [
                {"artifact_id": "a-docx", "format": "DOCX", "sha256": hashlib.sha256(DOCX).hexdigest()},
                {"artifact_id": "a-pdf", "format": "PDF", "sha256": hashlib.sha256(PDF).hexdigest()}]}
            self.drafts.append(draft)
            return 201, draft
        return 404, {"detail": path}


@pytest.fixture
def downloads(monkeypatch):
    def fake(api, path):
        return DOCX if path.endswith("a-docx/download") else api.pdf

    monkeypatch.setattr(eoi_smoke, "download", fake)


def test_eoi_smoke_creates_the_library_once_drafts_and_checks_both_files(downloads) -> None:
    api = FakeApi()
    record = eoi_smoke.run(api, "Plasma Smoke Test")
    assert record["pursuit_id"] == "p1" and record["draft_id"] == "d1" and record["criteria"] == 1
    assert record["files"] == {"DOCX": {"bytes": len(DOCX), "sha_ok": True, "signature_ok": True},
                               "PDF": {"bytes": len(PDF), "sha_ok": True, "signature_ok": True}}
    assert eoi_smoke.problems_of(record) == []
    assert [path for _, path in api.writes].count("/candidates/firms/f1/project-references") == 2
    eoi_smoke.run(api, "Plasma Smoke Test")  # a second run reuses the two references
    assert [path for _, path in api.writes].count("/candidates/firms/f1/project-references") == 2


def test_eoi_smoke_refuses_outside_a_dedicated_organization_and_a_non_passive_read(downloads) -> None:
    for api in (FakeApi(organizations=2), FakeApi(members=2)):
        with pytest.raises(analysis_smoke.LiveSmokeError):
            eoi_smoke.run(api, "Plasma Smoke Test")
        assert api.writes == []  # nothing written before the guard passes
    with pytest.raises(analysis_smoke.LiveSmokeError, match="passive"):
        eoi_smoke.run(FakeApi(passive=False), "Plasma Smoke Test")


def test_eoi_smoke_reports_a_corrupt_or_mismatched_file(downloads) -> None:
    record = eoi_smoke.run(FakeApi(pdf=b"<html>error</html>"), "Plasma Smoke Test")
    problems = eoi_smoke.problems_of(record)
    assert "PDF sha256 differs from the draft" in problems and any("is not a PDF file" in item for item in problems)


def test_eoi_smoke_needs_only_the_standard_library_and_a_token_from_the_environment() -> None:
    script = BACKEND / "scripts" / "eoi_smoke.py"
    result = subprocess.run([sys.executable, "-I", "-S", str(script), "--help"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "--org-name" in result.stdout
    assert eoi_smoke.main(["--api-base", "x", "--org-id", ORG, "--org-name", "n"], environ={}) == 2
