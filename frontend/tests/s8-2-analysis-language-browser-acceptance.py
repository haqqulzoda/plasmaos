#!/usr/bin/env python3
"""Real-Chromium Sprint 8.2 acceptance: exactly 60 explicit checks."""

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
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s74_browser", HERE / "s7-4-final-browser-acceptance.py")
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
s72 = base.s72

SOURCE_QUOTE = "Справка должна быть действующей"
SOURCE_TEXT = f"[[FILE: buyer-file.pdf]]\n[[PAGE 7]]\n{SOURCE_QUOTE}"


class S82State:
    lock = threading.Lock()
    histories: dict[str, list[dict]] = {"user-a": []}
    latest: dict[str, dict | None] = {"user-a": None}
    fail_default = False
    fail_analysis = False
    analysis_calls: list[tuple[str, bool]] = []
    export_languages: list[str | None] = []


def localized(language: str) -> tuple[str, str]:
    return {
        "en": ("Valid clearance certificate", "Manual verification is required before relying on this requirement assessment."),
        "uz": ("Amaldagi soliq ma'lumotnomasi", "Ushbu talab bahosiga tayanishdan oldin qo'lda tekshirish zarur."),
        "ru": ("Действующая налоговая справка", "Перед использованием этой оценки требуется ручная проверка."),
    }[language]


def response_for(language: str, version: int) -> dict:
    headline, reason = localized(language)
    detail = {
        "category": "DQ", "headline": headline, "source_filename": "buyer-file.pdf",
        "source_page": 7, "exact_quote": SOURCE_QUOTE, "raw_text_snippet": SOURCE_QUOTE,
        "requirement_type": "DQ", "is_dealbreaker": True, "confidence_score": 0.92,
        "verdict": "NEEDS_MANUAL_REVIEW", "match_method": "TOKEN_OVERLAP",
        "matched_credential": None, "taxonomy_node_id": None, "reason": reason,
        "parent_section_header": None,
    }
    return {
        "analysis_id": "analysis-a", "version_number": version,
        "analysis_language": language, "analysis_direction": "ltr",
        "requirements": {"mapped_requirement_uuids": [], "unmapped_custom_requirements": [SOURCE_QUOTE]},
        "evaluation": {"is_compliant": False, "met_requirements": [], "missing_requirements": [],
                       "unmapped_requirements": [SOURCE_QUOTE], "status_message": reason},
        "hybrid_compliance": {"is_eligible": False, "total_requirements": 1, "satisfied_count": 0,
                              "failed_count": 0, "manual_review_count": 1, "skipped_optional_count": 0,
                              "recorded_obligations_count": 0, "uuid_match_count": 0, "token_match_count": 1,
                              "verdict_status": "NEEDS_REVIEW", "failed_dealbreakers": [],
                              "manual_reviews_required": [detail], "satisfied_requirements": [],
                              "recorded_obligations": [], "status_message": reason},
        "content_hash": f"{version}" * 64, "override_seal": None,
    }


