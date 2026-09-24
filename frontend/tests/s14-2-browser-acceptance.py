#!/usr/bin/env python3
"""S14.2 Explorer acceptance against a local, deterministic API and production build."""

import importlib.util
import json
import os
import signal
import subprocess
import threading
import time
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend"
OUT = ROOT / "docs/audits/s14_2/browser"
BASE = "http://localhost:3115"
SPEC = importlib.util.spec_from_file_location("s142_fixture", FRONT / "tests/s8-3-arabic-rtl-browser-acceptance.py")
assert SPEC and SPEC.loader
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
s72 = fixture.s72

state = {"dismissed": False, "saved": False, "save_fail": False, "empty": False, "partial": False, "slow": False, "failed": False}
requests = []
rows = []
titles = [
    "Environmental and Social Specialist",
    "Technical Assistance for Green Urban Development",
    "Consulting Services for Renewable Energy Study",
    "Waste Management Infrastructure",
    "Public service digital transformation",
    "Unverified source opportunity",
]
sources = ["world_bank", "giz", "adb", "ebrd", "uzex", "unlisted_source"]


def tender(index):
    return {
        **s72.tender(), "id": f"s142-tender-{index}", "title": titles[index],
        "source_system": sources[index], "external_id": f"REF-2026-{index}",
        "source_url": "https://example.invalid/tender/0" if index == 0 else ("javascript:alert(1)" if index == 5 else None),
        "summary": None if index == 5 else "Technical assistance and advisory services for a verified development opportunity.",
        "country": "Tajikistan" if index == 0 else "Uzbekistan", "sector": "Consulting Services",
        "status": "UNKNOWN" if index == 5 else "OPEN", "deadline": None if index == 5 else "2026-10-20T10:00:00Z",
        "budget": [500000, 1200000, 750000, 1500000, 0, 0][index],
        "currency": ["USD", "EUR", "USD", "EUR", "USD", ""][index],
        "is_new": index == 0, "created_at": "2026-09-19T08:00:00Z", "new_until": "2026-09-20T08:00:00Z",
    }


def recommendation(index):
    if index >= 4:
        return None
    return {
        "recommendation_id": f"s142-rec-{index}", "match_score": [92, 88, 85, 78][index],
        "rationale_summary": "Stored recommendation rationale.", "is_dismissed": state["dismissed"],
        "created_at": "2026-09-18T10:00:00Z",
    }


