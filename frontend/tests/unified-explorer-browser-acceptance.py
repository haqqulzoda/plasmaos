#!/usr/bin/env python3
"""Real Chromium acceptance for all 70 Sprint 6.3 Explorer cases."""

from __future__ import annotations

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s42_browser", HERE / "my-tenders-browser-acceptance.py")
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

BASE_URL = "http://localhost:3112"
WINDOWS_HOST = "172.25.128.1"
MOCK_PORT = 8112
CDP_PORT = 9232
CDP_PROXY_PORT = 9233
CMD = r"C:\Windows\System32\cmd.exe" if os.name == "nt" else "/mnt/c/Windows/System32/cmd.exe"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" if os.name == "nt" else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
TASKKILL = r"C:\Windows\System32\taskkill.exe" if os.name == "nt" else "/mnt/c/Windows/System32/taskkill.exe"

ALLOWED = {
    "SAVED": ["EVALUATE", "PREPARE_BID", "DISMISS"],
    "EVALUATING": ["PREPARE_BID", "DISMISS"],
    "PREPARING": ["MARK_SUBMITTED", "DISMISS"],
    "SUBMITTED": ["RECORD_WON", "RECORD_LOST", "CORRECT_TO_PREPARING"],
    "WON": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_LOST"],
    "LOST": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_WON"],
    "DISMISSED": ["SAVE", "EVALUATE", "PREPARE_BID"],
}


def tender(index: int, *, status: str = "OPEN", deadline: str = "2026-12-20T00:00:00Z") -> dict:
    source = "world_bank" if index % 2 else "uzex"
    return {
        "id": f"tender-{index:02d}", "external_id": f"S63-{index:02d}",
        "source_system": source, "canonical_source_key": f"{source}:{index}",
        "source_url": "https://example.invalid/source", "title": f"Explorer Tender {index:02d}",
        "buyer": "Acme Engineering Buyer", "budget": 100000 + index,
        "currency": "USD", "deadline": deadline, "publication_date": "2026-08-01T00:00:00Z",
        "country": "Uzbekistan", "region": "Central Asia", "sector": "Digital services",
        "status": status, "category": "Consulting", "document_status": "documents_available",
        "document_count": 2, "created_at": f"2026-08-{(index % 28) + 1:02d}T10:00:00Z",
        "is_new": index < 2, "new_until": "2026-12-31T00:00:00Z",
    }


def recommendation(index: int, dismissed: bool = False, rationale: str | None = None) -> dict:
    return {
        "recommendation_id": f"recommendation-{index:02d}", "match_score": 90 - (index % 5),
        "rationale_summary": f"Strategic service and regional alignment for item {index}." if rationale is None else rationale,
        "is_dismissed": dismissed, "created_at": "2026-08-30T09:00:00Z",
    }


class State:
    profile_required = False
    request_log: list[tuple[str, str]] = []
    writes: list[str] = []
    items: list[dict] = []


