#!/usr/bin/env python3
"""Real Chromium acceptance for Sprint 4.3 Bid Preparation reconciliation."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


BASE_URL = "http://localhost:3107"
MOCK_PORT = 8107
CDP_PORT = 9227
ROOT = Path(__file__).resolve().parents[1]
CMD = r"C:\Windows\System32\cmd.exe" if os.name == "nt" else "/mnt/c/Windows/System32/cmd.exe"
POWERSHELL = (
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    if os.name == "nt"
    else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)
TASKKILL = r"C:\Windows\System32\taskkill.exe" if os.name == "nt" else "/mnt/c/Windows/System32/taskkill.exe"
NETSTAT = r"C:\Windows\System32\netstat.exe" if os.name == "nt" else "/mnt/c/Windows/System32/netstat.exe"


def tender(tender_id: str, title: str, *, status: str = "OPEN") -> dict:
    return {
        "id": tender_id,
        "external_id": f"S43-{tender_id}",
        "source_system": "uzex",
        "canonical_source_key": f"uzex:{tender_id}",
        "source_url": "https://example.invalid/source",
        "title": title,
        "description": "Sprint 4.3 browser acceptance Tender.",
        "budget": 125000,
        "currency": "USD",
        "deadline": "2026-10-20T00:00:00Z",
        "publication_date": "2026-08-01T00:00:00Z",
        "country": "Uzbekistan",
        "region": "Tashkent",
        "sector": "Digital services",
        "buyer": "Public Buyer",
        "procurement_category": "Services",
        "procurement_method": "Open procedure",
        "notice_type": "Invitation",
        "project_id": None,
        "price_amount": 125000,
        "price_currency": "USD",
        "price_display": "125,000 USD",
        "status": status,
        "category": "Other",
        "has_compiled_text": False,
        "document_status": "no_documents_found",
        "document_count": 0,
        "available_document_count": 0,
        "downloadable_document_count": 0,
        "missing_file_document_count": 0,
        "parsed_document_count": 0,
        "metadata_only_document_count": 0,
        "failed_document_count": 0,
        "compliance_analysis_available": False,
        "compliance_unavailable_reason": "No documents",
        "contact_submission": None,
        "created_at": "2026-08-28T10:00:00Z",
    }


def proposal(proposal_id: str, tender_row: dict, *, owner: str = "A", status: str = "DRAFT") -> dict:
    return {
        "owner": owner,
        "id": proposal_id,
        "user_id": f"tenant-{owner.lower()}",
        "tender_id": tender_row["id"],
        "status": status,
        "ai_confidence_score": 0,
        "structured_data": {"our_price": 1000, "delivery_days": 30},
        "final_pdf_url": None,
        "margin_percent": 20,
        "include_vat": True,
        "currency": "USD",
        "created_at": "2026-08-28T10:00:00Z",
        "tender_title": tender_row["title"],
        "tender_budget": tender_row["budget"],
        "tender_currency": tender_row["currency"],
        "tender_deadline": tender_row["deadline"],
        "tender_region": tender_row["region"],
        "tender_source_system": tender_row["source_system"],
        "tender_status": tender_row["status"],
    }


class State:
    authority = True
    tenders: dict[str, dict] = {}
    proposals: dict[str, dict] = {}
    engagements: dict[tuple[str, str], str] = {}
    prepare_calls = 0
    export_calls: list[str] = []


def public_proposal(row: dict) -> dict:
    payload = {key: value for key, value in row.items() if key != "owner"}
    payload["engagement_status"] = State.engagements.get((row["owner"], row["tender_id"]))
    return payload


def my_tender_item(owner: str, tender_id: str, status: str) -> dict:
    row = State.tenders[tender_id]
    allowed = {
        "SAVED": ["EVALUATE", "PREPARE_BID", "DISMISS"],
        "EVALUATING": ["PREPARE_BID", "DISMISS"],
        "PREPARING": ["MARK_SUBMITTED", "DISMISS"],
        "SUBMITTED": ["RECORD_WON", "RECORD_LOST", "CORRECT_TO_PREPARING"],
        "WON": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_LOST"],
        "LOST": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_WON"],
        "DISMISSED": ["SAVE", "EVALUATE", "PREPARE_BID"],
    }
    return {
        "engagement_id": f"engagement-{owner}-{tender_id}",
        "tender_id": tender_id,
        "engagement_status": status,
        "engagement_origin": "BID_PREPARATION",
        "engagement_created_at": "2026-08-28T10:00:00Z",
        "engagement_updated_at": "2026-08-28T10:00:00Z",
        "status_changed_at": "2026-08-28T10:00:00Z",
        "allowed_actions": allowed[status],
        "tender_title": row["title"],
        "buyer": row["buyer"],
        "source_system": row["source_system"],
        "tender_status": row["status"],
        "deadline": row["deadline"],
        "estimated_value": row["budget"],
        "currency": row["currency"],
        "notice_type": row["notice_type"],
        "procurement_method": row["procurement_method"],
        "country": row["country"],
        "region": row["region"],
        "project_external_id": None,
        "project_name": None,
        "project_source_system": None,
        "project_enrichment_status": None,
    }


def prepare_for(owner: str, tender_id: str, existing: dict | None = None) -> dict:
    State.prepare_calls += 1
    current = State.engagements.get((owner, tender_id))
    if current not in {"SUBMITTED", "WON", "LOST"}:
        State.engagements[(owner, tender_id)] = "PREPARING"
    matching = existing or next(
        (row for row in State.proposals.values() if row["owner"] == owner and row["tender_id"] == tender_id),
        None,
    )
    created = matching is None
    if matching is None:
        matching = proposal(f"proposal-{tender_id}", State.tenders[tender_id], owner=owner)
        State.proposals[matching["id"]] = matching
    status = State.engagements[(owner, tender_id)]
    return {
        "proposal": {**public_proposal(matching), "engagement_status": status},
        "engagement": {
            "engagement_id": f"engagement-{owner}-{tender_id}",
            "tender_id": tender_id,
            "engagement_status": status,
            "engagement_origin": "BID_PREPARATION",
            "engagement_created_at": "2026-08-28T10:00:00Z",
            "engagement_updated_at": "2026-08-28T10:00:00Z",
            "status_changed_at": "2026-08-28T10:00:00Z",
            "allowed_actions": my_tender_item(owner, tender_id, status)["allowed_actions"],
        },
        "proposal_created": created,
        "engagement_created": current is None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_binary(self, media_type: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v1/users/me":
            self.send_json(200, {"id": "tenant-a", "email": "tenant-a@s43.invalid"}) if State.authority else self.send_json(401, {"detail": "stale credentials"})
            return
        if path == "/api/v1/users/me/access-status":
            if not State.authority:
                self.send_json(401, {"detail": "stale credentials"})
            else:
                self.send_json(200, {
                    "company_profile_id": "profile-a", "company_name": "Same Name Company",
                    "onboarding_required": False, "onboarding_completed": True,
                    "user_approval_status": "approved", "company_approval_status": "approved",
                    "platform_role": "pilot_user", "access_allowed": True, "state": "approved",
                })
            return
        if path == "/api/v1/vault":
            self.send_json(200, {"company_name": "Same Name Company"})
            return
        if path == "/api/v1/proposals":
            rows = [public_proposal(row) for row in State.proposals.values() if row["owner"] == "A"]
            self.send_json(200, rows)
            return
        if path == "/api/v1/my-tenders":
            query = parse_qs(parsed.query)
            status_filter = query.get("status", ["ACTIVE"])[0]
            search = query.get("search", [""])[0].casefold()
            owner_rows = [my_tender_item(owner, tid, status) for (owner, tid), status in State.engagements.items() if owner == "A"]
            rows = owner_rows
            if status_filter == "ACTIVE":
                rows = [row for row in rows if row["engagement_status"] != "DISMISSED"]
            elif status_filter != "ALL":
                rows = [row for row in rows if row["engagement_status"] == status_filter]
            if search:
                rows = [row for row in rows if search in row["tender_title"].casefold()]
            statuses = ("SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED")
            counts = {status.lower(): sum(row["engagement_status"] == status for row in owner_rows) for status in statuses}
            counts["all"] = len(owner_rows)
            counts["active"] = len(owner_rows) - counts["dismissed"]
            self.send_json(200, {"items": rows, "total": len(rows), "limit": 25, "offset": 0, "counts": counts})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:3] == ["api", "v1", "proposals"]:
            row = State.proposals.get(parts[3])
            if row is None or row["owner"] != "A":
                self.send_json(404, {"detail": "Bid Preparation not found"})
            else:
                self.send_json(200, public_proposal(row))
            return
        if len(parts) >= 4 and parts[:3] == ["api", "v1", "tenders"]:
            tender_id = parts[3]
            row = State.tenders.get(tender_id)
            if row is None:
                self.send_json(404, {"detail": "Tender not found"})
                return
            if len(parts) == 4:
                self.send_json(200, row)
                return
            action = parts[4]
            if action == "engagement":
                status = State.engagements.get(("A", tender_id))
                payload = None if status is None else {
                    "engagement_id": f"engagement-A-{tender_id}", "tender_id": tender_id,
                    "engagement_status": status, "engagement_origin": "BID_PREPARATION",
                    "engagement_created_at": "2026-08-28T10:00:00Z", "engagement_updated_at": "2026-08-28T10:00:00Z",
                    "status_changed_at": "2026-08-28T10:00:00Z",
                }
                if payload is not None:
                    payload["allowed_actions"] = my_tender_item("A", tender_id, status)["allowed_actions"]
                matching = next((proposal_id for proposal_id, proposal_row in State.proposals.items() if proposal_row["owner"] == "A" and proposal_row["tender_id"] == tender_id), None)
                self.send_json(200, {"engagement": payload, "proposal_id": matching})
            elif action == "sync-status":
                self.send_json(200, {"state": "SUCCESS", "progress": 100, "docs_parsed": 0, "error": None})
            elif action == "documents":
                self.send_json(200, [])
            elif action == "competitors":
                self.send_json(200, {"tender_id": tender_id, "message": "Unavailable", "groups": []})
            elif action == "project":
                self.send_json(200, None)
            elif action == "decision-snapshot":
                self.send_json(404, {"detail": "Unavailable"})
            else:
                self.send_json(404, {"detail": "not found"})
            return
        self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        payload = json.loads(raw or b"{}")
        if path == "/api/v1/auth/refresh":
            if not State.authority:
                self.send_json(403, {"detail": "stale credentials"})
            else:
                self.send_json(200, {
                    "access_token": "s43-rotated-access-token", "token_type": "bearer",
                    "approval_status": "approved", "platform_role": "pilot_user", "is_admin": False,
                    "onboarding_required": False, "company_profile_id": "profile-a",
                    "company_approval_status": "approved", "company_pilot_status": "active_pilot",
                })
            return
        if path == "/api/v1/proposals/prepare":
            tender_id = payload.get("tender_id")
            if tender_id not in State.tenders:
                self.send_json(404, {"detail": "Tender not found"})
            else:
                self.send_json(200, prepare_for("A", tender_id))
            return
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "proposals"] and parts[4] == "continue":
            row = State.proposals.get(parts[3])
            if row is None or row["owner"] != "A":
                self.send_json(404, {"detail": "Bid Preparation not found"})
            else:
                self.send_json(200, prepare_for("A", row["tender_id"], row))
            return
        if len(parts) == 5 and parts[:3] == ["api", "v1", "proposals"] and parts[4] in {"generate-pdf", "export"}:
            State.export_calls.append(parts[4])
            self.send_binary("application/octet-stream", b"s43")
            return
        if len(parts) == 6 and parts[:3] == ["api", "v1", "proposals"] and parts[4:6] == ["export", "docx"]:
            State.export_calls.append("docx")
            self.send_binary("application/octet-stream", b"s43")
            return
        self.send_json(404, {"detail": "not found"})


def wait_for_url(url: str, timeout: float = 60) -> None:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}")


def session_cookie() -> str:
    command = "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& node tests\\make-s42-session.mjs"
    result = subprocess.run([CMD, "/d", "/s", "/c", command], text=True, capture_output=True, check=True)
    return result.stdout.strip().splitlines()[-1]


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3107&& set BACKEND_INTERNAL_URL=http://127.0.0.1:8107/api/v1&& "
        "set NEXT_DIST_DIR=.next-s43&& npm run dev -- -p 3107"
    )
    return subprocess.Popen([CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def record(results: list[dict[str, str]], case: str) -> None:
    results.append({"case": case, "result": "passed"})


def kill_listener(port: int) -> None:
    result = subprocess.run([NETSTAT, "-ano", "-p", "tcp"], text=True, capture_output=True, check=False)
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 5 and columns[3] == "LISTENING" and columns[1].rsplit(":", 1)[-1] == str(port):
            subprocess.run([TASKKILL, "/PID", columns[4], "/T", "/F"], capture_output=True, check=False)
            return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    results: list[dict[str, str]] = []
    browser = None
    try:
        wait_for_url(BASE_URL)
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_path = r"C:\Users\acer\AppData\Local\Temp\s43-browser-profile"
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--remote-debugging-address=0.0.0.0','--remote-debugging-port={CDP_PORT}',"
            f"'--user-data-dir={profile_path}','about:blank'"
        )
        subprocess.run([POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        wait_for_url(f"http://127.0.0.1:{CDP_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{"name": "authjs.session-token", "value": session_cookie(), "url": BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1360, "height": 850})

            page.goto(f"{BASE_URL}/dashboard/bid-preparation", wait_until="networkidle")
            page.get_by_role("link", name="Bid Preparation", exact=True).wait_for()
            assert page.get_by_role("link", name="My Bids", exact=True).count() == 0
            record(results, "My Bids nav replaced by Bid Preparation")

            page.goto(f"{BASE_URL}/dashboard/bids", wait_until="networkidle")
            assert urlparse(page.url).path == "/dashboard/bid-preparation"
            record(results, "legacy bids list redirects")

            owned_tender = tender("t-owned", "Owned Legacy Artifact")
            State.tenders[owned_tender["id"]] = owned_tender
            State.proposals["p-owned"] = proposal("p-owned", owned_tender)
            page.goto(f"{BASE_URL}/dashboard/bids/p-owned", wait_until="networkidle")
            page.wait_for_url("**/dashboard/bid-preparation/p-owned")
            record(results, "owned legacy Proposal bookmark redirects")

            tender_bookmark = tender("t-bookmark", "Tender Bookmark Must Not Create")
            State.tenders[tender_bookmark["id"]] = tender_bookmark
            proposal_count = len(State.proposals)
            page.goto(f"{BASE_URL}/dashboard/bids/t-bookmark", wait_until="networkidle")
            page.get_by_text("This legacy bookmark is not an owned Bid Preparation artifact.", exact=True).wait_for()
            assert len(State.proposals) == proposal_count
            record(results, "legacy Tender ID bookmark creates nothing")

            engagement_count = len(State.engagements)
            page.goto(f"{BASE_URL}/dashboard/bid-preparation/p-owned", wait_until="networkidle")
            page.get_by_role("heading", name="Owned Legacy Artifact").wait_for()
            assert len(State.proposals) == proposal_count and len(State.engagements) == engagement_count
            record(results, "opening canonical detail creates nothing")

            async_cases = [
                ("none", None, "PREPARING"),
                ("saved", "SAVED", "PREPARING"),
                ("evaluating", "EVALUATING", "PREPARING"),
                ("dismissed", "DISMISSED", "PREPARING"),
                ("preparing", "PREPARING", "PREPARING"),
            ]
            for label, initial, expected in async_cases:
                row = tender(f"t-{label}", f"Prepare {label.title()}")
                State.tenders[row["id"]] = row
                if initial:
                    State.engagements[("A", row["id"])] = initial
                page.goto(f"{BASE_URL}/dashboard/tenders/{row['id']}", wait_until="networkidle")
                if initial == "PREPARING":
                    response = page.request.post(f"{BASE_URL}/api/v1/proposals/prepare", data={"tender_id": row["id"]})
                    assert response.status == 200
                else:
                    page.get_by_role("button", name="Prepare Bid", exact=True).click()
                    page.wait_for_url("**/dashboard/bid-preparation/proposal-*")
                assert State.engagements[("A", row["id"])] == expected
                record(results, f"Prepare from {label}")

            higher_ids = []
            for higher in ("SUBMITTED", "WON", "LOST"):
                row = tender(f"t-{higher.lower()}", f"Prepare {higher.title()}")
                State.tenders[row["id"]] = row
                State.engagements[("A", row["id"])] = higher
                higher_ids.append((row, higher))
                page.goto(f"{BASE_URL}/dashboard/tenders/{row['id']}", wait_until="networkidle")
                response = page.request.post(f"{BASE_URL}/api/v1/proposals/prepare", data={"tender_id": row["id"]})
                assert response.status == 200
                assert State.engagements[("A", row["id"])] == higher
            record(results, "SUBMITTED WON LOST not downgraded")

            repeated_tender = State.tenders["t-preparing"]
            proposal_id = next(row["id"] for row in State.proposals.values() if row["tender_id"] == repeated_tender["id"])
            before = (len(State.proposals), len(State.engagements))
            page.goto(f"{BASE_URL}/dashboard/tenders/{repeated_tender['id']}", wait_until="networkidle")
            response = page.request.post(f"{BASE_URL}/api/v1/proposals/prepare", data={"tender_id": repeated_tender["id"]})
            assert response.status == 200
            assert (len(State.proposals), len(State.engagements)) == before
            record(results, "repeated Prepare reuses Proposal and engagement")

            legacy_tender = tender("t-legacy-only", "Legacy Proposal Only")
            unrelated_tender = tender("t-unrelated", "Unrelated Proposal Only")
            State.tenders[legacy_tender["id"]] = legacy_tender
            State.tenders[unrelated_tender["id"]] = unrelated_tender
            State.proposals["p-legacy"] = proposal("p-legacy", legacy_tender)
            State.proposals["p-unrelated"] = proposal("p-unrelated", unrelated_tender)
            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=Legacy", wait_until="networkidle")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            record(results, "Proposal-only legacy Tender absent from My Tenders")

            page.goto(f"{BASE_URL}/dashboard/bid-preparation", wait_until="networkidle")
            card = page.get_by_text("Legacy Proposal Only", exact=True).locator("xpath=ancestor::div[contains(@class,'group')]")
            card.get_by_role("button", name="Continue Bid Preparation", exact=True).click()
            page.wait_for_url("**/dashboard/bid-preparation/p-legacy")
            assert State.engagements[("A", "t-legacy-only")] == "PREPARING"
            assert State.proposals["p-legacy"]["id"] == "p-legacy"
            record(results, "explicit Continue legacy preparation")

            completed_tender = tender("t-completed", "Completed Artifact")
            State.tenders[completed_tender["id"]] = completed_tender
            State.proposals["p-completed"] = proposal("p-completed", completed_tender, status="COMPLETED")
            page.goto(f"{BASE_URL}/dashboard/bid-preparation/p-completed", wait_until="networkidle")
            assert ("A", "t-completed") not in State.engagements
            record(results, "Completed artifact does not infer Submitted")

            export_tender, export_status = higher_ids[0]
            export_proposal = next(row for row in State.proposals.values() if row["tender_id"] == export_tender["id"])
            page.goto(f"{BASE_URL}/dashboard/bid-preparation/{export_proposal['id']}", wait_until="networkidle")
            page.get_by_role("button", name="Download PDF", exact=True).click()
            page.get_by_role("button", name="Download Word", exact=True).click()
            page.wait_for_timeout(500)
            assert State.engagements[("A", export_tender["id"])] == export_status
            assert {"generate-pdf", "docx"}.issubset(State.export_calls)
            record(results, "PDF and DOCX do not infer Submitted")

            other_tender = tender("t-other", "Other Tenant Secret")
            State.tenders[other_tender["id"]] = other_tender
            State.proposals["p-other"] = proposal("p-other", other_tender, owner="B")
            page.goto(f"{BASE_URL}/dashboard/bid-preparation", wait_until="networkidle")
            assert page.get_by_text("Other Tenant Secret", exact=True).count() == 0
            page.goto(f"{BASE_URL}/dashboard/bids/p-other", wait_until="networkidle")
            page.get_by_text("This legacy bookmark is not an owned Bid Preparation artifact.", exact=True).wait_for()
            assert ("A", "t-other") not in State.engagements
            record(results, "same-name tenant isolation")

            page.goto(f"{BASE_URL}/dashboard/bid-preparation/not-a-proposal", wait_until="networkidle")
            page.get_by_text("Bid Preparation not found", exact=True).wait_for()
            record(results, "invalid and foreign Proposal IDs are safe")

            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=Proposal+Only", wait_until="networkidle")
            page.get_by_text("Legacy Proposal Only", exact=True).wait_for()
            assert page.get_by_text("Unrelated Proposal Only", exact=True).count() == 0
            record(results, "My Tenders remains engagement-only after Continue")

            State.authority = False
            page.goto(f"{BASE_URL}/dashboard/bid-preparation", wait_until="domcontentloaded")
            page.wait_for_url(lambda url: urlparse(url).path == "/", timeout=15000)
            record(results, "stale or revoked credential denied")
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        subprocess.run([TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        kill_listener(3107)
        kill_listener(9227)

    print(json.dumps({"results": results, "passed": len(results)}, indent=2))
    assert len(results) == 20
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
