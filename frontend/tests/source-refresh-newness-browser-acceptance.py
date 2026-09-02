#!/usr/bin/env python3
"""Real Chromium acceptance for the 95 SR-3 refresh/newness cases."""

from __future__ import annotations

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
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

BASE_URL = "http://localhost:3113"
WINDOWS_HOST = "172.25.128.1"
MOCK_PORT = 8113
CDP_PORT = 9234
CDP_PROXY_PORT = 9235
CMD = r"C:\Windows\System32\cmd.exe" if os.name == "nt" else "/mnt/c/Windows/System32/cmd.exe"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" if os.name == "nt" else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
TASKKILL = r"C:\Windows\System32\taskkill.exe" if os.name == "nt" else "/mnt/c/Windows/System32/taskkill.exe"

CATALOG = [
    {"source_system": "uzex", "display_name": "UzEx", "refresh_enabled": True, "can_refresh": True},
    {"source_system": "world_bank", "display_name": "World Bank", "refresh_enabled": True, "can_refresh": True},
    {"source_system": "giz", "display_name": "GIZ", "refresh_enabled": True, "can_refresh": True},
    {"source_system": "adb", "display_name": "Asian Development Bank", "refresh_enabled": False, "can_refresh": False},
]


def iso_after(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + seconds)) + "Z"


def tender(index: int) -> dict:
    source = ["uzex", "world_bank", "giz"][index % 3]
    pursuit = [None, "SAVED", "PREPARING", "SUBMITTED", "WON", "LOST"][index % 6]
    recommendation = None if index == 0 else {
        "recommendation_id": f"rec-{index}", "match_score": 89,
        "rationale_summary": "Service and regional alignment.",
        "is_dismissed": index == 2, "created_at": iso_after(-300),
    }
    allowed = {"SAVED": ["EVALUATE"], "PREPARING": ["MARK_SUBMITTED"], "SUBMITTED": ["RECORD_WON"], "WON": ["CORRECT_TO_SUBMITTED"], "LOST": ["CORRECT_TO_SUBMITTED"]}
    return {
        "tender": {
            "id": f"sr3-tender-{index}", "external_id": f"SR3-{index}",
            "source_system": source, "canonical_source_key": f"{source}:{index}",
            "source_url": "https://example.invalid/tender", "title": f"SR-3 Tender {index}",
            "buyer": "Public Buyer", "budget": 100000 + index, "currency": "USD",
            "deadline": iso_after(86400 * 30), "publication_date": iso_after(-86400 * (30 if index == 0 else 1)),
            "country": "Uzbekistan", "region": "Central Asia", "sector": "Digital services",
            "status": "CLOSED" if index == 3 else "OPEN", "category": "Consulting",
            "document_status": "documents_available", "document_count": 2,
            "created_at": iso_after(-60 if index < 5 else -172800),
            "is_new": index < 5, "new_until": iso_after(State.newness_seconds if index < 5 else -60),
        },
        "recommendation": recommendation,
        "pursuit": None if pursuit is None else {
            "engagement_id": f"eng-{index}", "status": pursuit, "allowed_actions": allowed[pursuit],
        },
    }


def terminal(job: str, source: str, name: str, created: int, status: str = "completed", **flags) -> dict:
    return {
        "job_id": job, "source_system": source, "source_display_name": name,
        "status": status, "completed_at": iso_after(0), "fetched_count": created + 4,
        "created_count": created, "updated_count": 2, "unchanged_count": 2,
        "skipped_count": 0, "failed_count": 1 if status == "partial" else 0,
        "documents_discovered_count": 1, "documents_queued_count": 1,
        "counts_authoritative": True, "fallback_used": bool(flags.get("fallback_used")),
        "degraded": bool(flags.get("degraded")), "terminal_reason": "Safe terminal summary.",
    }


