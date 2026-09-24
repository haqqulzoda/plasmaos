#!/usr/bin/env python3
"""Sprint 14.1 Dashboard acceptance against local, deterministic API fixtures."""

from __future__ import annotations

from collections import Counter
import importlib.util
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
FRONT = Path(os.environ.get("PLASMA_FRONTEND_TEST_ROOT", ROOT / "frontend"))
OUT = ROOT / "docs" / "audits" / "s14_1" / "browser"
WINDOWS_HOST = "172.25.128.1"
BASE = "http://localhost:4114"
PROBE_BASE = f"http://{WINDOWS_HOST}:4114"
MOCK_PORT = 8114
CDP_PROXY_PORT = 9469
AXE = FRONT / "node_modules" / "axe-core" / "axe.min.js"
NODE = "/mnt/c/Program Files/nodejs/node.exe"
CMD = "/mnt/c/Windows/System32/cmd.exe"
TASKKILL = "/mnt/c/Windows/System32/taskkill.exe"
POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("s141_rtl", "s8-3-arabic-rtl-browser-acceptance.py")
s72 = fixture.s72


class State:
    mode = "populated"
    opportunity_count = 4
    saved = False
    requests: list[tuple[str, str]] = []


def tender(index: int = 0, *, status: str = "OPEN", deadline: str | None = None) -> dict:
    row = dict(s72.tender())
    ids = ["active-a", "active-b", "active-c", "active-d"]
    tender_id = ids[index] if index < len(ids) else f"excluded-{index}"
    deadlines = [
        "2026-10-30T10:00:00Z",
        "2026-10-20T10:00:00Z",
        "2026-10-20T10:00:00Z",
        "2026-09-20T10:00:00Z",
    ]
    row.update(
        {
            "id": tender_id,
            "external_id": f"WB-S141-{index}",
            "canonical_source_key": "a-stable" if index == 2 else f"stable-{index}",
            "title": f"Dashboard opportunity {tender_id}",
            "status": status,
            "deadline": deadline if deadline is not None else deadlines[index % 4],
            "country": "Tajikistan",
            "region": "Central Asia",
            "category": "Consulting Services",
            "sector": "Digital services",
            "document_status": "documents_available",
            "created_at": "2026-09-10T10:00:00Z",
            "is_new": False,
            "new_until": "2026-09-11T10:00:00Z",
        }
    )
    return row


def recommendation(index: int) -> dict:
    scores = [90, 90, 90, 89]
    return {
        "recommendation_id": f"recommendation-{index}",
        "match_score": scores[index % 4],
        "rationale_summary": "Stored company relevance from the canonical Recommendation.",
        "is_dismissed": False,
        "created_at": "2026-09-12T10:00:00Z",
    }


def terminal() -> dict:
    return {
        "job_id": "s141-refresh", "status": "completed",
        "completed_at": "2026-09-15T10:24:00Z", "fetched_count": 8,
        "created_count": 2, "updated_count": 1, "unchanged_count": 5,
        "skipped_count": 0, "failed_count": 0,
        "documents_discovered_count": 0, "documents_queued_count": 0,
        "counts_authoritative": True, "fallback_used": False,
        "degraded": False, "terminal_reason": "Refresh completed",
    }


def engagement(status: str) -> dict:
    allowed = ["SAVE", "EVALUATE", "PREPARE_BID"] if status == "DISMISSED" else ["EVALUATE", "PREPARE_BID", "DISMISS"]
    return {
        "engagement_id": "engagement-s141", "tender_id": "active-c",
        "engagement_status": status, "engagement_origin": "MANUAL_SAVE",
        "engagement_created_at": "2026-09-17T10:00:00Z",
        "engagement_updated_at": "2026-09-17T10:00:00Z",
        "status_changed_at": "2026-09-17T10:00:00Z",
        "allowed_actions": allowed,
    }


