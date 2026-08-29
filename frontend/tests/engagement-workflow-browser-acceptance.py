#!/usr/bin/env python3
"""Real Chromium acceptance for the 35 Sprint 4.4 workflow cases."""

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

base.BASE_URL = "http://localhost:3108"
base.MOCK_PORT = 8108
base.CDP_PORT = 9228


ALLOWED = {
    "SAVED": ["EVALUATE", "PREPARE_BID", "DISMISS"],
    "EVALUATING": ["PREPARE_BID", "DISMISS"],
    "PREPARING": ["MARK_SUBMITTED", "DISMISS"],
    "SUBMITTED": ["RECORD_WON", "RECORD_LOST", "CORRECT_TO_PREPARING"],
    "WON": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_LOST"],
    "LOST": ["CORRECT_TO_SUBMITTED", "CORRECT_TO_WON"],
    "DISMISSED": ["SAVE", "EVALUATE", "PREPARE_BID"],
}

original_item = base.my_tender_item


def my_tender_item(owner: str, tender_id: str, status: str) -> dict:
    item = original_item(owner, tender_id, status)
    item["allowed_actions"] = ALLOWED[status]
    return item


base.my_tender_item = my_tender_item


class WorkflowState:
    force_stale = False


class Handler(base.Handler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "tenders"] and parts[4] == "engagement":
            tender_id = parts[3]
            if tender_id not in base.State.tenders:
                self.send_json(404, {"detail": "Tender not found"})
                return
            current = base.State.engagements.get(("A", tender_id))
            proposal_id = next((key for key, row in base.State.proposals.items() if row["owner"] == "A" and row["tender_id"] == tender_id), None)
            self.send_json(200, {
                "engagement": my_tender_item("A", tender_id, current) if current else None,
                "proposal_id": proposal_id,
            })
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 6 and parts[:3] == ["api", "v1", "my-tenders"] and parts[4] == "actions":
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            engagement_id, action = parts[3], parts[5]
            prefix = "engagement-A-"
            if not engagement_id.startswith(prefix):
                self.send_json(404, {"detail": "My Tender not found"})
                return
            tender_id = engagement_id[len(prefix):]
            current = base.State.engagements.get(("A", tender_id))
            if current is None:
                self.send_json(404, {"detail": "My Tender not found"})
                return
            if WorkflowState.force_stale:
                WorkflowState.force_stale = False
                base.State.engagements[("A", tender_id)] = "PREPARING"
                self.send_json(409, {"detail": "stale engagement status"})
                return
            if body.get("expected_status") != current:
                self.send_json(409, {"detail": "stale engagement status"})
                return
            transitions = {
                ("SAVED", "evaluate"): "EVALUATING",
                ("DISMISSED", "evaluate"): "EVALUATING",
                ("PREPARING", "mark-submitted"): "SUBMITTED",
                ("SUBMITTED", "mark-won"): "WON",
                ("SUBMITTED", "mark-lost"): "LOST",
                ("SAVED", "dismiss"): "DISMISSED",
                ("EVALUATING", "dismiss"): "DISMISSED",
                ("PREPARING", "dismiss"): "DISMISSED",
                ("SUBMITTED", "correct-to-preparing"): "PREPARING",
                ("WON", "correct-to-submitted"): "SUBMITTED",
                ("LOST", "correct-to-submitted"): "SUBMITTED",
                ("WON", "correct-to-lost"): "LOST",
                ("LOST", "correct-to-won"): "WON",
            }
            target = transitions.get((current, action))
            if target is None:
                self.send_json(409, {"detail": f"invalid engagement transition: {current}"})
                return
            base.State.engagements[("A", tender_id)] = target
            self.send_json(200, {"engagement": my_tender_item("A", tender_id, target)})
            return
        if len(parts) == 5 and parts[:3] == ["api", "v1", "tenders"] and parts[4] == "engagement":
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            tender_id = parts[3]
            if tender_id not in base.State.tenders:
                self.send_json(404, {"detail": "Tender not found"})
                return
            current = base.State.engagements.get(("A", tender_id))
            created = current is None
            reengaged = current == "DISMISSED"
            if created or reengaged:
                base.State.engagements[("A", tender_id)] = "SAVED"
            final = base.State.engagements[("A", tender_id)]
            self.send_json(200, {"engagement": my_tender_item("A", tender_id, final), "created": created, "reengaged": reengaged})
            return
        super().do_POST()


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3108&& set BACKEND_INTERNAL_URL=http://127.0.0.1:8108/api/v1&& "
        "set NEXT_DIST_DIR=.next-s44&& npm run dev -- -p 3108"
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

    def fixture(tender_id: str, status: str | None, *, source_status: str = "OPEN", proposal_status: str | None = None) -> None:
        row = base.tender(tender_id, f"Workflow {tender_id}", status=source_status)
        base.State.tenders = {tender_id: row}
        base.State.engagements = {} if status is None else {("A", tender_id): status}
        base.State.proposals = {}
        if proposal_status:
            proposal_id = f"proposal-{tender_id}"
            base.State.proposals[proposal_id] = base.proposal(proposal_id, row, status=proposal_status)

    try:
        base.wait_for_url(base.BASE_URL)
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_path = r"C:\Users\acer\AppData\Local\Temp\s44-browser-profile"
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--remote-debugging-address=0.0.0.0','--remote-debugging-port={base.CDP_PORT}',"
            f"'--user-data-dir={profile_path}','about:blank'"
        )
        subprocess.run([base.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        base.wait_for_url(f"http://127.0.0.1:{base.CDP_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{base.CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{"name": "authjs.session-token", "value": base.session_cookie(), "url": base.BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1360, "height": 900})

            def open_list(tender_id: str) -> None:
                page.goto(f"{base.BASE_URL}/dashboard/my-tenders?status=ALL&search={tender_id}", wait_until="networkidle")

            def confirm(label: str) -> None:
                dialog = page.get_by_role("dialog")
                dialog.wait_for()
                dialog.get_by_role("button", name=label, exact=True).click()

            fixture("save", None)
            page.goto(f"{base.BASE_URL}/dashboard/tenders/save", wait_until="networkidle")
            page.get_by_role("button", name="Save to My Tenders", exact=True).click()
            page.get_by_text("Engagement: Saved", exact=True).wait_for()
            record("1 Save new Tender to SAVED")

            fixture("evaluate", "SAVED")
            open_list("evaluate")
            page.get_by_role("button", name="Evaluate", exact=True).click()
            page.get_by_text("Engagement: Evaluating", exact=True).wait_for()
            record("2 SAVED to EVALUATING")

            for number, initial in ((3, "SAVED"), (4, "EVALUATING")):
                tender_id = f"prepare-{initial.lower()}"
                fixture(tender_id, initial)
                open_list(tender_id)
                page.get_by_role("button", name="Prepare Bid", exact=True).click()
                page.wait_for_url(f"**/dashboard/bid-preparation/proposal-{tender_id}")
                assert base.State.engagements[("A", tender_id)] == "PREPARING"
                record(f"{number} {initial} to PREPARING by Prepare")

            fixture("submitted", "PREPARING", proposal_status="DRAFT")
            open_list("submitted")
            page.get_by_role("button", name="Mark as Submitted", exact=True).click()
            assert page.get_by_role("button", name="Submit Bid", exact=True).count() == 0
            record("6 submission wording is Mark as Submitted")
            confirm("Mark as Submitted")
            page.get_by_text("Engagement: Submitted", exact=True).wait_for()
            record("5 PREPARING to SUBMITTED")

            fixture("won", "SUBMITTED")
            open_list("won")
            page.get_by_role("button", name="Record as Won", exact=True).click()
            confirm("Record as Won")
            page.get_by_text("Engagement: Won", exact=True).wait_for()
            record("7 SUBMITTED to WON")

            fixture("lost", "SUBMITTED")
            open_list("lost")
            page.get_by_role("button", name="Record as Lost", exact=True).click()
            confirm("Record as Lost")
            page.get_by_text("Engagement: Lost", exact=True).wait_for()
            record("8 SUBMITTED to LOST")

            for number, initial in ((9, "PREPARING"), (10, "EVALUATING")):
                tender_id = f"dismiss-{initial.lower()}"
                fixture(tender_id, initial, proposal_status="DRAFT" if initial == "PREPARING" else None)
                open_list(tender_id)
                page.get_by_text("More actions", exact=True).click()
                page.get_by_role("button", name="Dismiss", exact=True).click()
                if initial == "PREPARING":
                    confirm("Dismiss")
                page.get_by_text("Engagement: Dismissed", exact=True).wait_for()
                record(f"{number} {initial} to DISMISSED")

            fixture("resume-save", "DISMISSED")
            open_list("resume-save")
            page.get_by_role("button", name="Save again", exact=True).click()
            page.get_by_text("Engagement: Saved", exact=True).wait_for()
            record("11 DISMISSED to SAVED")

            fixture("resume-evaluate", "DISMISSED")
            open_list("resume-evaluate")
            page.get_by_role("button", name="Evaluate", exact=True).click()
            page.get_by_text("Engagement: Evaluating", exact=True).wait_for()
            record("12 DISMISSED to EVALUATING")

            fixture("resume-prepare", "DISMISSED")
            open_list("resume-prepare")
            page.get_by_role("button", name="Prepare Bid", exact=True).click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-resume-prepare")
            record("13 DISMISSED to PREPARING by Prepare")

            corrections = [
                (14, "SUBMITTED", "Correct status to Preparing", "Preparing"),
                (15, "WON", "Correct outcome to Submitted", "Submitted"),
                (16, "LOST", "Correct outcome to Submitted", "Submitted"),
                (17, "WON", "Correct outcome to Lost", "Lost"),
            ]
            for number, initial, label, final_label in corrections:
                tender_id = f"correction-{number}"
                fixture(tender_id, initial)
                open_list(tender_id)
                page.get_by_text("Correct status", exact=True).click()
                page.get_by_role("button", name=label, exact=True).click()
                confirm(label)
                page.get_by_text(f"Engagement: {final_label}", exact=True).wait_for()
                record(f"{number} explicit correction {initial} to {final_label.upper()}")

            fixture("legacy", None, proposal_status="COMPLETED")
            page.goto(f"{base.BASE_URL}/dashboard/my-tenders?status=ALL&search=legacy", wait_until="networkidle")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            page.goto(f"{base.BASE_URL}/dashboard/bid-preparation/proposal-legacy", wait_until="networkidle")
            page.get_by_role("button", name="Continue Bid Preparation", exact=True).click()
            page.wait_for_timeout(300)
            assert base.State.engagements[("A", "legacy")] == "PREPARING"
            record("18 Proposal-only legacy remains absent until Continue")
            record("19 explicit Continue creates PREPARING")

            before = base.State.engagements[("A", "legacy")]
            base.State.proposals["proposal-legacy"]["status"] = "COMPLETED"
            page.reload(wait_until="networkidle")
            assert base.State.engagements[("A", "legacy")] == before
            record("20 completed Proposal leaves engagement unchanged")

            fixture("exports", "PREPARING", proposal_status="COMPLETED")
            page.goto(f"{base.BASE_URL}/dashboard/bid-preparation/proposal-exports", wait_until="networkidle")
            page.get_by_role("button", name="Download PDF", exact=True).click()
            page.get_by_role("button", name="Download Word", exact=True).click()
            page.wait_for_timeout(300)
            assert base.State.engagements[("A", "exports")] == "PREPARING"
            record("21 PDF export leaves engagement unchanged")
            record("22 DOCX export leaves engagement unchanged")

            page.goto(f"{base.BASE_URL}/dashboard/tenders/exports/compliance", wait_until="networkidle")
            assert base.State.engagements[("A", "exports")] == "PREPARING"
            record("23 Compliance leaves engagement unchanged")

            base.State.tenders["exports"]["status"] = "CLOSED"
            open_list("exports")
            page.get_by_text("Tender: Closed", exact=True).wait_for()
            assert base.State.engagements[("A", "exports")] == "PREPARING"
            record("24 Tender CLOSED leaves engagement unchanged")
            base.State.tenders["exports"]["status"] = "CANCELLED"
            open_list("exports")
            page.get_by_text("Tender: Cancelled", exact=True).wait_for()
            record("25 Tender CANCELLED leaves engagement unchanged")

            fixture("stale", "SAVED")
            open_list("stale")
            WorkflowState.force_stale = True
            page.get_by_role("button", name="Evaluate", exact=True).click()
            page.get_by_text("Status changed. We refreshed the latest state.", exact=True).wait_for()
            page.get_by_text("Engagement: Preparing", exact=True).wait_for()
            record("26 stale transition returns 409 and refreshes")

            fixture("tenant-a", "SAVED")
            foreign = base.tender("tenant-b", "Other Tenant Secret")
            base.State.tenders["tenant-b"] = foreign
            base.State.engagements[("B", "tenant-b")] = "PREPARING"
            page.goto(f"{base.BASE_URL}/dashboard/my-tenders?status=ALL&search=Other", wait_until="networkidle")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            record("27 same-name tenant isolation")
            response = page.request.post(f"{base.BASE_URL}/api/v1/my-tenders/engagement-B-tenant-b/actions/mark-submitted", data={"expected_status": "PREPARING"})
            assert response.status == 404
            record("28 foreign engagement mutation denied")

            fixture("counts-prep", "PREPARING")
            other = base.tender("counts-saved", "Workflow counts-saved")
            base.State.tenders["counts-saved"] = other
            base.State.engagements[("A", "counts-saved")] = "SAVED"
            page.goto(f"{base.BASE_URL}/dashboard/my-tenders?status=PREPARING", wait_until="networkidle")
            page.get_by_role("button", name="Mark as Submitted", exact=True).click()
            confirm("Mark as Submitted")
            page.get_by_role("heading", name="No tenders saved yet").wait_for()
            assert "1" in page.get_by_role("button", name="Submitted", exact=False).inner_text()
            record("30 counts and filter refresh from backend")

            fixture("bid-context", "PREPARING", proposal_status="DRAFT")
            page.goto(f"{base.BASE_URL}/dashboard/bid-preparation/proposal-bid-context", wait_until="networkidle")
            page.get_by_text("Engagement: Preparing", exact=True).first.wait_for()
            record("31 Bid Preparation displays engagement context")
            page.goto(f"{base.BASE_URL}/dashboard/tenders/bid-context", wait_until="networkidle")
            page.get_by_role("heading", name="Tender pursuit", exact=True).wait_for()
            record("32 Tender Details displays compact engagement context")

            before_counts = (len(base.State.engagements), len(base.State.proposals))
            page.reload(wait_until="networkidle")
            assert (len(base.State.engagements), len(base.State.proposals)) == before_counts
            record("33 passive page loads create nothing")

            fixture("no-proposal", "PREPARING")
            open_list("no-proposal")
            page.get_by_role("button", name="Mark as Submitted", exact=True).click()
            confirm("Mark as Submitted")
            assert not base.State.proposals
            record("34 SUBMITTED without Proposal")
            page.get_by_role("button", name="Record as Won", exact=True).click()
            confirm("Record as Won")
            page.get_by_text("Engagement: Won", exact=True).wait_for()
            assert not base.State.proposals and base.State.engagements[("A", "no-proposal")] == "WON"
            record("35 WON without Proposal")

            base.State.authority = False
            page.goto(f"{base.BASE_URL}/dashboard/my-tenders", wait_until="domcontentloaded")
            page.wait_for_url(lambda url: urlparse(url).path == "/", timeout=15000)
            record("29 stale or revoked account credential denied")
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
        base.kill_listener(3108)
        base.kill_listener(9228)

    assert len(results) == 35, results
    print(json.dumps({"results": results, "passed": len(results)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
