#!/usr/bin/env python3
"""Real Chromium acceptance for Sprint 7.3 visible controls and P0 surfaces."""

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
    "s72_browser", HERE / "s7-2-localization-browser-acceptance.py"
)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def envelope(data: object | None) -> dict:
    return {
        "state": "AVAILABLE" if data is not None else "EMPTY",
        "data": data,
        "reason_code": None,
    }


def engagement() -> dict:
    return {
        "engagement_id": "engagement-s73",
        "tender_id": "s72-tender",
        "engagement_status": "PREPARING",
        "engagement_origin": "BID_PREPARATION",
        "engagement_created_at": "2026-09-01T10:00:00Z",
        "engagement_updated_at": "2026-09-02T10:00:00Z",
        "status_changed_at": "2026-09-02T10:00:00Z",
        "allowed_actions": ["MARK_SUBMITTED", "DISMISS"],
    }


def proposal() -> dict:
    row = base.tender()
    return {
        "id": "s73-proposal",
        "user_id": "user-a",
        "tender_id": row["id"],
        "status": "DRAFT",
        "ai_confidence_score": 81,
        "structured_data": {
            "strategic_summary": "User-authored Proposal body — keep original.",
            "ai_summary": "AI-authored Proposal rationale — keep original.",
            "our_price": 12000,
            "delivery_days": "45 days",
            "line_items": [],
        },
        "final_pdf_url": None,
        "margin_percent": 15,
        "include_vat": True,
        "currency": "USD",
        "created_at": "2026-09-02T10:00:00Z",
        "tender_title": row["title"],
        "tender_budget": row["budget"],
        "tender_currency": row["currency"],
        "tender_deadline": row["deadline"],
        "tender_region": row["region"],
        "tender_source_system": row["source_system"],
        "tender_status": "OPEN",
        "engagement_status": "PREPARING",
    }


def my_tender() -> dict:
    row = base.tender()
    return {
        **engagement(),
        "tender_title": row["title"],
        "buyer": row["buyer"],
        "source_system": row["source_system"],
        "tender_status": "OPEN",
        "deadline": row["deadline"],
        "estimated_value": row["budget"],
        "currency": row["currency"],
        "notice_type": row["notice_type"],
        "procurement_method": row["procurement_method"],
        "country": row["country"],
        "region": row["region"],
        "project_external_id": row["project_id"],
        "project_name": "Source Project Name — keep original",
        "project_source_system": row["source_system"],
        "project_enrichment_status": "successful",
    }


def tender_details() -> dict:
    return {
        "tender_id": "s72-tender",
        "project_context": envelope(None),
        "project_leadership": envelope(None),
        "procurement_contacts": envelope(None),
        "requirements": envelope(
            {
                "source_native_available": False,
                "derivation": "ANALYSIS_VERSION",
                "items": [
                    {
                        "label": "AI evidence sentence — keep original.",
                        "source_type": "AI_EXTRACTED",
                        "document_name": "Source Document.pdf",
                        "page": 3,
                        "section": "Source section",
                    }
                ],
                "total_count": 1,
                "returned_count": 1,
                "truncated": False,
            }
        ),
        "documents": envelope(None),
        "compliance": envelope(None),
        "company_readiness": envelope(None),
        "pursuit": envelope(engagement()),
        "bid_preparation": envelope(
            {
                "proposal_id": "s73-proposal",
                "proposal_status": "DRAFT",
                "created_at": "2026-09-02T10:00:00Z",
                "detail_route_id": "s73-proposal",
            }
        ),
    }


