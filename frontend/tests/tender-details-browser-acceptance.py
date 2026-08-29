#!/usr/bin/env python3
"""Real Chromium acceptance for the 40 Sprint 5.3 Tender Details cases."""

from __future__ import annotations

import importlib.util
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s43_browser", HERE / "bid-preparation-browser-acceptance.py")
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

base.BASE_URL = "http://localhost:3110"
base.MOCK_PORT = 8110
base.CDP_PORT = 9230
HARNESS_HOST = "127.0.0.1"

ALLOWED = {
    "SAVED": ["EVALUATE", "PREPARE_BID", "DISMISS"],
    "EVALUATING": ["PREPARE_BID", "DISMISS"],
    "PREPARING": ["MARK_SUBMITTED", "DISMISS"],
    "SUBMITTED": ["RECORD_WON", "RECORD_LOST", "CORRECT_TO_PREPARING"],
    "WON": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_LOST"],
    "LOST": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_WON"],
    "DISMISSED": ["SAVE", "EVALUATE", "PREPARE_BID"],
}


class AcceptanceState:
    details: dict[str, dict] = {}
    details_fail: set[str] = set()
    request_log: list[tuple[str, str]] = []
    mutation_count = 0
    force_stale = False


def envelope(data=None, state: str | None = None, reason: str | None = None) -> dict:
    return {
        "state": state or ("AVAILABLE" if data is not None else "EMPTY"),
        "data": data,
        "reason_code": reason,
    }


def engagement(tender_id: str, status: str) -> dict:
    return {
        "engagement_id": f"engagement-A-{tender_id}",
        "engagement_status": status,
        "engagement_origin": "MANUAL_SAVE",
        "status_changed_at": "2026-08-29T10:00:00Z",
        "allowed_actions": ALLOWED[status],
    }