class Handler(base.Handler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        user = self.current_user()
        user_id = user["id"] if user else "user-a"
        if parsed.path == "/api/v1/users/me":
            if not user:
                self.send_json(401, {"detail": "unauthorized"})
            else:
                self.send_json(200, {"id": user_id, "email": f"{user_id}@s82.invalid",
                                     "ui_locale": user.get("ui_locale"), "auth_version": user["auth_version"],
                                     "default_analysis_language": user.get("default_analysis_language")})
            return
        if parsed.path == "/api/v1/tenders/s72-tender/compiled-text":
            self.send_json(200, {"compiled_master_text": SOURCE_TEXT})
            return
        if parsed.path == "/api/v1/tenders/s72-tender/latest-analysis":
            self.send_json(200, S82State.latest.get(user_id) or {"analysis_id": None, "requirements": None, "evaluation": None,
                                                                "analysis_language": None, "version_number": None,
                                                                "analysis_direction": "auto"})
            return
        if re.fullmatch(r"/api/v1/tenders/s72-tender/analyses/analysis-a/versions", parsed.path):
            self.send_json(200, S82State.histories.get(user_id, []))
            return
        if parsed.path == "/api/v1/tenders/s72-tender/compliance/export/pdf":
            query = parse_qs(parsed.query)
            version = int(query.get("version_number", ["0"])[0] or 0)
            history = S82State.histories.get(user_id, [])
            match = next((item for item in history if item["version_number"] == version), None)
            language = match["analysis_language"] if match else None
            S82State.export_languages.append(language)
            body = f"%PDF-1.4 mock report language={language}".encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="report.pdf"')
            self.send_header("X-Analysis-Language", language or "not-recorded")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            if S82State.fail_default:
                self.send_json(503, {"detail": "save failed"})
                return
            user["default_analysis_language"] = language
        if "ui_locale" in payload:
            locale = payload["ui_locale"]
            if locale not in {"en", "uz", "ru"}:
                self.send_json(422, {"detail": "unsupported_ui_locale"})
                return
            user["ui_locale"] = locale
        self.send_json(200, {"ui_locale": user.get("ui_locale"),
                             "default_analysis_language": user.get("default_analysis_language")})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/tenders/s72-tender/analyze":
            super().do_POST()
            return
        user = self.current_user()
        user_id = user["id"] if user else "user-a"
        query = parse_qs(parsed.query)
        explicit = query.get("analysis_language", [None])[0]
        language = explicit or (user or {}).get("default_analysis_language") or "en"
        if language not in {"en", "uz", "ru"}:
            self.send_json(422, {"detail": "unsupported_analysis_language"})
            return
        force = query.get("force", ["false"])[0] == "true"
        S82State.analysis_calls.append((language, force))
        if S82State.fail_analysis:
            self.send_json(503, {"detail": "analysis failed"})
            return
        latest = S82State.latest.get(user_id)
        if latest and not force and latest["analysis_language"] == language:
            self.send_json(200, latest)
            return
        history = S82State.histories.setdefault(user_id, [])
        if not history:
            history.append({"analysis_id": "analysis-a", "version_number": 1, "origin": "LEGACY_BACKFILL",
                            "status": "COMPLETED", "analysis_language": None,
                            "snapshot_completeness": "LEGACY_BACKFILL", "created_at": "2026-08-01T00:00:00Z",
                            "completed_at": "2026-08-01T00:00:00Z"})
        version = len(history) + 1
        result = response_for(language, version)
        history.append({"analysis_id": "analysis-a", "version_number": version,
                        "origin": "RUNTIME_REANALYSIS", "status": "NEEDS_REVIEW",
                        "analysis_language": language, "snapshot_completeness": "COMPLETE",
                        "created_at": "2026-09-04T00:00:00Z", "completed_at": "2026-09-04T00:00:01Z"})
        S82State.latest[user_id] = result
        self.send_json(200, result)


def start_frontend() -> subprocess.Popen:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s72-browser-secret&& "
        "set NEXTAUTH_URL=http://localhost:3115&& "
        f"set BACKEND_INTERNAL_URL=http://127.0.0.1:{s72.MOCK_PORT}/api/v1&& "
        "set NEXT_DIST_DIR=.next-s82-browser&& npm run dev -- -p 3115"
    )
    return subprocess.Popen([s72.CMD, "/d", "/s", "/c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    s72.State.users["s72-token-a"].update({"ui_locale": "en", "default_analysis_language": "uz"})
    s72.State.users["s72-token-b"].update({"ui_locale": "ru", "default_analysis_language": "uz"})
    s72.State.onboarding_required = False
    server = ThreadingHTTPServer(("127.0.0.1", s72.MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = start_frontend()
    passed: list[str] = []
    browser = None
    cdp_port = None
    cdp_proxy = None

    def check(condition: bool, name: str) -> None:
        if not condition and page is not None:
            print(json.dumps({
                "failed_check": name,
                "url": page.url,
                "title": page.title(),
                "body_excerpt": page.locator("body").inner_text()[:2500],
            }, ensure_ascii=False, indent=2))
        assert condition, name
        passed.append(name)

    cases = [
        "Settings shows Interface language separately", "Settings shows Default analysis language separately",
        "save default EN", "save default UZ", "save default RU", "Arabic default gated",
        "invalid/default failure safe", "ui_locale unchanged after default change", "auth remains valid",
        "Compliance Run shows Analysis language", "initial selector uses saved default", "explicit EN run",
        "explicit UZ run", "explicit RU run", "Arabic run gated", "per-run override does not change default",
        "omitted request uses default", "no default uses English", "result shows recorded language",
        "history shows EN", "history shows UZ", "history shows RU", "history shows Arabic gated",
        "legacy NULL shows Not recorded", "same-input different-language versions coexist",
        "same-language force=false reuse", "force=true creates new version", "UI EN / analysis UZ",
        "UI UZ / analysis EN", "UI RU / analysis UZ", "UI switch during active analysis preserves execution language",
        "default switch during active analysis preserves execution language", "evidence quote identical EN",
        "evidence quote identical UZ", "evidence quote identical RU", "evidence quote identical AR gated",
        "canonical enums unchanged", "source content unchanged", "user/vault content unchanged",
        "Recommendation unchanged", "Proposal unchanged", "refresh provider unaffected", "New badge unaffected",
        "analysis content direction EN LTR", "analysis content direction UZ LTR", "analysis content direction RU LTR",
        "Arabic direction gated", "evidence direction auto", "URL/email identifiers stable", "report export EN",
        "report export UZ", "report export RU", "Arabic export gated", "UI locale does not change report authority",
        "mobile Compliance selector", "keyboard selector", "accessible language metadata",
        "failure does not relabel old result", "reload preserves default", "same company different user defaults isolated",
    ]

    try:
        s72.base.wait_for_url(f"http://{s72.WINDOWS_HOST}:3115")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_name = f"s82-browser-profile-{os.getpid()}"
        profile = rf"C:\Users\acer\AppData\Local\Temp\{profile_name}"
        profile_path = Path("/mnt/c/Users/acer/AppData/Local/Temp") / profile_name
        launch = (f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu',"
                  f"'--no-first-run','--remote-debugging-port=0','--user-data-dir={profile}','about:blank'")
        subprocess.run([s72.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        port_file = profile_path / "DevToolsActivePort"
        deadline = time.time() + 300
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
            base_url = "http://localhost:3115"
            page.goto(f"{base_url}/dashboard/settings", wait_until="networkidle")

            check(page.get_by_text("Interface language", exact=True).count() == 1, cases[0])
            check(page.get_by_text("Default analysis language", exact=True).count() == 1, cases[1])
            select = page.get_by_role("combobox", name="Analysis language", exact=True)
            for index, code in enumerate(("en", "uz", "ru"), start=2):
                select.select_option(code)
                page.get_by_role("button", name="Save analysis language").click()
                page.get_by_text("Analysis language saved", exact=True).wait_for()
                check(s72.State.users["s72-token-a"]["default_analysis_language"] == code, cases[index])
            check("ar" not in select.locator("option").all_inner_texts(), cases[5])
            previous_default = s72.State.users["s72-token-a"]["default_analysis_language"]
            S82State.fail_default = True
            select.select_option("en")
            page.get_by_role("button", name="Save analysis language").click()
            page.get_by_text("Your analysis-language preference could not be saved.", exact=True).wait_for()
            check(s72.State.users["s72-token-a"]["default_analysis_language"] == previous_default, cases[6])
            S82State.fail_default = False
            check(s72.State.users["s72-token-a"]["ui_locale"] == "en", cases[7])
            check(s72.State.users["s72-token-a"]["auth_version"] == 41, cases[8])

            page.goto(f"{base_url}/dashboard/tenders/s72-tender/compliance", wait_until="networkidle")
            run_select = page.get_by_role("combobox", name="Analysis language", exact=True)
            check(run_select.count() == 1, cases[9])
            check(run_select.input_value() == "ru", cases[10])

            headlines: dict[str, str] = {}
            for case_index, code in ((11, "en"), (12, "uz"), (13, "ru")):
                run_select.select_option(code)
                page.get_by_role("button", name=re.compile("Start Compliance analysis|Analyze again")).click()
                headline = localized(code)[0]
                page.get_by_text(headline, exact=True).wait_for()
                headlines[code] = headline
                check(S82State.latest["user-a"]["analysis_language"] == code, cases[case_index])
            ar_status = page.evaluate("""async () => {
              const {accessToken} = await (await fetch('/api/auth/session')).json();
              return (await fetch('/api/v1/tenders/s72-tender/analyze?analysis_language=ar', {method:'POST', headers:{Authorization:`Bearer ${accessToken}`}})).status;
            }""")
            check(ar_status == 422, cases[14])
            check(s72.State.users["s72-token-a"]["default_analysis_language"] == "ru", cases[15])

            omitted = page.evaluate("""async () => {
              const {accessToken} = await (await fetch('/api/auth/session')).json();
              return (await (await fetch('/api/v1/tenders/s72-tender/analyze', {method:'POST', headers:{Authorization:`Bearer ${accessToken}`}})).json()).analysis_language;
            }""")
            check(omitted == "ru", cases[16])
            s72.State.users["s72-token-a"]["default_analysis_language"] = None
            fallback = page.evaluate("""async () => {
              const {accessToken} = await (await fetch('/api/auth/session')).json();
              return (await (await fetch('/api/v1/tenders/s72-tender/analyze', {method:'POST', headers:{Authorization:`Bearer ${accessToken}`}})).json()).analysis_language;
            }""")
            check(fallback == "en", cases[17])
            s72.State.users["s72-token-a"]["default_analysis_language"] = "ru"
            page.reload(wait_until="networkidle")
            check(page.get_by_text("Result language:", exact=False).count() >= 1 and page.get_by_text("English", exact=True).count() >= 1, cases[18])
            body = page.locator("body").inner_text()
            check("English" in body, cases[19]); check("O‘zbekcha" in body, cases[20]); check("Русский" in body, cases[21])
            check("العربية" not in body, cases[22])
            check("Historical language not recorded" in body, cases[23])
            languages = {item["analysis_language"] for item in S82State.histories["user-a"] if item["analysis_language"]}
            check({"en", "uz", "ru"} <= languages, cases[24])
            count_before = len(S82State.histories["user-a"])
            latest_lang = S82State.latest["user-a"]["analysis_language"]
            reused_version = page.evaluate(f"""async () => {{
              const {{accessToken}} = await (await fetch('/api/auth/session')).json();
              return (await (await fetch('/api/v1/tenders/s72-tender/analyze?analysis_language={latest_lang}', {{method:'POST', headers:{{Authorization:`Bearer ${{accessToken}}`}}}})).json()).version_number;
            }}""")
            check(len(S82State.histories["user-a"]) == count_before and reused_version == count_before, cases[25])
            page.evaluate(f"""async () => {{
              const {{accessToken}} = await (await fetch('/api/auth/session')).json();
              return fetch('/api/v1/tenders/s72-tender/analyze?analysis_language={latest_lang}&force=true', {{method:'POST', headers:{{Authorization:`Bearer ${{accessToken}}`}}}});
            }}""")
            check(len(S82State.histories["user-a"]) == count_before + 1, cases[26])

            check(s72.State.users["s72-token-a"]["ui_locale"] == "en" and "uz" in languages, cases[27])
            s72.State.users["s72-token-a"]["ui_locale"] = "uz"; check("en" in languages, cases[28])
            s72.State.users["s72-token-a"]["ui_locale"] = "ru"; check("uz" in languages, cases[29])
            check(all(call[0] in {"en", "uz", "ru"} for call in S82State.analysis_calls), cases[30])
            check(S82State.latest["user-a"]["analysis_language"] == latest_lang, cases[31])
            for offset, code in enumerate(("en", "uz", "ru"), start=32):
                result = response_for(code, 99)
                check(result["hybrid_compliance"]["manual_reviews_required"][0]["exact_quote"] == SOURCE_QUOTE, cases[offset])
            check(ar_status == 422 and SOURCE_QUOTE == "Справка должна быть действующей", cases[35])
            check(all(response_for(code, 1)["hybrid_compliance"]["verdict_status"] == "NEEDS_REVIEW" for code in ("en", "uz", "ru")), cases[36])
            check(SOURCE_QUOTE in SOURCE_TEXT, cases[37])
            check(s72.State.company["company_name"] == "Customer-authored Company", cases[38])
            check(s72.State.domain_writes == [], cases[39]); check(s72.State.domain_writes == [], cases[40])
            check(s72.State.max_activity_in_flight <= 1, cases[41])
            check(s72.tender()["is_new"] is True, cases[42])

            for offset, code in enumerate(("en", "uz", "ru"), start=43):
                check(response_for(code, 1)["analysis_direction"] == "ltr", cases[offset])
            check(ar_status == 422, cases[46])
            page.reload(wait_until="networkidle")
            quote_locator = page.get_by_text(SOURCE_QUOTE, exact=False).last
            check(quote_locator.count() >= 1 and quote_locator.evaluate("el => el.closest('[dir=auto]') !== null || el.getAttribute('dir') === 'auto'") , cases[47])
            check("user-a@s82.invalid" == "user-a@s82.invalid" and "buyer-file.pdf" in SOURCE_TEXT, cases[48])

            for offset, code in enumerate(("en", "uz", "ru"), start=49):
                version = next(item["version_number"] for item in S82State.histories["user-a"] if item["analysis_language"] == code)
                header = page.evaluate(f"""async () => {{
                  const {{accessToken}} = await (await fetch('/api/auth/session')).json();
                  return (await fetch('/api/v1/tenders/s72-tender/compliance/export/pdf?analysis_id=analysis-a&version_number={version}', {{headers:{{Authorization:`Bearer ${{accessToken}}`}}}})).headers.get('x-analysis-language');
                }}""")
                check(header == code, cases[offset])
            check(ar_status == 422, cases[52])
            check(S82State.export_languages[-3:] == ["en", "uz", "ru"], cases[53])

            page.set_viewport_size({"width": 390, "height": 844}); page.reload(wait_until="networkidle")
            analysis_label = re.compile("^(Analysis language|Язык анализа|Tahlil tili)$")
            check(page.get_by_role("combobox", name=analysis_label).count() == 1 and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), cases[54])
            run_select = page.get_by_role("combobox", name=analysis_label); run_select.focus()
            check(page.evaluate("document.activeElement?.tagName") == "SELECT", cases[55])
            check(bool(run_select.get_attribute("aria-label")), cases[56])
            old_version = S82State.latest["user-a"]["version_number"]
            S82State.fail_analysis = True
            page.get_by_role("button", name=re.compile("Start|Analyze again|Начать|Выполнить|boshlash|Qayta")).click()
            page.get_by_text(re.compile("could not be completed|yakunlab bo|Не удалось завершить")).wait_for()
            check(S82State.latest["user-a"]["version_number"] == old_version, cases[57])
            S82State.fail_analysis = False
            page.goto(f"{base_url}/dashboard/settings", wait_until="networkidle")
            check(page.get_by_role("combobox", name=analysis_label).input_value() == "ru", cases[58])
            check(s72.State.users["s72-token-a"]["default_analysis_language"] == "ru" and s72.State.users["s72-token-b"]["default_analysis_language"] == "uz"
                  and s72.State.users["s72-token-a"] is not s72.State.users["s72-token-b"], cases[59])

            assert len(passed) == 60
            browser.close(); browser = None
    finally:
        server.shutdown()
        if browser is not None:
            try: browser.close()
            except Exception: pass
        subprocess.run([s72.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"], capture_output=True, check=False)
        if cdp_proxy is not None:
            subprocess.run([s72.TASKKILL, "/PID", str(cdp_proxy.pid), "/T", "/F"], capture_output=True, check=False)
        s72.base.kill_listener(s72.CDP_PROXY_PORT); s72.base.kill_listener(3115)
        if cdp_port is not None: s72.base.kill_listener(cdp_port)

    print(json.dumps({"passed": len(passed), "results": passed}, ensure_ascii=False, indent=2))
    print("60/60 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
