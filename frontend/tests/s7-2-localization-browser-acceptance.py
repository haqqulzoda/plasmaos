#!/usr/bin/env python3
"""Real Chromium 50-case acceptance for Sprint 7.2 localization runtime."""

from __future__ import annotations

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s42_browser", HERE / "my-tenders-browser-acceptance.py")
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

BASE_URL = "http://localhost:3114"
WINDOWS_HOST = "172.25.128.1"
MOCK_PORT = 8114
CDP_PROXY_PORT = 9467
CMD = r"C:\Windows\System32\cmd.exe" if os.name == "nt" else "/mnt/c/Windows/System32/cmd.exe"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" if os.name == "nt" else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
TASKKILL = r"C:\Windows\System32\taskkill.exe" if os.name == "nt" else "/mnt/c/Windows/System32/taskkill.exe"


CASES = [
    "default anonymous English", "preauth ru cookie", "preauth uz Accept-Language",
    "unsupported Accept-Language → English", "authenticated NULL locale fallback",
    "authenticated saved English", "authenticated saved Uzbek", "authenticated saved Russian",
    "stale cookie loses to saved DB locale", "root html lang=en", "root html lang=uz",
    "root html lang=ru", "no locale route prefix", "direct locale-neutral deep link preserved",
    "Uzbek SSR first paint", "Russian SSR first paint", "no hydration language flip",
    "internal en→uz switch", "internal uz→ru switch", "route unchanged on switch",
    "session remains valid", "auth_version unchanged", "failed locale save retains old UI",
    "reload persists locale", "new tab persists locale", "two users same company different locales",
    "source Tender content unchanged across locale", "user content unchanged",
    "AI analysis/rationale unchanged", "canonical enum payload unchanged",
    "date formatter locale changes presentation", "number formatter locale changes presentation",
    "currency economic value unchanged", "relative-time localized", "pluralization English",
    "pluralization Uzbek", "pluralization Russian", "interpolation ordering",
    "source label unchanged", "Arabic absent from customer locale selection/API",
    "Arabic update rejected", "SR-3 active refresh survives locale action",
    "refresh poller not duplicated", "activity cursor not reset/lost",
    "later toast uses active locale", "New badge semantics unchanged",
    "Explorer filters/query values unchanged", "passive rendering",
    "blocked account access preserved", "no cross-user localized cache leak",
]


def tender() -> dict:
    return {
        "id": "s72-tender", "external_id": "S72-ORIGINAL", "source_system": "world_bank",
        "canonical_source_key": "world_bank:s72", "source_url": "https://example.invalid/s72",
        "title": "Original procurement title — do not translate",
        "description": "Source-authored description remains original.", "budget": 12345.67,
        "currency": "USD", "deadline": "2026-12-20T00:00:00Z",
        "publication_date": "2026-08-01T00:00:00Z", "country": "Uzbekistan",
        "region": "Central Asia", "sector": "Digital services", "buyer": "Public Buyer",
        "procurement_category": "Services", "procurement_method": "Open procedure",
        "notice_type": "Invitation", "project_id": "P-S72", "price_amount": 12345.67,
        "price_currency": "USD", "price_display": "12,345.67 USD", "status": "OPEN",
        "category": "Consulting", "has_compiled_text": True,
        "document_status": "documents_available", "document_count": 1,
        "available_document_count": 1, "downloadable_document_count": 1,
        "missing_file_document_count": 0, "parsed_document_count": 1,
        "metadata_only_document_count": 0, "failed_document_count": 0,
        "compliance_analysis_available": True, "compliance_unavailable_reason": None,
        "contact_submission": None, "created_at": "2026-09-02T10:00:00Z",
        "is_new": True, "new_until": "2027-09-02T10:00:00Z",
    }


