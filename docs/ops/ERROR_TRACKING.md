# Error tracking (Sentry)

Unhandled errors of the API, the Celery workers and Beat, the Next.js server and the browser go
to Sentry, **only when a DSN is configured**. Without the variables nothing is loaded: the Python
SDK is not even imported, the browser never downloads the SDK (tested).

| Variable | Read by | Default |
| --- | --- | --- |
| `SENTRY_DSN_BACKEND` | backend, celery_worker, worker_heavy, worker_private_documents, worker_pursuit_analysis, celery_beat (from `.env`) | unset = off |
| `SENTRY_DSN_FRONTEND` | frontend container (compose passes it from `.env`); server and browser | unset = off |
| `ENVIRONMENT` | Sentry `environment` (backend already had it; compose now passes it to the frontend) | `production` |
| `PLASMA_BUILD_SHA` | Sentry `release` (baked into every image) | from the image |

## What leaves the host, and what never does

Sent: exception type, stack trace (file, function, line, our source lines), release, environment,
component tag (`backend`, `celery_worker`, …, `frontend`, `frontend-browser`), request method and
path, a short scrubbed message.

Never sent (`backend/app/core/observability.py`, `frontend/lib/errorTracking.ts`, same rules):
request bodies (`max_request_body_size="never"`, and `request.data` is dropped), cookies,
`Authorization` and every other non-allowlisted header, query strings, user data, IP addresses,
local variables of stack frames (`include_local_variables=False`, and `vars` is stripped), the
process command line, performance traces (`traces_sample_rate=0`, transactions dropped).
In every message, exception value, breadcrumb and extra field: e-mail addresses → `[email]`;
bearer/basic tokens, JWTs, `password=`/`token=`/`api_key=`… values, URL credentials and long
hex/base64 strings → `[redacted …]`; quoted strings of 40+ characters, validation errors'
`input_value=…` and any run of ten or more words (document text) → `[redacted text]`; keys such as
`text`, `content`, `body`, `document`, `notice`, `prompt`, `email`, `token` → `[Filtered]`;
everything truncated to 300 characters. Tested end to end with a capturing transport: an API error
whose body, message and headers carry a document passage, an e-mail address and a JWT, a logged
error and a worker exception: none of them appears in the envelopes (`backend/test_r3_error_tracking.py`,
`frontend/tests/r3-error-tracking.test.mjs`).

## Enable (owner, optional, any time after Deploy 3)

1. https://sentry.io → create an organization (EU data region) → two projects: **plasma-backend**
   (platform Python/FastAPI) and **plasma-frontend** (Next.js). Copy each project's DSN
   (Settings → Client Keys). Free plan: 5k errors/month.
2. Project settings, both projects: Security & Privacy → **Data Scrubber on**, **Use Default
   Scrubbers on**, **Prevent Storing of IP Addresses on** (a second line of defence).
3. On the host:
   ```
   prod$ cp -p .env .env.pre-sentry
   prod$ printf '\n# --- error tracking (R3) ---\nSENTRY_DSN_BACKEND=<backend DSN>\nSENTRY_DSN_FRONTEND=<frontend DSN>\n' >> .env
   ```
   then the pre-stop gate and recreate the app services with the running images (DEPLOY_3_RUNBOOK.md,
   optional step "Sentry").
4. Check: the logs show `error_tracking_enabled component=backend`; in Sentry, Issues stays empty
   until a real error happens. To prove delivery once:
   `prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import app.main, sentry_sdk; sentry_sdk.capture_message('plasma sentry check'); sentry_sdk.flush(5)"`
   and look for "plasma sentry check" in plasma-backend.
Disable: remove the two lines from `.env` and recreate the app services (or restore `.env.pre-sentry`).