class Handler(base.Handler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/users/me/access-status":
            user = self.current_user()
            self.send_json(
                200,
                {
                    "company_profile_id": None if base.State.onboarding_required else "shared-company",
                    "company_name": None if base.State.onboarding_required else base.State.company["company_name"],
                    "onboarding_required": base.State.onboarding_required,
                    "onboarding_completed": not base.State.onboarding_required,
                    "user_approval_status": "approved",
                    "company_approval_status": "approved",
                    "platform_role": "pilot_user",
                    "access_allowed": bool(user) and not base.State.onboarding_required,
                    "state": "approved",
                },
            )
            return
        if path == "/api/v1/tenders/s72-tender":
            self.send_json(200, base.tender())
            return
        if path == "/api/v1/tenders/s72-tender/details":
            self.send_json(200, tender_details())
            return
        if path == "/api/v1/tenders/s72-tender/documents":
            self.send_json(200, [])
            return
        if path == "/api/v1/tenders/s72-tender/engagement":
            self.send_json(200, {"engagement": engagement(), "proposal_id": "s73-proposal"})
            return
        if path == "/api/v1/my-tenders":
            self.send_json(
                200,
                {
                    "items": [my_tender()],
                    "total": 1,
                    "limit": 25,
                    "offset": 0,
                    "counts": {
                        "all": 1,
                        "active": 1,
                        "saved": 0,
                        "evaluating": 0,
                        "preparing": 1,
                        "submitted": 0,
                        "won": 0,
                        "lost": 0,
                        "dismissed": 0,
                    },
                },
            )
            return
        if path == "/api/v1/proposals":
            self.send_json(200, [proposal()])
            return
        if path == "/api/v1/proposals/s73-proposal":
            self.send_json(200, proposal())
            return
        if path == "/api/v1/vault":
            self.send_json(200, {"company_name": base.State.company["company_name"]})
            return
        super().do_GET()


CASES = [
    "onboarding selector has exactly three native labels",
    "onboarding selector has no Arabic or flags",
    "onboarding selector is keyboard-focusable",
    "onboarding EN→UZ persists",
    "onboarding switch preserves form values",
    "onboarding route remains unchanged",
    "failed onboarding switch retains Uzbek",
    "failed onboarding switch exposes localized alert",
    "reload retains persisted Uzbek",
    "settings shows active Uzbek locale",
    "settings UZ→RU persists",
    "settings switch preserves customer-authored value",
    "new tab uses Russian preference",
    "Russian Explorer shell renders",
    "Explorer query values remain canonical",
    "Russian New badge renders",
    "Explorer source title stays original",
    "Russian Tender Details shell renders",
    "Tender source description stays original",
    "AI evidence stays original",
    "Russian My Tenders shell renders",
    "My Tenders canonical pursuit semantics render",
    "Russian Bid Preparation shell renders",
    "Proposal content stays original",
    "English P0 matrix renders",
    "Uzbek P0 matrix renders",
    "Russian P0 matrix renders",
    "mobile English layout has no page overflow",
    "mobile Uzbek layout has no page overflow",
    "mobile Russian layout has no page overflow",
    "html lang follows every active locale",
    "locale controls add no domain mutation",
]


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", base.MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frontend = base.start_frontend()
    passed: list[str] = []
    browser = None
    cdp_port: int | None = None
    cdp_proxy: subprocess.Popen | None = None

    def check(condition: bool, name: str) -> None:
        assert condition, name
        passed.append(name)

    def radio(page, native_name: str):
        return page.locator('[data-language-selector]').get_by_role(
            "radio", name=re.compile(re.escape(native_name))
        )

    try:
        base.base.wait_for_url(f"http://{base.WINDOWS_HOST}:3114")
        chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        profile_name = f"s73-browser-profile-{os.getpid()}"
        profile = rf"C:\Users\acer\AppData\Local\Temp\{profile_name}"
        profile_path = Path("/mnt/c/Users/acer/AppData/Local/Temp") / profile_name
        launch = (
            f"Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new',"
            f"'--disable-gpu','--no-first-run','--remote-debugging-port=0',"
            f"'--user-data-dir={profile}','about:blank'"
        )
        subprocess.run([base.POWERSHELL, "-NoProfile", "-Command", launch], check=True)
        port_file = profile_path / "DevToolsActivePort"
        deadline = time.time() + 20
        while time.time() < deadline and not port_file.exists():
            time.sleep(0.2)
        if not port_file.exists():
            raise RuntimeError("Chromium did not publish DevToolsActivePort")
        cdp_port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        proxy_command = (
            "cd /d D:\\projects\\plasmaos\\frontend && "
            f"node tests\\cdp-port-forward.mjs {base.CDP_PROXY_PORT} {cdp_port}"
        )
        cdp_proxy = subprocess.Popen(
            [base.CMD, "/d", "/s", "/c", proxy_command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base.base.wait_for_url(
            f"http://{base.WINDOWS_HOST}:{base.CDP_PROXY_PORT}/json/version"
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://{base.WINDOWS_HOST}:{base.CDP_PROXY_PORT}"
            )
            context = browser.contexts[0]
            context.clear_cookies()
            base.add_session(context, "a")
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1360, "height": 900})

            base.State.users["s72-token-a"]["ui_locale"] = "en"
            base.State.onboarding_required = True
            page.goto(f"{base.BASE_URL}/dashboard/onboarding", wait_until="networkidle")
            selector = page.locator('[data-language-selector="onboarding"]')
            labels = ["English", "O‘zbekcha", "Русский"]
            check(all(radio(page, label).count() == 1 for label in labels), CASES[0])
            text = selector.inner_text()
            check("العربية" not in text and not re.search(r"[🇦-🇿]", text), CASES[1])
            radio(page, "O‘zbekcha").focus()
            check(page.evaluate("document.activeElement?.getAttribute('role')") == "radio", CASES[2])
            company = page.get_by_label("Company name")
            company.fill("Unsaved customer form value")
            route_before = page.url
            radio(page, "O‘zbekcha").click()
            page.locator('html[lang="uz"]').wait_for()
            check(base.State.users["s72-token-a"]["ui_locale"] == "uz", CASES[3])
            check(
                page.get_by_label("Kompaniya nomi").input_value()
                == "Unsaved customer form value",
                CASES[4],
            )
            check(page.url == route_before, CASES[5])
            base.State.fail_save = True
            radio(page, "Русский").click()
            selector_alert = page.locator('[data-language-selector]').get_by_role("alert")
            selector_alert.wait_for()
            check(page.locator("html").get_attribute("lang") == "uz", CASES[6])
            check("saqlab bo‘lmadi" in selector_alert.inner_text(), CASES[7])
            base.State.fail_save = False
            page.reload(wait_until="networkidle")
            check(page.locator("html").get_attribute("lang") == "uz", CASES[8])

            base.State.onboarding_required = False
            page.goto(f"{base.BASE_URL}/dashboard/settings", wait_until="networkidle")
            radio(page, "O‘zbekcha").wait_for()
            check(radio(page, "O‘zbekcha").get_attribute("aria-checked") == "true", CASES[9])
            customer_value = page.get_by_label("Kompaniya nomi").input_value()
            radio(page, "Русский").click()
            page.locator('html[lang="ru"]').wait_for()
            check(base.State.users["s72-token-a"]["ui_locale"] == "ru", CASES[10])
            check(page.get_by_label("Название компании").input_value() == customer_value, CASES[11])
            new_tab = context.new_page()
            new_tab.goto(f"{base.BASE_URL}/dashboard/settings", wait_until="networkidle")
            check(new_tab.locator("html").get_attribute("lang") == "ru", CASES[12])
            new_tab.close()

            explorer_url = (
                f"{base.BASE_URL}/dashboard/tenders?view=all&source=world_bank"
                "&new_only=true&q=Original"
            )
            page.goto(explorer_url, wait_until="networkidle")
            check(page.get_by_role("heading", name="Каталог тендеров").count() == 1, CASES[13])
            check(all(value in page.url for value in ["view=all", "source=world_bank", "new_only=true", "q=Original"]), CASES[14])
            check(page.get_by_text("Новое", exact=True).count() == 1, CASES[15])
            check(page.get_by_text(base.tender()["title"], exact=True).count() == 1, CASES[16])

            page.goto(f"{base.BASE_URL}/dashboard/tenders/s72-tender", wait_until="networkidle")
            check(page.get_by_text("Требования и документы", exact=True).count() >= 1, CASES[17])
            check(page.get_by_text(base.tender()["description"], exact=True).count() == 1, CASES[18])
            check(page.get_by_text("AI evidence sentence — keep original.", exact=True).count() == 1, CASES[19])

            page.goto(f"{base.BASE_URL}/dashboard/my-tenders", wait_until="networkidle")
            check(page.get_by_role("heading", name="Мои тендеры").count() == 1, CASES[20])
            check(page.get_by_text(re.compile(r"Участие:.*Подготовка")).count() >= 1, CASES[21])

            page.goto(f"{base.BASE_URL}/dashboard/bid-preparation/s73-proposal", wait_until="networkidle")
            check(page.get_by_text("Стратегическое резюме", exact=True).count() == 1, CASES[22])
            check(page.get_by_text("User-authored Proposal body — keep original.", exact=True).count() == 1, CASES[23])

            matrix = {
                "en": ("Tender Explorer", "My Tenders", "Bid Preparation"),
                "uz": ("Tenderlar katalogi", "Mening tenderlarim", "Taklif tayyorlash"),
                "ru": ("Каталог тендеров", "Мои тендеры", "Подготовка заявки"),
            }
            for index, (locale, headings) in enumerate(matrix.items(), start=24):
                result = base.switch_locale(page, locale)
                ok = result["ok"]
                for path, heading in zip(
                    ["tenders?view=all", "my-tenders", "bid-preparation"], headings
                ):
                    page.goto(f"{base.BASE_URL}/dashboard/{path}", wait_until="networkidle")
                    ok = ok and page.get_by_role("heading", name=heading).count() == 1
                check(ok, CASES[index])

            page.set_viewport_size({"width": 390, "height": 844})
            for index, locale in enumerate(["en", "uz", "ru"], start=27):
                base.switch_locale(page, locale)
                page.goto(f"{base.BASE_URL}/dashboard/settings", wait_until="networkidle")
                no_overflow = page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1"
                )
                check(no_overflow, CASES[index])
            check(page.locator("html").get_attribute("lang") == "ru", CASES[30])
            check(base.State.domain_writes == [], CASES[31])
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
            [base.TASKKILL, "/PID", str(frontend.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        if cdp_proxy is not None:
            subprocess.run(
                [base.TASKKILL, "/PID", str(cdp_proxy.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        base.base.kill_listener(base.CDP_PROXY_PORT)
        base.base.kill_listener(3114)
        if cdp_port is not None:
            base.base.kill_listener(cdp_port)

    assert len(passed) == len(set(passed)) == len(CASES), (
        len(passed),
        [case for case in CASES if case not in passed],
    )
    print(json.dumps({"passed": len(passed), "results": passed}, indent=2, ensure_ascii=False))
    print(f"{len(CASES)}/{len(CASES)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
