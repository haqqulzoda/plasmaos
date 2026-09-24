#!/usr/bin/env python3
"""Sprint 14.4 Compliance workspace browser acceptance against synthetic APIs."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FRONT = ROOT / "frontend"
OUT = ROOT / "docs" / "audits" / "s14_4" / "browser"
BASE = "http://localhost:3116"
MOCK_PORT = 8116


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


s82 = load("s144_s82", "s8-2-analysis-language-browser-acceptance.py")
s72 = s82.s72


def analysis_fixture() -> dict:
    result = s82.response_for("en", 4)
    review = copy.deepcopy(result["hybrid_compliance"]["manual_reviews_required"][0])
    review.update(
        headline="Valid tax clearance certificate",
        parent_section_header="Eligibility · Tax compliance",
        is_dealbreaker=False,
    )
    critical = copy.deepcopy(review)
    critical.update(
        headline="Minimum annual turnover",
        raw_text_snippet="Audited annual turnover must meet the tender threshold.",
        exact_quote="Annual turnover shall meet the stated tender threshold.",
        source_page=9,
        parent_section_header="Qualification · Financial capacity",
        verdict="FAILED",
        is_dealbreaker=True,
        taxonomy_node_id="11111111-1111-4111-8111-111111111111",
        reason="Recorded turnover evidence is below the stated requirement.",
    )
    satisfied = copy.deepcopy(review)
    satisfied.update(
        headline="Company registration",
        raw_text_snippet="The bidder must provide current company registration.",
        exact_quote="Provide a valid certificate of company registration.",
        source_page=4,
        parent_section_header="Eligibility · Registration",
        verdict="SATISFIED",
        is_dealbreaker=False,
        match_method="VAULT_DETERMINISTIC",
        matched_credential="Certificate of incorporation",
        vault_evidence_id="record-registration",
        vault_match_source="readiness_vault",
        reason="A current registration record supports this requirement.",
    )
    recorded = copy.deepcopy(review)
    recorded.update(
        headline="Submission language",
        raw_text_snippet="The proposal must be submitted in English.",
        exact_quote="All proposal documents shall be submitted in English.",
        source_page=3,
        parent_section_header="Instructions · Submission",
        verdict="NEEDS_MANUAL_REVIEW",
        is_dealbreaker=False,
        reason="This obligation is recorded for proposal preparation.",
    )
    result["hybrid_compliance"].update(
        total_requirements=4,
        satisfied_count=1,
        failed_count=1,
        manual_review_count=1,
        recorded_obligations_count=1,
        verdict_status="NOT_ELIGIBLE",
        failed_dealbreakers=[critical],
        manual_reviews_required=[review],
        satisfied_requirements=[satisfied],
        recorded_obligations=[recorded],
        status_message="One failed dealbreaker and one manual review require attention.",
    )
    result["coverage_metadata"] = {"coverage_status": "complete"}
    return result


ANALYSIS = analysis_fixture()
REQUESTS: list[tuple[str, str]] = []
WRITES: list[tuple[str, str]] = []


class Handler(s82.Handler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        REQUESTS.append(("GET", self.path))
        if parsed.path == "/api/v1/tenders/s72-tender/latest-analysis":
            self.send_json(200, ANALYSIS)
            return
        if parsed.path == "/api/v1/tenders/s72-tender/documents":
            self.send_json(
                200,
                [
                    {
                        "id": "doc-1",
                        "file_type": "pdf",
                        "display_name": "buyer-file.pdf",
                        "download_url": "/document-preview/doc-1",
                        "download_status": "available",
                        "original_filename": "buyer-file.pdf",
                        "storage_filename": "buyer-file.pdf",
                        "parsed_source_filenames": ["buyer-file.pdf"],
                        "archive_inner_filenames": [],
                        "analysis_text_available": True,
                        "file_size": 1234,
                        "created_at": "2026-09-20T10:00:00Z",
                    }
                ],
            )
            return
        if parsed.path == "/api/v1/tenders/s72-tender/overrides":
            self.send_json(200, {"accepted_node_ids": []})
            return
        if parsed.path == "/api/v1/tenders/s72-tender/analyses/analysis-a/versions":
            self.send_json(
                200,
                [
                    {
                        "analysis_id": "analysis-a",
                        "version_number": 4,
                        "origin": "GENERATED",
                        "status": "COMPLETED",
                        "analysis_language": "en",
                        "snapshot_completeness": "COMPLETE",
                        "created_at": "2026-09-20T10:00:00Z",
                        "completed_at": "2026-09-20T10:01:00Z",
                    }
                ],
            )
            return
        version_match = re.fullmatch(
            r"/api/v1/tenders/s72-tender/analyses/analysis-a/versions/(\d+)",
            parsed.path,
        )
        if version_match:
            self.send_json(
                200,
                {
                    "metadata": {
                        "analysis_id": "analysis-a",
                        "version_number": 4,
                        "origin": "GENERATED",
                        "status": "COMPLETED",
                        "analysis_language": "en",
                        "snapshot_completeness": "COMPLETE",
                        "created_at": "2026-09-20T10:00:00Z",
                        "completed_at": "2026-09-20T10:01:00Z",
                    },
                    "result_snapshot": ANALYSIS,
                    "integrity": {"snapshot_completeness": "COMPLETE"},
                },
            )
            return
        if parsed.path == "/api/v1/tenders/s72-tender/compliance/export/pdf":
            query = parse_qs(parsed.query)
            assert query.get("analysis_id") == ["analysis-a"]
            assert query.get("version_number") == ["4"]
            body = b"%PDF-1.4 Sprint 14.4 exact version"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="compliance.pdf"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/tenders/s72-tender/override":
            WRITES.append(("POST", parsed.path))
            payload = self.body()
            self.send_json(
                200,
                {
                    "state_hash": "b" * 64,
                    "override_seal": "a" * 64,
                    "overridden_node_ids": [payload["node_id"]],
                },
            )
            return
        super().do_POST()


def session_token(env: dict[str, str]) -> str:
    script = """