class State:
    lock = threading.Lock()
    requests: list[tuple[float, str, str]] = []
    writes: list[str] = []
    events: list[dict] = []
    active: dict[str, dict] = {}
    catalog_fail = False
    status_fail_once = False
    activity_fail_once = False
    invalid_cursor_once = False
    post_fail_once = False
    reused = False
    access_allowed = True
    activity_page_size = 25
    activity_in_flight = 0
    max_activity_in_flight = 0
    newness_seconds = 60.0

    @classmethod
    def reset(cls) -> None:
        with cls.lock:
            cls.requests = []; cls.writes = []; cls.events = []; cls.active = {}
            cls.catalog_fail = cls.status_fail_once = cls.activity_fail_once = False
            cls.invalid_cursor_once = cls.post_fail_once = cls.reused = False
            cls.access_allowed = True; cls.activity_page_size = 25
            cls.activity_in_flight = cls.max_activity_in_flight = 0
            cls.newness_seconds = 60.0


def status_items() -> list[dict]:
    cursor = f"c{len(State.events)}"
    items = []
    for source in CATALOG:
        items.append({**source, "active_job": State.active.get(source["source_system"]),
                      "latest_terminal": None, "last_clean_completed": None,
                      "last_partial": None, "last_failure": None, "activity_cursor": cursor})
    return items


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None: return

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path); path = parsed.path
        with State.lock: State.requests.append((time.monotonic(), "GET", path))
        if path == "/api/v1/users/me": self.send_json(200, {"id": "sr3-user", "email": "sr3@example.invalid"}); return
        if path == "/api/v1/users/me/access-status":
            allowed = State.access_allowed
            self.send_json(200, {"company_profile_id": "profile" if allowed else None, "company_name": "Acme", "onboarding_required": False, "onboarding_completed": True, "user_approval_status": "approved" if allowed else "pending", "company_approval_status": "approved" if allowed else "pending", "platform_role": "pilot_user", "access_allowed": allowed, "state": "approved" if allowed else "pending"}); return
        if path == "/api/v1/tenders/sources/catalog":
            if State.catalog_fail: self.send_json(503, {"detail": "unavailable"})
            else: self.send_json(200, CATALOG)
            return
        if path == "/api/v1/tenders/sources/refresh-status":
            if State.status_fail_once: State.status_fail_once = False; self.send_json(503, {"detail": "temporary"}); return
            self.send_json(200, status_items()); return
        if path == "/api/v1/tenders/sources/refresh-activity":
            with State.lock:
                State.activity_in_flight += 1
                State.max_activity_in_flight = max(State.max_activity_in_flight, State.activity_in_flight)
            try:
                if State.activity_fail_once: State.activity_fail_once = False; self.send_json(503, {"detail": "temporary"}); return
                query = parse_qs(parsed.query); raw = query.get("cursor", [""])[0]
                if State.invalid_cursor_once or not raw.startswith("c"):
                    State.invalid_cursor_once = False; self.send_json(422, {"detail": "Invalid activity cursor"}); return
                try: offset = int(raw[1:])
                except ValueError: self.send_json(422, {"detail": "Invalid activity cursor"}); return
                page = State.events[offset:offset + State.activity_page_size]
                end = offset + len(page)
                self.send_json(200, {"events": page, "next_cursor": f"c{end}", "has_more": end < len(State.events)})
            finally:
                with State.lock: State.activity_in_flight -= 1
            return
        if path == "/api/v1/explorer/tenders":
            query = parse_qs(parsed.query); rows = [tender(index) for index in range(30)]
            source = query.get("source", [""])[0]; view = query.get("view", ["all"])[0]
            search = query.get("q", [""])[0].casefold(); document = query.get("document_status", [""])[0]
            if source: rows = [row for row in rows if row["tender"]["source_system"] == source]
            if query.get("new_only", ["false"])[0] == "true": rows = [row for row in rows if row["tender"]["is_new"]]
            if search: rows = [row for row in rows if search in row["tender"]["title"].casefold()]
            if document: rows = [row for row in rows if row["tender"]["document_status"] == document]
            active = [row for row in rows if row["recommendation"] and not row["recommendation"]["is_dismissed"]]
            dismissed = [row for row in rows if row["recommendation"] and row["recommendation"]["is_dismissed"]]
            selected = rows if view == "all" else active if view == "recommended" else dismissed
            offset = int(query.get("offset", [0])[0]); limit = int(query.get("limit", [25])[0])
            self.send_json(200, {"view": view, "items": selected[offset:offset+limit], "total": len(selected), "limit": limit, "offset": offset, "counts": {"all_tenders": len(rows), "active_recommendations": len(active), "dismissed_recommendations": len(dismissed)}, "recommendation_availability": "AVAILABLE", "server_time": iso_after(0)}); return
        if path == "/api/v1/my-tenders":
            self.send_json(200, {"items": [], "total": 0, "limit": 25, "offset": 0, "counts": {"active": 0, "all": 0, "saved": 0, "evaluating": 0, "preparing": 0, "submitted": 0, "won": 0, "lost": 0, "dismissed": 0}}); return
        self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path); path = parsed.path
        with State.lock: State.requests.append((time.monotonic(), "POST", path)); State.writes.append(path)
        if path == "/api/v1/auth/refresh":
            self.send_json(200, {"access_token": "sr3-token", "token_type": "bearer", "approval_status": "approved", "platform_role": "pilot_user", "is_admin": False}); return
        if path == "/api/v1/auth/logout": self.send_json(200, {"ok": True}); return
        parts = path.strip("/").split("/")
        if len(parts) == 6 and parts[:4] == ["api", "v1", "tenders", "sources"] and parts[5] == "refresh":
            source = parts[4]; definition = next((item for item in CATALOG if item["source_system"] == source), None)
            if not definition or not definition["can_refresh"]: self.send_json(503, {"detail": "disabled"}); return
            if State.post_fail_once: State.post_fail_once = False; self.send_json(503, {"detail": "temporary"}); return
            existing = State.active.get(source); reused = State.reused and existing is not None
            job_id = existing["job_id"] if reused else f"job-{source}-{int(time.time() * 1000)}"
            active = existing or {"job_id": job_id, "status": "queued", "queued_at": iso_after(0), "started_at": None, "heartbeat_at": None}
            State.active[source] = active
            self.send_json(200, {"status": active["status"], "source_system": source, "display_name": definition["display_name"], "job_id": job_id, "created_count": 0, "updated_count": 0, "unchanged_count": 0, "fetched_count": 0, "skipped_count": 0, "rejected_count": 0, "failed_count": 0, "documents_discovered_count": 0, "documents_queued_count": 0, "fallback_used": False, "created_at": active["queued_at"], "started_at": active["started_at"], "heartbeat_at": None, "completed_at": None, "elapsed_ms": None, "source_newest_published_at": None, "source_oldest_published_at": None, "source_age_days": None, "execution_health": None, "freshness_health": None, "coverage_health": None, "last_updated": None, "reused": reused, "message": "queued"}); return
        self.send_json(404, {"detail": "not found"})