def details(
    tender_id: str,
    *,
    project_state: str = "AVAILABLE",
    project_enrichment: str = "successful",
    pursuit: str | None = None,
    proposal: bool = False,
    compliance: str | None = "COMPLETE",
    legacy: bool = False,
) -> dict:
    project = {
        "project_id": f"project-{tender_id}",
        "external_project_id": "P179267",
        "name": "Regional Solar Infrastructure Project",
        "source_system": "world_bank",
        "project_status": "Active",
        "country": "Uzbekistan",
        "region": "Central Asia",
        "approval_date": "2023-02-01T00:00:00Z",
        "closing_date": "2027-06-30T00:00:00Z",
        "enrichment_state": project_enrichment,
        "last_enriched_at": "2026-08-29T09:00:00Z",
    }
    leadership = {
        "items": [{
            "role_id": f"role-{tender_id}", "role_type": "PROJECT_LEADERSHIP",
            "display_name": "Project Leader A", "native_role": "Task Team Leader",
            "canonical_role": "TASK_TEAM_LEADER", "source_system": "world_bank",
            "source_url": None, "is_current": True,
            "first_observed_at": "2026-01-01T00:00:00Z",
            "last_observed_at": "2026-08-29T00:00:00Z", "ended_at": None,
        }],
        "total_count": 1, "returned_count": 1, "truncated": False,
    }
    contacts = {
        "buyer_agency": "Public Buyer", "contact_person": "Procurement Contact A",
        "email": "procurement@example.invalid", "phone": "+998 00 000 00 00",
        "address": "Tashkent", "submission_method": "Official portal",
        "submission_deadline": "2026-10-20T00:00:00Z",
        "question_deadline": "2026-10-01T00:00:00Z", "procedure_type": "Open",
        "participation_instructions": "Submit on the official portal.",
        "official_source_url": "https://example.invalid/source",
        "document_access_notes": None, "source_type": "TENDER_SOURCE",
    }
    requirements = {
        "source_native_available": False, "derivation": "ANALYSIS_VERSION",
        "items": [{"label": "Provide three years of audited accounts", "source_type": "AI_EXTRACTED", "document_name": "RFP.pdf", "page": 12, "section": "Eligibility"}],
        "total_count": 1, "returned_count": 1, "truncated": False,
    }
    documents = {
        "items": [{
            "document_id": f"public-{tender_id}", "display_name": "RFP.pdf",
            "document_type": "RFP", "metadata_classification": "PUBLIC_SOURCE_METADATA",
            "source_system": "uzex", "availability": "AVAILABLE", "file_size": 2048,
            "content_type": "application/pdf", "created_at": "2026-08-29T08:00:00Z",
        }],
        "visible_total_count": 1, "returned_count": 1, "omitted_unknown_count": 1,
        "truncated": False, "download_authorization_separate": True,
    }
    compliance_data = None if compliance is None else {
        "analysis_id": f"analysis-{tender_id}", "version_number": 2,
        "execution_state": "FAILED" if compliance == "FAILED" else "COMPLETED",
        "compliance_completeness": "PARTIAL" if compliance == "PARTIAL" else "COMPLETE",
        "decision_label": "REVIEW" if compliance == "PARTIAL" else "COMPLIANT",
        "key_issue_count": 2, "coverage_signal": "BOUNDED",
        "version_origin": "LEGACY_BACKFILL" if legacy else "NATIVE",
        "override_applied": False, "created_at": "2026-08-29T08:00:00Z",
        "completed_at": None if compliance == "FAILED" else "2026-08-29T08:01:00Z",
    }
    readiness = {
        "profile_available": True, "certifications_total": 4, "expired_certifications": 1,
        "licenses_total": 3, "active_licenses": 2, "credentials_total": 5,
        "expired_credentials": 1, "readiness_documents_total": 8,
        "readiness_documents_available": 6, "readiness_documents_missing": 1,
        "readiness_documents_expired": 1, "readiness_documents_unknown": 0,
        "financial_history_years": 3,
    }
    proposal_data = None
    if proposal:
        proposal_id = f"proposal-{tender_id}"
        proposal_data = {
            "proposal_id": proposal_id, "proposal_status": "DRAFT",
            "created_at": "2026-08-29T10:00:00Z", "detail_route_id": proposal_id,
        }
    return {
        "tender_id": tender_id,
        "project_context": envelope(project, project_state, "UPSTREAM_UNAVAILABLE" if project_state == "UNAVAILABLE" else None),
        "project_leadership": envelope(leadership),
        "procurement_contacts": envelope(contacts),
        "requirements": envelope(requirements),
        "documents": envelope(documents),
        "compliance": envelope(compliance_data, "UNAVAILABLE" if compliance == "FAILED" else None, "ANALYSIS_FAILED" if compliance == "FAILED" else None),
        "company_readiness": envelope(readiness),
        "pursuit": envelope(engagement(tender_id, pursuit) if pursuit else None),
        "bid_preparation": envelope(proposal_data),
    }