class Handler(fixture.Handler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        requests.append(("GET", self.path))
        if parsed.path == "/api/v1/tenders/sources/catalog":
            return self.send_json(200, [dict(source_system=source, display_name=source.replace("_", " ").title(), refresh_enabled=True, can_refresh=True) for source in sources[:4]])
        if parsed.path == "/api/v1/tenders/sources/refresh-status":
            last = {"job_id": "partial-s142", "status": "partial", "completed_at": "2026-09-19T09:00:00Z", "fetched_count": 4, "created_count": 1, "updated_count": 0, "unchanged_count": 0, "skipped_count": 0, "failed_count": 1, "documents_discovered_count": 0, "documents_queued_count": 0, "counts_authoritative": True, "fallback_used": False, "degraded": True, "terminal_reason": "partial"}
            return self.send_json(200, [dict(source_system="world_bank", display_name="World Bank", refresh_enabled=True, can_refresh=True, active_job=None, latest_terminal=last if state["partial"] else None, last_clean_completed=None, last_partial=last if state["partial"] else None, last_failure=None, activity_cursor="c0")])
        if parsed.path == "/api/v1/explorer/tenders":
            if state["slow"]:
                time.sleep(0.8)
            if state["failed"]:
                return self.send_json(503, {"detail": "fixture unavailable"})
            view = query.get("view", ["all"])[0]
            indices = [] if state["empty"] else list(range(6))
            if view == "recommended" and state["dismissed"]:
                indices = []
            if view == "dismissed" and not state["dismissed"]:
                indices = []
            if view != "all":
                indices = [i for i in indices if i < 4]
            if query.get("status", ["open"])[0] == "open":
                indices = [i for i in indices if i != 5]
            if "source" in query:
                indices = [i for i in indices if sources[i] == query["source"][0]]
            if query.get("q", [""])[0]:
                indices = [i for i in indices if query["q"][0].casefold() in titles[i].casefold()]
            if query.get("new_only", [""])[0] == "true":
                indices = [i for i in indices if i == 0]
            if query.get("status", [""])[0] == "unknown":
                indices = [i for i in indices if i == 5]
            offset = int(query.get("offset", ["0"])[0])
            items = [{"tender": tender(i), "recommendation": recommendation(i), "pursuit": {"engagement_id": "s142-engagement", "status": "SAVED", "allowed_actions": ["EVALUATE", "PREPARE_BID", "DISMISS"]} if state["saved"] and i == 0 else None} for i in indices]
            total = 61 if not state["empty"] and view == "all" and not any(key in query for key in ("source", "q", "new_only", "region")) and query.get("status", ["open"])[0] == "open" else len(items)
            return self.send_json(200, {"view": view, "items": items, "total": total, "limit": 25, "offset": offset, "counts": {"all_tenders": 61, "active_recommendations": 0 if state["dismissed"] else 4, "dismissed_recommendations": 4 if state["dismissed"] else 0}, "recommendation_availability": "AVAILABLE", "server_time": "2026-09-19T10:00:00Z"})
        return super().do_GET()

    def do_POST(self):
        requests.append(("POST", self.path))
        path = urlparse(self.path).path
        if path == "/api/v1/tenders/s142-tender-0/engagement":
            if state["save_fail"]:
                return self.send_json(503, {"detail": "fixture save failure"})
            state["saved"] = True
            return self.send_json(200, {"engagement": {"engagement_id": "s142-engagement", "engagement_status": "SAVED", "allowed_actions": ["EVALUATE", "PREPARE_BID", "DISMISS"]}})
        if path == "/api/v1/my-tenders/s142-engagement/actions/dismiss":
            state["saved"] = False
            return self.send_json(200, {"engagement": {"engagement_id": "s142-engagement", "engagement_status": "DISMISSED", "allowed_actions": ["SAVE"]}})
        if path.startswith("/api/v1/recommendations/"):
            state["dismissed"] = path.endswith("/dismiss")
            return self.send_json(200, {"status": "dismissed" if state["dismissed"] else "restored", "recommendation": recommendation(0)})
        return super().do_POST()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def case(name, fn):
    try:
        detail = fn()
        rows.append({"case": name, "status": "PASS", "detail": detail})
    except Exception as exc:
        rows.append({"case": name, "status": "FAIL", "error": str(exc)[:1200]})
    print(rows[-1]["status"], name, flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s72.State.active = False
    server = ThreadingHTTPServer(("127.0.0.1", 8115), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {**os.environ, "AUTH_SECRET": "s142-browser-secret", "AUTH_URL": BASE, "NEXTAUTH_URL": BASE, "AUTH_TRUST_HOST": "true", "NEXT_DIST_DIR": ".next-s14-2", "BACKEND_INTERNAL_URL": "http://127.0.0.1:8115/api/v1"}
    log = (OUT / "frontend.log").open("w")
    proc = subprocess.Popen(["npm.cmd" if os.name == "nt" else "npm", "run", "start", "--", "-p", "3115"], cwd=FRONT, env=env, stdout=log, stderr=log, start_new_session=True)
    js = "import {encode} from 'next-auth/jwt'; console.log(await encode({secret:'s142-browser-secret',salt:'authjs.session-token',token:{name:'Synthetic Pilot',email:'pilot@example.invalid',sub:'72000000-0000-4000-8000-000000000001',accessToken:'s72-token-a',approval_status:'approved',platform_role:'pilot_user'},maxAge:3600}));"
    token = subprocess.check_output(["node.exe" if os.name == "nt" else "node", "--input-type=module", "-e", js], cwd=FRONT, env=env, text=True).strip()
    try:
        for _ in range(45):
            try:
                urlopen(BASE, timeout=2)
                break
            except Exception:
                time.sleep(1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            case("browser/chromium-version", lambda: browser.version)
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            context.add_cookies([{"name": "authjs.session-token", "value": token, "domain": "localhost", "path": "/", "secure": False}])
            external = []
            def route(request):
                if urlparse(request.request.url).hostname not in {"localhost", "127.0.0.1"}:
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()
            context.route("**/*", route)
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for locale in ("en", "uz", "ru", "ar"):
                s72.State.users["s72-token-a"]["ui_locale"] = locale
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    start = len(requests)
                    page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
                    if page.locator(".explorer-card").count() == 0:
                        print("DEBUG", page.url, ascii(page.locator("body").inner_text()[:900]), requests[start:][-10:], flush=True)
                    expect(page.locator(".explorer-card")).to_have_count(5)
                    key = f"{locale}-{width}"
                    page.screenshot(path=str(OUT / f"explorer-{key}.png"), full_page=True)
                    case(key + "/render", lambda: check(not errors and page.locator("h1").count() == 1, str(errors)))
                    case(key + "/overflow", lambda: check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "horizontal overflow"))
                    case(key + "/locale", lambda locale=locale: check(page.locator("html").get_attribute("lang") == locale and page.locator("html").get_attribute("dir") == ("rtl" if locale == "ar" else "ltr"), "locale/RTL mismatch"))
                    def passive(start=start):
                        calls = requests[start:]
                        check(all(method == "GET" or path.startswith("/api/v1/auth/refresh") for method, path in calls), f"write on load: {calls}")
                        check(len(calls) <= 30, f"request budget: {Counter(urlparse(p).path for _, p in calls)}")
                        return len(calls)
                    case(key + "/passive-budget", passive)
                    if locale in {"en", "ar"} and width in {390, 1440}:
                        def axe_check(key=key):
                            axe_path = Path(os.environ.get("PLASMA_AXE_PATH", str(Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "Temp/plasma-s142-qa/node_modules/axe-core/axe.min.js")))
                            page.add_script_tag(path=str(axe_path))
                            result = page.evaluate('async () => await axe.run(document, {runOnly: {type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"]}})')
                            (OUT / f"axe-{key}.json").write_text(json.dumps(result))
                            serious = [(violation["id"], len(violation["nodes"])) for violation in result["violations"] if violation["impact"] in {"serious", "critical"}]
                            check(not serious, str(serious))
                            return {"serious_critical": 0}
                        case(key + "/axe", axe_check)
            s72.State.users["s72-token-a"]["ui_locale"] = "en"
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
            case("mockup/deviations", lambda: check(page.get_by_text("Saved searches").count() == 0 and page.get_by_text("Compact").count() == 0, "unsupported controls shown"))
            case("branding/supplied-world-bank-art", lambda: check(page.locator('.explorer-card').first.locator('.explorer-source-logo img').evaluate('(img) => img.complete && img.naturalWidth === 3000 && img.getAttribute("src").endsWith("world-bank-supplied.png")'), "supplied logo not loaded"))
            case("branding/supplied-ebrd-art", lambda: check(page.locator('.explorer-card').nth(3).locator('.explorer-source-logo img').evaluate('(img) => img.complete && img.naturalWidth === 1140 && img.getAttribute("src").endsWith("ebrd-supplied.png") && Boolean(img.alt)'), "supplied EBRD logo not loaded or unnamed"))
            case("branding/logo-only", lambda: check(page.locator('.explorer-card .explorer-source-name').count() == 0, "duplicate source caption under logo"))
            case("content/no-card-description", lambda: check(page.locator('.explorer-card-summary').count() == 0 and page.locator('.explorer-card').get_by_text('Technical assistance and advisory services for a verified development opportunity.', exact=True).count() == 0, "description still shown in a tender card"))
            case("canonical/budget-values", lambda: check(
                page.locator('.explorer-card-budget').count() == 5
                and page.locator('.explorer-card-budget').nth(0).inner_text().endswith('$500,000')
                and page.locator('.explorer-card-budget').nth(1).inner_text().endswith('€1,200,000')
                and page.locator('.explorer-card-budget').nth(4).inner_text().endswith('Value not disclosed'),
                "budget values or missing-state semantics mismatch",
            ))
            case("canonical/missing-match", lambda: check(page.locator(".explorer-match").count() == 4 and page.locator(".explorer-open-source").count() == 1, "missing match/source mismatch"))
            page.goto(BASE + "/dashboard/tenders?view=all&status=unknown", wait_until="networkidle")
            case("canonical/missing-deadline-logo", lambda: check(page.locator('[data-source-logo="fallback"]').count() == 1 and page.locator('.explorer-source-name').count() == 1 and page.locator('.explorer-source-name').inner_text().strip() and page.get_by_text("Deadline unavailable").count() == 1 and page.locator(".explorer-open-source").count() == 0, "missing state mismatch"))
            page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
            case("source/safe-link", lambda: check(page.locator(".explorer-open-source").first.get_attribute("href") == "https://example.invalid/tender/0" and page.locator(".explorer-open-source").first.get_attribute("target") == "_blank", "source link unsafe"))
            def search_filters():
                page.get_by_role("searchbox").fill("Environmental")
                page.wait_for_url("**q=Environmental**")
                expect(page.locator(".explorer-card")).to_have_count(1)
                page.get_by_role("button", name="Remove Search tenders: Environmental").click()
                page.wait_for_url(lambda url: "q=" not in url)
                page.get_by_label("Source", exact=True).select_option("world_bank")
                page.wait_for_url("**source=world_bank**")
                page.get_by_label("Region / Country").select_option("Central Asia")
                page.wait_for_url("**region=Central+Asia**")
                page.locator(".explorer-active-filters").locator('button[aria-label*="World Bank"]').click()
                page.wait_for_url(lambda url: "source=" not in url and "region=" in url)
                page.get_by_role("button", name="Clear all").click()
                page.wait_for_url(lambda url: "source=" not in url and "region=" not in url)
                check(page.get_by_label("Source", exact=True).input_value() == "", "clear all failed")
            case("filters/search-chips-clear", search_filters)
            def modes():
                page.get_by_role("tab", name="Recommended 4").click()
                page.wait_for_url("**view=recommended**")
                page.get_by_role("tab", name="Dismissed 0").click()
                page.wait_for_url("**view=dismissed**")
                page.get_by_role("tab", name="All 61").click()
                page.wait_for_url("**view=all**")
                expect(page.get_by_role("tab", name="All 61")).to_have_attribute("aria-selected", "true")
                page.get_by_role("checkbox", name="New in last 24h").click()
                page.wait_for_url("**new_only=true**")
                expect(page.get_by_role("checkbox", name="New in last 24h")).to_be_checked()
                expect(page.locator(".explorer-card")).to_have_count(1)
            case("views/all-recommended-dismissed-new", modes)
            page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
            def sorting_pagination():
                page.get_by_label("Sort by").select_option("deadline_soonest")
                page.wait_for_url("**sort=deadline_soonest**")
                page.get_by_role("button", name="Next").click()
                page.wait_for_url("**page=2**")
                page.wait_for_timeout(500)
                check(any("offset=25" in path for _, path in requests[-30:]), f"unbounded/wrong page: {requests[-12:]}")
            case("results/sort-pagination", sorting_pagination)
            page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
            def bookmark():
                start = len(requests)
                first = page.locator('[data-tender-id="s142-tender-0"]')
                first.get_by_role("button", name="Save tender").click()
                expect(first.get_by_role("button", name="Unsave tender")).to_be_visible()
                first.get_by_role("button", name="Unsave tender").click()
                expect(first.get_by_role("button", name="Save tender")).to_be_visible()
                page.wait_for_timeout(300)
                writes = [path for method, path in requests[start:] if method == "POST" and not path.startswith("/api/v1/auth/")]
                check(writes == ["/api/v1/tenders/s142-tender-0/engagement", "/api/v1/my-tenders/s142-engagement/actions/dismiss"], str(writes))
            case("bookmark/save-unsave", bookmark)
            def bookmark_failure():
                state["save_fail"] = True
                try:
                    first = page.locator('[data-tender-id="s142-tender-0"]')
                    first.get_by_role("button", name="Save tender").click()
                    expect(first.get_by_role("alert")).to_contain_text("Bookmark could not be updated.")
                    expect(first.get_by_role("button", name="Save tender")).to_have_attribute("aria-pressed", "false")
                finally:
                    state["save_fail"] = False
            case("bookmark/failure-rollback", bookmark_failure)
            def recommendation_actions():
                page.get_by_role("button", name="Preview tender").first.click()
                expect(page.locator("dialog[open]")).to_be_visible()
                page.get_by_role("button", name="Dismiss recommendation").click()
                page.wait_for_timeout(300)
                check(state["dismissed"], "recommendation not dismissed")
                page.keyboard.press("Escape")
                page.goto(BASE + "/dashboard/tenders?view=dismissed", wait_until="networkidle")
                page.get_by_role("button", name="Preview tender").first.click()
                page.get_by_role("button", name="Restore recommendation").click()
                page.wait_for_timeout(300)
                check(not state["dismissed"], "recommendation not restored")
            case("recommendation/dismiss-restore", recommendation_actions)
            page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
            def empty():
                state["empty"] = True
                page.reload(wait_until="networkidle")
                expect(page.get_by_text("No tenders match these filters.")).to_be_visible()
                state["empty"] = False
            case("states/empty", empty)
            def partial():
                state["partial"] = True
                page.reload(wait_until="networkidle")
                expect(page.get_by_text("Some sources may be incomplete")).to_be_visible()
                state["partial"] = False
            case("states/partial", partial)
            def failure():
                state["failed"] = True
                page.reload(wait_until="networkidle")
                expect(page.get_by_text("Tender Explorer could not be loaded.")).to_be_visible()
                state["failed"] = False
            case("states/failure", failure)
            def initial_loading():
                state["slow"] = True
                try:
                    page.goto(BASE + "/dashboard/tenders?view=all", wait_until="domcontentloaded")
                    expect(page.locator(".explorer-results-skeleton")).to_be_visible()
                    page.screenshot(path=str(OUT / "explorer-loading.png"), full_page=True)
                    expect(page.locator(".explorer-card")).to_have_count(5)
                finally:
                    state["slow"] = False
            case("states/initial-loading", initial_loading)
            def preserve_results():
                state["slow"] = True
                try:
                    page.get_by_label("Source", exact=True).select_option("giz")
                    page.wait_for_url("**source=giz**")
                    expect(page.locator('.explorer-results[aria-busy="true"] .explorer-card')).to_have_count(5)
                    expect(page.locator(".explorer-card")).to_have_count(1)
                finally:
                    state["slow"] = False
            case("states/preserve-results-while-filtering", preserve_results)
            case("network/no-external", lambda: check(not external, str(external)))
            browser.close()
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=15)
        server.shutdown()
        log.close()
        (OUT / "results.json").write_text(json.dumps(rows, indent=2))
    passed = sum(row["status"] == "PASS" for row in rows)
    print(f"{passed}/{len(rows)} PASS")
    if passed != len(rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
