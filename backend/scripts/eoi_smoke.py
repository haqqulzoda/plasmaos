#!/usr/bin/env python3
"""EOI smoke after a deploy, in the dedicated smoke organization (end to end through the API).

Run it after ``analysis_smoke.py --live``, which leaves a completed analysis of an open World
Bank REOI in the smoke organization. Like that script it needs only the Python standard
library, reads the bearer token from ANALYSIS_SMOKE_TOKEN (never argv, never printed) and
refuses to run unless the token's user belongs to exactly one organization whose display name
equals --org-name and whose only active member is that user:

    ANALYSIS_SMOKE_TOKEN=<smoke user's token> python3 -I -S backend/scripts/eoi_smoke.py \\
        --api-base http://127.0.0.1:8000/api/v1 --org-id <uuid> --org-name "Plasma Smoke Test"

Steps: ensure the organization's own firm and two synthetic project references (idempotent by
name); take the newest completed analysis of a source pursuit; read the EOI suggestions twice
(passive: no draft is created by reading); generate one English draft; download its DOCX and
PDF and check their sha256 against the draft and their file signatures. Output: one JSON line
of ids, counts and timings, then ``eoi smoke: OK`` or ``FAIL: ...`` lines. Exit 0 / 1 / 2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I does not add the script's directory

from analysis_smoke import Api, LiveSmokeError, assert_dedicated_test_organization  # noqa: E402

FIRM = {"display_name": "Plasma Smoke Test", "country": "Uzbekistan", "sectors": ["Energy"],
        "services": ["Engineering design"]}
REFERENCES = [
    {"project_name": "EOI smoke reference A (synthetic)", "client_name": "Synthetic client", "country": "Uzbekistan",
     "sector": "Energy", "service": "Detailed engineering design", "role": "LEAD", "value_basis": "UNKNOWN",
     "start_date": "2021-01-01", "completion_date": "2023-06-30", "completion_state": "COMPLETED",
     "relevant_scope": "Detailed engineering design of substations and transmission lines", "evidence_state": "UNVERIFIED"},
    {"project_name": "EOI smoke reference B (synthetic)", "client_name": "Synthetic client", "country": "Kazakhstan",
     "sector": "Energy", "service": "Construction supervision", "role": "JV_MEMBER", "value_basis": "UNKNOWN",
     "start_date": "2019-01-01", "completion_date": "2020-12-31", "completion_state": "COMPLETED",
     "relevant_scope": "Supervision of substation construction", "evidence_state": "UNVERIFIED"},
]
SIGNATURES = {"DOCX": b"PK", "PDF": b"%PDF"}


def ensure_library(api: Api) -> tuple[str, list[str]]:
    status, firm = api.call("GET", "/candidates/self-firm")
    if status == 404:
        status, firm = api.call("PUT", "/candidates/self-firm", FIRM)
    if status != 200 or not isinstance(firm, dict):
        raise LiveSmokeError(f"own firm unavailable (HTTP {status})")
    existing = {item["project_name"]: item["reference_id"] for item in firm.get("project_references", [])}
    ids = []
    for reference in REFERENCES:
        if reference["project_name"] not in existing:
            status, created = api.call("POST", f"/candidates/firms/{firm['firm_id']}/project-references", reference)
            if status != 201 or not isinstance(created, dict):
                raise LiveSmokeError(f"reference create failed (HTTP {status})")
            existing[reference["project_name"]] = created["reference_id"]
        ids.append(existing[reference["project_name"]])
    return firm["firm_id"], ids


def latest_completed_analysis(api: Api) -> tuple[str, str]:
    status, page = api.call("GET", "/pursuits?limit=50")
    if status != 200 or not isinstance(page, dict):
        raise LiveSmokeError(f"pursuit list failed (HTTP {status})")
    best = None
    for pursuit in page.get("items", []):
        if pursuit.get("origin") != "SOURCE":
            continue
        status, run = api.call("GET", f"/pursuits/{pursuit['pursuit_id']}/analysis-runs/latest")
        if status == 200 and isinstance(run, dict) and run.get("status") == "COMPLETED":
            if best is None or str(run.get("completed_at")) > str(best[2]):
                best = (pursuit["pursuit_id"], run["analysis_run_id"], run.get("completed_at"))
    if best is None:
        raise LiveSmokeError("no completed analysis in the smoke organization; run analysis_smoke.py --live first")
    return best[0], best[1]


def download(api: Api, path: str) -> bytes:
    request = urllib.request.Request(api.base + path)
    request.add_header("Authorization", f"Bearer {api._token}")
    request.add_header("X-Organization-ID", api.organization_id)
    try:
        with urllib.request.urlopen(request, timeout=api.timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise LiveSmokeError(f"download failed (HTTP {exc.code})") from None


def run(api: Api, org_name: str) -> dict:
    assert_dedicated_test_organization(api, org_name)
    _, own_ids = ensure_library(api)
    pursuit_id, run_id = latest_completed_analysis(api)
    base = f"/pursuits/{pursuit_id}"
    status, before = api.call("GET", f"{base}/eoi-drafts")
    if status != 200 or not isinstance(before, list):
        raise LiveSmokeError(f"EOI drafts unavailable (HTTP {status})")
    started = time.monotonic()
    status, suggestions = api.call("GET", f"{base}/eoi/suggestions?analysis_run_id={run_id}")
    suggestions_ms = round((time.monotonic() - started) * 1000)
    if status != 200 or not isinstance(suggestions, dict):
        raise LiveSmokeError(f"EOI suggestions failed (HTTP {status})")
    api.call("GET", f"{base}/eoi/suggestions?analysis_run_id={run_id}")
    status, after = api.call("GET", f"{base}/eoi-drafts")
    if status != 200 or len(after) != len(before):
        raise LiveSmokeError("reading EOI suggestions created a draft (must be passive)")
    defaults = suggestions["defaults"]
    request = {
        "analysis_run_id": run_id, "language": "en", "own_reference_ids": own_ids, "partners": [],
        "include_relevance_notes": True,
        "letter": {"addressee_organization": defaults.get("addressee_organization") or "Procurement unit",
                   "addressee_name": defaults.get("addressee_name"), "signatory_name": "Plasma Smoke Test",
                   "signatory_title": "Smoke check", "contact_email": "plasma-smoke-test@plasma.invalid",
                   "contact_phone": None, "contact_address": None},
    }
    started = time.monotonic()
    status, draft = api.call("POST", f"{base}/eoi-drafts", request)
    generation_s = round(time.monotonic() - started, 1)
    if status != 201 or not isinstance(draft, dict):
        raise LiveSmokeError(f"EOI draft failed (HTTP {status})")
    files = {}
    for artifact in draft["artifacts"]:
        body = download(api, f"{base}/eoi-artifacts/{artifact['artifact_id']}/download")
        files[artifact["format"]] = {
            "bytes": len(body), "sha_ok": hashlib.sha256(body).hexdigest() == artifact["sha256"],
            "signature_ok": body.startswith(SIGNATURES.get(artifact["format"], b"")),
        }
    return {"pursuit_id": pursuit_id, "analysis_run_id": run_id, "criteria": len(suggestions.get("criteria", [])),
            "notes": len(suggestions.get("notes", [])), "suggestions_ms": suggestions_ms,
            "draft_id": draft["draft_id"], "version": draft["version"], "generation_s": generation_s,
            "summary": draft["summary"], "files": files}


def problems_of(record: dict) -> list[str]:
    problems = []
    if sorted(record["files"]) != ["DOCX", "PDF"]:
        problems.append(f"artifacts {sorted(record['files'])}, expected DOCX and PDF")
    for kind, check in record["files"].items():
        if not check["sha_ok"]:
            problems.append(f"{kind} sha256 differs from the draft")
        if not check["signature_ok"] or check["bytes"] < 1_000:
            problems.append(f"{kind} is not a {kind} file ({check['bytes']} bytes)")
    if record["criteria"] < 1:
        problems.append("no shortlisting criteria in the suggestions")
    return problems


def main(argv: list[str] | None = None, environ: dict | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--org-name", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)
    token = (os.environ if environ is None else environ).get("ANALYSIS_SMOKE_TOKEN", "").strip()
    if not token:
        print("FAIL: set ANALYSIS_SMOKE_TOKEN to the smoke user's bearer token", file=sys.stderr)
        return 2
    api = Api(args.api_base, token, args.org_id, timeout=args.timeout)
    try:
        record = run(api, args.org_name)
    except LiveSmokeError as exc:
        print(f"FAIL: {exc}")
        print("eoi smoke: FAILED")
        return 1
    print(json.dumps(record))
    problems = problems_of(record)
    for problem in problems:
        print(f"FAIL: {problem}")
    print("eoi smoke: " + ("FAILED" if problems else "OK"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