class Handler(base.Handler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        AcceptanceState.request_log.append(("GET", path))
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "tenders"] and parts[4] == "details":
            tender_id = parts[3]
            if tender_id in AcceptanceState.details_fail:
                self.send_json(503, {"detail": "Consolidated details are temporarily unavailable."})
            elif tender_id not in base.State.tenders:
                self.send_json(404, {"detail": "Tender not found"})
            else:
                self.send_json(200, AcceptanceState.details[tender_id])
            return
        if len(parts) == 6 and parts[:4] == ["api", "v1", "tenders", "documents"] and parts[5] == "download":
            document_id = parts[4]
            if document_id.startswith("private-"):
                self.send_json(403, {"detail": "Document access denied"})
            else:
                self.send_binary("application/pdf", b"%PDF-s53")
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        AcceptanceState.request_log.append(("POST", path))
        if path != "/api/v1/auth/refresh":
            AcceptanceState.mutation_count += 1
        parts = path.strip("/").split("/")
        if len(parts) == 6 and parts[:3] == ["api", "v1", "my-tenders"] and parts[4] == "actions":
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            tender_id = parts[3].removeprefix("engagement-A-")
            if AcceptanceState.force_stale:
                AcceptanceState.force_stale = False
                base.State.engagements[("A", tender_id)] = "PREPARING"
                AcceptanceState.details[tender_id]["pursuit"] = envelope(engagement(tender_id, "PREPARING"))
                self.send_json(409, {"detail": "stale engagement status"})
                return
        super().do_POST()


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3110&& set BACKEND_INTERNAL_URL=http://127.0.0.1:8110/api/v1&& "
        "set NEXT_DIST_DIR=.next-s53&& npm run dev -- -p 3110"
    )
    return subprocess.Popen([base.CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", base.MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    results: list[dict[str, str]] = []
    browser = None

    def record(case: str) -> None:
        results.append({"case": case, "result": "passed"})

    def fixture(
        tender_id: str,
        *,
        source_status: str = "OPEN",
        project_state: str = "AVAILABLE",
        project_enrichment: str = "successful",
        pursuit: str | None = None,
        proposal_exists: bool = False,
        compliance: str | None = "COMPLETE",
        legacy: bool = False,
    ) -> None:
        row = base.tender(tender_id, f"Consolidated Tender {tender_id}", status=source_status)
        base.State.tenders[tender_id] = row
        if pursuit:
            base.State.engagements[("A", tender_id)] = pursuit
        if proposal_exists:
            proposal_id = f"proposal-{tender_id}"
            base.State.proposals[proposal_id] = base.proposal(proposal_id, row)
        AcceptanceState.details[tender_id] = details(
            tender_id, project_state=project_state, project_enrichment=project_enrichment,
            pursuit=pursuit, proposal=proposal_exists, compliance=compliance, legacy=legacy,
        )

    def open_tender(page, tender_id: str, fragment: str = "") -> None:
        page.goto(f"{base.BASE_URL}/dashboard/tenders/{tender_id}{fragment}", wait_until="networkidle")
        page.get_by_role("heading", name=f"Consolidated Tender {tender_id}").wait_for()

    try:
        # Run this harness with the workspace's Windows Python, matching the
        # existing browser acceptances and the Windows Chromium installation.
        base.wait_for_url(f"http://{HARNESS_HOST}:3110")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_path = r"C:\Users\acer\AppData\Local\Temp\s53-browser-profile"
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--remote-debugging-address=0.0.0.0','--remote-debugging-port={base.CDP_PORT}',"
            f"'--user-data-dir={profile_path}','about:blank'"
        )
        subprocess.run([base.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        base.wait_for_url(f"http://{HARNESS_HOST}:{base.CDP_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{HARNESS_HOST}:{base.CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{"name": "authjs.session-token", "value": base.session_cookie(), "url": base.BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1360, "height": 900})

            fixture("tender-only", compliance=None)
            for section in ("project_context", "project_leadership", "procurement_contacts", "requirements", "documents", "company_readiness", "pursuit", "bid_preparation"):
                AcceptanceState.details["tender-only"][section] = envelope()
            open_tender(page, "tender-only")
            page.get_by_text("No canonical Project is linked", exact=False).wait_for()
            record("1 Tender-only page")
            fixture("full")
            open_tender(page, "full")
            page.get_by_role("heading", name="Project Context").wait_for(); record("2 Project section")

            fixture("pending", project_enrichment="running")
            open_tender(page, "pending")
            page.get_by_text("Project details are being prepared", exact=False).wait_for(); record("3 Project pending")

            fixture("project-unavailable", project_state="UNAVAILABLE")
            open_tender(page, "project-unavailable")
            page.get_by_text("Project details are not currently available", exact=False).first.wait_for(); record("4 Project unavailable")

            open_tender(page, "full")
            page.get_by_text("Project Leader A", exact=True).wait_for(); record("5 Project Leadership")
            page.get_by_text("Procurement Contact A", exact=True).wait_for(); record("6 Procurement Contacts")
            assert page.get_by_text("Project Leader A", exact=True).count() == 1 and page.get_by_text("Procurement Contact A", exact=True).count() == 1
            record("7 Leadership/contact separation")
            page.get_by_text("AI-extracted requirement", exact=True).wait_for(); record("8 requirements analysis-derived label")
            page.get_by_text("RFP.pdf", exact=True).wait_for(); record("9 documents metadata")
            denied = page.request.get(f"{base.BASE_URL}/api/v1/tenders/documents/private-foreign/download")
            assert denied.status == 403; record("10 unauthorized document remains denied")
            page.get_by_text("Summary from the latest immutable Compliance version.", exact=True).wait_for(); record("11 Compliance complete")

            fixture("partial", compliance="PARTIAL")
            open_tender(page, "partial"); page.get_by_text("Partial analysis", exact=True).wait_for(); record("12 Compliance PARTIAL")
            fixture("failed", compliance="FAILED")
            open_tender(page, "failed"); page.get_by_text("Analysis failed", exact=True).wait_for(); record("13 Compliance FAILED")
            fixture("legacy", legacy=True)
            open_tender(page, "legacy"); page.get_by_text("Legacy analysis", exact=True).first.wait_for(); record("14 Compliance LEGACY")

            page.get_by_role("heading", name="Company Readiness", exact=True).wait_for(); record("15 readiness summary")
            assert page.get_by_text("No readiness percentage is calculated", exact=False).count() == 1
            assert page.locator("text=Readiness score").count() == 0; record("16 no invented readiness score")

            fixture("none", compliance=None)
            open_tender(page, "none"); page.get_by_text("Not currently in My Tenders.", exact=True).wait_for(); record("17 no engagement")
            for number, status in ((18, "SAVED"), (19, "PREPARING"), (20, "SUBMITTED")):
                tender_id = status.lower()
                fixture(tender_id, pursuit=status, proposal_exists=status == "PREPARING")
                open_tender(page, tender_id)
                page.get_by_text(f"Pursuit: {status.title()}", exact=True).wait_for(); record(f"{number} {status} pursuit")

            fixture("proposal-only", proposal_exists=True)
            open_tender(page, "proposal-only")
            page.get_by_text("Not currently in My Tenders.", exact=True).wait_for()
            page.get_by_role("link", name="Open Bid Preparation", exact=True).wait_for(); record("21 Proposal-only legacy")

            fixture("engagement-only", pursuit="SAVED")
            open_tender(page, "engagement-only")
            assert page.get_by_text("Pursuit: Saved", exact=True).count() == 1
            assert page.get_by_text("Not started", exact=True).count() == 1; record("22 engagement-only")

            fixture("both", pursuit="PREPARING", proposal_exists=True)
            open_tender(page, "both")
            assert page.get_by_text("Pursuit: Preparing", exact=True).count() == 1
            assert page.get_by_role("link", name="Open Bid Preparation", exact=True).count() >= 1; record("23 engagement + Proposal")

            fixture("compliance-only")
            payload = AcceptanceState.details["compliance-only"]
            for section in ("project_context", "project_leadership", "procurement_contacts", "requirements", "documents", "company_readiness", "pursuit", "bid_preparation"):
                payload[section] = envelope()
            open_tender(page, "compliance-only")
            page.get_by_text("Summary from the latest immutable Compliance version.", exact=True).wait_for(); record("24 Compliance-only")

            fixture("prepare-route")
            open_tender(page, "prepare-route")
            page.get_by_role("button", name="Prepare Bid", exact=True).click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-prepare-route"); record("25 Prepare Bid navigation uses Proposal ID")

            open_tender(page, "both")
            page.get_by_role("link", name="Open Bid Preparation", exact=True).first.click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-both"); record("26 Open Bid Preparation uses Proposal ID")
            open_tender(page, "full")
            page.get_by_role("link", name="Open Compliance", exact=True).first.click()
            page.wait_for_url("**/dashboard/tenders/full/compliance"); record("27 Open Compliance uses Tender ID")

            open_tender(page, "saved")
            assert page.get_by_text("Tender status: Open", exact=True).count() == 1
            assert page.get_by_text("Pursuit: Saved", exact=True).count() == 1; record("28 source status + pursuit status coexist")

            fixture("cancelled", source_status="CANCELLED", pursuit="SAVED")
            open_tender(page, "cancelled")
            assert page.get_by_text("Tender status: Cancelled", exact=True).count() == 1
            assert page.get_by_text("Pursuit: Saved", exact=True).count() == 1; record("29 Tender CANCELLED + pursuit state")

            fixture("details-failure")
            AcceptanceState.details_fail.add("details-failure")
            open_tender(page, "details-failure")
            page.get_by_text("Additional Tender details could not be loaded.", exact=True).wait_for(); record("30 details endpoint failure isolation")
            AcceptanceState.details_fail.remove("details-failure")

            fixture("stale", pursuit="SAVED")
            open_tender(page, "stale")
            AcceptanceState.force_stale = True
            page.get_by_role("button", name="Evaluate", exact=True).click()
            page.get_by_text("Pursuit: Preparing", exact=True).wait_for(); record("31 stale engagement 409 refresh")

            fixture("same-name-a")
            fixture("same-name-b")
            AcceptanceState.details["same-name-b"]["procurement_contacts"]["data"]["contact_person"] = "Tenant B Private Contact"
            open_tender(page, "same-name-a")
            assert page.get_by_text("Tenant B Private Contact", exact=True).count() == 0; record("32 same-name tenant isolation")
            assert "Tenant B Private Contact" not in json.dumps(AcceptanceState.details["same-name-a"]); record("33 foreign private context hidden")

            for number, fragment, heading in (
                (34, "#project-context", "Project Context"),
                (35, "#compliance-readiness", "Compliance & Company Readiness"),
                (36, "#bid-preparation", "Bid Preparation"),
            ):
                open_tender(page, "full", fragment)
                page.get_by_role("heading", name=heading).wait_for()
                assert page.evaluate("location.hash") == fragment
                record(f"{number} section deep-link {fragment}")

            before_mutations = AcceptanceState.mutation_count
            for _ in range(2):
                open_tender(page, "full")
                page.get_by_role("link", name="Project", exact=True).click()
            assert AcceptanceState.mutation_count == before_mutations; record("37 repeated passive loads cause zero writes")
            initial_paths = [path for method, path in AcceptanceState.request_log if method == "GET"]
            assert not any("decision-snapshot" in path for path in initial_paths); record("38 no redundant Decision Snapshot request")
            proposal_count = len(base.State.proposals)
            open_tender(page, "none")
            assert len(base.State.proposals) == proposal_count; record("39 no GET-side Proposal creation")
            engagement_count = len(base.State.engagements)
            open_tender(page, "none")
            assert len(base.State.engagements) == engagement_count; record("40 no GET-side engagement creation")

            core = [path for method, path in AcceptanceState.request_log if method == "GET" and path.startswith("/api/v1/tenders/full")]
            assert "/api/v1/tenders/full" in core and "/api/v1/tenders/full/details" in core
            assert not any(path.endswith(("/project", "/engagement", "/competitors", "/documents", "/decision-snapshot")) for path in core)
            page.set_viewport_size({"width": 390, "height": 844})
            open_tender(page, "full")
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        subprocess.run([base.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        base.kill_listener(base.BASE_URL.rsplit(":", 1)[-1])
        base.kill_listener(base.CDP_PORT)

    print(json.dumps({"results": results, "passed": len(results)}, indent=2))
    assert len(results) == 40
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
