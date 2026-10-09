"""R3 error tracking: Sentry is a no-op without a DSN, and nothing private leaves the host.

The end-to-end cases run in a subprocess (Sentry patches logging and Starlette globally) with
a capturing transport instead of the network, and check the serialized envelopes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from app.core.observability import scrub_breadcrumb, scrub_event, scrub_text

BACKEND = Path(__file__).resolve().parent
DOCUMENT_TEXT = (
    "The Consultant shall deliver the feasibility study for the Tashkent water network "
    "rehabilitation, including hydraulic modelling of zones 4-7 and a resettlement plan."
)
EMAIL = "jane.doe@client-firm.example"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.c2lnbmF0dXJlLXZhbHVlLWZvci10ZXN0cw"


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SENTRY_")}
    environment.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=environment,
                          capture_output=True, text=True, timeout=180)


def test_scrub_text_redacts_emails_tokens_and_quoted_document_text() -> None:
    message = (
        f"upload failed for {EMAIL}: Authorization: Bearer abcdefghijklmnop1234 token={JWT} "
        f"api_key=sk_live_0123456789abcdef password='hunter22' "
        f"postgresql://plasma:s3cret@db:5432/plasma_ai text '{DOCUMENT_TEXT}'"
    )
    scrubbed = scrub_text(message, limit=10_000)
    for secret in (EMAIL, "abcdefghijklmnop1234", JWT, "sk_live_0123456789abcdef", "hunter22", "s3cret", DOCUMENT_TEXT[:40]):
        assert secret not in scrubbed, secret
    assert "[email]" in scrubbed and "[redacted text]" in scrubbed
    validation = f"1 validation error for Requirement\nquote\n  Input should be short [type=string_too_long, input_value='{DOCUMENT_TEXT}', input_type=str]"
    assert DOCUMENT_TEXT[:30] not in scrub_text(validation)
    assert scrub_text("ab1 " * 2000).endswith("…[truncated]") and len(scrub_text("ab1 " * 2000)) < 400
    assert scrub_text("a" * 64) == "[redacted token]"  # hex/base64-looking secrets
    assert scrub_text("Tender 7f0c3a52-0d7c-4b61-9b8e-2b1d8c6b0a11 not found") == "Tender 7f0c3a52-0d7c-4b61-9b8e-2b1d8c6b0a11 not found"


def test_scrub_event_drops_bodies_headers_locals_user_and_sensitive_keys() -> None:
    event = {
        "request": {
            "method": "POST", "url": f"https://api.example/api/v1/pursuits/1/documents?email={EMAIL}&token=abc",
            "data": {"text": DOCUMENT_TEXT}, "cookies": {"session": "abc"}, "query_string": f"email={EMAIL}",
            "headers": {"Authorization": f"Bearer {JWT}", "Cookie": "a=b", "User-Agent": "pytest", "X-Organization-ID": "org"},
            "env": {"REMOTE_ADDR": "10.0.0.1"},
        },
        "user": {"id": "u1", "email": EMAIL, "ip_address": "10.0.0.1"},
        "exception": {"values": [{
            "type": "ValueError", "value": f"cannot parse '{DOCUMENT_TEXT}' for {EMAIL}",
            "stacktrace": {"frames": [{"function": "parse", "vars": {"document_text": DOCUMENT_TEXT}}]},
        }]},
        "logentry": {"message": "failed for %s", "params": [EMAIL]},
        "extra": {"notice_text": DOCUMENT_TEXT, "tender_id": "T-1", "nested": {"api_key": "k", "count": 3}},
        "contexts": {"celery_job": {"args": [DOCUMENT_TEXT], "task_name": "app.workers.x"}},
        "breadcrumbs": {"values": [{"message": f"GET {EMAIL}", "data": {"url": "https://u:p@host/x?q=1", "body": DOCUMENT_TEXT}}]},
    }
    scrubbed = scrub_event(event, {})
    dumped = json.dumps(scrubbed)
    for secret in (DOCUMENT_TEXT[:30], EMAIL, JWT, "a=b", "10.0.0.1", "token=abc", "u:p@"):
        assert secret not in dumped, secret
    assert scrubbed["request"] == {"method": "POST", "url": "https://api.example/api/v1/pursuits/1/documents",
                                   "headers": {"User-Agent": "pytest"}}
    assert "user" not in scrubbed
    assert "vars" not in scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert scrubbed["exception"]["values"][0]["type"] == "ValueError"       # what failed stays visible
    assert scrubbed["extra"]["tender_id"] == "T-1" and scrubbed["extra"]["nested"]["count"] == 3
    assert scrubbed["extra"]["notice_text"] == "[Filtered]" and scrubbed["extra"]["nested"]["api_key"] == "[Filtered]"
    crumb = scrub_breadcrumb({"message": "ok", "data": {"url": "https://u:p@host/x?q=1"}})
    assert crumb["data"]["url"] == "https://host/x"


def test_without_a_dsn_error_tracking_is_a_no_op() -> None:
    result = _run(
        "import sys\n"
        "import app.main, app.core.celery_app\n"
        "from app.core.observability import init_error_tracking\n"
        "from app.core.celery_app import init_worker_error_tracking, init_beat_error_tracking\n"
        "init_worker_error_tracking(); init_beat_error_tracking()\n"
        "print(init_error_tracking('backend'), 'sentry_sdk' in sys.modules)\n",
        ENVIRONMENT="test",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False False"  # not even imported


_E2E = r'''
import json, logging, sys
import sentry_sdk
from sentry_sdk.transport import Transport
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.core.observability import init_error_tracking

class Capture(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.payloads = []
    def capture_envelope(self, envelope):
        for item in envelope.items:
            self.payloads.append(item.payload.get_bytes().decode("utf-8", "replace"))

capture = Capture()
assert init_error_tracking("backend", transport=capture)
app = FastAPI()

@app.post("/api/v1/pursuits/{pursuit_id}/documents")
async def upload(pursuit_id: str, request: Request):
    body = await request.body()
    document_text = body.decode()
    raise ValueError(f"cannot parse '{document_text}' uploaded by {request.headers['x-uploader']}")

client = TestClient(app, raise_server_exceptions=False)
response = client.post("/api/v1/pursuits/7/documents?email=" + sys.argv[2], content=sys.argv[1],
                       headers={"Authorization": "Bearer " + sys.argv[3], "x-uploader": sys.argv[2],
                                "Cookie": "authjs.session-token=" + sys.argv[3]})
assert response.status_code == 500
logging.getLogger("app.workers.private_document_tasks").error("scan failed for %s: %s", sys.argv[2], sys.argv[1])
def worker_task(document_text):
    try:
        raise RuntimeError("extraction failed")
    except RuntimeError:
        sentry_sdk.capture_exception()
worker_task(sys.argv[1])
sentry_sdk.flush(5)
print(json.dumps(capture.payloads))
'''


def test_enabled_sentry_sends_release_environment_and_no_private_content() -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SENTRY_")}
    environment.update({
        "SENTRY_DSN_BACKEND": "https://publickey@sentry.example.invalid/42",
        "PLASMA_BUILD_SHA": "4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d", "ENVIRONMENT": "production",
    })
    result = subprocess.run([sys.executable, "-c", _E2E, DOCUMENT_TEXT, EMAIL, JWT], cwd=BACKEND, env=environment,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr[-3000:]
    payloads = json.loads(result.stdout.strip().splitlines()[-1])
    events = [json.loads(item) for item in payloads
              if item.startswith("{") and ('"exception"' in item or '"logentry"' in item)]
    assert len(events) >= 3, payloads  # the API error, the logged error, the worker exception
    everything = "\n".join(payloads)
    for secret in (DOCUMENT_TEXT[:25], "hydraulic modelling", EMAIL, JWT, "authjs.session-token"):
        assert secret not in everything, secret
    for event in events:
        assert event["release"] == "4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d"
        assert event["environment"] == "production"
        assert "user" not in event or not event["user"]
    api_error = next(event for event in events if event.get("request"))
    assert "data" not in api_error["request"] and "cookies" not in api_error["request"]
    assert set(api_error["request"]["headers"]) <= {"user-agent", "content-length", "content-type", "host", "accept"} | {
        key.title() for key in ("user-agent", "content-length", "content-type", "host", "accept")}
    assert api_error["exception"]["values"][-1]["type"] == "ValueError"
    assert all("vars" not in frame for event in events for value in event.get("exception", {}).get("values", [])
               for frame in value.get("stacktrace", {}).get("frames", []))
