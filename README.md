# Plasma AI (plasmaos)

Plasma AI helps consulting firms find and prepare bids for public tenders, with a focus on
Central Asia. It collects notices from UzEx (Uzbekistan's e-procurement exchange), the World
Bank, ADB, EBRD and GIZ. It analyses tender documents and private uploads with Google Gemini,
extracting requirements, required positions and compliance risks with verbatim quotes. It
matches them against a firm's own experts, experience and documents. The interface is
available in English, Uzbek, Russian and Arabic (Arabic analysis output is gated).

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI application (`app/`), Alembic migrations (`alembic/`), Celery workers, scripts (`scripts/`, see `scripts/README.md`), tests (`test_*.py` at this level), the evaluation harness (`evaluation/`) |
| `frontend/` | Next.js 16 / React 19 application with next-auth and next-intl; messages in `messages/{en,uz,ru,ar}` |
| `deploy/` | Caddy proxy, ClamAV, systemd units, host profiles |
| `scripts/` | Release gate (`run_release_gate.sh`), release compose wrapper, operations scripts (`ops/`) |
| `docs/` | Sprint and feature documents; `docs/ops/` runbooks; `docs/audits/` evidence |
| `db/` | Monitoring SQL views |
| `docker-compose*.yml` | Main stack, TLS proxy overlay, isolated staging overlay |

## Stack

* Python 3.12 (the CI version) with FastAPI, SQLAlchemy (async, asyncpg), Alembic, Celery,
  `google-genai` 0.3.0, PyMuPDF and Tesseract OCR. Dependencies:
  `backend/requirements.txt`, pinned by `backend/constraints.txt`.
* Node 22.14.0 (the CI version) with Next.js 16.4.3, React 19.2.3, next-auth 5 (beta) and
  next-intl.
* PostgreSQL 16, Redis 7, ClamAV 1.4. The Compose file also has optional pgAdmin under the
  `tools` profile.

## Running locally with Docker Compose

The stack in `docker-compose.yml` has these services: db, redis, clamav, backend,
frontend, and five Celery services (`celery_worker`, `worker_heavy`,
`worker_private_documents`, `worker_pursuit_analysis`, `celery_beat`).

1. Create a `.env` file in the repository root. It is gitignored; never commit it. No
   local example file is tracked. `.env.staging.example` lists and explains the variables
   (for staging).
   * Compose refuses to start without `POSTGRES_PASSWORD`, `AUTH_SECRET`,
     `AUTH_BRIDGE_SECRET`, `NEXTAUTH_URL` and `BACKEND_CORS_ORIGINS`.
   * The backend settings (`backend/app/core/config.py`) also require `POSTGRES_SERVER`,
     `POSTGRES_USER`, `POSTGRES_DB`, `SECRET_KEY` and `TELEGRAM_BOT_TOKEN`.
   * Analysis needs `GEMINI_API_KEY`.
   * Generate secrets with `openssl rand -base64 48`.
2. Start the stack:

   ```bash
   docker compose up -d --build
   ```

   Ports are bound to loopback only: frontend 3000, backend 8000, PostgreSQL 6543,
   Redis 6379.
3. Database schema. An empty database is bootstrapped from the immutable baseline, then
   migrated. See `backend/scripts/bootstrap_database.py` (it refuses any non-empty
   database and any non-loopback host unless explicitly allowed), then run
   `alembic upgrade head`. Do not use the old `init_db.py`, `reset_db.py`, `add_*.py`
   or `seed_*.py` scripts as a setup path (`backend/scripts/README.md`).

Production and staging deployment are documented in `docs/ops/`. Start with
`PRODUCTION_READINESS.md`, `HOST_SETUP.md` and the latest `DEPLOY_*_RUNBOOK.md`.

## Tests

The CI workflow `.github/workflows/release-gate.yml` runs `scripts/run_release_gate.sh all`
on pull requests. It uses a disposable PostgreSQL 16 and Redis 7 and synthetic secrets (the
workflow's `env:` block lists them). Locally:

```bash
python -m pip install -r backend/requirements-test.txt
```

```bash
python -m playwright install --with-deps chromium
```

```bash
PLASMA_RELEASE_TEST_CONFIRM=DISPOSABLE_LOCAL_ONLY bash scripts/run_release_gate.sh all
```

The gate refuses to run without that confirmation and expects a disposable local
PostgreSQL and Redis, as in CI. Run one group by naming it instead of `all`: `backend`,
`security`, `analysis`, `connectors`, `migrations`, `performance`, `frontend`, `browser`
or `config-dependencies`.

Backend tests alone, from `backend/` with the same environment variables as CI:

```bash
python -m pytest -q
```

Many backend tests use the disposable PostgreSQL and Redis. Without them those tests fail
with connection errors.

Frontend checks, from `frontend/`:

```bash
npm ci
```

```bash
npm run typecheck && npm run lint
```

```bash
node --no-warnings --experimental-strip-types --test tests/*.test.mjs
```

## Evaluation of requirement extraction (English, Russian, Uzbek)

`backend/evaluation/` scores requirement extraction against a hand-labelled set of 35
public tender notices (12 English, 12 Russian, 11 Uzbek). The set is a **draft** until a
procurement expert has reviewed it. Offline scoring needs no API key; live runs use the
operator's own key and an explicit confirmation flag.

* Harness: `backend/evaluation/README.md`
* Labelled set: `backend/evaluation/datasets/req_eval_v0_draft/README.md`
* What is measured, bias checks and results: `docs/M3_EVAL_READINESS.md`

## Data and secrets

* `.env`, `.env.staging` and `.env.production` are gitignored. Never commit real secrets;
  CI uses synthetic values only.
* Private uploads are stored under `.private-storage/` (gitignored). The D1 model bench
  writes only counts to `docs/audits/d1/`; source text and model output stay in
  `.private-storage/`.

## Licence

The repository has no licence file. Choosing a licence is an open decision for the
project's owners.
