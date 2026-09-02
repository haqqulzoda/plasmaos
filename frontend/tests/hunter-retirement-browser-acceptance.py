#!/usr/bin/env python3
"""Real Chromium final Sprint 6 acceptance: S6.3 70 + S6.4 redirect 5."""

from __future__ import annotations

import importlib.util
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "s63_browser",
    HERE / "unified-explorer-browser-acceptance.py",
)
assert spec and spec.loader
s63 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s63)

REDIRECT_CASES = [
    "Hunter primary navigation absent",
    "direct Hunter bookmark redirects without legacy UI flash",
    "Hunter redirect uses unified network and causes zero domain writes",
    "no-profile Hunter bookmark reaches PROFILE_REQUIRED Recommended",
    "Hunter redirect browser history is sane and dead UI remains absent",
]

CDP_PORT = 9242
CDP_PROXY_PORT = 9243


def run_redirect_cases() -> list[str]:
    s63.reset()
    s63.MOCK_PORT = 8113
    server = ThreadingHTTPServer(("127.0.0.1", s63.MOCK_PORT), s63.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = s63.start_frontend()
    browser = None
    passed: list[str] = []

    def check(condition: bool, name: str) -> None:
        assert condition, name
        passed.append(name)

    try:
        s63.base.wait_for_url(f"http://{s63.WINDOWS_HOST}:3112")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile = r"C:\Users\acer\AppData\Local\Temp\s64-browser-profile"
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList "
            f"'--headless=new','--disable-gpu','--remote-debugging-port={CDP_PORT}',"
            f"'--user-data-dir={profile}','about:blank'"
        )
        subprocess.run([s63.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        subprocess.run(
            [
                r"/mnt/c/Windows/System32/netsh.exe", "interface", "portproxy", "add", "v4tov4",
                f"listenport={CDP_PROXY_PORT}", "listenaddress=0.0.0.0",
                f"connectport={CDP_PORT}", "connectaddress=127.0.0.1",
            ],
            check=True,
        )
        s63.base.wait_for_url(
            f"http://{s63.WINDOWS_HOST}:{CDP_PROXY_PORT}/json/version"
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://{s63.WINDOWS_HOST}:{CDP_PROXY_PORT}"
            )
            context = browser.contexts[0]
            context.add_cookies([{
                "name": "authjs.session-token",
                "value": s63.session_cookie(),
                "url": s63.BASE_URL,
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})

            page.goto(f"{s63.BASE_URL}/dashboard", wait_until="networkidle")
            nav = page.get_by_role("navigation", name="Dashboard navigation").inner_text()
            check("Tenders" in nav and "Hunter" not in nav, REDIRECT_CASES[0])

            observed_urls: list[str] = []
            page.on("request", lambda request: observed_urls.append(request.url))
            s63.State.request_log = []
            s63.State.writes = []
            page.goto(f"{s63.BASE_URL}/dashboard/hunter?unknown=ignored", wait_until="networkidle")
            body = page.locator("body").inner_text()
            selected = page.get_by_role("tab", name="Recommended", exact=False)
            check(
                urlparse_path(page.url) == "/dashboard/tenders"
                and "view=recommended" in page.url
                and selected.get_attribute("aria-selected") == "true"
                and "Hunter Feed" not in body,
                REDIRECT_CASES[1],
            )
            domain_paths = [
                path for method, path in s63.State.request_log
                if method == "GET" and path.startswith("/api/v1/")
                and path not in {"/api/v1/users/me", "/api/v1/users/me/access-status"}
            ]
            check(
                set(domain_paths).issubset({
                    "/api/v1/explorer/tenders",
                    "/api/v1/tenders/sources/catalog",
                    "/api/v1/tenders/sources/refresh-status",
                    "/api/v1/tenders/sources/refresh-activity",
                })
                and "/api/v1/explorer/tenders" in domain_paths
                and not any("/api/v1/hunter" in url for url in observed_urls)
                and not s63.State.writes,
                REDIRECT_CASES[2],
            )

            s63.State.profile_required = True
            page.goto(f"{s63.BASE_URL}/dashboard/hunter", wait_until="networkidle")
            profile_body = page.locator("body").inner_text()
            check(
                "Complete your company profile" in profile_body
                and "view=recommended" in page.url
                and "scanning the market" not in profile_body,
                REDIRECT_CASES[3],
            )

            s63.State.profile_required = False
            page.goto(f"{s63.BASE_URL}/dashboard", wait_until="networkidle")
            page.goto(f"{s63.BASE_URL}/dashboard/hunter", wait_until="networkidle")
            page.go_back(wait_until="networkidle")
            back_ok = urlparse_path(page.url) == "/dashboard"
            page.go_forward(wait_until="networkidle")
            forward_body = page.locator("body").inner_text()
            check(
                back_ok
                and urlparse_path(page.url) == "/dashboard/tenders"
                and "view=recommended" in page.url
                and "Hunter Feed" not in forward_body,
                REDIRECT_CASES[4],
            )
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        subprocess.run(
            [s63.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            [
                r"/mnt/c/Windows/System32/netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                f"listenport={CDP_PROXY_PORT}", "listenaddress=0.0.0.0",
            ],
            capture_output=True,
            check=False,
        )
        s63.base.kill_listener(3112)
        s63.base.kill_listener(CDP_PORT)
    return passed


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).path


def main() -> int:
    s63.main()
    redirect_results = run_redirect_cases()
    assert redirect_results == REDIRECT_CASES
    print(json.dumps({
        "sprint_6_3_cases": 70,
        "sprint_6_4_redirect_cases": [
            {"case": case, "result": "passed"} for case in redirect_results
        ],
        "passed": 75,
    }, indent=2))
    print("75/75 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