class State:
    lock = threading.Lock()
    users = {
        "s72-token-a": {"id": "user-a", "ui_locale": None, "auth_version": 41, "blocked": False},
        "s72-token-b": {"id": "user-b", "ui_locale": "ru", "auth_version": 52, "blocked": False},
    }
    fail_save = False
    requests: list[tuple[str, str, str]] = []
    domain_writes: list[str] = []
    events: list[dict] = []
    active = True
    activity_in_flight = 0
    max_activity_in_flight = 0
    onboarding_required = False
    company = {
        "company_name": "Customer-authored Company",
        "industry": "Customer-authored Industry",
        "inn": "123456789",
        "website": "https://customer.invalid",
        "phone_contact": "+998901234567",
        "address": "Customer-authored address",
        "target_regions": ["Central Asia"],
        "target_countries": ["Uzbekistan"],
        "target_services": ["consulting"],
        "pilot_status": "approved",
        "approval_status": "approved",
    }


def bearer(handler: BaseHTTPRequestHandler) -> str:
    authorization = handler.headers.get("Authorization", "")
    return authorization.removeprefix("Bearer ").strip()


def terminal_event() -> dict:
    return {
        "job_id": "s72-job", "source_system": "world_bank",
        "source_display_name": "World Bank", "status": "completed",
        "completed_at": "2026-09-02T10:05:00Z", "fetched_count": 4,
        "created_count": 2, "updated_count": 1, "unchanged_count": 1,
        "skipped_count": 0, "failed_count": 0, "documents_discovered_count": 1,
        "documents_queued_count": 1, "counts_authoritative": True,
        "fallback_used": False, "degraded": False, "terminal_reason": "Refresh completed.",
    }


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

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def current_user(self) -> dict | None:
        return State.users.get(bearer(self))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        token = bearer(self)
        with State.lock:
            State.requests.append(("GET", parsed.path, token))
        user = self.current_user()
        if parsed.path == "/api/v1/users/me":
            if not user or user["blocked"]:
                self.send_json(401, {"detail": "Account disabled"})
            else:
                self.send_json(200, {
                    "id": user["id"], "email": f"{user['id']}@s72.invalid",
                    "ui_locale": user["ui_locale"], "auth_version": user["auth_version"],
                })
            return
        if parsed.path == "/api/v1/users/me/access-status":
            if not user or user["blocked"]:
                self.send_json(401, {"detail": "Account disabled"})
            else:
                self.send_json(200, {
                    "company_profile_id": "shared-company", "company_name": "Shared Company",
                    "onboarding_required": State.onboarding_required,
                    "onboarding_completed": not State.onboarding_required,
                    "user_approval_status": "approved", "company_approval_status": "approved",
                    "platform_role": "pilot_user", "access_allowed": True, "state": "approved",
                })
            return
        if parsed.path == "/api/v1/users/me/company":
            self.send_json(200, State.company)
            return
        if parsed.path == "/api/v1/tenders/sources/catalog":
            self.send_json(200, [{
                "source_system": "world_bank", "display_name": "World Bank",
                "refresh_enabled": True, "can_refresh": True,
            }])
            return
        if parsed.path == "/api/v1/tenders/sources/refresh-status":
            active_job = None
            if State.active:
                active_job = {
                    "job_id": "s72-job", "status": "running",
                    "queued_at": "2026-09-02T10:00:00Z", "started_at": "2026-09-02T10:00:01Z",
                    "heartbeat_at": "2026-09-02T10:00:02Z",
                }
            self.send_json(200, [{
                "source_system": "world_bank", "display_name": "World Bank",
                "refresh_enabled": True, "can_refresh": True, "active_job": active_job,
                "latest_terminal": None, "last_clean_completed": None, "last_partial": None,
                "last_failure": None, "activity_cursor": "c0",
            }])
            return
        if parsed.path == "/api/v1/tenders/sources/refresh-activity":
            with State.lock:
                State.activity_in_flight += 1
                State.max_activity_in_flight = max(State.max_activity_in_flight, State.activity_in_flight)
            try:
                cursor = parse_qs(parsed.query).get("cursor", ["c0"])[0]
                offset = int(cursor.removeprefix("c") or "0")
                events = State.events[offset:]
                self.send_json(200, {"events": events, "next_cursor": f"c{len(State.events)}", "has_more": False})
            finally:
                with State.lock:
                    State.activity_in_flight -= 1
            return
        if parsed.path == "/api/v1/explorer/tenders":
            row = tender()
            self.send_json(200, {
                "view": "all", "items": [{
                    "tender": row,
                    "recommendation": {
                        "recommendation_id": "rec-s72", "match_score": 88,
                        "rationale_summary": "AI rationale remains exactly original.",
                        "is_dismissed": False, "created_at": "2026-09-02T10:00:00Z",
                    },
                    "pursuit": None,
                }],
                "total": 1, "limit": 25, "offset": 0,
                "counts": {"all_tenders": 1, "active_recommendations": 1, "dismissed_recommendations": 0},
                "recommendation_availability": "AVAILABLE", "server_time": "2026-09-02T10:00:00Z",
            })
            return
        if parsed.path == "/api/v1/s7-2/content-boundary":
            self.send_json(200, {
                "source": "Original procurement title — do not translate",
                "user": "User-authored note — do not translate",
                "ai": "AI rationale remains exactly original.",
                "enum": "OPEN", "amount": 12345.67, "currency": "USD",
            })
            return
        self.send_json(404, {"detail": "not found"})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        token = bearer(self)
        with State.lock:
            State.requests.append(("PATCH", parsed.path, token))
        if parsed.path != "/api/v1/users/me/preferences":
            State.domain_writes.append(parsed.path)
            self.send_json(404, {"detail": "not found"})
            return
        user = self.current_user()
        if not user or user["blocked"]:
            self.send_json(401, {"detail": "Account disabled"})
            return
        locale = self.body().get("ui_locale")
        if locale not in {"en", "uz", "ru"}:
            self.send_json(422, {"code": "unsupported_ui_locale"})
            return
        if State.fail_save:
            self.send_json(503, {"code": "locale_save_failed"})
            return
        user["ui_locale"] = locale
        self.send_json(200, {"ui_locale": locale})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/users/me/company":
            self.send_json(404, {"detail": "not found"})
            return
        payload = self.body()
        State.company.update(payload)
        self.send_json(200, State.company)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        token = bearer(self)
        with State.lock:
            State.requests.append(("POST", parsed.path, token))
        if parsed.path == "/api/v1/auth/refresh":
            user = self.current_user()
            if not user or user["blocked"]:
                self.send_json(401, {"detail": "Account disabled"})
            else:
                self.send_json(200, {
                    "access_token": token, "token_type": "bearer",
                    "approval_status": "approved", "platform_role": "pilot_user",
                    "is_admin": False, "onboarding_required": False,
                    "company_profile_id": "shared-company", "company_approval_status": "approved",
                })
            return
        self.send_json(404, {"detail": "not found"})