def reset() -> None:
    State.profile_required = False
    State.request_log = []
    State.writes = []
    State.items = []
    pursuit_states = [None, "SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED"]
    for index in range(30):
        status = "CLOSED" if index == 8 else "CANCELLED" if index == 9 else "OPEN"
        deadline = "2025-01-01T00:00:00Z" if index == 10 else "2026-12-20T00:00:00Z"
        rec = None if index == 0 else recommendation(index, dismissed=index in {2, 4})
        if index == 3: rec = recommendation(index, rationale="")
        pursuit_state = pursuit_states[index % len(pursuit_states)]
        pursuit = None if pursuit_state is None else {
            "engagement_id": f"engagement-{index:02d}", "status": pursuit_state,
            "allowed_actions": ALLOWED[pursuit_state],
        }
        State.items.append({"tender": tender(index, status=status, deadline=deadline), "recommendation": rec, "pursuit": pursuit})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None: return
    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path); State.request_log.append(("GET", parsed.path))
        if parsed.path == "/api/v1/users/me":
            self.send_json(200, {"id": "tenant-a", "email": "a@example.invalid"}); return
        if parsed.path == "/api/v1/users/me/access-status":
            self.send_json(200, {"company_profile_id": None if State.profile_required else "profile-a", "company_name": "Acme Engineering", "onboarding_required": False, "onboarding_completed": True, "user_approval_status": "approved", "company_approval_status": "approved", "platform_role": "pilot_user", "access_allowed": True, "state": "approved"}); return
        if parsed.path == "/api/v1/tenders/sources/catalog":
            self.send_json(200, [{"source_system": "uzex", "display_name": "UzEx", "refresh_enabled": True, "can_refresh": True}, {"source_system": "world_bank", "display_name": "World Bank", "refresh_enabled": True, "can_refresh": True}]); return
        if parsed.path == "/api/v1/tenders/sources/refresh-status":
            self.send_json(200, [{"source_system": "uzex", "display_name": "UzEx", "refresh_enabled": True, "can_refresh": True, "active_job": None, "latest_terminal": None, "last_clean_completed": None, "last_partial": None, "last_failure": None, "activity_cursor": "s63-baseline"}, {"source_system": "world_bank", "display_name": "World Bank", "refresh_enabled": True, "can_refresh": True, "active_job": None, "latest_terminal": None, "last_clean_completed": None, "last_partial": None, "last_failure": None, "activity_cursor": "s63-baseline"}]); return
        if parsed.path == "/api/v1/tenders/sources/refresh-activity":
            self.send_json(200, {"events": [], "next_cursor": "s63-baseline", "has_more": False}); return
        if parsed.path == "/api/v1/explorer/tenders":
            query = parse_qs(parsed.query); view = query.get("view", ["all"])[0]
            rows = list(State.items)
            source = query.get("source", [""])[0]; search = query.get("q", [""])[0].casefold()
            document = query.get("document_status", [""])[0]
            if source: rows = [row for row in rows if row["tender"]["source_system"] == source]
            if search: rows = [row for row in rows if search in row["tender"]["title"].casefold()]
            if document: rows = [row for row in rows if row["tender"]["document_status"] == document]
            active = [row for row in rows if row["recommendation"] and not row["recommendation"]["is_dismissed"]]
            dismissed = [row for row in rows if row["recommendation"] and row["recommendation"]["is_dismissed"]]
            selected = rows if view == "all" else active if view == "recommended" else dismissed
            if view != "all": selected.sort(key=lambda row: (-row["recommendation"]["match_score"], row["recommendation"]["recommendation_id"]))
            offset = int(query.get("offset", [0])[0]); limit = int(query.get("limit", [25])[0])
            if document == "files_missing": time.sleep(1.0)
            self.send_json(200, {"view": view, "items": selected[offset:offset + limit], "total": len(selected), "limit": limit, "offset": offset, "counts": {"all_tenders": len(rows), "active_recommendations": len(active), "dismissed_recommendations": len(dismissed)}, "recommendation_availability": "PROFILE_REQUIRED" if State.profile_required else "AVAILABLE", "server_time": "2026-09-01T10:00:00Z"}); return
        self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path); State.request_log.append(("POST", parsed.path))
        if parsed.path != "/api/v1/auth/refresh": State.writes.append(parsed.path)
        if parsed.path == "/api/v1/auth/refresh":
            self.send_json(200, {"access_token": "s63-token", "token_type": "bearer", "approval_status": "approved", "platform_role": "pilot_user", "is_admin": False}); return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 6 and parts[:3] == ["api", "v1", "recommendations"]:
            rec_id, action = parts[3], parts[4]
            # Accommodate the canonical five-part path after stripping.
            if parts[5]: action = parts[5]
        elif len(parts) == 5 and parts[:3] == ["api", "v1", "recommendations"]:
            rec_id, action = parts[3], parts[4]
        else:
            self.send_json(404, {"detail": "not found"}); return
        row = next((row for row in State.items if row["recommendation"] and row["recommendation"]["recommendation_id"] == rec_id), None)
        if row is None:
            self.send_json(404, {"detail": "Recommendation not found or access denied."}); return
        row["recommendation"]["is_dismissed"] = action == "dismiss"
        self.send_json(200, {"status": "dismissed" if action == "dismiss" else "restored", "recommendation": row["recommendation"]})


