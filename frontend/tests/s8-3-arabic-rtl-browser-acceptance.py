#!/usr/bin/env python3
"""Formal real-Chromium Sprint 8.3 Arabic/RTL acceptance (100+ explicit checks)."""

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
spec = importlib.util.spec_from_file_location(
    "s82_browser", HERE / "s8-2-analysis-language-browser-acceptance.py"
)
assert spec and spec.loader
s82 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s82)
s72 = s82.s72

BASE_URL = "http://localhost:3114"
MIXED_TITLE = "English tender — مناقصة عربية — Тендер"


def mixed_tender() -> dict:
    return {**s72.tender(), "title": MIXED_TITLE}


class Handler(s82.Handler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/tenders/s72-tender":
            self.send_json(200, mixed_tender())
            return
        if path == "/api/v1/explorer/tenders":
            row = mixed_tender()
            self.send_json(200, {
                "view": "all",
                "items": [{
                    "tender": row,
                    "recommendation": {
                        "recommendation_id": "rec-s83", "match_score": 88,
                        "rationale_summary": "English analysis rationale remains original.",
                        "is_dismissed": False, "created_at": "2026-09-02T10:00:00Z",
                    },
                    "pursuit": None,
                }],
                "total": 1, "limit": 25, "offset": 0,
                "counts": {"all_tenders": 1, "active_recommendations": 1, "dismissed_recommendations": 0},
                "recommendation_availability": "AVAILABLE", "server_time": "2026-09-02T10:00:00Z",
            })
            return
        super().do_GET()

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/users/me/preferences":
            super().do_PATCH()
            return
        user = self.current_user()
        if not user:
            self.send_json(401, {"detail": "unauthorized"})
            return
        payload = self.body()
        if not payload:
            self.send_json(422, {"detail": "preference_required"})
            return
        if "default_analysis_language" in payload:
            language = payload["default_analysis_language"]
            if language not in {"en", "uz", "ru"}:
                self.send_json(422, {"detail": "unsupported_analysis_language"})
                return
            user["default_analysis_language"] = language
        if "ui_locale" in payload:
            locale = payload["ui_locale"]
            if locale not in {"en", "uz", "ru", "ar"}:
                self.send_json(422, {"detail": "unsupported_ui_locale"})
                return
            user["ui_locale"] = locale
        self.send_json(200, {
            "ui_locale": user.get("ui_locale"),
            "default_analysis_language": user.get("default_analysis_language"),
        })

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/auth/refresh":
            token = s72.bearer(self)
            user = self.current_user()
            if not user or user["blocked"]:
                self.send_json(401, {"detail": "Account disabled"})
                return
            is_admin = token == "s72-token-admin"
            self.send_json(200, {
                "access_token": token,
                "token_type": "bearer",
                "approval_status": "approved",
                "platform_role": "admin" if is_admin else "pilot_user",
                "is_admin": is_admin,
                "onboarding_required": False,
                "company_profile_id": "shared-company",
                "company_approval_status": "approved",
            })
            return
        super().do_POST()


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s72-browser-secret&& "
        "set NEXTAUTH_URL=http://localhost:3114&& "
        f"set BACKEND_INTERNAL_URL=http://127.0.0.1:{s72.MOCK_PORT}/api/v1&& "
        "set NEXT_DIST_DIR=.next-s83-browser&& npm run dev -- -p 3114"
    )
    return subprocess.Popen(
        [s72.CMD, "/d", "/s", "/c", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def admin_session_cookie() -> str:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s72-browser-secret&& "
        "set S72_USER_LABEL=admin&& set S72_ACCESS_TOKEN=s72-token-admin&& "
        "set S72_PLATFORM_ROLE=admin&& set S72_IS_ADMIN=1&& "
        "node tests\\make-s72-session.mjs"
    )
    result = subprocess.run(
        [s72.CMD, "/d", "/s", "/c", command],
        text=True, capture_output=True, check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def main() -> int:
    s72.State.users["s72-token-a"].update({"ui_locale": "en", "default_analysis_language": "uz"})
    s72.State.users["s72-token-admin"] = {
        "id": "user-admin", "ui_locale": "ar", "default_analysis_language": "en",
        "auth_version": 61, "blocked": False,
    }
    s72.State.onboarding_required = False
    server = ThreadingHTTPServer(("127.0.0.1", s72.MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    passed: list[str] = []
    browser = None
    cdp_port = None
    cdp_proxy = None
    page = None

    def check(condition: bool, name: str) -> None:
        if not condition and page is not None:
            print(json.dumps({
                "failed_check": name, "url": page.url,
                "body_excerpt": page.locator("body").inner_text()[:1800],
            }, ensure_ascii=False, indent=2))
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
        "ar": [
            ("", "لوحة التحكم"), ("tenders?view=all", "مستكشف المناقصات"),
            ("tenders/s72-tender", "المتطلبات والمستندات"), ("my-tenders", "مناقصاتي"),
            ("bid-preparation", "إعداد العطاء"), ("readiness-vault", "سجل الجاهزية"),
            ("settings", "ملف الشركة"), ("tenders/s72-tender/compliance", "تحليل الامتثال"),
        ],
    }

    try:
        s72.base.wait_for_url(f"http://{s72.WINDOWS_HOST}:3114")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_name = f"s83-browser-profile-{os.getpid()}"
        profile = rf"C:\Users\acer\AppData\Local\Temp\{profile_name}"
        profile_path = (
            Path(os.environ["LOCALAPPDATA"]) / "Temp" / profile_name
            if os.name == "nt"
            else Path("/mnt/c/Users/acer/AppData/Local/Temp") / profile_name
        )
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
            f"'--no-first-run','--remote-debugging-port=0','--user-data-dir={profile}','about:blank'"
        )
        subprocess.run([s72.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        port_file = profile_path / "DevToolsActivePort"
        deadline = time.time() + 60
        while time.time() < deadline and not port_file.exists():
            time.sleep(0.2)
        if not port_file.exists():
            raise RuntimeError("Chromium did not publish DevToolsActivePort")
        cdp_port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        proxy_command = (
            f"cd /d D:\\projects\\plasmaos\\frontend && "
            f"node tests\\cdp-port-forward.mjs {s72.CDP_PROXY_PORT} {cdp_port}"
        )
        cdp_proxy = subprocess.Popen(
            [s72.CMD, "/d", "/s", "/c", proxy_command],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        s72.base.wait_for_url(f"http://{s72.WINDOWS_HOST}:{s72.CDP_PROXY_PORT}/json/version")

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://{s72.WINDOWS_HOST}:{s72.CDP_PROXY_PORT}"
            )
            context = browser.contexts[0]
            context.clear_cookies()
            s72.add_session(context, "a")
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1366, "height": 900})
            page.goto(f"{BASE_URL}/dashboard/settings", wait_until="networkidle")

            selector = page.locator('[data-language-selector="settings"]')
            check(selector.get_by_role("radio").count() == 4, "activation selector exposes four UI locales")
            check(selector.get_by_text("العربية", exact=True).count() == 1, "activation selector exposes Arabic natively")
            analysis = page.get_by_role("combobox", name="Analysis language", exact=True)
            check(analysis.locator("option").count() == 3, "default analysis selector retains three languages")
            check("العربية" not in analysis.locator("option").all_inner_texts(), "Arabic remains absent from default analysis selector")
            route_before = page.url
            selector.get_by_text("العربية", exact=True).click()
            page.locator('html[lang="ar"][dir="rtl"]').wait_for()
            check(s72.State.users["s72-token-a"]["ui_locale"] == "ar", "Arabic UI preference persists canonically")
            check(page.url == route_before, "Arabic switch preserves route")
            check(page.locator('html[lang="ar"]').count() == 1, "Arabic switch sets root lang")
            check(page.locator('html[dir="rtl"]').count() == 1, "Arabic switch sets root dir")
            cookie = next((item for item in context.cookies() if item["name"] == "plasma_ui_locale"), None)
            check(cookie is not None and cookie["value"] == "ar", "Arabic presentation cookie is canonical")
            page.reload(wait_until="networkidle")
            check(page.locator('html[lang="ar"][dir="rtl"]').count() == 1, "reload first render remains Arabic RTL")
            new_tab = context.new_page()
            new_tab.goto(f"{BASE_URL}/dashboard/settings", wait_until="networkidle")
            check(new_tab.locator('html[lang="ar"][dir="rtl"]').count() == 1, "new tab inherits persisted Arabic RTL")
            new_tab.close()
            context.add_cookies([{"name": "plasma_ui_locale", "value": "en", "url": BASE_URL}])
            page.reload(wait_until="networkidle")
            check(page.locator('html[lang="ar"][dir="rtl"]').count() == 1, "stored preference outranks stale cookie")
            check(s72.switch_locale(page, "en")["ok"] and page.locator('html[lang="en"][dir="ltr"]').count() == 1, "Arabic to English restores LTR")
            check(s72.switch_locale(page, "ar")["ok"] and page.locator('html[lang="ar"][dir="rtl"]').count() == 1, "English to Arabic restores RTL")

            anonymous = browser.new_context(
                extra_http_headers={"Accept-Language": "ru;q=0.3, ar-SA;q=0.9, en;q=0.5"}
            )
            anon_page = anonymous.new_page()
            anon_page.goto(BASE_URL, wait_until="domcontentloaded")
            initial_direction = anon_page.locator("html").get_attribute("dir")
            anon_page.wait_for_load_state("networkidle")
            check(anon_page.locator('html[lang="ar"]').count() == 1, "ar-SA Accept-Language resolves Arabic pre-auth")
            check(anon_page.locator('html[dir="rtl"]').count() == 1, "pre-auth Arabic is server RTL")
            check(initial_direction == "rtl" and anon_page.locator("html").get_attribute("dir") == "rtl", "Arabic hydration has no direction flip")
            check(anon_page.get_by_text("أهلاً بعودتك", exact=True).count() == 1, "auth surface renders Arabic copy")
            anonymous.close()

            # 96 explicit checks: localized marker, root locale/direction, and bounded viewport
            # for eight P0/P1 surfaces in all four released locales.
            for locale, surfaces in locale_surfaces.items():
                assert s72.switch_locale(page, locale)["ok"]
                expected_dir = "rtl" if locale == "ar" else "ltr"
                for route, marker in surfaces:
                    page.goto(f"{BASE_URL}/dashboard/{route}", wait_until="networkidle")
                    marker_ok = page.get_by_text(marker, exact=True).count() >= 1
                    check(marker_ok, f"{locale} {route or 'dashboard'} localized customer marker")
                    check(
                        page.locator(f'html[lang="{locale}"][dir="{expected_dir}"]').count() == 1,
                        f"{locale} {route or 'dashboard'} root lang and direction",
                    )
                    check(
                        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
                        f"{locale} {route or 'dashboard'} desktop has no page overflow",
                    )

            assert s72.switch_locale(page, "ar")["ok"]
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle")
            title = page.get_by_text(MIXED_TITLE, exact=True).first
            check(title.count() == 1, "mixed English Arabic Russian tender title remains exact")
            check(title.evaluate("node => node.tagName === 'BDI' && node.dir === 'auto'"), "mixed tender title uses auto bidi isolation")
            source = page.get_by_text("World Bank", exact=True).first
            check(source.evaluate("node => node.tagName === 'BDI' && node.dir === 'auto'"), "World Bank source name uses auto bidi isolation")
            external_id = page.get_by_text("S72-ORIGINAL", exact=True).first
            check(external_id.evaluate("node => node.tagName === 'BDI' && node.dir === 'ltr'"), "tender identifier is isolated LTR")
            search = page.get_by_placeholder("البحث عن المناقصات")
            check(search.get_attribute("dir") == "auto", "Arabic Explorer search input uses auto direction")
            search.fill("water مياه")
            page.wait_for_timeout(500)
            check("q=water+%D9%85%D9%8A%D8%A7%D9%87" in page.url, "Arabic Explorer search keeps canonical query encoding")

            page.goto(f"{BASE_URL}/dashboard/tenders/s72-tender/compliance", wait_until="networkidle")
            run_select = page.get_by_role("combobox", name="لغة التحليل", exact=True)
            check(run_select.locator("option").count() == 3, "Arabic Compliance analysis selector retains EN UZ RU")
            check("العربية" not in run_select.locator("option").all_inner_texts(), "Arabic Compliance selector keeps Arabic analysis gated")
            for code in ("en", "uz", "ru"):
                run_select.select_option(code)
                page.get_by_role("button", name=re.compile("بدء تحليل الامتثال|تحليل مرة أخرى")).click()
                headline = s82.localized(code)[0]
                page.get_by_text(headline, exact=True).wait_for()
                check(s82.S82State.latest["user-a"]["analysis_language"] == code, f"Arabic UI runs {code.upper()} analysis")
                analysis_node = page.get_by_text(headline, exact=True).first
                check(analysis_node.evaluate("node => node.closest('[dir]')?.getAttribute('dir') === 'ltr'"), f"{code.upper()} analysis remains an LTR content island")
            quote = page.get_by_text(s82.SOURCE_QUOTE, exact=True).last
            check(quote.count() == 1, "Russian source evidence remains exact in Arabic UI")
            check(quote.evaluate("node => node.closest('[dir]')?.getAttribute('dir') === 'auto'"), "source evidence uses auto direction")
            ar_run_status = page.evaluate("""async () => {
              const session = await (await fetch('/api/auth/session')).json();
              return (await fetch('/api/v1/tenders/s72-tender/analyze?analysis_language=ar', {
                method: 'POST', headers: {Authorization: `Bearer ${session.accessToken}`}
              })).status;
            }""")
            check(ar_run_status == 422, "hand-crafted Arabic analysis request remains rejected")
            ar_default_status = page.evaluate("""async () => {
              const session = await (await fetch('/api/auth/session')).json();
              return (await fetch('/api/v1/users/me/preferences', {
                method: 'PATCH', headers: {'Content-Type':'application/json', Authorization:`Bearer ${session.accessToken}`},
                body: JSON.stringify({default_analysis_language:'ar'})
              })).status;
            }""")
            check(ar_default_status == 422, "hand-crafted Arabic default remains rejected")

            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                for route in (
                    "tenders?view=all", "tenders/s72-tender", "my-tenders",
                    "bid-preparation", "readiness-vault", "settings",
                    "tenders/s72-tender/compliance",
                ):
                    page.goto(f"{BASE_URL}/dashboard/{route}", wait_until="networkidle")
                    check(
                        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
                        f"Arabic {route} width {width} has no page overflow",
                    )

            second_user = browser.new_context(viewport={"width": 1366, "height": 900})
            s72.add_session(second_user, "b")
            second_user_page = second_user.new_page()
            second_user_page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
            check(second_user_page.locator('html[lang="ru"][dir="ltr"]').count() == 1, "Russian User B does not receive Arabic User A SSR state")
            check(page.locator('html[lang="ar"][dir="rtl"]').count() == 1, "Arabic User A remains isolated from Russian User B")
            second_user.close()

            admin = browser.new_context(viewport={"width": 1366, "height": 900})
            admin.add_cookies([{
                "name": "authjs.session-token", "value": admin_session_cookie(),
                "url": BASE_URL, "httpOnly": True, "sameSite": "Lax",
            }])
            admin_page = admin.new_page()
            admin_page.goto(f"{BASE_URL}/admin", wait_until="networkidle")
            check(admin_page.locator('html[lang="ar"][dir="rtl"]').count() == 1, "authorized Admin keeps shared Arabic root shell")
            check(admin_page.locator('[data-admin-ltr-island][lang="en"][dir="ltr"]').count() == 1, "dedicated Admin content is explicit English LTR")
            check(admin_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "Admin LTR island has no page overflow")
            admin.close()

            check(s72.State.domain_writes == [], "locale presentation remains passive for domain state")
            check(len(passed) >= 100, "formal suite executes at least 100 explicit acceptance checks")
            total = len(passed)
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        subprocess.run([s72.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        if cdp_proxy is not None:
            subprocess.run([s72.TASKKILL, "/PID", str(cdp_proxy.pid), "/T", "/F"], capture_output=True, check=False)
        s72.base.kill_listener(s72.CDP_PROXY_PORT)
        s72.base.kill_listener(3114)
        if cdp_port is not None:
            s72.base.kill_listener(cdp_port)

    print(json.dumps({"passed": total, "results": passed}, ensure_ascii=False, indent=2))
    print(f"{total}/{total} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
