#!/usr/bin/env python3
"""S1 browser check: the Opportunities coverage strip (en/ru/ar, 1440/390) and the legacy redirects.

Windows-native (no WSL): a mock API on 127.0.0.1:8131, a production build in .next-s1,
`next start` on :3131 and a minted Auth.js session. Screenshots go to the directory given
as the first argument (default: ./s1-screenshots).

    python tests/s1-outreach-browser.py [screenshot-dir]
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MOCK_PORT, APP_PORT = 8131, 3131
BASE = f"http://localhost:{APP_PORT}"
SECRET = "s1-outreach-browser-secret"
DIST = ".next-s1"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "s1-screenshots")

CATALOG = [
    {"source_system": "uzex", "display_name": "UzEx", "refresh_enabled": True, "can_refresh": True},
    {"source_system": "world_bank", "display_name": "World Bank", "refresh_enabled": True, "can_refresh": True},
    {"source_system": "giz", "display_name": "GIZ", "refresh_enabled": True, "can_refresh": True},
    {"source_system": "ebrd", "display_name": "EBRD", "refresh_enabled": True, "can_refresh": True},
]
LAST_SUCCESS = {"uzex": "2026-10-10T06:15:00Z", "world_bank": "2026-10-10T05:00:00Z", "giz": "2026-10-09T21:40:00Z", "ebrd": None}


def iso_after(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def status_items() -> list[dict]:
    return [{**source, "active_job": None, "latest_terminal": None, "last_clean_completed": None, "last_partial": None,
             "last_failure": None, "scheduled_cadence_seconds": 21600, "last_success_at": LAST_SUCCESS[source["source_system"]],
             "last_success_partial": source["source_system"] == "giz", "stale": source["source_system"] == "ebrd",
             "activity_cursor": "c0"} for source in CATALOG]


def tender(index: int) -> dict:
    source = ["world_bank", "uzex", "giz", "ebrd"][index % 4]
    return {"tender": {
        "id": f"s1-tender-{index}", "external_id": f"S1-{index}", "source_system": source, "canonical_source_key": f"{source}:{index}",
        "source_url": "https://example.invalid/tender", "title": f"Consulting services for water supply design {index}",
        "buyer": "Public Buyer", "budget": None, "currency": None, "deadline": iso_after(86400 * 20),
        "publication_date": iso_after(-86400 * 2), "country": "Uzbekistan", "region": "Central Asia", "sector": "Water",
        "status": "OPEN", "category": "Consulting", "document_status": "documents_available", "document_count": 1,
        "created_at": iso_after(-86400), "is_new": False, "new_until": None,
    }, "recommendation": None, "pursuit": None}


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
        path = self.path.split("?", 1)[0]
        if path == "/api/v1/users/me":
            return self.send_json(200, {"id": "s1-user", "email": "pilot@example.invalid", "name": "Synthetic Pilot"})
        if path == "/api/v1/users/me/access-status":
            return self.send_json(200, {"company_profile_id": "profile", "company_name": "Acme", "onboarding_required": False,
                                        "onboarding_completed": True, "user_approval_status": "approved",
                                        "company_approval_status": "approved", "platform_role": "pilot_user",
                                        "access_allowed": True, "state": "approved"})
        if path == "/api/v1/tenders/sources/catalog":
            return self.send_json(200, CATALOG)
        if path == "/api/v1/tenders/sources/refresh-status":
            return self.send_json(200, status_items())
        if path == "/api/v1/tenders/sources/refresh-activity":
            return self.send_json(200, {"events": [], "next_cursor": "c0", "has_more": False})
        if path == "/api/v1/explorer/tenders":
            rows = [tender(index) for index in range(8)]
            return self.send_json(200, {"view": "all", "items": rows, "total": len(rows), "limit": 25, "offset": 0,
                                        "counts": {"all_tenders": len(rows), "active_recommendations": 0, "dismissed_recommendations": 0},
                                        "recommendation_availability": "AVAILABLE", "server_time": iso_after(0)})
        if path == "/api/v1/my-tenders":
            return self.send_json(200, {"items": [], "total": 0, "limit": 25, "offset": 0, "counts": {
                "active": 0, "all": 0, "saved": 0, "evaluating": 0, "preparing": 0, "submitted": 0, "won": 0, "lost": 0, "dismissed": 0}})
        return self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        if self.path.startswith("/api/v1/auth/refresh"):
            return self.send_json(200, {"access_token": "s1-token", "token_type": "bearer", "approval_status": "approved",
                                        "platform_role": "pilot_user", "is_admin": False})
        return self.send_json(404, {"detail": "not found"})


def run(command: str, env: dict) -> None:
    subprocess.run(command, cwd=ROOT, env=env, shell=True, check=True)


def session_token(env: dict) -> str:
    script = ("import {encode} from 'next-auth/jwt'; console.log(await encode({secret: process.env.AUTH_SECRET, "
              "salt: 'authjs.session-token', token: {name: 'Synthetic Pilot', email: 'pilot@example.invalid', "
              "sub: '51000000-0000-4000-8000-000000000001', accessToken: 's1-token', approval_status: 'approved', "
              "platform_role: 'pilot_user', is_admin: false}, maxAge: 3600}));")
    return subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=env, capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {**os.environ, "AUTH_SECRET": SECRET, "AUTH_URL": BASE, "NEXTAUTH_URL": BASE, "AUTH_TRUST_HOST": "true",
           "NEXT_DIST_DIR": DIST, "BACKEND_INTERNAL_URL": f"http://127.0.0.1:{MOCK_PORT}/api/v1",
           "NEXT_PUBLIC_API_URL": "/api/v1", "NEXT_TELEMETRY_DISABLED": "1"}
    if os.environ.get("S1_SKIP_BUILD") != "1":
        run("npx next build", env)
    app = subprocess.Popen(f"npx next start -p {APP_PORT}", cwd=ROOT, env=env, shell=True)
    problems: list[str] = []
    try:
        for _ in range(60):
            try:
                urlopen(BASE + "/", timeout=2)
                break
            except Exception:
                time.sleep(1)
        token = session_token(env)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for locale in ("en", "ru", "ar"):
                for width, height in ((1440, 1000), (390, 844)):
                    context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
                    context.add_cookies([
                        {"name": "authjs.session-token", "value": token, "domain": "localhost", "path": "/"},
                        {"name": "plasma_ui_locale", "value": locale, "domain": "localhost", "path": "/"},
                    ])
                    page = context.new_page()
                    page.goto(BASE + "/dashboard/tenders", wait_until="networkidle")
                    strip = page.locator("[data-coverage-strip]")
                    strip.wait_for(timeout=15000)
                    sources = strip.locator("[data-coverage-source]").evaluate_all("els => els.map(e => e.dataset.coverageSource)")
                    if sources != ["uzex", "world_bank", "giz", "ebrd", "adb-consulting"]:
                        problems.append(f"{locale}@{width}: sources {sources}")
                    refreshed = strip.locator("[data-coverage-refreshed=true]").count()
                    if refreshed != 3:
                        problems.append(f"{locale}@{width}: {refreshed} sources show a last successful refresh, expected 3")
                    if page.evaluate("document.documentElement.scrollWidth") > width:
                        problems.append(f"{locale}@{width}: horizontal overflow")
                    page.screenshot(path=str(OUT / f"opportunities-coverage-{locale}-{width}.png"), full_page=False)
                    strip.screenshot(path=str(OUT / f"coverage-strip-{locale}-{width}.png"))
                    context.close()
            context = browser.new_context()
            context.add_cookies([{"name": "authjs.session-token", "value": token, "domain": "localhost", "path": "/"}])
            page = context.new_page()
            redirects = {
                "/dashboard/bids": "/dashboard/my-tenders", "/dashboard/proposals": "/dashboard/my-tenders",
                "/dashboard/bid-preparation": "/dashboard/my-tenders", "/dashboard/workspace": "/dashboard/my-tenders",
                "/dashboard/readiness-vault": "/dashboard/settings/readiness",
                "/bids": "/dashboard/my-tenders", "/proposals": "/dashboard/my-tenders", "/bid-preparation": "/dashboard/my-tenders",
                "/workspace": "/dashboard/my-tenders", "/readiness-vault": "/dashboard/settings/readiness",
            }
            for source, target in redirects.items():
                page.goto(BASE + source, wait_until="domcontentloaded")
                try:  # inside the streamed dashboard layout the redirect completes on the client
                    page.wait_for_url(lambda url: url.split("?", 1)[0].endswith(target), timeout=15000)
                except Exception:
                    pass
                landed = page.url.replace(BASE, "").split("?", 1)[0]
                print(f"redirect {source:30} -> {landed}")
                if landed != target:
                    problems.append(f"{source} landed on {landed}, expected {target}")
            browser.close()
    finally:
        subprocess.run(f"taskkill /F /T /PID {app.pid}", shell=True, capture_output=True)
        server.shutdown()
    for problem in problems:
        print("FAIL:", problem)
    print("PASS" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