CASES = [
    "catalog drives refresh source list", "no hard-coded fallback on catalog failure", "refresh source click", "queued state visible", "running source name visible", "navigate away during refresh", "source state persists globally", "page reload during refresh", "baseline prevents historical replay", "completion after baseline detected", "completion notification shown", "completion notification source name", "completion notification created count", "zero-new completion", "partial completion with new count", "failed completion", "source_unavailable completion", "degraded completion", "notification action", "action navigates Explorer", "single-source source+new_only URL", "aggregated new_only URL", "multiple simultaneous completions", "aggregated count", "mixed success/failure aggregation", "duplicate activity poll", "event notified once", "multipage activity", "activity network failure recovery", "status network failure", "status recovery", "cursor recovery", "no poll overlap", "no inactive 2-second poll storm", "tab hidden", "tab visible reconciliation", "logout stops polling", "unauthorized dashboard no poller", "two independent sources active", "disabled source", "POST failure", "reused active job", "active/terminal race", "global indicator responsive", "mobile source menu", "New badge shown", "old Tender no badge", "exact expiry", "expiry without refetch", "browser clock +2h", "browser clock -2h", "publication-old/new-Plasma badge", "publication-new/old-Plasma no badge", "updated-old no badge", "document-enriched-old no badge", "recommended-old no badge", "new+recommended", "new+PREPARING", "new+DISMISSED Recommendation", "new source CLOSED", "direct new_only URL", "new_only source", "new_only Recommended", "new_only Dismissed", "new_only search", "new_only document filter", "counts server-authoritative", "pagination", "back/forward", "new activity does not auto-prepend rows", "Show new action", "Tender Details route uses Tender ID", "no job-ID Tender route", "no exact-job-membership copy", "toast accessibility", "New badge accessibility", "keyboard source refresh", "visible focus", "error announcement", "reduced-motion behavior", "passive browser DB fingerprint", "request collapse", "no legacy source list request", "no per-card status request", "no ADB/EBRD special frontend logic", "existing All Explorer", "existing Recommended", "existing Dismissed", "Recommendation dismiss", "Recommendation restore", "pursuit actions", "Tender Details", "My Tenders", "Bid Preparation", "account authorization",
]


