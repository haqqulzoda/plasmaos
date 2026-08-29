#!/usr/bin/env python3
"""Real Chromium acceptance for the Sprint 4.2 My Tenders customer flow."""

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


BASE_URL = "http://localhost:3106"
MOCK_PORT = 8106
CDP_PORT = 9226
ROOT = Path(__file__).resolve().parents[1]
CMD = r"C:\Windows\System32\cmd.exe" if os.name == "nt" else "/mnt/c/Windows/System32/cmd.exe"
POWERSHELL = (
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    if os.name == "nt"
    else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)
TASKKILL = r"C:\Windows\System32\taskkill.exe" if os.name == "nt" else "/mnt/c/Windows/System32/taskkill.exe"
NETSTAT = r"C:\Windows\System32\netstat.exe" if os.name == "nt" else "/mnt/c/Windows/System32/netstat.exe"


def tender(tender_id: str, title: str, *, status: str = "OPEN", source: str = "uzex") -> dict:
    return {
        "id": tender_id,
        "external_id": f"S42-{tender_id}",
        "source_system": source,
        "canonical_source_key": f"{source}:{tender_id}",
        "source_url": "https://example.invalid/source",
        "title": title,
        "description": "Browser acceptance tender.",
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
        "project_id": "P424242" if source == "world_bank" else None,
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


def engagement(
    tender_row: dict,
    status: str,
    *,
    owner: str = "A",
    suffix: str | None = None,
    project: bool = False,
) -> dict:
    marker = suffix or tender_row["id"]
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
        "owner": owner,
        "engagement_id": f"engagement-{marker}",
        "tender_id": tender_row["id"],
        "engagement_status": status,
        "engagement_origin": "MANUAL_SAVE",
        "engagement_created_at": "2026-08-28T10:00:00Z",
        "engagement_updated_at": "2026-08-28T10:00:00Z",
        "status_changed_at": "2026-08-28T10:00:00Z",
        "allowed_actions": allowed[status],
        "tender_title": tender_row["title"],
        "buyer": tender_row["buyer"],
        "source_system": tender_row["source_system"],
        "tender_status": tender_row["status"],
        "deadline": tender_row["deadline"],
        "estimated_value": tender_row["budget"],
        "currency": tender_row["currency"],
        "notice_type": tender_row["notice_type"],
        "procurement_method": tender_row["procurement_method"],
        "country": tender_row["country"],
        "region": tender_row["region"],
        "project_external_id": "P424242" if project else None,
        "project_name": None,
        "project_source_system": "world_bank" if project else None,
        "project_enrichment_status": "queued" if project else None,
    }


class State:
    authority = True
    tenders: dict[str, dict] = {}
    items: list[dict] = []