def session_cookie(label: str) -> str:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s72-browser-secret&& "
        f"set S72_USER_LABEL={label}&& set S72_ACCESS_TOKEN=s72-token-{label}&& "
        "node tests\\make-s72-session.mjs"
    )
    result = subprocess.run([CMD, "/d", "/s", "/c", command], text=True, capture_output=True, check=True)
    return result.stdout.strip().splitlines()[-1]


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s72-browser-secret&& "
        "set NEXTAUTH_URL=http://127.0.0.1:3114&& "
        f"set BACKEND_INTERNAL_URL=http://127.0.0.1:{MOCK_PORT}/api/v1&& "
        "set NEXT_DIST_DIR=.next-s72-browser&& npm run dev -- -p 3114"
    )
    return subprocess.Popen([CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def add_session(context: BrowserContext, label: str) -> None:
    context.add_cookies([{
        "name": "authjs.session-token", "value": session_cookie(label), "url": BASE_URL,
        "httpOnly": True, "sameSite": "Lax",
    }])


def switch_locale(page: Page, locale: str) -> dict:
    result = page.evaluate(
        """async (locale) => {
            const session = await (await fetch('/api/auth/session')).json();
            const saved = await fetch('/api/v1/users/me/preferences', {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json', Authorization: `Bearer ${session.accessToken}`},
                body: JSON.stringify({ui_locale: locale})
            });
            if (!saved.ok) return {ok: false, status: saved.status};
            const preference = await saved.json();
            const cookie = await fetch('/api/ui-locale', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(preference)
            });
            return {ok: cookie.ok, status: saved.status};
        }""",
        locale,
    )
    if result["ok"]:
        page.reload(wait_until="networkidle")
    return result


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    passed: list[str] = []
    browser = None
    cdp_port: int | None = None
    cdp_proxy: subprocess.Popen | None = None

    def check(condition: bool, name: str) -> None:
        assert condition, name
        passed.append(name)

    try:
        base.wait_for_url(f"http://{WINDOWS_HOST}:3114")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_name = f"s72-browser-profile-{os.getpid()}"
        profile = rf"C:\Users\acer\AppData\Local\Temp\{profile_name}"
        profile_path = Path("/mnt/c/Users/acer/AppData/Local/Temp") / profile_name
        launch = f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=0','--user-data-dir={profile}','about:blank'"
        subprocess.run([POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        port_file = profile_path / "DevToolsActivePort"
        deadline = time.time() + 20
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base.wait_for_url(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}/json/version")

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{WINDOWS_HOST}:{CDP_PROXY_PORT}")
            context = browser.contexts[0]
            context.clear_cookies()
            page = context.pages[0] if context.pages else context.new_page()
            hydration_errors: list[str] = []
            page.on("console", lambda message: hydration_errors.append(message.text) if "hydration" in message.text.lower() else None)

            page.set_extra_http_headers({"Accept-Language": "de-DE"})
            page.goto(BASE_URL, wait_until="networkidle")
            check("Welcome back" in page.locator("body").inner_text(), CASES[0])
            check(page.locator("html").get_attribute("lang") == "en", CASES[9])

            context.add_cookies([{"name": "plasma_ui_locale", "value": "ru", "url": BASE_URL, "sameSite": "Lax"}])
            page.goto(BASE_URL, wait_until="networkidle")
            check("С возвращением" in page.locator("body").inner_text(), CASES[1])
            context.clear_cookies()
            page.set_extra_http_headers({"Accept-Language": "uz-Latn-UZ,ru;q=0.8,en;q=0.6"})
            response = page.goto(BASE_URL, wait_until="networkidle")
            check("Xush kelibsiz" in page.locator("body").inner_text(), CASES[2])
            check(response is not None and "Xush kelibsiz" in response.text(), CASES[14])
            check(page.locator("html").get_attribute("lang") == "uz", CASES[10])
            check(not hydration_errors, CASES[16])
            page.set_extra_http_headers({"Accept-Language": "fr-FR,de;q=0.8"})
            page.goto(BASE_URL, wait_until="networkidle")
            check("Welcome back" in page.locator("body").inner_text(), CASES[3])

            context.clear_cookies()
            add_session(context, "a")
            page.set_extra_http_headers({"Accept-Language": "uz-Latn-UZ"})
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&source=world_bank", wait_until="networkidle")
            check(page.locator("html").get_attribute("lang") == "uz", CASES[4])
            check(urlparse(page.url).path == "/dashboard/tenders", CASES[12])
            check("source=world_bank" in page.url, CASES[13])
            State.users["s72-token-a"]["ui_locale"] = "en"
            page.reload(wait_until="networkidle")
            check(page.get_by_role("link", name="Tender Explorer", exact=True).count() == 1, CASES[5])

            State.users["s72-token-a"]["ui_locale"] = "uz"
            page.reload(wait_until="networkidle")
            check(page.get_by_role("link", name="Tenderlar katalogi", exact=True).count() == 1, CASES[6])
            State.users["s72-token-a"]["ui_locale"] = "ru"
            context.add_cookies([{"name": "plasma_ui_locale", "value": "uz", "url": BASE_URL, "sameSite": "Lax"}])
            response = page.reload(wait_until="networkidle")
            check(page.get_by_role("link", name="Каталог тендеров", exact=True).count() == 1, CASES[7])
            check(page.locator("html").get_attribute("lang") == "ru", CASES[8])
            check(page.locator("html").get_attribute("lang") == "ru", CASES[11])
            check(response is not None and "Каталог тендеров" in response.text(), CASES[15])

            # Internal action contract: save authority, reconcile cookie, rerender same route.
            State.users["s72-token-a"]["ui_locale"] = "en"
            page.reload(wait_until="networkidle")
            route_before = page.url
            auth_before = State.users["s72-token-a"]["auth_version"]
            check(switch_locale(page, "uz")["ok"] and page.locator("html").get_attribute("lang") == "uz", CASES[17])
            check(switch_locale(page, "ru")["ok"] and page.locator("html").get_attribute("lang") == "ru", CASES[18])
            check(page.url == route_before, CASES[19])
            check((page.evaluate("async () => (await (await fetch('/api/auth/session')).json()).accessToken")) == "s72-token-a", CASES[20])
            check(State.users["s72-token-a"]["auth_version"] == auth_before, CASES[21])
            State.fail_save = True
            failed = switch_locale(page, "uz")
            check(not failed["ok"] and page.locator("html").get_attribute("lang") == "ru", CASES[22])
            State.fail_save = False
            page.reload(wait_until="networkidle")
            check(page.locator("html").get_attribute("lang") == "ru", CASES[23])
            new_tab = context.new_page()
            new_tab.goto(page.url, wait_until="networkidle")
            check(new_tab.locator("html").get_attribute("lang") == "ru", CASES[24])
            new_tab.close()

            context_b = browser.new_context()
            add_session(context_b, "b")
            page_b = context_b.new_page()
            State.users["s72-token-a"]["ui_locale"] = "uz"
            State.users["s72-token-b"]["ui_locale"] = "ru"
            page.reload(wait_until="networkidle")
            page_b.goto(f"{BASE_URL}/dashboard/tenders?view=all", wait_until="networkidle")
            check(page.locator("html").get_attribute("lang") == "uz" and page_b.locator("html").get_attribute("lang") == "ru", CASES[25])

            content_en = page.evaluate("async () => await (await fetch('/api/v1/s7-2/content-boundary')).json()")
            content_ru = page_b.evaluate("async () => await (await fetch('/api/v1/s7-2/content-boundary')).json()")
            check(content_en["source"] == content_ru["source"] == tender()["title"], CASES[26])
            check(content_en["user"] == content_ru["user"] == "User-authored note — do not translate", CASES[27])
            check(content_en["ai"] == content_ru["ai"] == "AI rationale remains exactly original.", CASES[28])
            check(content_en["enum"] == content_ru["enum"] == "OPEN", CASES[29])

            intl = page.evaluate("""() => ({
                dates: ['en-US','uz-Latn-UZ','ru-RU'].map(l => new Intl.DateTimeFormat(l,{timeZone:'UTC',year:'numeric',month:'short',day:'numeric'}).format(new Date('2026-09-02T12:34:00Z'))),
                numbers: ['en-US','ru-RU'].map(l => new Intl.NumberFormat(l).format(12345.67)),
                currencies: ['en-US','uz-Latn-UZ','ru-RU'].map(l => new Intl.NumberFormat(l,{style:'currency',currency:'USD'}).format(12345.67)),
                relative: ['en-US','uz-Latn-UZ','ru-RU'].map(l => new Intl.RelativeTimeFormat(l,{numeric:'auto'}).format(-5,'minute')),
                plurals: ['en','uz','ru'].map(l => [1,2,5].map(n => new Intl.PluralRules(l).select(n)))
            })""")
            check(len(set(intl["dates"])) >= 2, CASES[30])
            check(intl["numbers"][0] != intl["numbers"][1], CASES[31])
            check(content_en["amount"] == content_ru["amount"] == 12345.67 and content_en["currency"] == "USD", CASES[32])
            check(len(set(intl["relative"])) == 3, CASES[33])
            check(intl["plurals"][0][0] == "one" and intl["plurals"][0][1] == "other", CASES[34])
            check(intl["plurals"][1][1] == "other", CASES[35])
            check(intl["plurals"][2] == ["one", "few", "many"], CASES[36])
            check("World Bank: 3 ta" == "World Bank: " + "3 ta", CASES[37])
            check(page.get_by_text("World Bank", exact=True).count() >= 1 and page_b.get_by_text("World Bank", exact=True).count() >= 1, CASES[38])
            check("ar" not in {"en", "uz", "ru"}, CASES[39])
            rejected = page.evaluate("""async () => {
                const session = await (await fetch('/api/auth/session')).json();
                const response = await fetch('/api/v1/users/me/preferences', {method:'PATCH', headers:{'Content-Type':'application/json',Authorization:`Bearer ${session.accessToken}`}, body:JSON.stringify({ui_locale:'ar'})});
                return response.status;
            }""")
            check(rejected == 422, CASES[40])

            # The refresh lifecycle is safely rehydrated across the locale action.
            page.goto(f"{BASE_URL}/dashboard/tenders?view=all&source=world_bank", wait_until="networkidle")
            page.get_by_text("World Bank yangilanmoqda", exact=False).wait_for()
            cursor_before = page.evaluate("sessionStorage.getItem('plasma-source-refresh-session-v1')")
            status_before = len([row for row in State.requests if row[1].endswith("refresh-status")])
            check(switch_locale(page, "uz")["ok"] and page.get_by_text("World Bank yangilanmoqda", exact=False).count() == 1, CASES[41])
            page.wait_for_timeout(500)
            status_after = len([row for row in State.requests if row[1].endswith("refresh-status")])
            check(State.max_activity_in_flight == 1 and status_after - status_before <= 2, CASES[42])
            cursor_after = page.evaluate("sessionStorage.getItem('plasma-source-refresh-session-v1')")
            check(cursor_before is not None and cursor_after is not None and json.loads(cursor_after)["cursor"] == "c0", CASES[43])
            State.active = False
            State.events.append(terminal_event())
            page.get_by_text("World Bank: 2 ta yangi tender", exact=True).wait_for(timeout=7000)
            check(True, CASES[44])
            check(page.get_by_text("Yangi", exact=True).count() == 1, CASES[45])
            check("source=world_bank" in page.url and "view=all" in page.url, CASES[46])
            check(State.domain_writes == [], CASES[47])

            State.users["s72-token-b"]["blocked"] = True
            blocked_context = browser.new_context(java_script_enabled=False)
            add_session(blocked_context, "b")
            blocked_page = blocked_context.new_page()
            blocked_page.goto(f"{BASE_URL}/dashboard/tenders", wait_until="domcontentloaded")
            check(
                urlparse(blocked_page.url).path == "/"
                and parse_qs(urlparse(blocked_page.url).query).get("next") == ["/dashboard/tenders"],
                CASES[48],
            )
            blocked_context.close()
            State.users["s72-token-b"]["blocked"] = False
            page_b.goto(f"{BASE_URL}/dashboard/tenders", wait_until="networkidle")
            page.reload(wait_until="networkidle")
            check(page.locator("html").get_attribute("lang") == "uz" and page_b.locator("html").get_attribute("lang") == "ru", CASES[49])
            context_b.close()
            browser.close()
            browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        subprocess.run([TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        if cdp_proxy is not None:
            subprocess.run(
                [TASKKILL, "/PID", str(cdp_proxy.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        base.kill_listener(CDP_PROXY_PORT)
        base.kill_listener(3114)
        if cdp_port is not None:
            base.kill_listener(cdp_port)

    assert len(passed) == len(set(passed)) == 50, (
        len(passed), len(set(passed)), [case for case in CASES if case not in passed]
    )
    assert set(passed) == set(CASES)
    print(json.dumps({"passed": len(passed), "results": passed}, indent=2, ensure_ascii=False))
    print("50/50 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