import {encode} from 'next-auth/jwt';
console.log(await encode({
  secret:'s72-browser-secret',
  salt:'authjs.session-token',
  token:{
    name:'Synthetic Pilot', email:'pilot@example.invalid',
    sub:'72000000-0000-4000-8000-000000000001',
    accessToken:'s72-token-a', approval_status:'approved',
    platform_role:'pilot_user'
  },
  maxAge:3600
}));
"""
    return subprocess.check_output(
        ["node", "--input-type=module", "-e", script],
        cwd=FRONT,
        env=env,
        text=True,
    ).strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s72.State.active = False
    s72.State.onboarding_required = False
    s72.State.users["s72-token-a"].update(
        ui_locale="en", default_analysis_language="en"
    )
    s82.S82State.latest["user-a"] = ANALYSIS
    s82.S82State.histories["user-a"] = []
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {
        **os.environ,
        "AUTH_SECRET": "s72-browser-secret",
        "AUTH_URL": BASE,
        "NEXTAUTH_URL": BASE,
        "AUTH_TRUST_HOST": "true",
        "NEXT_DIST_DIR": ".next-release-test",
        "BACKEND_INTERNAL_URL": f"http://127.0.0.1:{MOCK_PORT}/api/v1",
    }
    log = (OUT / "frontend.log").open("w")
    frontend = subprocess.Popen(
        ["npm", "run", "start", "--", "-p", "3116"],
        cwd=FRONT,
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    results: list[dict[str, object]] = []

    def record(name: str, evidence: object = None) -> None:
        results.append({"case": name, "status": "PASS", "evidence": evidence})
        print("PASS", name, flush=True)

    def axe(page, name: str) -> None:
        page.add_script_tag(path=str(FRONT / "node_modules" / "axe-core" / "axe.min.js"))
        result = page.evaluate(
            "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})"
        )
        (OUT / f"{name}-axe.json").write_text(json.dumps(result, indent=2))
        severe = [
            item
            for item in result["violations"]
            if item["impact"] in {"serious", "critical"}
        ]
        assert not severe, [(item["id"], len(item["nodes"])) for item in severe]
        record(f"{name}/axe", {"serious_critical": 0})

    browser = None
    try:
        for _ in range(60):
            try:
                urlopen(BASE, timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("frontend did not start")

        token = session_token(env)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(reduced_motion="reduce")
            context.add_cookies(
                [
                    {
                        "name": "authjs.session-token",
                        "value": token,
                        "url": BASE,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
            page = context.new_page()
            page.set_default_timeout(15_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            catalogs = {
                locale: json.loads((FRONT / "messages" / locale / "compliance.json").read_text())
                for locale in ("en", "uz", "ru", "ar")
            }

            for locale in ("en", "uz", "ru", "ar"):
                s72.State.users["s72-token-a"]["ui_locale"] = locale
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    REQUESTS.clear()
                    WRITES.clear()
                    errors.clear()
                    response = page.goto(
                        f"{BASE}/dashboard/tenders/s72-tender/compliance",
                        wait_until="networkidle",
                    )
                    prefix = f"{locale}/{width}"
                    assert response and response.status == 200
                    expect(page.locator(".compliance-page")).to_be_visible()
                    expect(page.locator("h1")).to_contain_text(
                        "Original procurement title — do not translate"
                    )
                    expect(page.get_by_text(catalogs[locale]["workspace"]["beta"], exact=True)).to_be_visible()
                    expect(page.locator(".compliance-summary")).to_be_visible()
                    expect(page.locator(".compliance-group.is-critical")).to_be_visible()
                    expect(page.locator(".compliance-group.is-review")).to_be_visible()
                    show_matched_pattern = re.escape(
                        catalogs[locale]["workspace"]["showMatched"]
                    ).replace(re.escape("{count}"), r"\d+")
                    expect(
                        page.get_by_role(
                            "button", name=re.compile(f"^{show_matched_pattern}$")
                        )
                    ).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    assert not errors, errors
                    assert not WRITES
                    assert not any("/document-preview/" in path for _, path in REQUESTS)
                    record(f"{prefix}/render-bounds-passivity")

                    page.screenshot(path=str(OUT / f"compliance-{locale}-{width}.png"), full_page=True)

                    if width < 1200:
                        expect(page.locator(".compliance-context")).to_be_hidden()
                        page.locator(".compliance-requirement").first.locator(
                            ".compliance-row-select"
                        ).click()
                        drawer = page.locator("dialog[open]")
                        expect(drawer).to_be_visible()
                        text = drawer.inner_text()
                        source_label = catalogs[locale]["workspace"]["sourceEvidenceLabel"]
                        analysis_label = catalogs[locale]["workspace"]["plasmaAnalysisLabel"]
                        assert text.index(source_label) < text.index(analysis_label)
                        page.keyboard.press("Escape")
                        expect(drawer).to_have_count(0)
                        page.wait_for_timeout(100)
                        assert page.evaluate(
                            "document.activeElement?.classList.contains('compliance-row-select')"
                        )
                    else:
                        inspector = page.locator(".compliance-context .compliance-inspector")
                        expect(inspector).to_be_visible()
                        text = inspector.inner_text()
                        assert text.index(catalogs[locale]["workspace"]["sourceEvidenceLabel"]) < text.index(
                            catalogs[locale]["workspace"]["plasmaAnalysisLabel"]
                        )
                    record(f"{prefix}/evidence-first-inspector")

                    if locale in {"en", "ar"} and width in {390, 1440}:
                        axe(page, f"compliance-{locale}-{width}")

            s72.State.users["s72-token-a"]["ui_locale"] = "en"
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(f"{BASE}/dashboard/tenders/s72-tender/compliance", wait_until="networkidle")
            before = len(REQUESTS)
            search = page.get_by_role("searchbox", name="Search requirements")
            search.fill("turnover")
            expect(page.locator(".compliance-requirement h3")).to_have_count(1)
            expect(page.locator(".compliance-requirement h3")).to_contain_text("Minimum annual turnover")
            assert len(REQUESTS) == before
            page.get_by_role("button", name="Reset", exact=True).click()
            record("interactions/local-search-reset")

            page.get_by_role("button", name=re.compile("Show .* satisfied requirements")).click()
            expect(page.get_by_text("Company registration", exact=True)).to_be_visible()
            record("interactions/matched-progressive-disclosure")

            page.locator(".compliance-requirement").first.locator(".compliance-row-select").click()
            expect(page.locator(".compliance-context")).to_contain_text("Minimum annual turnover")
            page.get_by_role("button", name="Override system flag", exact=True).click()
            dialog = page.locator("dialog[open]")
            expect(dialog).to_be_visible()
            dialog.get_by_label("Justification", exact=True).fill(
                "Recorded company evidence requires this explicit decision."
            )
            dialog.get_by_role("button", name="Record override", exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.locator(".compliance-requirement").first).to_contain_text("Overridden")
            record("interactions/audited-override")

            with page.expect_download():
                page.get_by_role("button", name="Download Compliance PDF", exact=True).click()
            assert any(
                "analysis_id=analysis-a" in path and "version_number=4" in path
                for _, path in REQUESTS
            )
            record("interactions/exact-version-export")
            browser.close()
            browser = None

        (OUT / "results.json").write_text(json.dumps(results, indent=2))
        print(f"S14.4 browser acceptance: {len(results)} passed", flush=True)
        return 0
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        try:
            os.killpg(frontend.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        server.shutdown()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