def public_item(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "owner"}


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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v1/users/me":
            if State.authority:
                self.send_json(200, {"id": "tenant-a", "email": "tenant-a@s42.invalid"})
            else:
                self.send_json(401, {"detail": "stale credentials"})
            return
        if path == "/api/v1/users/me/access-status":
            if not State.authority:
                self.send_json(401, {"detail": "stale credentials"})
            else:
                self.send_json(200, {
                    "company_profile_id": "profile-a",
                    "company_name": "Acme Engineering",
                    "onboarding_required": False,
                    "onboarding_completed": True,
                    "user_approval_status": "approved",
                    "company_approval_status": "approved",
                    "platform_role": "pilot_user",
                    "access_allowed": True,
                    "state": "approved",
                })
            return
        if path == "/api/v1/my-tenders":
            query = parse_qs(parsed.query)
            status_filter = query.get("status", ["ACTIVE"])[0]
            source = query.get("source", [""])[0]
            tender_status = query.get("tender_status", [""])[0]
            search = query.get("search", [""])[0].casefold()
            offset = int(query.get("offset", [0])[0])
            limit = int(query.get("limit", [25])[0])
            owner_rows = [item for item in State.items if item["owner"] == "A"]
            rows = owner_rows
            if status_filter == "ACTIVE":
                rows = [item for item in rows if item["engagement_status"] != "DISMISSED"]
            elif status_filter != "ALL":
                rows = [item for item in rows if item["engagement_status"] == status_filter]
            if source:
                rows = [item for item in rows if item["source_system"] == source]
            if tender_status:
                rows = [item for item in rows if item["tender_status"] == tender_status]
            if search:
                rows = [item for item in rows if search in item["tender_title"].casefold() or search in (item["buyer"] or "").casefold()]
            statuses = ("SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED")
            counts = {status.lower(): sum(item["engagement_status"] == status for item in owner_rows) for status in statuses}
            counts["all"] = len(owner_rows)
            counts["active"] = len(owner_rows) - counts["dismissed"]
            self.send_json(200, {
                "items": [public_item(item) for item in rows[offset:offset + limit]],
                "total": len(rows),
                "limit": limit,
                "offset": offset,
                "counts": counts,
            })
            return
        parts = path.strip("/").split("/")
        if len(parts) >= 5 and parts[:3] == ["api", "v1", "tenders"]:
            tender_id = parts[3]
            tender_row = State.tenders.get(tender_id)
            if tender_row is None:
                self.send_json(404, {"detail": "Tender not found"})
                return
            if len(parts) == 5 and parts[4] == "engagement":
                item = next((item for item in State.items if item["owner"] == "A" and item["tender_id"] == tender_id), None)
                self.send_json(200, {"engagement": public_item(item) if item else None, "proposal_id": None})
                return
            if len(parts) == 5 and parts[4] == "documents":
                self.send_json(200, [])
                return
            if len(parts) == 5 and parts[4] == "competitors":
                self.send_json(200, {"tender_id": tender_id, "message": "Unavailable", "groups": []})
                return
            if len(parts) == 5 and parts[4] == "project":
                self.send_json(200, None)
                return
            if len(parts) == 5 and parts[4] == "decision-snapshot":
                self.send_json(404, {"detail": "Unavailable"})
                return
        if len(parts) == 4 and parts[:3] == ["api", "v1", "tenders"]:
            tender_row = State.tenders.get(parts[3])
            self.send_json(200, tender_row) if tender_row else self.send_json(404, {"detail": "Tender not found"})
            return
        self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if parsed.path == "/api/v1/auth/refresh":
            if not State.authority:
                self.send_json(403, {"detail": "stale credentials"})
            else:
                self.send_json(200, {
                    "access_token": "s42-rotated-access-token",
                    "token_type": "bearer",
                    "approval_status": "approved",
                    "platform_role": "pilot_user",
                    "is_admin": False,
                    "onboarding_required": False,
                    "company_profile_id": "profile-a",
                    "company_approval_status": "approved",
                    "company_pilot_status": "active_pilot",
                })
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "tenders"] and parts[4] == "engagement":
            tender_id = parts[3]
            tender_row = State.tenders.get(tender_id)
            if tender_row is None:
                self.send_json(404, {"detail": "Tender not found"})
                return
            item = next((item for item in State.items if item["owner"] == "A" and item["tender_id"] == tender_id), None)
            created = item is None
            reengaged = bool(item and item["engagement_status"] == "DISMISSED")
            if item is None:
                item = engagement(tender_row, "SAVED")
                State.items.append(item)
            elif reengaged:
                item["engagement_status"] = "SAVED"
            self.send_json(200, {
                "engagement": public_item(item),
                "created": created,
                "reengaged": reengaged,
            })
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
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s42-browser-secret&& node tests\\make-s42-session.mjs"
    )
    result = subprocess.run([CMD, "/d", "/s", "/c", command], text=True, capture_output=True, check=True)
    return result.stdout.strip().splitlines()[-1]


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s42-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3106&& "
        "set BACKEND_INTERNAL_URL=http://127.0.0.1:8106/api/v1&& "
        "set NEXT_DIST_DIR=.next-s42&& "
        "npm run dev -- -p 3106"
    )
    return subprocess.Popen(
        [CMD, "/d", "/s", "/c", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record(results: list[dict[str, str]], case: str) -> None:
    results.append({"case": case, "result": "passed"})


def kill_listener(port: int) -> None:
    result = subprocess.run(
        [NETSTAT, "-ano", "-p", "tcp"],
        text=True,
        capture_output=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) < 5 or columns[3] != "LISTENING":
            continue
        if columns[1].rsplit(":", 1)[-1] != str(port):
            continue
        subprocess.run(
            [TASKKILL, "/PID", columns[4], "/T", "/F"],
            capture_output=True,
            check=False,
        )
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
        profile = r"C:\Users\acer\AppData\Local\Temp\s42-browser-profile"
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList "
            f"'--headless=new','--disable-gpu','--remote-debugging-address=0.0.0.0',"
            f"'--remote-debugging-port={CDP_PORT}','--user-data-dir={profile}','about:blank'"
        )
        subprocess.run([POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        wait_for_url(f"http://127.0.0.1:{CDP_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{
                "name": "authjs.session-token",
                "value": session_cookie(),
                "url": BASE_URL,
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})
            session_response = page.request.get(f"{BASE_URL}/api/auth/session")
            assert session_response.status == 200
            assert "s42-rotated-access-token" in session_response.text()

            State.items = []
            page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="networkidle")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            record(results, "empty My Tenders")

            save_tender = tender("t-save", "Explicit Save Tender")
            State.tenders[save_tender["id"]] = save_tender
            page.goto(f"{BASE_URL}/dashboard/tenders/t-save", wait_until="networkidle")
            page.get_by_role("button", name="Save to My Tenders", exact=True).click()
            page.get_by_text("Engagement: Saved", exact=True).wait_for()
            assert sum(item["tender_id"] == "t-save" for item in State.items) == 1
            record(results, "explicit Save creates row")

            response = page.request.post(f"{BASE_URL}/api/v1/tenders/t-save/engagement")
            assert response.status == 200
            assert sum(item["tender_id"] == "t-save" for item in State.items) == 1
            record(results, "duplicate Save is idempotent")

            preparing = tender("t-preparing", "Preparing Tender")
            State.tenders[preparing["id"]] = preparing
            State.items.append(engagement(preparing, "PREPARING"))
            page.goto(f"{BASE_URL}/dashboard/tenders/t-preparing", wait_until="networkidle")
            response = page.request.post(f"{BASE_URL}/api/v1/tenders/t-preparing/engagement")
            assert response.status == 200
            assert next(item for item in State.items if item["tender_id"] == "t-preparing")["engagement_status"] == "PREPARING"
            record(results, "PREPARING Save does not downgrade")

            dismissed = tender("t-dismissed", "Dismissed Tender")
            State.tenders[dismissed["id"]] = dismissed
            State.items.append(engagement(dismissed, "DISMISSED"))
            page.goto(f"{BASE_URL}/dashboard/tenders/t-dismissed", wait_until="networkidle")
            page.get_by_role("button", name="Save again", exact=True).click()
            page.get_by_text("Engagement: Saved", exact=True).wait_for()
            record(results, "DISMISSED Save re-engages")

            # Representative list fixtures for filters/search/pagination/legacy isolation.
            State.items = []
            for index in range(30):
                row = tender(f"t-page-{index:02d}", f"Page Tender {index:02d}")
                State.tenders[row["id"]] = row
                State.items.append(engagement(row, "PREPARING" if index == 0 else "SAVED"))
            dismissed_row = tender("t-hidden-dismissed", "Hidden Dismissed")
            State.tenders[dismissed_row["id"]] = dismissed_row
            State.items.append(engagement(dismissed_row, "DISMISSED"))
            needle = tender("t-needle", "Needle Procurement")
            State.tenders[needle["id"]] = needle
            State.items.append(engagement(needle, "EVALUATING"))
            mixed_b = tender("t-mixed-b", "Mixed Engagement B")
            mixed_c = tender("t-mixed-c", "Mixed Engagement C")
            State.tenders[mixed_b["id"]] = mixed_b
            State.tenders[mixed_c["id"]] = mixed_c
            State.items.extend([engagement(mixed_b, "SAVED"), engagement(mixed_c, "SAVED")])
            # "Legacy Proposal A" intentionally has no engagement item.
            legacy = tender("t-legacy-a", "Legacy Proposal A")
            State.tenders[legacy["id"]] = legacy
            other = tender("t-other-tenant", "Other Tenant Secret")
            State.tenders[other["id"]] = other
            State.items.append(engagement(other, "SAVED", owner="B"))
            wb = tender("t-wb", "World Bank Pending Project", source="world_bank")
            State.tenders[wb["id"]] = wb
            State.items.append(engagement(wb, "SAVED", project=True))

            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=PREPARING", wait_until="networkidle")
            page.get_by_text("Page Tender 00", exact=True).wait_for()
            assert page.get_by_text("Page Tender 01", exact=True).count() == 0
            record(results, "status filtering")

            page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="networkidle")
            assert page.get_by_text("Hidden Dismissed", exact=True).count() == 0
            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=DISMISSED", wait_until="networkidle")
            page.get_by_text("Hidden Dismissed", exact=True).wait_for()
            record(results, "dismissed default and filter")

            page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="networkidle")
            search = page.get_by_label("Search title or buyer")
            search.fill("Needle")
            page.get_by_role("button", name="Search", exact=True).click()
            page.wait_for_url("**search=Needle**")
            page.get_by_text("Needle Procurement", exact=True).wait_for()
            record(results, "search")

            page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="networkidle")
            page.get_by_role("button", name="Next", exact=True).click()
            page.get_by_text("Page 2 of", exact=False).wait_for()
            record(results, "pagination")

            prep_item = next(item for item in State.items if item["tender_id"] == "t-page-00")
            State.tenders["t-page-00"]["status"] = "CLOSED"
            prep_item["tender_status"] = "CLOSED"
            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=PREPARING", wait_until="networkidle")
            page.get_by_text("Engagement: Preparing", exact=True).wait_for()
            page.get_by_text("Tender: Closed", exact=True).wait_for()
            record(results, "Tender OPEN to CLOSED without engagement mutation")

            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=Legacy", wait_until="networkidle")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            record(results, "Proposal-only Tender absent")

            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=Mixed", wait_until="networkidle")
            page.get_by_text("Mixed Engagement B", exact=True).wait_for()
            assert page.get_by_text("Mixed Engagement C", exact=True).count() == 1
            assert page.get_by_text("Legacy Proposal A", exact=True).count() == 0
            record(results, "mixed legacy and new fixture")

            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=Other", wait_until="networkidle")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            record(results, "same-name tenant isolation")

            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=World+Bank", wait_until="networkidle")
            page.get_by_text("World Bank Pending Project", exact=True).wait_for()
            page.get_by_text("Project: P424242", exact=True).wait_for()
            record(results, "WB pending Project does not break row")

            State.authority = False
            page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="domcontentloaded")
            page.wait_for_url(lambda url: urlparse(url).path == "/", timeout=15000)
            record(results, "expired or stale session denied")
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
        kill_listener(3106)
        kill_listener(9226)

    print(json.dumps({"results": results, "passed": len(results)}, indent=2))
    assert len(results) == 15
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
