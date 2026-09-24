#!/usr/bin/env python3
"""Sprint 14.3 Tender Details browser evidence against a deterministic local API."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = Path(os.environ.get("PLASMA_BROWSER_RESULTS", str(ROOT / "docs/audits/s14_3/browser")))
AXE = ROOT / "frontend/node_modules/axe-core/axe.min.js"
SPEC = importlib.util.spec_from_file_location("s143_base", HERE / "tender-details-browser-acceptance.py")
assert SPEC and SPEC.loader
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
HOST = os.environ.get("PLASMA_WINDOWS_HOST", "127.0.0.1")
base.base.BASE_URL = "http://localhost:4210"


def start_frontend():
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && set AUTH_SECRET=s42-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:4210&& set BACKEND_INTERNAL_URL=http://127.0.0.1:8110/api/v1&& "
        "set NEXT_DIST_DIR=.next-s143&& npm run dev -- -p 4210"
    )
    return subprocess.Popen([base.base.CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Handler(base.Handler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/v1/tenders/sources/catalog":
            self.send_json(200, [{"source_system": "world_bank", "display_name": "World Bank", "refresh_enabled": True, "can_refresh": True}])
            return
        if path == "/api/v1/tenders/sources/refresh-status":
            self.send_json(200, [])
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        base.AcceptanceState.request_log.append(("POST", path))
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "tenders"] and parts[4] == "engagement":
            tender_id = parts[3]
            base.AcceptanceState.mutation_count += 1
            base.base.State.engagements[("A", tender_id)] = "SAVED"
            saved = base.engagement(tender_id, "SAVED")
            base.AcceptanceState.details[tender_id]["pursuit"] = base.envelope(saved)
            self.send_json(200, {"engagement": saved, "created": True, "reengaged": False})
            return
        if path == "/api/v1/tenders/s143-remote/sync-docs":
            base.AcceptanceState.mutation_count += 1
            payload = base.AcceptanceState.details["s143-remote"]["documents"]["data"]
            payload["acquisition_state"] = "QUEUED"
            payload["job_id"] = "s143-job"
            self.send_json(202, {"job_id": "s143-job", "status": "QUEUED", "progress": 0})
            return
        super().do_POST()


def fixture(tender_id: str, *, recommendation=True, document_state="READY", competitor_state="AVAILABLE", pursuit=None, project=True, contacts=True, compliance="COMPLETE", leadership_count=1):
    row = base.base.tender(tender_id, f"Consolidated Tender {tender_id}")
    row["source_system"] = "world_bank"
    row["description"] = "SOURCE DESCRIPTION MUST NOT APPEAR IN THE MAIN PAGE"
    base.base.State.tenders[tender_id] = row
    payload = base.details(tender_id, pursuit=pursuit, compliance=compliance, competitor_state=competitor_state)
    payload["recommendation"] = ({
        "recommendation_id": "stored-s143", "match_score": 75,
        "rationale_summary": "Stored recommendation rationale.", "is_dismissed": False,
        "created_at": "2026-09-17T10:00:00Z",
    } if recommendation else None)
    if not project:
        payload["project_context"] = base.envelope()
        payload["project_leadership"] = base.envelope()
    elif leadership_count == 0:
        leadership = payload["project_leadership"]["data"]
        leadership["items"] = []
        leadership.update({"total_count": 0, "returned_count": 0, "truncated": False})
        payload["project_leadership"] = base.envelope()
    elif leadership_count > 1:
        leadership = payload["project_leadership"]["data"]
        prototype = leadership["items"][0]
        leadership["items"] = [
            {**prototype, "role_id": f"role-{tender_id}-{index}", "display_name": f"Project Leader {chr(65 + index)}"}
            for index in range(leadership_count)
        ]
        leadership.update({"total_count": leadership_count, "returned_count": leadership_count, "truncated": False})
    if not contacts:
        payload["procurement_contacts"] = base.envelope()
    docs = payload["documents"]["data"]
    docs.update({
        "download_authorization_separate": True, "acquisition_supported": True,
        "acquisition_state": document_state, "job_id": None, "job_state": None,
        "ready_count": 1 if document_state == "READY" else 0,
        "failed_count": 1 if document_state in {"FAILED", "PARTIAL"} else 0,
        "processing_count": 1 if document_state == "PROCESSING" else 0,
        "remote_count": 1 if document_state in {"AVAILABLE_REMOTE", "QUEUED", "DOWNLOADING"} else 0,
    })
    item = docs["items"][0]
    item["acquisition_state"] = "READY" if document_state == "READY" else "FAILED" if document_state in {"FAILED", "PARTIAL"} else "AVAILABLE_REMOTE" if document_state == "AVAILABLE_REMOTE" else document_state
    item["availability"] = "AVAILABLE" if document_state == "READY" else "METADATA_ONLY"
    base.AcceptanceState.details[tender_id] = payload
    if pursuit:
        base.base.State.engagements[("A", tender_id)] = pursuit


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", base.base.MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    browser = None
    results = []
    try:
        base.base.wait_for_url(f"http://{HOST}:4210")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile = r"C:\Users\acer\AppData\Local\Temp\s143-browser-profile"
        command = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--remote-debugging-address=0.0.0.0','--remote-debugging-port={base.base.CDP_PORT}',"
            f"'--user-data-dir={profile}','about:blank'"
        )
        subprocess.run([base.base.POWERSHELL, "-NoProfile", "-Command", command], check=True)
        base.base.wait_for_url(f"http://{HOST}:{base.base.CDP_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{HOST}:{base.base.CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{"name": "authjs.session-token", "value": base.base.session_cookie(), "url": base.base.BASE_URL, "httpOnly": True, "sameSite": "Lax"}])
            page = context.pages[0] if context.pages else context.new_page()

            def open_page(tender_id, *, locale="en", width=1440):
                context.add_cookies([{"name": "plasma_ui_locale", "value": locale, "url": base.base.BASE_URL, "sameSite": "Lax"}])
                page.set_viewport_size({"width": width, "height": 950})
                page.goto(f"{base.base.BASE_URL}/dashboard/tenders/{tender_id}", wait_until="networkidle")
                page.get_by_role("heading", name=f"Consolidated Tender {tender_id}").wait_for()

            fixture("s143-full", leadership_count=3)
            before = len(base.AcceptanceState.request_log)
            open_page("s143-full")
            assert page.locator(".s143-decision-grid > *").count() == 3
            assert page.locator(".details-anchors").count() == 0
            assert page.get_by_text("SOURCE DESCRIPTION MUST NOT APPEAR IN THE MAIN PAGE").count() == 0
            assert page.locator("#project-leadership").get_by_text("Project Leader A").count() == 1
            assert page.locator("#project-leadership").get_by_text("Task Team Leader").count() == 0
            assert page.locator("#contacts").get_by_text("Procurement Contact A").count() == 1
            assert page.locator("#competitors").get_by_role("link", name="Open evidence: ACME Qurilish MCHJ").count() == 1
            assert page.locator("#competitors").get_by_text("Won a recent World Bank construction tender", exact=False).count() == 1
            assert page.locator("#tender-documents").get_by_role("button", name="Open document: RFP.pdf").count() == 1
            assert page.get_by_text("Stored recommendation rationale.").count() == 1
            project_grid = page.locator(".s143-project-grid").last
            assert project_grid.get_attribute("data-balanced") == "true"
            assert page.locator("#project-context dt").all_text_contents() == [
                "Name", "Country / Region", "Status", "Approval date", "Closing date",
            ]
            assert page.locator("#project-leadership .s143-leadership-list").get_attribute("data-columns") == "one"
            context_box = page.locator("#project-context").bounding_box()
            leadership_box = page.locator("#project-leadership").bounding_box()
            assert context_box and leadership_box
            assert abs(context_box["height"] - leadership_box["height"]) <= 1
            paths = base.AcceptanceState.request_log[before:]
            assert not [path for method, path in paths if method == "POST" and not path.endswith("/auth/refresh")], paths
            assert not [path for _, path in paths if any(term in path for term in ("/competitors", "/project", "/sync-docs", "/engagement"))], paths
            results.append("full-hierarchy-and-passivity")

            fixture("s143-leadership-six", leadership_count=6)
            open_page("s143-leadership-six")
            project_grid = page.locator(".s143-project-grid").last
            assert project_grid.get_attribute("data-balanced") == "true"
            assert page.locator("#project-leadership .s143-leadership-list").get_attribute("data-columns") == "two"
            context_box = page.locator("#project-context").bounding_box()
            leadership_box = page.locator("#project-leadership").bounding_box()
            assert context_box and leadership_box
            assert abs(context_box["height"] - leadership_box["height"]) <= 1
            results.append("leadership-one-to-six-balanced-height")

            fixture("s143-leadership-empty", leadership_count=0)
            open_page("s143-leadership-empty")
            project_grid = page.locator(".s143-project-grid").last
            assert project_grid.get_attribute("data-balanced") == "true"
            assert page.locator("#project-leadership").get_by_text("No current Project Leadership is available.").count() == 1
            context_box = page.locator("#project-context").bounding_box()
            leadership_box = page.locator("#project-leadership").bounding_box()
            assert context_box and leadership_box
            assert abs(context_box["height"] - leadership_box["height"]) <= 1
            results.append("leadership-empty-balanced-height")

            fixture("s143-leadership-many", leadership_count=8)
            base.AcceptanceState.details["s143-leadership-many"]["project_leadership"]["data"]["items"][-1]["is_current"] = False
            open_page("s143-leadership-many")
            leadership_section = page.locator("#project-leadership")
            assert page.locator(".s143-project-grid").last.get_attribute("data-balanced") == "false"
            assert leadership_section.locator(".s143-leadership-list li").count() == 6
            assert leadership_section.locator('.s143-leadership-list[data-columns="two"]').count() == 1
            leadership_section.get_by_role("button", name="View all (8)").click()
            assert leadership_section.locator(".s143-leadership-list li").count() == 8
            assert leadership_section.get_by_role("button", name="Show less").get_attribute("aria-expanded") == "true"
            results.append("leadership-responsive-scaling")

            fixture("s143-empty", recommendation=False, competitor_state="INSUFFICIENT_EVIDENCE", project=False, contacts=False, compliance=None)
            open_page("s143-empty")
            for copy in ("No stored recommendation", "No canonical Project", "No current Project Leadership", "Not enough verified procurement history", "No Procurement Contacts"):
                assert page.get_by_text(copy, exact=False).count() >= 1, copy
            results.append("truthful-empty-states")

            fixture("s143-remote", document_state="AVAILABLE_REMOTE")
            open_page("s143-remote")
            assert page.locator("#tender-documents").get_by_role("button", name="Open document: RFP.pdf").count() == 0
            before = base.AcceptanceState.mutation_count
            page.locator("#tender-documents").get_by_role("button", name="Download documents").click()
            page.get_by_text("Document acquisition queued").wait_for()
            assert base.AcceptanceState.mutation_count == before + 1
            results.append("remote-explicit-bulk-acquisition")

            fixture("s143-partial", document_state="PARTIAL")
            open_page("s143-partial")
            assert page.locator("#tender-documents").get_by_role("button", name="Try document acquisition again").count() == 1
            assert page.locator("#tender-documents").get_by_role("button", name="Open document: RFP.pdf").count() == 0
            results.append("partial-truthful-retry")

            fixture("s143-saved", pursuit="SAVED")
            open_page("s143-saved")
            assert page.locator(".s143-decision-grid").get_by_text("Pursuit: Saved").count() == 1
            assert page.locator("#bid-preparation").count() == 1
            results.append("saved-pursuit-and-bid-separation")

            fixture("s143-save")
            open_page("s143-save")
            before = base.AcceptanceState.mutation_count
            page.locator(".s143-pursuit-actions").get_by_role("button", name="Save to My Tenders").click()
            page.get_by_text("Pursuit: Saved").wait_for()
            assert base.AcceptanceState.mutation_count == before + 1
            results.append("explicit-save-pursuit")

            fixture("s143-prepare")
            open_page("s143-prepare")
            page.locator("#bid-preparation").get_by_role("button", name="Prepare Bid").click()
            page.wait_for_url("**/dashboard/bid-preparation/proposal-s143-prepare")
            results.append("explicit-prepare-bid-proposal-route")

            fixture("s143-routes")
            open_page("s143-routes")
            page.get_by_role("link", name="Open Compliance").first.click()
            page.wait_for_url("**/dashboard/tenders/s143-routes/compliance")
            results.append("compliance-route")
            open_page("s143-routes")
            page.get_by_role("link", name="Open Readiness Vault").click()
            page.wait_for_url("**/dashboard/readiness-vault")
            results.append("readiness-route")

            state_copy = {"QUEUED": "Document acquisition queued", "DOWNLOADING": "Downloading documents", "PROCESSING": "Preparing for analysis", "FAILED": "Document acquisition failed"}
            for document_state in state_copy:
                tender_id = f"s143-{document_state.lower()}"
                fixture(tender_id, document_state=document_state)
                open_page(tender_id)
                assert page.locator("#tender-documents").get_by_role("button", name="Open document: RFP.pdf").count() == 0
                assert page.locator("#tender-documents").get_by_text(state_copy[document_state], exact=False).count() >= 1
                results.append(f"document-{document_state.lower()}")

            fixture("s143-source-safe")
            base.base.State.tenders["s143-source-safe"]["source_url"] = "javascript:alert(1)"
            open_page("s143-source-safe")
            assert page.get_by_role("link", name="Open source notice").count() == 0
            results.append("unsafe-source-url-omitted")

            fixture("s143-return")
            open_page("s143-return")
            page.evaluate("""() => sessionStorage.setItem('plasmaos:tender-explorer:return', JSON.stringify({explorerUrl:'/dashboard/tenders?view=recommended&page=2',tenderId:'s143-return',scrollY:100,page:2,createdAt:Date.now()}))""")
            open_page("s143-return")
            assert page.get_by_role("link", name="Back to tenders").get_attribute("href") == "/dashboard/tenders?view=recommended&page=2"
            results.append("explorer-return-state")

            fixture("s143-full", leadership_count=3)
            for locale in ("en", "uz", "ru", "ar"):
                for width in (320, 390, 768, 1440):
                    open_page("s143-full", locale=locale, width=width)
                    assert page.locator("html").get_attribute("dir") == ("rtl" if locale == "ar" else "ltr")
                    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), (locale, width)
                    assert page.locator(".s143-decision-grid > *").count() == 3
                    page.screenshot(path=str(OUT / f"tender-details-{locale}-{width}.png"), full_page=True)
                    results.append(f"responsive-{locale}-{width}")
                    if locale in {"en", "ar"} and width in {390, 1440}:
                        page.add_script_tag(path=str(AXE))
                        axe = page.evaluate("async () => await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})")
                        (OUT / f"axe-{locale}-{width}.json").write_text(json.dumps(axe), encoding="utf-8")
                        bad = [item for item in axe["violations"] if item["impact"] in {"serious", "critical"}]
                        assert not bad, [(item["id"], len(item["nodes"])) for item in bad]
                        results.append(f"axe-{locale}-{width}")
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser:
            try: browser.close()
            except Exception: pass
        subprocess.run([base.base.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        base.base.kill_listener(base.base.BASE_URL.rsplit(":", 1)[-1])
        base.base.kill_listener(base.base.CDP_PORT)
    summary = {"passed": len(results), "cases": results}
    (OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
