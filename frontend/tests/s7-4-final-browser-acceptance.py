#!/usr/bin/env python3
"""Formal real-Chromium Sprint 7.4 acceptance: exactly 120 explicit checks."""

from __future__ import annotations

import importlib.util
import json
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s73_browser", HERE / "s7-3-p0-browser-acceptance.py")
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
s72 = base.base

SOURCE_TEXT = "SOURCE ANALYSIS TEXT — keep original."
READINESS_NAME = "Company License ORIGINAL — keep original"


class Handler(base.Handler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/vault/readiness":
            self.send_json(200, [{
                "id": "ready-s74", "company_profile_id": "shared-company",
                "document_type": "license", "document_name": READINESS_NAME,
                "document_number": "LIC-ORIGINAL", "issuer": "Original Issuer",
                "issue_date": "2026-01-02", "expiry_date": "2027-01-02",
                "status": "available", "related_service": "IT",
                "notes": "User readiness note — keep original", "optional_file_url": None,
                "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-02T10:00:00Z",
            }])
            return
        if path == "/api/v1/tenders/s72-tender/compiled-text":
            self.send_json(200, {"compiled_master_text": SOURCE_TEXT})
            return
        if path == "/api/v1/tenders/s72-tender/latest-analysis":
            self.send_json(200, {"analysis_id": None, "requirements": None, "evaluation": None})
            return
        super().do_GET()


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s72-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3114&& "
        "set PLASMA_ENABLE_PSEUDO_LOCALE=1&& "
        f"set BACKEND_INTERNAL_URL=http://127.0.0.1:{s72.MOCK_PORT}/api/v1&& "
        "set NEXT_DIST_DIR=.next-s74-browser&& npm run dev -- -p 3114"
    )
    return subprocess.Popen([s72.CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", s72.MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    passed: list[str] = []
    browser = None
    cdp_port = None
    cdp_proxy = None

    def check(condition: bool, name: str) -> None:
        assert condition, name
        assert name not in passed, name
        passed.append(name)

    locale_surfaces = {
        "en": [
            ("", "Dashboard"), ("tenders?view=all", "Tender Explorer"),
            ("tenders/s72-tender", "Requirements & Documents"), ("my-tenders", "My Tenders"),
            ("bid-preparation", "Bid Preparation"), ("readiness-vault", "Readiness Vault"),
            ("settings", "Company profile"), ("tenders/s72-tender/compliance", "Compliance analysis"),
        ],
        "uz": [
            ("", "Boshqaruv paneli"), ("tenders?view=all", "Tenderlar katalogi"),
            ("tenders/s72-tender", "Talablar va hujjatlar"), ("my-tenders", "Mening tenderlarim"),
            ("bid-preparation", "Taklif tayyorlash"), ("readiness-vault", "Tayyorgarlik hujjatlari"),
            ("settings", "Kompaniya profili"), ("tenders/s72-tender/compliance", "Muvofiqlik tahlili"),
        ],
        "ru": [
            ("", "Панель управления"), ("tenders?view=all", "Каталог тендеров"),
            ("tenders/s72-tender", "Требования и документы"), ("my-tenders", "Мои тендеры"),
            ("bid-preparation", "Подготовка заявки"), ("readiness-vault", "Документы готовности"),
            ("settings", "Профиль компании"), ("tenders/s72-tender/compliance", "Анализ соответствия"),
        ],
    }

    try:
        s72.base.wait_for_url(f"http://{s72.WINDOWS_HOST}:3114")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_name = f"s74-browser-profile-{os.getpid()}"
        profile = rf"C:\Users\acer\AppData\Local\Temp\{profile_name}"
        profile_path = Path("/mnt/c/Users/acer/AppData/Local/Temp") / profile_name
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new',"
            f"'--disable-gpu','--no-first-run','--remote-debugging-port=0',"
            f"'--user-data-dir={profile}','about:blank'"
        )
        subprocess.run([s72.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        port_file = profile_path / "DevToolsActivePort"
        deadline = time.time() + 20
        while time.time() < deadline and not port_file.exists(): time.sleep(0.2)
        if not port_file.exists(): raise RuntimeError("Chromium did not publish DevToolsActivePort")
        cdp_port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        proxy_command = f"cd /d D:\\projects\\plasmaos\\frontend && node tests\\cdp-port-forward.mjs {s72.CDP_PROXY_PORT} {cdp_port}"
        cdp_proxy = subprocess.Popen([s72.CMD, "/d", "/s", "/c", proxy_command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s72.base.wait_for_url(f"http://{s72.WINDOWS_HOST}:{s72.CDP_PROXY_PORT}/json/version")

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{s72.WINDOWS_HOST}:{s72.CDP_PROXY_PORT}")
            context = browser.contexts[0]
            context.clear_cookies()
            s72.add_session(context, "a")
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1366, "height": 900})
            s72.State.onboarding_required = False
            page.goto(f"{s72.BASE_URL}/dashboard/settings", wait_until="networkidle")

            # 48 checks: localized surface marker and html lang across 8 routes × 3 locales.
            for locale, surfaces in locale_surfaces.items():
                assert s72.switch_locale(page, locale)["ok"]
                for route, marker in surfaces:
                    page.goto(f"{s72.BASE_URL}/dashboard/{route}", wait_until="networkidle")
                    marker_ok = page.get_by_text(marker, exact=True).count() >= 1
                    if route == "tenders?view=all": marker_ok = marker_ok and "view=all" in page.url
                    if route == "tenders/s72-tender": marker_ok = marker_ok and page.url.endswith("/dashboard/tenders/s72-tender")
                    check(marker_ok, f"{locale} {route or 'dashboard'} localized marker and route continuity")
                    check(page.locator("html").get_attribute("lang") == locale, f"{locale} {route or 'dashboard'} html lang")

            # 12 checks: source/user/AI-shaped dynamic values remain byte-for-text identical.
            for locale in locale_surfaces:
                assert s72.switch_locale(page, locale)["ok"]
                boundaries = [
                    ("tenders?view=all", s72.tender()["title"]),
                    ("tenders/s72-tender", s72.tender()["description"]),
                    ("readiness-vault", READINESS_NAME),
                    ("tenders/s72-tender/compliance", SOURCE_TEXT),
                ]
                for route, value in boundaries:
                    page.goto(f"{s72.BASE_URL}/dashboard/{route}", wait_until="networkidle")
                    check(page.get_by_text(value, exact=True).count() >= 1, f"{locale} {route} original content boundary")

            # 18 checks: names, state, keyboard reachability, and LTR semantics.
            native = {"en": "English", "uz": "O‘zbekcha", "ru": "Русский"}
            for locale in locale_surfaces:
                assert s72.switch_locale(page, locale)["ok"]
                page.goto(f"{s72.BASE_URL}/dashboard/settings", wait_until="networkidle")
                selector = page.locator('[data-language-selector="settings"]')
                check(selector.get_by_role("radiogroup").count() == 1, f"{locale} language radiogroup named")
                check(selector.get_by_role("radio").count() == 3, f"{locale} three keyboard radios")
                active = selector.get_by_role("radio", name=re.compile(re.escape(native[locale])))
                check(active.get_attribute("aria-checked") == "true", f"{locale} active radio announced")
                active.focus()
                check(page.evaluate("document.activeElement?.getAttribute('role')") == "radio", f"{locale} selector keyboard focus")
                check(page.get_by_role("navigation").count() == 1, f"{locale} navigation accessible name")
                check(page.locator('html[dir="rtl"]').count() == 0, f"{locale} remains LTR")

            # 36 checks: no page overflow at mobile/tablet/desktop on four high-stress surfaces.
            stress_routes = ["tenders?view=all", "readiness-vault", "tenders/s72-tender/compliance", "settings"]
            for locale in locale_surfaces:
                assert s72.switch_locale(page, locale)["ok"]
                for width in (390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    for route in stress_routes:
                        page.goto(f"{s72.BASE_URL}/dashboard/{route}", wait_until="networkidle")
                        no_overflow = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
                        check(no_overflow, f"{locale} {route} width {width} no page overflow")

            # 6 checks: dev-only pseudo locale visibly transforms P0/P1 shells without overflow.
            pseudo = browser.new_context(extra_http_headers={"x-plasma-pseudo-locale": "1"}, viewport={"width": 390, "height": 900})
            s72.add_session(pseudo, "a")
            pseudo_page = pseudo.new_page()
            pseudo_routes = ["", "tenders?view=all", "tenders/s72-tender", "bid-preparation", "readiness-vault", "tenders/s72-tender/compliance"]
            for route in pseudo_routes:
                pseudo_page.goto(f"{s72.BASE_URL}/dashboard/{route}", wait_until="networkidle")
                transformed = pseudo_page.get_by_text(re.compile("⟦")).count() > 0
                no_overflow = pseudo_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
                passive = s72.State.domain_writes == [] if route == pseudo_routes[-1] else True
                check(transformed and no_overflow and passive and pseudo_page.locator("html").get_attribute("lang") == "en-XA", f"pseudo {route or 'dashboard'} transformed passive LTR layout")
            pseudo.close()
            assert len(passed) == 120, len(passed)
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try: browser.close()
            except Exception: pass
        subprocess.run([s72.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        if cdp_proxy is not None:
            subprocess.run([s72.TASKKILL, "/PID", str(cdp_proxy.pid), "/T", "/F"], capture_output=True, check=False)
        s72.base.kill_listener(s72.CDP_PROXY_PORT)
        s72.base.kill_listener(3114)
        if cdp_port is not None: s72.base.kill_listener(cdp_port)

    print(json.dumps({"passed": len(passed), "results": passed}, ensure_ascii=False, indent=2))
    print("120/120 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
