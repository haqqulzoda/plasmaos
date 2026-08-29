#!/usr/bin/env python3
"""Real Chromium acceptance for all 60 Sprint 5.4 final cases."""

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
spec = importlib.util.spec_from_file_location("s53_browser", HERE / "tender-details-browser-acceptance.py")
assert spec and spec.loader
s53 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s53)
base = s53.base

BASE_URL = "http://localhost:3111"
MOCK_PORT = 8111
CDP_PORT = 9231


class Handler(s53.Handler):
    pass


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3111&& set BACKEND_INTERNAL_URL=http://127.0.0.1:8111/api/v1&& "
        "set NEXT_DIST_DIR=.next-s54&& npm run dev -- -p 3111"
    )
    return subprocess.Popen([base.CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_cleanup_twenty() -> list[dict[str, str]]:
    base.BASE_URL = BASE_URL
    base.MOCK_PORT = MOCK_PORT
    base.CDP_PORT = CDP_PORT
    base.State.authority = True
    base.State.tenders = {}
    base.State.proposals = {}
    base.State.engagements = {}
    base.State.prepare_calls = 0
    base.State.export_calls = []
    s53.AcceptanceState.details = {}
    s53.AcceptanceState.details_fail = set()
    s53.AcceptanceState.request_log = []
    s53.AcceptanceState.mutation_count = 0

    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    results: list[dict[str, str]] = []
    browser = None

    def record(number: int, case: str) -> None:
        results.append({"case": f"{number} {case}", "result": "passed"})

    def fixture(
        tender_id: str,
        *,
        pursuit: str | None = None,
        proposal_id: str | None = None,
        proposal_status: str = "DRAFT",
        proposal_owner: str = "A",
    ) -> dict:
        row = base.tender(tender_id, f"Cleanup Tender {tender_id}")
        base.State.tenders[tender_id] = row
        if pursuit:
            base.State.engagements[("A", tender_id)] = pursuit
        if proposal_id:
            base.State.proposals[proposal_id] = base.proposal(
                proposal_id,
                row,
                owner=proposal_owner,
                status=proposal_status,
            )
        s53.AcceptanceState.details[tender_id] = s53.details(
            tender_id,
            pursuit=pursuit,
            proposal=proposal_id is not None and proposal_owner == "A",
        )
        if proposal_id and proposal_owner == "A":
            bid = s53.AcceptanceState.details[tender_id]["bid_preparation"]["data"]
            bid["proposal_id"] = proposal_id
            bid["detail_route_id"] = proposal_id
            bid["proposal_status"] = proposal_status
        return row

    try:
        base.wait_for_url(BASE_URL)
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_path = r"C:\Users\acer\AppData\Local\Temp\s54-browser-profile"
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--remote-debugging-address=0.0.0.0','--remote-debugging-port={CDP_PORT}',"
            f"'--user-data-dir={profile_path}','about:blank'"
        )
        subprocess.run([base.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        base.wait_for_url(f"http://127.0.0.1:{CDP_PORT}/json/version")

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{"name": "authjs.session-token", "value": base.session_cookie(), "url": BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1360, "height": 900})

            page.goto(f"{BASE_URL}/dashboard/bids", wait_until="networkidle")
            assert urlparse(page.url).path == "/dashboard/bid-preparation", page.url
            record(41, "legacy bids list redirect")

            fixture("owned", proposal_id="proposal-owned")
            page.goto(f"{BASE_URL}/dashboard/bids/proposal-owned", wait_until="networkidle")
            page.wait_for_url("**/dashboard/bid-preparation/proposal-owned")
            record(42, "owned legacy bid detail redirect")

            fixture("tender-id-bookmark")
            fingerprint = (len(base.State.proposals), len(base.State.engagements), s53.AcceptanceState.mutation_count)
            page.goto(f"{BASE_URL}/dashboard/bids/tender-id-bookmark", wait_until="networkidle")
            page.get_by_text("This legacy bookmark is not an owned Bid Preparation artifact.", exact=True).wait_for()
            assert fingerprint == (len(base.State.proposals), len(base.State.engagements), s53.AcceptanceState.mutation_count)
            record(43, "Tender-ID legacy bid route passive and creates nothing")

            page.goto(f"{BASE_URL}/dashboard/bids/not-a-proposal", wait_until="networkidle")
            page.get_by_text("This legacy bookmark is not an owned Bid Preparation artifact.", exact=True).wait_for()
            record(44, "invalid legacy bid route safe")

            fixture("foreign", proposal_id="proposal-foreign", proposal_owner="B")
            page.goto(f"{BASE_URL}/dashboard/bids/proposal-foreign", wait_until="networkidle")
            page.get_by_text("This legacy bookmark is not an owned Bid Preparation artifact.", exact=True).wait_for()
            assert page.get_by_text("Cleanup Tender foreign", exact=True).count() == 0
            record(45, "foreign legacy bid route safe")

            page.goto(f"{BASE_URL}/dashboard/proposals", wait_until="networkidle")
            assert urlparse(page.url).path == "/dashboard/bid-preparation"
            record(46, "legacy proposals redirect")

            page.goto(f"{BASE_URL}/dashboard/workspace", wait_until="networkidle")
            assert urlparse(page.url).path == "/dashboard/tenders"
            record(47, "workspace compatibility redirect")

            before = (len(base.State.proposals), len(base.State.engagements), s53.AcceptanceState.mutation_count)
            s53.AcceptanceState.request_log.clear()
            for artifact_status in ("DRAFT", "COMPLETED", "SUBMITTED"):
                base.State.proposals["proposal-owned"]["status"] = artifact_status
                page.goto(f"{BASE_URL}/dashboard/bid-preparation/proposal-owned", wait_until="networkidle")
                assert before == (len(base.State.proposals), len(base.State.engagements), s53.AcceptanceState.mutation_count)
            paths = [path for _, path in s53.AcceptanceState.request_log]
            assert not any("sync-docs" in path or "sync-status" in path for path in paths)
            base.State.proposals["proposal-owned"]["status"] = "DRAFT"
            record(48, "DRAFT, COMPLETED, and SUBMITTED passive opens cause no document sync")

            for _ in range(2):
                page.reload(wait_until="networkidle")
            assert before == (len(base.State.proposals), len(base.State.engagements), s53.AcceptanceState.mutation_count)
            assert not any("sync-docs" in path or "sync-status" in path for _, path in s53.AcceptanceState.request_log)
            record(49, "repeated Bid Preparation passive loads cause no writes")

            fixture("proposal-only", proposal_id="proposal-only")
            engagement_count = len(base.State.engagements)
            page.goto(f"{BASE_URL}/dashboard/bid-preparation/proposal-only", wait_until="networkidle")
            page.get_by_text("Not currently in My Tenders.", exact=True).wait_for()
            assert len(base.State.engagements) == engagement_count
            record(50, "Proposal-only passive open remains no-engagement")

            page.get_by_role("button", name="Continue Bid Preparation", exact=True).click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-only")
            page.wait_for_timeout(750)
            assert base.State.engagements[("A", "proposal-only")] == "PREPARING"
            record(51, "Continue remains explicit")

            fixture("prepare-explicit")
            page.goto(f"{BASE_URL}/dashboard/tenders/prepare-explicit", wait_until="networkidle")
            page.get_by_role("button", name="Prepare Bid", exact=True).click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-prepare-explicit")
            assert base.State.engagements[("A", "prepare-explicit")] == "PREPARING"
            record(52, "Prepare remains explicit")

            fixture("exports", pursuit="PREPARING", proposal_id="proposal-exports")
            page.goto(f"{BASE_URL}/dashboard/bid-preparation/proposal-exports", wait_until="networkidle")
            page.get_by_role("button", name="Download PDF", exact=True).click()
            page.get_by_role("button", name="Download Word", exact=True).click()
            page.wait_for_timeout(500)
            assert {"generate-pdf", "docx"}.issubset(base.State.export_calls)
            assert base.State.engagements[("A", "exports")] == "PREPARING"
            record(53, "PDF and DOCX remain non-submission")

            page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
            assert page.get_by_role("link", name="Tenders", exact=True).count() == 1
            assert page.get_by_role("link", name="My Tenders", exact=True).count() == 1
            assert page.get_by_role("link", name="Bid Preparation", exact=True).count() == 1
            assert page.get_by_text("My Bids", exact=True).count() == 0
            assert page.get_by_text("Tender Workspace", exact=True).count() == 0
            record(54, "removed surfaces have no broken canonical navigation")

            page.goto(f"{BASE_URL}/dashboard/bid-preparation/proposal-owned", wait_until="networkidle")
            page.get_by_role("link", name="Back to Tender Details", exact=True).click()
            page.wait_for_url("**/dashboard/tenders/owned")
            page.get_by_role("link", name="Open Bid Preparation", exact=True).first.click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-owned")
            record(55, "canonical Tender and Bid Preparation return links")

            page.goto(f"{BASE_URL}/dashboard/tenders/owned", wait_until="networkidle")
            page.get_by_role("link", name="Open Compliance", exact=True).first.click()
            page.wait_for_url("**/dashboard/tenders/owned/compliance")
            page.get_by_role("link", name="Back to Tender Details", exact=True).click()
            page.wait_for_url("**/dashboard/tenders/owned")
            record(56, "canonical Tender and Compliance return links")

            fixture("my-tender-link", pursuit="SAVED")
            page.goto(f"{BASE_URL}/dashboard/my-tenders?status=ALL&search=my-tender-link", wait_until="networkidle")
            card = page.get_by_text("Cleanup Tender my-tender-link", exact=True).locator("xpath=ancestor::article")
            card.get_by_role("link", name="Open Tender", exact=True).click()
            page.wait_for_url("**/dashboard/tenders/my-tender-link")
            record(57, "My Tenders to Tender Details link")

            page.goto(f"{BASE_URL}/dashboard/tenders/owned#requirements-documents", wait_until="networkidle")
            page.get_by_role("heading", name="Requirements & Documents", exact=True).wait_for()
            assert page.evaluate("location.hash") == "#requirements-documents"
            record(58, "deep-link anchors remain functional")

            page.goto(f"{BASE_URL}/dashboard/bid-preparation", wait_until="networkidle")
            assert page.get_by_text("Cleanup Tender foreign", exact=True).count() == 0
            page.goto(f"{BASE_URL}/dashboard/bids/proposal-foreign", wait_until="networkidle")
            page.get_by_text("This legacy bookmark is not an owned Bid Preparation artifact.", exact=True).wait_for()
            record(59, "same-name and foreign tenant isolation")

            base.State.authority = False
            page.goto(f"{BASE_URL}/dashboard/bid-preparation/proposal-owned", wait_until="domcontentloaded")
            page.wait_for_url(lambda url: urlparse(url).path == "/", timeout=15000)
            record(60, "stale or revoked credential denied")

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
        base.kill_listener(3111)
        base.kill_listener(CDP_PORT)

    assert len(results) == 20
    return results


def main() -> int:
    # Preserve the independently asserted Sprint 5.3 forty-case matrix, then
    # add the twenty Sprint 5.4 cleanup/passivity cases.
    assert s53.main() == 0
    cleanup = run_cleanup_twenty()
    print(json.dumps({"cleanup_results": cleanup, "passed": 60}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