class Handler(fixture.Handler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        State.requests.append(("GET", self.path))
        if State.mode == "loading" and path in {
            "/api/v1/users/me/company", "/api/v1/vault/readiness",
            "/api/v1/explorer/tenders", "/api/v1/tenders",
        }:
            time.sleep(0.8)
        if State.mode == "failure" and path in {
            "/api/v1/users/me/company", "/api/v1/vault/readiness",
            "/api/v1/explorer/tenders", "/api/v1/tenders",
        }:
            self.send_json(503, {"detail": "fixture unavailable"})
            return
        if path == "/api/v1/users/me/company":
            self.send_json(200, {
                **s72.State.company,
                "company_profile_id": "shared-company",
                "onboarding_required": False,
                "director_name": None,
            })
            return
        if path == "/api/v1/vault/readiness":
            if State.mode == "partial":
                self.send_json(503, {"detail": "readiness unavailable"})
            else:
                self.send_json(200, [])
            return
        if path == "/api/v1/explorer/tenders":
            items = [
                {
                    "tender": tender(index),
                    "recommendation": recommendation(index),
                    "pursuit": engagement("SAVED") if State.saved and index == 2 else None,
                }
                for index in range(State.opportunity_count)
            ]
            items.extend(
                [
                    {"tender": tender(4, status="CLOSED", deadline="2026-10-01T00:00:00Z"), "recommendation": recommendation(0), "pursuit": None},
                    {"tender": tender(5, status="UNKNOWN", deadline="2026-10-01T00:00:00Z"), "recommendation": recommendation(0), "pursuit": None},
                    {"tender": tender(6, deadline="2026-09-01T00:00:00Z"), "recommendation": recommendation(0), "pursuit": None},
                ]
            )
            self.send_json(200, {
                "view": "recommended", "items": items,
                "total": len(items), "limit": 100, "offset": 0,
                "counts": {"all_tenders": len(items), "active_recommendations": len(items), "dismissed_recommendations": 0},
                "recommendation_availability": "AVAILABLE",
                "server_time": "2026-09-17T10:00:00Z",
            })
            return
        if path == "/api/v1/tenders":
            self.send_json(200, [tender(0), tender(1)])
            return
        if path.endswith("/latest-analysis"):
            failed = "active-a" in path
            self.send_json(200, {
                "analysis_id": "analysis-failed" if failed else "analysis-complete",
                "analysis_status": "failed" if failed else "completed",
                "requirement_count": 8, "manual_review_count": 0,
                "coverage_metadata": {"coverage_status": "failed" if failed else "complete"},
                "created_at": "2026-09-15T08:00:00Z" if failed else "2026-09-14T08:00:00Z",
            })
            return
        if path == "/api/v1/tenders/sources/catalog":
            self.send_json(200, [{
                "source_system": "world_bank", "display_name": "World Bank",
                "refresh_enabled": True, "can_refresh": True,
            }])
            return
        if path == "/api/v1/tenders/sources/refresh-status":
            self.send_json(200, [{
                "source_system": "world_bank", "display_name": "World Bank",
                "refresh_enabled": True, "can_refresh": True, "active_job": None,
                "latest_terminal": terminal(), "last_clean_completed": terminal(),
                "last_partial": None, "last_failure": None, "activity_cursor": "s141-baseline",
            }])
            return
        if path == "/api/v1/tenders/sources/refresh-activity":
            self.send_json(200, {"events": [], "next_cursor": "s141-baseline", "has_more": False})
            return
        if path == "/api/v1/notifications/unread-count":
            self.send_json(200, {"unread_count": 0})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        State.requests.append(("POST", path))
        if path == "/api/v1/tenders/active-c/engagement":
            State.saved = True
            self.send_json(200, {"engagement": engagement("SAVED"), "created": True, "reengaged": False})
            return
        if path == "/api/v1/my-tenders/engagement-s141/actions/dismiss":
            State.saved = False
            self.send_json(200, {"engagement": engagement("DISMISSED")})
            return
        if path == "/api/v1/tenders/sources/world_bank/refresh":
            self.send_json(200, {
                "status": "queued", "source_system": "world_bank", "display_name": "World Bank",
                "job_id": "s141-requested", "created_count": 0, "updated_count": 0,
                "unchanged_count": 0, "fetched_count": 0, "skipped_count": 0,
                "rejected_count": 0, "failed_count": 0, "documents_discovered_count": 0,
                "documents_queued_count": 0, "fallback_used": False,
                "created_at": "2026-09-17T10:00:00Z", "started_at": None,
                "heartbeat_at": None, "completed_at": None, "elapsed_ms": None,
                "source_newest_published_at": None, "source_oldest_published_at": None,
                "source_age_days": None, "execution_health": None,
                "freshness_health": None, "coverage_health": None,
                "last_updated": None, "reused": False, "message": "queued",
            })
            return
        super().do_POST()


def session_token(salt: str) -> str:
    source = f"""import {{encode}} from 'next-auth/jwt'; console.log(await encode({{secret:'s141-browser-secret',salt:'{salt}',token:{{name:'Synthetic Pilot',email:'pilot@example.invalid',sub:'72000000-0000-4000-8000-000000000001',accessToken:'s72-token-a',approval_status:'approved',platform_role:'pilot_user'}},maxAge:3600}}));"""
    return subprocess.check_output(
        [NODE, "--input-type=module", "-e", source],
        cwd=FRONT, text=True,
    ).strip()


def wait_for_frontend() -> None:
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            urlopen(PROBE_BASE, timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("frontend did not start")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s72.State.active = False
    s72.State.onboarding_required = False
    s72.State.users["s72-token-a"].update(ui_locale="en", default_analysis_language="uz")
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env_command = (
        "set AUTH_SECRET=s141-browser-secret&& "
        "set AUTH_URL=http://localhost:4114&& set NEXTAUTH_URL=http://localhost:4114&& "
        "set AUTH_TRUST_HOST=true&& set NEXT_DIST_DIR=.next-s141-acceptance&& "
        f"set BACKEND_INTERNAL_URL=http://127.0.0.1:{MOCK_PORT}/api/v1&& "
        "C:\\Progra~1\\nodejs\\npm.cmd run start -- -p 4114"
    )
    log = (OUT / "frontend.log").open("w", encoding="utf-8")
    frontend = subprocess.Popen(
        [CMD, "/d", "/s", "/c", env_command], cwd=FRONT,
        stdout=log, stderr=log, start_new_session=True,
    )
    results: list[dict] = []
    external: list[str] = []
    page_errors: list[str] = []
    dashboard_cookie_headers: list[str | None] = []
    cdp_proxy = None
    browser_pid = None

    def record(case: str, evidence: object = None) -> None:
        results.append({"case": case, "status": "PASS", "evidence": evidence})
        print("PASS", case, flush=True)

    try:
        wait_for_frontend()
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_name = f"s141-browser-profile-{os.getpid()}"
        profile = rf"C:\Users\acer\AppData\Local\Temp\{profile_name}"
        profile_path = Path("/mnt/c/Users/acer/AppData/Local/Temp") / profile_name
        launch = (
            f"$process = Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--no-first-run','--remote-debugging-port=0','--user-data-dir={profile}','about:blank' -PassThru; $process.Id"
        )
        browser_pid = int(subprocess.check_output(
            [POWERSHELL, "-NoProfile", "-Command", launch], text=True,
        ).strip().splitlines()[-1])
        port_file = profile_path / "DevToolsActivePort"
        deadline = time.time() + 60
        while time.time() < deadline and not port_file.exists():
            time.sleep(0.2)
        if not port_file.exists():
            raise RuntimeError("Chromium did not publish DevToolsActivePort")
        cdp_port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        proxy_command = (
            "cd /d D:\\projects\\plasmaos\\frontend && "
            f"node tests\\cdp-port-forward.mjs {CDP_PROXY_PORT} {cdp_port}"
        )
        cdp_proxy = subprocess.Popen(
            [CMD, "/d", "/s", "/c", proxy_command],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urlopen(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}/json/version", timeout=2)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("CDP proxy did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}"
            )
            context = browser.contexts[0]
            context.clear_cookies()
            context.add_cookies([
                {
                    "name": "__Secure-authjs.session-token",
                    "value": session_token("__Secure-authjs.session-token"),
                    "url": "https://localhost:4114", "secure": True,
                    "httpOnly": True, "sameSite": "Lax",
                },
                {
                    "name": "authjs.session-token",
                    "value": session_token("authjs.session-token"),
                    "url": BASE, "secure": False,
                    "httpOnly": True, "sameSite": "Lax",
                },
            ])
            assert any(
                cookie["name"] == "authjs.session-token"
                for cookie in context.cookies(BASE)
            ), "browser session cookie was not installed"
            context.set_default_timeout(8000)

            def route_handler(route) -> None:
                host = urlparse(route.request.url).hostname
                if urlparse(route.request.url).path == "/dashboard":
                    dashboard_cookie_headers.append(route.request.header_value("cookie"))
                if host not in {WINDOWS_HOST, "localhost", "127.0.0.1"}:
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", route_handler)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(8000)
            page.emulate_media(reduced_motion="reduce")
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(BASE + "/api/auth/session", wait_until="domcontentloaded")
            session_payload = json.loads(page.locator("body").inner_text())
            assert session_payload.get("accessToken") == "s72-token-a", (
                "Auth.js rejected the synthetic browser session", session_payload
            )
            headings = {
                "en": "Dashboard", "uz": "Boshqaruv paneli",
                "ru": "Панель управления", "ar": "لوحة التحكم",
            }

            State.mode = "populated"
            State.opportunity_count = 4
            for locale in ["en", "uz", "ru", "ar"]:
                s72.State.users["s72-token-a"]["ui_locale"] = locale
                for width in [320, 390, 768, 1440]:
                    page.set_viewport_size({"width": width, "height": 1000})
                    before = len(State.requests)
                    response = page.goto(BASE + "/dashboard", wait_until="networkidle")
                    if not page.url.startswith(BASE + "/dashboard"):
                        raise AssertionError(
                            f"synthetic session was rejected; cookies={dashboard_cookie_headers[-2:]}; "
                            f"backend requests={s72.State.requests[-5:]}"
                        )
                    expect(page.get_by_role("heading", name=headings[locale], exact=True)).to_be_visible()
                    assert response and response.status == 200
                    assert page.locator("html").get_attribute("dir") == ("rtl" if locale == "ar" else "ltr")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    assert page.locator(".dashboard-opportunity").count() == 3
                    assert page.locator('[data-source-logo="official"]').count() == 3
                    assert "match score" not in page.locator(".customer-page").inner_text().lower()
                    assert page.locator(".dashboard-active").count() == 1
                    assert page.locator(".dashboard-readiness").count() == 1
                    assert page.locator(".dashboard-attention").count() == 1
                    assert page.locator(".dashboard-profile").count() == 1
                    assert page.locator(".dashboard-analyses").count() == 1
                    if width < 1200:
                        tops = page.locator(
                            ".dashboard-active,.dashboard-attention,.dashboard-analyses,.dashboard-readiness,.dashboard-profile"
                        ).evaluate_all("els => els.map(el => el.getBoundingClientRect().top)")
                        assert tops == sorted(tops), tops
                    else:
                        active = page.locator(".dashboard-active").bounding_box()
                        readiness = page.locator(".dashboard-readiness").bounding_box()
                        profile = page.locator(".dashboard-profile").bounding_box()
                        assert active and readiness and active["x"] != readiness["x"]
                        assert profile and abs(profile["y"] - (readiness["y"] + readiness["height"] + 16)) <= 1
                        assert page.locator(".shell-context").count() == 0
                    writes = [path for method, path in State.requests[before:] if method != "GET" and "/auth/" not in path]
                    assert writes == [], writes
                    assert len(State.requests[before:]) <= 30, Counter(urlparse(path).path for _, path in State.requests[before:])
                    page.screenshot(path=str(OUT / f"dashboard-{locale}-{width}.png"), full_page=True)
                    record(f"responsive/{locale}/{width}")
                    if locale in {"en", "ar"} and width in {390, 1440}:
                        page.add_script_tag(path=str(AXE))
                        axe = page.evaluate("async () => await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})")
                        bad = [item for item in axe["violations"] if item["impact"] in {"serious", "critical"}]
                        (OUT / f"dashboard-{locale}-{width}-axe.json").write_text(json.dumps(axe), encoding="utf-8")
                        assert not bad, [(item["id"], len(item["nodes"])) for item in bad]
                        record(f"axe/{locale}/{width}", {"serious_critical": 0})

            s72.State.users["s72-token-a"]["ui_locale"] = "en"
            page.set_viewport_size({"width": 1440, "height": 1000})
            for count in [0, 1, 3, 4]:
                State.opportunity_count = count
                page.goto(BASE + "/dashboard", wait_until="networkidle")
                expected = min(count, 3)
                assert page.locator(".dashboard-opportunity").count() == expected
                if count == 0:
                    expect(page.get_by_text("No active opportunities right now", exact=True)).to_be_visible()
                record(f"shortlist/{count}", {"shown": expected})
            State.opportunity_count = 4
            page.reload(wait_until="networkidle")
            ids = page.locator(".dashboard-opportunity").evaluate_all("els => els.map(el => el.dataset.tenderId)")
            assert ids == ["active-c", "active-b", "active-a"], ids
            record("ranking-and-exclusion", ids)

            State.mode = "partial"
            page.reload(wait_until="networkidle")
            expect(page.get_by_text("Some supporting data is unavailable. Sections that loaded successfully are shown.", exact=True)).to_be_visible()
            assert page.locator(".dashboard-opportunity").count() == 3
            record("partial-preserves-sections")

            State.mode = "loading"
            page.goto(BASE + "/dashboard", wait_until="domcontentloaded")
            expect(page.locator(".dashboard-skeleton")).to_be_visible()
            expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible(timeout=10000)
            record("geometry-matched-loading")

            State.mode = "failure"
            page.goto(BASE + "/dashboard", wait_until="networkidle")
            expect(page.get_by_text("Dashboard could not be loaded", exact=True)).to_be_visible()
            record("full-error")

            State.mode = "populated"
            State.saved = False
            page.goto(BASE + "/dashboard", wait_until="networkidle")
            before = len(State.requests)
            save = page.get_by_role("button", name="Save tender", exact=True).first
            save.click()
            expect(page.get_by_role("button", name="Unsave tender", exact=True).first).to_be_visible()
            page.get_by_role("button", name="Unsave tender", exact=True).first.click()
            expect(page.get_by_role("button", name="Save tender", exact=True).first).to_be_visible()
            writes = [path for method, path in State.requests[before:] if method == "POST" and "/auth/" not in path]
            assert writes == [
                "/api/v1/tenders/active-c/engagement",
                "/api/v1/my-tenders/engagement-s141/actions/dismiss",
            ], writes
            record("save-unsave", writes)

            before = len(State.requests)
            page.get_by_role("button", name="Source refresh", exact=True).click()
            page.get_by_role("button", name="Refresh World Bank", exact=True).click()
            page.wait_for_timeout(250)
            refresh_writes = [path for method, path in State.requests[before:] if method == "POST"]
            assert refresh_writes == ["/api/v1/tenders/sources/world_bank/refresh"], refresh_writes
            record("canonical-refresh-owner", refresh_writes)

            assert not external, external
            assert not page_errors, page_errors
            record("zero-external-requests")
            record("zero-page-errors")
            browser.close()
    finally:
        (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        server.shutdown()
        subprocess.run(
            [TASKKILL, "/PID", str(frontend.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if cdp_proxy is not None:
            subprocess.run(
                [TASKKILL, "/PID", str(cdp_proxy.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        if browser_pid is not None:
            subprocess.run(
                [TASKKILL, "/PID", str(browser_pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            [
                POWERSHELL, "-NoProfile", "-Command",
                "Get-NetTCPConnection -LocalPort 4114,9469 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log.close()

    expected = 16 + 4 + 4 + 1 + 1 + 1 + 1 + 1 + 1 + 2
    assert len(results) == expected, (len(results), expected)
    print(f"Sprint 14.1 Dashboard browser acceptance: {len(results)}/{expected} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