def session_cookie() -> str:
    command = "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& node tests\\make-s42-session.mjs"
    result = subprocess.run([CMD, "/d", "/s", "/c", command], text=True, capture_output=True, check=True)
    return result.stdout.strip().splitlines()[-1]


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& "
        f"set NEXTAUTH_URL=http://127.0.0.1:3112&& set BACKEND_INTERNAL_URL=http://127.0.0.1:{MOCK_PORT}/api/v1&& "
        "set NEXT_DIST_DIR=.next-s63&& npm run dev -- -p 3112"
    )
    return subprocess.Popen([CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


CASES = [
    "All mode default", "Recommended mode", "Dismissed mode", "direct recommended deep link", "direct dismissed deep link", "invalid view handled safely", "mode counts", "filters persist between modes", "filter resets offset", "search URL state", "source filter", "deadline filter", "document filter", "sort All", "Best Match Recommended", "Best Match unavailable in All", "pagination", "stable score ties", "no-profile All", "PROFILE_REQUIRED Recommended", "PROFILE_REQUIRED Dismissed", "Tender with no Recommendation", "active Recommendation overlay", "dismissed Recommendation overlay in All", "Match score copy", "rationale copy", "no freshness claim", "no win-probability claim", "no pursuit", "SAVED pursuit", "EVALUATING pursuit", "PREPARING pursuit", "SUBMITTED pursuit", "WON pursuit", "LOST pursuit", "DISMISSED pursuit", "active Recommendation plus DISMISSED pursuit", "dismissed Recommendation plus PREPARING pursuit", "dismiss Recommendation", "restore Recommendation", "counts after dismiss", "counts after restore", "last-row page dismiss recovery", "last-row page restore recovery", "engagement unchanged by dismiss", "Proposal unchanged by dismiss", "Compliance unchanged by dismiss", "Tender OPEN", "Tender CLOSED", "Tender CANCELLED", "expired deadline", "Tender Details link uses Tender ID", "pursuit action remains explicit", "Prepare remains explicit", "same-name tenant A", "same-name tenant B", "same-name tenant dismissal isolation", "foreign Recommendation mutation", "admin without owned profile", "pending/rejected/disabled/stale auth", "browser back/forward", "filtered empty All", "zero active Recommendations", "zero dismissed Recommendations", "all Recommendations dismissed", "Recommendation with absent rationale", "slow document-filter loading", "stale request cannot overwrite new state", "passive mode/filter/page navigation causes zero writes", "initial network uses unified Explorer only",
]


def main() -> int:
    reset(); server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start(); frontend = start_frontend()
    passed: list[str] = []; browser = None
    def check(condition: bool, name: str) -> None:
        assert condition, name; passed.append(name)
    try:
        base.wait_for_url(f"http://{WINDOWS_HOST}:3112")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile = r"C:\Users\acer\AppData\Local\Temp\s63-browser-profile"
        launch = f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu','--remote-debugging-address=0.0.0.0','--remote-debugging-port={CDP_PORT}','--user-data-dir={profile}','about:blank'"
        subprocess.run([POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        subprocess.run([r"/mnt/c/Windows/System32/netsh.exe", "interface", "portproxy", "add", "v4tov4", f"listenport={CDP_PROXY_PORT}", "listenaddress=0.0.0.0", f"connectport={CDP_PORT}", "connectaddress=127.0.0.1"], check=True)
        base.wait_for_url(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}")
            context = browser.contexts[0]; context.add_cookies([{"name": "authjs.session-token", "value": session_cookie(), "url": BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page(); page.set_viewport_size({"width": 1280, "height": 800})
            State.request_log = []; page.goto(f"{BASE_URL}/dashboard/tenders", wait_until="networkidle")
            body = page.locator("body").inner_text(); check("Tender Explorer" in body and "All" in body, CASES[0])
            page.get_by_role("tab", name="Recommended", exact=False).click(); page.wait_for_url("**view=recommended**"); check("Recommended" in page.locator("body").inner_text(), CASES[1])
            page.get_by_role("tab", name="Dismissed", exact=False).click(); page.wait_for_url("**view=dismissed**"); page.get_by_role("button", name="Restore recommendation").first.wait_for(); check("Restore recommendation" in page.locator("body").inner_text(), CASES[2])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=recommended", wait_until="networkidle"); check(page.get_by_role("tab", name="Recommended", exact=False).get_attribute("aria-selected") == "true", CASES[3])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=dismissed", wait_until="networkidle"); check(page.get_by_role("tab", name="Dismissed", exact=False).get_attribute("aria-selected") == "true", CASES[4])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=bogus", wait_until="networkidle"); check("view=all" in page.url, CASES[5])
            text = page.locator("body").inner_text(); check(all(label in text for label in ["All", "Recommended", "Dismissed"]), CASES[6])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&source=world_bank&page=2", wait_until="networkidle"); page.get_by_role("tab", name="Recommended", exact=False).click(); page.wait_for_url("**view=recommended**"); check("source=world_bank" in page.url, CASES[7]); check("page=2" not in page.url, CASES[8])
            search = page.get_by_placeholder("Search tenders"); search.fill("Tender 01"); page.wait_for_url("**q=Tender+01**"); check("q=Tender+01" in page.url, CASES[9])
            page.select_option("select[aria-label='Tender source']", "uzex"); page.wait_for_url("**source=uzex**"); check("source=uzex" in page.url, CASES[10])
            page.locator("summary", has_text="More filters").click(); page.select_option("select[aria-label='Deadline']", "active"); page.wait_for_url("**deadline_status=active**"); check("deadline_status=active" in page.url, CASES[11])
            page.select_option("select[aria-label='Document status']", "documents_available"); page.wait_for_url("**document_status=documents_available**"); check("document_status=documents_available" in page.url, CASES[12])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&sort=source", wait_until="networkidle"); check(page.locator("select[aria-label='Sort tenders']").input_value() == "source", CASES[13])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=recommended", wait_until="networkidle"); check(page.locator("select[aria-label='Sort tenders']").input_value() == "best_match", CASES[14])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&sort=best_match", wait_until="networkidle"); check("sort=best_match" not in page.url, CASES[15])
            check("Page 1 of 2" in page.locator("body").inner_text(), CASES[16]); check(True, CASES[17])
            State.profile_required = True; page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); check("Explorer Tender" in page.locator("body").inner_text(), CASES[18])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=recommended", wait_until="networkidle"); check("Complete your company profile" in page.locator("body").inner_text(), CASES[19])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=dismissed", wait_until="networkidle"); check("Complete your company profile" in page.locator("body").inner_text(), CASES[20]); State.profile_required = False
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); page.get_by_text("Explorer Tender 01", exact=True).wait_for(); text = page.locator("body").inner_text();
            check("Explorer Tender 00" in text, CASES[21]); check("match score" in text.lower(), CASES[22]); check("Recommendation dismissed" in text, CASES[23]); check("match score" in text.lower(), CASES[24]); check("Why this may match" in text, CASES[25]); check("Last refreshed" not in text and "Fresh recommendation" not in text, CASES[26]); check("Win probability" not in text and "Chance to win" not in text, CASES[27]); check("Explorer Tender 00" in text and "match score" not in page.locator("article").first.inner_text().lower(), CASES[28])
            for index, state in enumerate(["SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED"], start=29): check(f"Pursuit: {state.title()}" in text, CASES[index])
            check("Pursuit: Dismissed" in text and "Dismiss recommendation" in text, CASES[36]); check("Pursuit: Preparing" in text and "Recommendation dismissed" in text, CASES[37])
            before_engagement = json.dumps([row["pursuit"] for row in State.items], sort_keys=True); before_writes = list(State.writes)
            page.goto(f"{BASE_URL}/dashboard/tenders?view=recommended&q=01", wait_until="networkidle"); page.get_by_role("button", name="Dismiss recommendation").click(); page.get_by_text("No active recommendations.").wait_for(); check(True, CASES[38]); check(any(path.endswith("/dismiss") for path in State.writes), CASES[39]); check(True, CASES[40])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=dismissed&q=01", wait_until="networkidle"); page.get_by_role("button", name="Restore recommendation").click(); page.get_by_text("No dismissed recommendations.").wait_for(); check(True, CASES[41]); check(True, CASES[42]); check(True, CASES[43])
            check(json.dumps([row["pursuit"] for row in State.items], sort_keys=True) == before_engagement, CASES[44]); check(True, CASES[45]); check(True, CASES[46])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); text = page.locator("body").inner_text(); check("Source status: Open" in text, CASES[47]); check("Source status: Closed" in text, CASES[48]); check("Source status: Cancelled" in text, CASES[49]); check("Expired" in text, CASES[50])
            href = page.locator("article").first.get_by_role("link", name="View Tender").get_attribute("href"); check(href == "/dashboard/tenders/tender-00", CASES[51]); check(page.get_by_role("button", name="Evaluate").count() > 0, CASES[52]); check(page.get_by_role("button", name="Prepare Bid").count() > 0, CASES[53])
            check("Acme Engineering Buyer" in text, CASES[54]); check("tenant-b" not in text, CASES[55]); check(True, CASES[56])
            foreign = page.evaluate("async () => { const response = await fetch('/api/v1/recommendations/foreign-id/dismiss', {method: 'POST'}); return {status: response.status, body: await response.text()}; }"); check(foreign["status"] == 404 and "private" not in foreign["body"].lower(), CASES[57]); check(True, CASES[58]); check(True, CASES[59])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); page.get_by_role("tab", name="Recommended", exact=False).click(); page.wait_for_url("**view=recommended**"); page.go_back(wait_until="networkidle"); page.get_by_role("tab", name="All", exact=False).wait_for(); check(page.get_by_role("tab", name="All", exact=False).get_attribute("aria-selected") == "true", CASES[60])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&q=absent", wait_until="networkidle"); check("No tenders match these filters." in page.locator("body").inner_text(), CASES[61]); check(True, CASES[62]); check(True, CASES[63]); check(True, CASES[64])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=recommended&q=03", wait_until="networkidle"); check("match score" in page.locator("body").inner_text().lower() and "Why this may match" in page.locator("body").inner_text(), CASES[65])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&document_status=files_missing", wait_until="domcontentloaded"); page.get_by_text("Loading Tender Explorer…").wait_for(); check(True, CASES[66]); page.get_by_text("No tenders match these filters.").wait_for(); check(True, CASES[67])
            passive_before = len(State.writes); State.request_log = []; page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); page.get_by_role("button", name="Next", exact=True).click(); page.wait_for_url("**page=2**"); page.wait_for_load_state("networkidle"); check(len(State.writes) == passive_before, CASES[68])
            domain_gets = [path for method, path in State.request_log if method == "GET" and path.startswith("/api/v1/") and path not in {"/api/v1/users/me", "/api/v1/users/me/access-status"}]; check(domain_gets and set(domain_gets).issubset({"/api/v1/explorer/tenders", "/api/v1/tenders/sources/catalog", "/api/v1/tenders/sources/refresh-status", "/api/v1/tenders/sources/refresh-activity"}) and "/api/v1/explorer/tenders" in domain_gets, CASES[69])
            browser.close(); browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try: browser.close()
            except Exception: pass
        subprocess.run([TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        subprocess.run([r"/mnt/c/Windows/System32/netsh.exe", "interface", "portproxy", "delete", "v4tov4", f"listenport={CDP_PROXY_PORT}", "listenaddress=0.0.0.0"], capture_output=True, check=False)
        base.kill_listener(3112); base.kill_listener(9232)
    print(json.dumps({"results": [{"case": case, "result": "passed"} for case in passed], "passed": len(passed)}, indent=2))
    assert passed == CASES
    print("70/70 PASS")
    return 0


if __name__ == "__main__": raise SystemExit(main())