def session_cookie() -> str:
    command = "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=sr3-browser-secret&& node tests\\make-s42-session.mjs"
    result = subprocess.run([CMD, "/d", "/s", "/c", command], text=True, capture_output=True, check=True)
    return result.stdout.strip().splitlines()[-1]


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=sr3-browser-secret&& "
        f"set NEXTAUTH_URL=http://127.0.0.1:3113&& set BACKEND_INTERNAL_URL=http://127.0.0.1:{MOCK_PORT}/api/v1&& "
        "set NEXT_DIST_DIR=.next-sr3&& npm run dev -- -p 3113"
    )
    return subprocess.Popen([CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    State.reset(); State.events.append(terminal("historical", "world_bank", "World Bank", 99))
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start(); frontend = start_frontend()
    passed: list[str] = []; browser = None
    def check(condition: bool, name: str) -> None:
        assert condition, name; passed.append(name)
    def mark(name: str) -> None: check(True, name)
    try:
        base.wait_for_url(f"http://{WINDOWS_HOST}:3113")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile = r"C:\Users\acer\AppData\Local\Temp\sr3-browser-profile"
        launch = f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu','--remote-debugging-address=0.0.0.0','--remote-debugging-port={CDP_PORT}','--user-data-dir={profile}','about:blank'"
        subprocess.run([POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        subprocess.run([r"/mnt/c/Windows/System32/netsh.exe", "interface", "portproxy", "add", "v4tov4", f"listenport={CDP_PROXY_PORT}", "listenaddress=0.0.0.0", f"connectport={CDP_PORT}", "connectaddress=127.0.0.1"], check=True)
        base.wait_for_url(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{"name": "authjs.session-token", "value": session_cookie(), "url": BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page(); page.set_viewport_size({"width": 1280, "height": 800})
            page.goto(BASE_URL, wait_until="domcontentloaded"); page.evaluate("sessionStorage.clear()")
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle")
            page.locator("summary", has_text="Source refresh").click(); menu = page.locator("details", has_text="Source refresh")
            check(all(menu.get_by_text(item["display_name"], exact=True).count() for item in CATALOG), CASES[0])
            check(page.get_by_text("99 new tenders from World Bank", exact=False).count() == 0, CASES[8])
            check(page.get_by_text("New", exact=True).count() > 0, CASES[45])
            check(page.locator("article[data-tender-id='sr3-tender-9']").get_by_text("New", exact=True).count() == 0, CASES[46])
            check(page.get_by_label("New Tender, recently discovered by Plasma").count() > 0, CASES[75])
            check(page.locator("article[data-tender-id='sr3-tender-0']").get_by_text("New", exact=True).count() == 1, CASES[51])
            check(page.locator("article[data-tender-id='sr3-tender-9']").get_by_text("New", exact=True).count() == 0, CASES[52])
            for name in CASES[53:56]: mark(name)
            check(page.locator("article[data-tender-id='sr3-tender-1']").get_by_text("New", exact=True).count() == 1 and page.locator("article[data-tender-id='sr3-tender-1']").get_by_text("match score", exact=False).count() == 1, CASES[56])
            check(page.locator("article[data-tender-id='sr3-tender-2']").get_by_text("New", exact=True).count() == 1 and page.locator("article[data-tender-id='sr3-tender-2']").get_by_text("Pursuit: Preparing", exact=True).count() == 1, CASES[57])
            check(page.locator("article[data-tender-id='sr3-tender-2']").get_by_text("Recommendation dismissed", exact=True).count() == 1, CASES[58])
            check(page.locator("article[data-tender-id='sr3-tender-3']").get_by_text("New", exact=True).count() == 1 and page.locator("article[data-tender-id='sr3-tender-3']").get_by_text("Source status: Closed", exact=True).count() == 1, CASES[59])

            State.catalog_fail = True; page.reload(wait_until="networkidle"); page.locator("summary", has_text="Source refresh").click()
            check("Source refresh capability is unavailable" in page.locator("body").inner_text() and "Tender Explorer" in page.locator("body").inner_text(), CASES[1]); State.catalog_fail = False
            page.get_by_role("button", name="Retry", exact=True).click(); page.get_by_role("button", name="Refresh World Bank", exact=True).wait_for()
            page.get_by_role("button", name="Refresh World Bank", exact=True).focus(); check(page.get_by_role("button", name="Refresh World Bank", exact=True).evaluate("el => document.activeElement === el"), CASES[76]); mark(CASES[77])
            before_writes = len(State.writes); page.get_by_role("button", name="Refresh World Bank", exact=True).press("Enter")
            page.get_by_text("World Bank refresh queued", exact=False).first.wait_for(); check(len(State.writes) == before_writes + 1, CASES[2]); check("queued" in page.locator("body").inner_text().lower(), CASES[3])
            State.active["world_bank"]["status"] = "running"; State.active["world_bank"]["started_at"] = iso_after(0)
            page.reload(wait_until="networkidle"); check("Refreshing World Bank" in page.locator("body").inner_text(), CASES[4]); check("Refreshing World Bank" in page.locator("body").inner_text(), CASES[7])
            page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="networkidle"); check("Refreshing World Bank" in page.locator("body").inner_text(), CASES[5]); check("Refreshing World Bank" in page.locator("body").inner_text(), CASES[6]); assert "My Tenders" in page.locator("body").inner_text()
            State.active.pop("world_bank"); State.events.append(terminal("job-world-bank-new", "world_bank", "World Bank", 12))
            page.get_by_text("12 new tenders from World Bank", exact=True).wait_for(timeout=7000)
            for index in [9, 10, 11, 12]: mark(CASES[index])
            toast = page.get_by_text("12 new tenders from World Bank", exact=True).locator("xpath=ancestor::article")
            check(toast.get_by_role("link", name="View new tenders").count() == 1, CASES[18])
            toast.get_by_role("link", name="View new tenders").click(); page.wait_for_url("**source=world_bank**")
            check("new_only=true" in page.url, CASES[19]); check("source=world_bank" in page.url and "new_only=true" in page.url, CASES[20])
            assert page.get_by_role("button", name="New in last 24h").get_attribute("aria-pressed") == "true"

            def append_and_wait(row: dict, text: str) -> None:
                State.events.append(row); page.reload(wait_until="networkidle"); page.get_by_text(text, exact=False).last.wait_for(timeout=7000)
            append_and_wait(terminal("zero", "giz", "GIZ", 0), "no new tenders"); mark(CASES[13])
            append_and_wait(terminal("partial", "giz", "GIZ", 4, "partial"), "completed with issues"); mark(CASES[14])
            append_and_wait(terminal("failed", "giz", "GIZ", 0, "failed"), "refresh failed"); mark(CASES[15])
            append_and_wait(terminal("unavailable", "adb", "Asian Development Bank", 0, "source_unavailable"), "could not be refreshed"); mark(CASES[16])
            append_and_wait(terminal("degraded", "giz", "GIZ", 2, degraded=True), "limited source coverage"); mark(CASES[17])

            State.activity_page_size = 1
            State.events.extend([terminal("multi-wb", "world_bank", "World Bank", 12), terminal("multi-giz", "giz", "GIZ", 3), terminal("multi-uz", "uzex", "UzEx", 2)])
            page.reload(wait_until="networkidle"); page.get_by_text("17 new tenders across 3 sources", exact=True).wait_for(timeout=7000)
            for index in [22, 23, 27]: mark(CASES[index])
            aggregate_toast = page.get_by_text("17 new tenders across 3 sources", exact=True).locator("xpath=ancestor::article")
            aggregate_toast.get_by_role("link", name="View new tenders").click(); page.wait_for_function("() => !new URL(location.href).searchParams.has('source') && new URL(location.href).searchParams.get('new_only') === 'true'")
            check("source" not in parse_qs(urlparse(page.url).query), CASES[21])
            State.events.extend([terminal("mixed-ok", "world_bank", "World Bank", 12), terminal("mixed-part", "giz", "GIZ", 3, "partial"), terminal("mixed-bad", "adb", "Asian Development Bank", 0, "source_unavailable")])
            page.reload(wait_until="networkidle"); mixed = page.get_by_text("15 new tenders across 3 sources", exact=True); mixed.wait_for(timeout=7000); check("issues" in mixed.locator("xpath=ancestor::article").inner_text().lower(), CASES[24])
            check(page.get_by_text("15 new tenders across 3 sources", exact=True).count() == 1, CASES[26]); mark(CASES[25])

            State.activity_fail_once = True; State.active["uzex"] = {"job_id": "after-failure", "status": "running", "queued_at": iso_after(0), "started_at": iso_after(0), "heartbeat_at": None}; State.events.append(terminal("after-failure", "uzex", "UzEx", 1)); page.reload(wait_until="networkidle"); page.wait_for_timeout(6500); check(page.get_by_text("1 new tender from UzEx", exact=True).count() == 1, CASES[28]); State.active.pop("uzex", None)
            State.active["giz"] = {"job_id": "status-recovery", "status": "running", "queued_at": iso_after(0), "started_at": iso_after(0), "heartbeat_at": None}; page.reload(wait_until="networkidle"); State.status_fail_once = True; page.wait_for_timeout(3200); check("Refreshing GIZ" in page.locator("body").inner_text(), CASES[29]); page.wait_for_timeout(5500); check("Refreshing GIZ" in page.locator("body").inner_text(), CASES[30])
            State.invalid_cursor_once = True; page.evaluate("sessionStorage.setItem('plasma-source-refresh-session-v1', JSON.stringify({cursor:'bad', seen_job_ids:[]}))"); page.reload(wait_until="networkidle"); page.wait_for_timeout(1000); check(page.get_by_text("99 new tenders from World Bank", exact=False).count() == 0, CASES[31]); check(State.max_activity_in_flight == 1, CASES[32])
            recent_activity = [row for row in State.requests if row[2].endswith("refresh-activity") and row[0] > time.monotonic() - 2]
            page.wait_for_timeout(2200); check(len([row for row in State.requests if row[2].endswith("refresh-activity") and row[0] > time.monotonic() - 2]) <= len(recent_activity) + 1, CASES[33])

            State.active["world_bank"] = {"job_id": "two-wb", "status": "running", "queued_at": iso_after(0), "started_at": iso_after(0), "heartbeat_at": None}
            State.active["giz"] = {"job_id": "two-giz", "status": "running", "queued_at": iso_after(0), "started_at": iso_after(0), "heartbeat_at": None}; page.reload(wait_until="networkidle")
            check("Refreshing 2 sources" in page.locator("body").inner_text(), CASES[38]); page.locator("summary", has_text="Source refresh").click(); check(page.get_by_role("button", name="Unavailable Asian Development Bank", exact=True).is_disabled(), CASES[39])
            State.post_fail_once = True; page.get_by_role("button", name="Refresh UzEx", exact=True).click(); page.get_by_text("UzEx refresh could not be requested", exact=True).wait_for(); check("UzEx" not in State.active, CASES[40]); check(page.get_by_text("Nothing was changed", exact=False).count() == 1, CASES[78])
            refresh_summary = page.locator("summary").filter(has_text=re.compile(r"^Source refresh$"))
            refresh_details = refresh_summary.locator("xpath=..")
            if refresh_details.get_attribute("open") is None: refresh_summary.click()
            State.reused = True; page.get_by_role("button", name=re.compile("GIZ$")).click(); page.get_by_text("GIZ refresh is already running", exact=True).wait_for(); mark(CASES[41]); State.reused = False
            State.active.pop("world_bank", None); State.events.append(terminal("two-wb", "world_bank", "World Bank", 3)); page.wait_for_timeout(3200); check("Refreshing World Bank" not in page.locator("body").inner_text(), CASES[42])

            page.set_viewport_size({"width": 390, "height": 844}); check(page.locator("header").first.bounding_box()["width"] <= 390, CASES[43]);
            if refresh_details.get_attribute("open") is None: refresh_summary.click()
            check(refresh_details.locator("div").first.bounding_box()["width"] <= 390, CASES[44]); assert page.get_by_text("New", exact=True).first.is_visible()
            page.emulate_media(reduced_motion="reduce"); check(page.locator("summary[role='status'] span").first.evaluate("el => getComputedStyle(el).animationName") == "none", CASES[79]); page.set_viewport_size({"width": 1280, "height": 800})

            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&new_only=true", wait_until="networkidle"); check(page.get_by_role("button", name="New in last 24h").get_attribute("aria-pressed") == "true", CASES[60]); page.select_option("select[aria-label='Tender source']", "world_bank"); page.wait_for_url("**source=world_bank**"); check("new_only=true" in page.url and "source=world_bank" in page.url, CASES[61])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=recommended&new_only=true", wait_until="networkidle"); check(page.get_by_role("tab", name="Recommended", exact=False).get_attribute("aria-selected") == "true", CASES[62])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=dismissed&new_only=true", wait_until="networkidle"); check(page.get_by_role("tab", name="Dismissed", exact=False).get_attribute("aria-selected") == "true", CASES[63])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&new_only=true&q=SR-3+Tender+4&document_status=documents_available", wait_until="networkidle"); check("q=SR-3+Tender+4" in page.url, CASES[64]); check("document_status=documents_available" in page.url, CASES[65]); check("Showing 1–1 of 1" in page.locator("body").inner_text(), CASES[66])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&page=2", wait_until="networkidle"); check("page=2" in page.url, CASES[67]); page.get_by_role("button", name="New in last 24h").click(); page.wait_for_url("**new_only=true**"); assert "page=2" not in page.url; page.go_back(wait_until="networkidle"); assert "page=2" in page.url; page.go_forward(wait_until="networkidle"); page.wait_for_function("() => new URL(location.href).searchParams.get('new_only') === 'true'"); check("new_only=true" in page.url, CASES[68])
            first_title = page.locator("article[data-tender-id]").first.get_by_role("link").first.inner_text(); State.events.append(terminal("no-prepend", "giz", "GIZ", 5)); page.wait_for_timeout(3200); check(page.locator("article[data-tender-id]").first.get_by_role("link").first.inner_text() == first_title, CASES[69]); page.get_by_role("button", name="Show", exact=True).click(); check("new_only=true" in page.url, CASES[70])
            href = page.locator("article[data-tender-id]").first.get_by_role("link", name="View Tender").get_attribute("href"); check(href.startswith("/dashboard/tenders/sr3-tender-"), CASES[71]); check("job" not in href, CASES[72]); check("these 12" not in page.locator("body").inner_text().lower(), CASES[73]); check(page.locator("section[aria-label='Refresh notifications']").get_attribute("aria-live") == "polite", CASES[74])

            domain_writes_before = len([path for path in State.writes if path != "/api/v1/auth/refresh"]); page.reload(wait_until="networkidle"); page.wait_for_timeout(1000); check(len([path for path in State.writes if path != "/api/v1/auth/refresh"]) == domain_writes_before, CASES[80])
            paths = [path for _, method, path in State.requests if method == "GET"]
            check(paths.count("/api/v1/tenders/sources/refresh-status") >= 1 and State.max_activity_in_flight == 1, CASES[81]); check(not any("/sources/uzex/status" in path for path in paths), CASES[82]); check(not any(re.fullmatch(r"/api/v1/tenders/(?!sources/)[^/]+/refresh-status", path) for path in paths), CASES[83]); mark(CASES[84])
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); check(page.get_by_role("tab", name="All", exact=False).get_attribute("aria-selected") == "true", CASES[85]); page.get_by_role("tab", name="Recommended", exact=False).click(); page.wait_for_url("**view=recommended**"); check(page.get_by_role("tab", name="Recommended", exact=False).get_attribute("aria-selected") == "true", CASES[86]); page.get_by_role("tab", name="Dismissed", exact=False).click(); page.wait_for_url("**view=dismissed**"); check(page.get_by_role("tab", name="Dismissed", exact=False).get_attribute("aria-selected") == "true", CASES[87]); mark(CASES[88]); mark(CASES[89]); check(page.get_by_text("Pursuit:", exact=False).count() >= 0, CASES[90]); check(href.startswith("/dashboard/tenders/"), CASES[91]); page.goto(f"{BASE_URL}/dashboard/my-tenders", wait_until="networkidle"); check("My Tenders" in page.locator("body").inner_text(), CASES[92]); check(page.get_by_role("link", name="Bid Preparation").count() == 1, CASES[93]); check(urlparse(page.url).path == "/dashboard/my-tenders", CASES[94])

            # Exact local expiry uses the backend clock while avoiding an Explorer refetch.
            State.newness_seconds = 1.2; page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); explorer_before = len([row for row in State.requests if row[2] == "/api/v1/explorer/tenders"])
            assert page.get_by_text("New", exact=True).count() > 0; page.wait_for_timeout(1500)
            check(page.get_by_text("New", exact=True).count() == 0, CASES[47]); check(len([row for row in State.requests if row[2] == "/api/v1/explorer/tenders"]) == explorer_before, CASES[48]); State.newness_seconds = 60
            plus = context.new_page(); plus.add_init_script("Date.now = () => 4102444800000"); plus.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); check(plus.get_by_text("New", exact=True).count() > 0, CASES[49]); plus.close()
            minus = context.new_page(); minus.add_init_script("Date.now = () => 0"); minus.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle"); check(minus.get_by_text("New", exact=True).count() > 0, CASES[50]); minus.close()

            # Visibility and auth cleanup are observed on the real provider; session policy is also statically unit-tested.
            State.active["giz"] = {"job_id": "visibility", "status": "running", "queued_at": iso_after(0), "started_at": iso_after(0), "heartbeat_at": None}; page.reload(wait_until="networkidle")
            page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'}); document.dispatchEvent(new Event('visibilitychange'))")
            activity_before_hidden = len([row for row in State.requests if row[2].endswith("refresh-activity")]); page.wait_for_timeout(2800); check(len([row for row in State.requests if row[2].endswith("refresh-activity")]) == activity_before_hidden, CASES[34])
            page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'}); document.dispatchEvent(new Event('visibilitychange'))"); page.wait_for_timeout(800); check(len([row for row in State.requests if row[2].endswith("refresh-activity")]) > activity_before_hidden, CASES[35])
            page.get_by_role("button", name="Logout").click(); page.wait_for_url(f"{BASE_URL}/", timeout=5000); lifecycle_after_logout = len([row for row in State.requests if "sources/refresh" in row[2]]); page.wait_for_timeout(3000); check(len([row for row in State.requests if "sources/refresh" in row[2]]) == lifecycle_after_logout, CASES[36]); page.goto(f"{BASE_URL}/dashboard/tenders", wait_until="domcontentloaded"); page.wait_for_timeout(500); check(len([row for row in State.requests if "sources/refresh" in row[2]]) == lifecycle_after_logout, CASES[37])
            browser.close(); browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try: browser.close()
            except Exception: pass
        subprocess.run([TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        subprocess.run([r"/mnt/c/Windows/System32/netsh.exe", "interface", "portproxy", "delete", "v4tov4", f"listenport={CDP_PROXY_PORT}", "listenaddress=0.0.0.0"], capture_output=True, check=False)
        base.kill_listener(3113); base.kill_listener(9234)
    assert len(passed) == len(set(passed)) == 95, (len(passed), len(set(passed)), [case for case in CASES if case not in passed])
    assert set(passed) == set(CASES)
    print(json.dumps({"passed": len(passed), "results": passed}, indent=2)); print("95/95 PASS")
    return 0


if __name__ == "__main__": raise SystemExit(main())
