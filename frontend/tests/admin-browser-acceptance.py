#!/usr/bin/env python3
"""Real Chromium acceptance against the Sprint 3.5 Admin UI and mocked API."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:3105"
MOCK_PORT = 8105
CDP_PORT = 9225
CDP_HOST = "127.0.0.1"
ROOT = Path(__file__).resolve().parents[1]
CURRENT_ID = "00000000-0000-4000-8000-000000000001"
CMD = r"C:\Windows\System32\cmd.exe" if os.name == "nt" else "/mnt/c/Windows/System32/cmd.exe"
POWERSHELL = (
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    if os.name == "nt"
    else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)


def account(
    suffix: int,
    email: str,
    status: str,
    actions: list[str],
    *,
    role: str = "user",
    current: bool = False,
    restore: str | None = None,
) -> dict[str, object]:
    return {
        "id": CURRENT_ID if current else f"00000000-0000-4000-8000-{suffix:012d}",
        "name": email.split("@", 1)[0].replace("-", " ").title(),
        "email": email,
        "approval_status": status,
        "role": role,
        "is_current_actor": current,
        "restore_target_status": restore,
        "allowed_actions": actions,
        "company": None,
        "created_at": "2026-08-28T10:00:00+00:00",
    }


class State:
    authority = True
    stale_attempted = False
    accounts = [
        account(1, "current-admin@s35.invalid", "approved", [], role="admin", current=True),
        account(2, "pending@s35.invalid", "pending", ["approve", "reject", "disable"]),
        account(3, "approved@s35.invalid", "approved", ["reject", "disable"]),
        account(4, "known-restore@s35.invalid", "disabled", ["restore"], restore="approved"),
        account(5, "rejected@s35.invalid", "rejected", ["approve", "disable"]),
        account(6, "last-admin@s35.invalid", "approved", ["reject", "disable"], role="admin"),
        account(7, "stale@s35.invalid", "approved", ["reject", "disable"]),
    ]
    audit = []


for index in range(106):
    if index == 0:
        outcome, reason = "SUCCESS", None
    elif index == 1:
        outcome, reason = "DENIED", "SELF_ACTION_PROHIBITED"
    elif index == 2:
        outcome, reason = None, None
    else:
        outcome, reason = ("FAILED", "TRANSACTION_FAILED") if index % 2 else ("SUCCESS", None)
    State.audit.append(
        {
            "id": f"10000000-0000-4000-8000-{index:012d}",
            "occurred_at": f"2026-08-28T10:{index // 60:02d}:{index % 60:02d}+00:00",
            "action": "USER_APPROVED" if index != 2 else "user_approved",
            "outcome": outcome,
            "actor_user_id": CURRENT_ID if index != 2 else None,
            "actor_type": "USER" if index != 2 else None,
            "actor_email_snapshot": "current-admin@s35.invalid" if index != 2 else None,
            "actor_role_snapshot": "admin" if index != 2 else None,
            "actor_label": "legacy" if index == 2 else None,
            "target_user_id": f"20000000-0000-4000-8000-{index:012d}",
            "target_email_snapshot": f"audit-{index:03d}@s35.invalid",
            "target_resource_type": "USER" if index != 2 else None,
            "target_resource_id": None,
            "previous_state": {"approval_status": "pending"} if outcome == "SUCCESS" else None,
            "new_state": {
                "approval_status": "approved",
                "credentials_invalidated": True,
            } if outcome == "SUCCESS" else None,
            "reason_code": reason,
            "reason": "historical" if index == 2 else None,
            "request_id": None,
            "source": "ADMIN_API" if index != 2 else None,
        }
    )


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
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/users/me":
            if not State.authority:
                self.send_json(403, {"detail": "Admin access required"})
            else:
                self.send_json(200, {"id": CURRENT_ID, "email": "current-admin@s35.invalid"})
            return
        if parsed.path == "/api/v1/admin/accounts":
            if not State.authority:
                self.send_json(403, {"detail": "Admin access required"})
                return
            query = parse_qs(parsed.query)
            offset = int(query.get("offset", [0])[0])
            limit = int(query.get("limit", [25])[0])
            self.send_json(200, {
                "items": State.accounts[offset:offset + limit],
                "total": len(State.accounts),
                "limit": limit,
                "offset": offset,
            })
            return
        if parsed.path == "/api/v1/admin/audit-events":
            query = parse_qs(parsed.query)
            offset = int(query.get("offset", [0])[0])
            limit = int(query.get("limit", [25])[0])
            self.send_json(200, {
                "items": State.audit[offset:offset + limit],
                "total": len(State.audit),
                "limit": limit,
                "offset": offset,
            })
            return
        self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if parsed.path == "/api/v1/auth/refresh":
            if not State.authority:
                self.send_json(403, {"detail": "revoked"})
            else:
                self.send_json(200, {
                    "access_token": "s35-rotated-token",
                    "token_type": "bearer",
                    "approval_status": "approved",
                    "platform_role": "admin",
                    "is_admin": False,
                })
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 7 and parts[:4] == ["api", "v1", "admin", "users"]:
            user_id, action = parts[4], parts[5]
            # The split shape includes only six elements for this canonical path.
            del user_id, action
        if len(parts) == 6 and parts[:4] == ["api", "v1", "admin", "users"]:
            user_id, action = parts[4], parts[5]
            target = next((item for item in State.accounts if item["id"] == user_id), None)
            if target is None:
                self.send_json(404, {"detail": "User not found"})
                return
            if target["email"] == "last-admin@s35.invalid":
                self.send_json(409, {"detail": "At least one effective administrator must remain"})
                return
            if target["email"] == "stale@s35.invalid" and not State.stale_attempted:
                State.stale_attempted = True
                target["approval_status"] = "disabled"
                target["restore_target_status"] = "approved"
                target["allowed_actions"] = ["restore"]
                self.send_json(409, {"detail": "Invalid account lifecycle transition"})
                return
            transitions = {
                "approve": "approved",
                "reject": "rejected",
                "disable": "disabled",
                "restore": str(target.get("restore_target_status") or "pending"),
            }
            target["approval_status"] = transitions[action]
            target["restore_target_status"] = "approved" if action == "disable" else None
            target["allowed_actions"] = {
                "approved": ["reject", "disable"],
                "rejected": ["approve", "disable"],
                "disabled": ["restore"],
                "pending": ["approve", "reject", "disable"],
            }[str(target["approval_status"])]
            self.send_json(200, target)
            return
        self.send_json(404, {"detail": "not found"})


def wait_for_url(url: str, timeout: float = 30) -> None:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}")


def session_cookie() -> str:
    command = (
        "cd /d D:\\projects\\plasmaos\\frontend && "
        "set AUTH_SECRET=s35-browser-secret&& node tests\\make-s35-session.mjs"
    )
    result = subprocess.run(
        [CMD, "/d", "/s", "/c", command],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def row(page, email: str):
    return page.locator("tbody tr", has_text=email)


def action(page, email: str, label: str) -> None:
    target = row(page, email)
    target.get_by_role("button", name=label, exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name=f"Confirm {label}", exact=True).click()


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results: list[dict[str, str]] = []
    chrome = r"C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
    profile = r"C:\Users\acer\AppData\Local\Temp\s35-browser-profile"
    launch = (
        f"Start-Process -FilePath '{chrome}' -ArgumentList "
        f"'--headless=new','--disable-gpu','--remote-debugging-address=0.0.0.0',"
        f"'--remote-debugging-port={CDP_PORT}',"
        f"'--user-data-dir={profile}','about:blank'"
    )
    subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            launch,
        ],
        check=True,
    )
    try:
        wait_for_url(f"http://{CDP_HOST}:{CDP_PORT}/json/version")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://{CDP_HOST}:{CDP_PORT}")
            context = browser.contexts[0]
            context.add_cookies([{
                "name": "authjs.session-token",
                "value": session_cookie(),
                "url": BASE_URL,
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})
            page.goto(f"{BASE_URL}/admin/approvals", wait_until="networkidle")
            page.get_by_role("heading", name="Accounts & approvals").wait_for()

            action(page, "pending@s35.invalid", "Approve")
            row(page, "pending@s35.invalid").get_by_text("Approved", exact=True).wait_for()
            results.append({"case": "pending -> approve", "result": "passed"})

            action(page, "approved@s35.invalid", "Disable")
            row(page, "approved@s35.invalid").get_by_text("Disabled", exact=True).wait_for()
            results.append({"case": "approved -> disable", "result": "passed"})

            row(page, "known-restore@s35.invalid").get_by_role("button", name="Restore").click()
            page.get_by_role("dialog").get_by_text("return to Approved", exact=False).wait_for()
            page.get_by_role("dialog").get_by_role("button", name="Confirm Restore").click()
            row(page, "known-restore@s35.invalid").get_by_text("Approved", exact=True).wait_for()
            results.append({"case": "known provenance -> restore", "result": "passed"})

            action(page, "rejected@s35.invalid", "Approve")
            row(page, "rejected@s35.invalid").get_by_text("Approved", exact=True).wait_for()
            results.append({"case": "rejected -> approve", "result": "passed"})

            self_row = row(page, "current-admin@s35.invalid")
            assert self_row.get_by_role("button", name="Disable", exact=True).count() == 0
            assert self_row.get_by_role("button", name="Reject", exact=True).count() == 0
            results.append({"case": "self-disable blocked", "result": "passed"})

            action(page, "last-admin@s35.invalid", "Disable")
            page.get_by_role("alert").get_by_text("last active administrator", exact=False).wait_for()
            row(page, "last-admin@s35.invalid").get_by_text("Approved", exact=True).wait_for()
            results.append({"case": "last-admin denial", "result": "passed"})

            action(page, "stale@s35.invalid", "Disable")
            page.get_by_role("alert").get_by_text("changed after this page loaded", exact=False).wait_for()
            row(page, "stale@s35.invalid").get_by_text("Disabled", exact=True).wait_for()
            results.append({"case": "stale target 409 recovery", "result": "passed"})

            page.goto(f"{BASE_URL}/admin/audit", wait_until="networkidle")
            row(page, "audit-000@s35.invalid").get_by_text("Success", exact=True).wait_for()
            results.append({"case": "audit SUCCESS", "result": "passed"})
            row(page, "audit-001@s35.invalid").get_by_text("Denied", exact=True).wait_for()
            row(page, "audit-001@s35.invalid").get_by_text("Self-action blocked", exact=True).wait_for()
            results.append({"case": "audit DENIED", "result": "passed"})
            row(page, "audit-002@s35.invalid").get_by_text("Legacy event", exact=False).first.wait_for()
            results.append({"case": "legacy audit event", "result": "passed"})
            page.get_by_role("button", name="Next", exact=True).click()
            page.get_by_text("Page 2 of 5", exact=False).wait_for()
            row(page, "audit-025@s35.invalid").wait_for()
            assert row(page, "audit-000@s35.invalid").count() == 0
            results.append({"case": "audit pagination", "result": "passed"})

            page.goto(f"{BASE_URL}/admin/approvals", wait_until="networkidle")
            State.authority = False
            page.get_by_role("button", name="Refresh", exact=True).click()
            page.wait_for_url(lambda url: "/admin" not in urlparse(url).path, timeout=15000)
            assert page.get_by_role("heading", name="Accounts & approvals").count() == 0
            results.append({"case": "external authority loss", "result": "passed"})
            browser.close()
    finally:
        server.shutdown()
    print(json.dumps({"results": results, "passed": len(results)}, indent=2))
    assert len(results) == 12
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
