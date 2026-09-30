# Rollout: pilot/week1 (D1-01 analyzer reliability, D1-03 official notices, D1-09 ops)

Status: prepared, **not executed**. Run staging first; production only after staging passes every
step. All commands run from the repository checkout on the target host, in order. `$` lines are
commands; everything else is a check you must see before going on.

What ships:

| Change | Runtime effect | Schema / data |
| --- | --- | --- |
| D1-03 official notice | Tenders with a substantive notice get one shared `OFFICIAL_NOTICE` tender document (created by source refresh and by the backfill) | Migration `20261003_0001_d1_03_official_notice_unique`: one partial unique index on `tender_documents`; additive, reversible, no data change. Backfill writes rows. |
| D1-01 analyzer | Pursuit analysis: length-based model routing, retries, budgets, provider error classes, exact-source contexts, worker concurrency 2 | None (new runs record `pursuit_analysis_pipeline_d1_v3`) |
| D1-09 ops | Staging stack, Caddy, backup/restore/smoke scripts, pgAdmin only with `--profile tools`, ClamAV watchdog, SHA-tagged release images | None |
| D1-04 / D1-05 (`pilot/d1-04-freshness`, when included) | Scheduled source refresh (Beat, `SOURCE_REFRESH_SCHEDULE`); ADB hidden from customers; "Not published" budgets; deadlines shown as published with their time basis; open/closed derived from the deadline | None (no migration; the notice header text changes, so step 9 updates notices) |

Alembic head after this release: `20261003_0001_d1_03_official_notice_unique` (single head).

## 0. Before the window (both environments)

1. The release gate passed on the exact commit (`scripts/run_release_gate.sh all`); note it:
   `$ git fetch origin && SHA=$(git rev-parse origin/pilot/week1) && echo $SHA`
2. Check which build is running now and record it in the deploy ticket as the rollback point:
   `$ PREV_SHA=$(curl -fsS http://127.0.0.1:8000/health | python3 -c 'import json,sys; print(json.load(sys.stdin)["build_sha"])') && echo $PREV_SHA`
3. Check the database is at the revision this release expects to upgrade from:
   `$ docker compose exec -T backend alembic current` → `20261002_0001_p0_extraction_trust_gate (head)`.
   If it shows anything else, stop: the release was built against that revision.
4. Free disk: the backup needs about the size of the database plus the document volumes, and the
   build about 5 GB of images. `$ df -h / && docker system df`.
5. The AI key for the environment has a budget alert (staging uses its own key).

## 1. Backup (restore point)

```
$ scripts/ops/backup.sh --target production        # staging: --target staging
```

Expect `backup set written: backups/plasma_prod_<UTC>_<hash>.*` with a `.dump`, a `.files.tar.gz`
and a `.sha256`, and `copied off-host to ...` (set `BACKUP_REMOTE` first; without it the script warns
that the copy exists only on this host). Record the set name as `RESTORE_POINT` in the ticket.
If the production Compose project is not named after the checkout directory, prefix with
`PROD_COMPOSE_PROJECT=<name>`.

## 2. Pull the release

```
$ git fetch origin
$ git checkout -B pilot/week1 origin/pilot/week1
$ test "$(git rev-parse HEAD)" = "$SHA"
```

## 3. Tag the running images (first release with SHA tags only)

The running images predate SHA tagging. Nothing has been built yet, so `:latest` is still the
running build; give it a tag so rollback is a tag switch:

```
$ scripts/compose-release.sh tag $PREV_SHA
$ scripts/compose-release.sh images                        # plasma-<service>:$PREV_SHA for all 7 built services
```

`tag` uses the SHA recorded inside each image; `$PREV_SHA` is only used for images that record
none (the old `worker_pursuit_analysis` image was built without the SHA build arguments).

## 4. Environment additions (`.env`)

Add or replace these lines. The API key must be the environment's own key (production and
staging never share one). Nothing else in `.env` changes.

```
# Pursuit analysis (D1 build)
GEMINI_PURSUIT_LONG_PACK_CHARS=60000
GEMINI_PURSUIT_MODEL=gemini-3.8-flash
GEMINI_PURSUIT_FALLBACK_MODELS=gemini-3.7-flash,gemini-3.1-pro-preview
GEMINI_PURSUIT_LONG_MODEL=gemini-3.1-pro-preview
GEMINI_PURSUIT_LONG_FALLBACK_MODELS=gemini-3.8-flash
GEMINI_PURSUIT_MODEL_TIMEOUTS=gemini-3.1-pro-preview=150
GEMINI_PURSUIT_TIMEOUT_SECONDS=90
GEMINI_PURSUIT_MAX_OUTPUT_TOKENS=32768
GEMINI_PURSUIT_CHUNK_CHARS=100000
GEMINI_PURSUIT_LONG_CHUNK_CHARS=100000
PURSUIT_ANALYSIS_CHUNK_CONCURRENCY=3
PURSUIT_ANALYSIS_CHUNK_BUDGET_SECONDS=240
PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS=900
PURSUIT_ANALYSIS_WORKER_CONCURRENCY=2

# Scheduled source refresh (D1-04; read by builds that include pilot/d1-04-freshness).
# <source>=<N>m|h|d, comma separated; unset = this default; empty = disabled. An unknown,
# hidden (adb) or repeated source stops worker, Beat and API at startup.
# Production:
SOURCE_REFRESH_SCHEDULE=world_bank=6h,uzex=6h,ebrd=24h,giz=24h
# Staging (.env.staging): every source once a day, to spare the live sources:
# SOURCE_REFRESH_SCHEDULE=world_bank=24h,uzex=24h,ebrd=24h,giz=24h
```

`PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS=900` overrides the code default of 480. It is safe with
the lease: the worker renews its 300 s lease every 60 s for the whole run, and the Celery
task has no time limit (acks late, Redis visibility timeout 3600 s).
`PURSUIT_ANALYSIS_WORKER_CONCURRENCY` is read by Compose (worker command line), so it must be
in `.env`, which `compose-release.sh` passes as `--env-file`.
`SOURCE_REFRESH_SCHEDULE` is read by Beat, the workers and the API (they share `.env`). Beat
ticks every `SOURCE_REFRESH_SCHEDULE_TICK_SECONDS` (default 300) per source and starts a
refresh only when that source's latest attempt is one cadence old, through the same durable
job path as the refresh buttons (`trigger_kind = scheduled`, no requesting user). A source
whose last success is older than twice its cadence shows "Stale" in the refresh menu.

Check the configuration renders: `$ scripts/compose-release.sh config --quiet`.

## 5. Build (no restart yet)

```
$ scripts/compose-release.sh build
```

The running containers are not touched. At the end the script prints
`tagged plasma-<service>:$SHA` for backend, frontend, celery_worker, worker_heavy,
worker_private_documents, worker_pursuit_analysis and celery_beat.

## 6. Migration

Run with the new image, while the old containers keep serving (the index is additive and the
old code never writes `OFFICIAL_NOTICE`):

```
$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
$ scripts/compose-release.sh run --rm --no-deps backend alembic current     # 20261003_0001_d1_03_official_notice_unique (head)
```

If the index build fails on duplicate rows (it cannot on a database that never had
`OFFICIAL_NOTICE` rows), stop and investigate. Nothing needs undoing: the migration is one
statement.

## 7. Backfill: report only

```
$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py
```

Read the per-source report (tenders, substantive notices, would create, would update,
unchanged, below threshold). Nothing is written. Record the counts in the ticket.

## 8. Restart, in order

`--no-deps` restarts exactly the named services; each step waits for the previous one.

```
# ClamAV first: new entrypoint (watchdog) and ConcurrentDatabaseReload=no.
# Uploads wait for it while it loads signatures (about 2 minutes locally).
$ scripts/compose-release.sh up -d --no-deps --no-build clamav
$ until [ "$(docker inspect -f '{{.State.Health.Status}}' plasma_clamav)" = healthy ]; do sleep 10; done

# Workers
$ scripts/compose-release.sh up -d --no-deps --no-build celery_worker worker_heavy worker_private_documents worker_pursuit_analysis
# Beat (exactly one instance)
$ scripts/compose-release.sh up -d --no-deps --no-build celery_beat
# API
$ scripts/compose-release.sh up -d --no-deps --no-build backend
$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done
# Frontend
$ scripts/compose-release.sh up -d --no-deps --no-build frontend
```

Workers and Beat go first so no new-API request enqueues work that only an old worker would
pick up; the frontend goes last so it never calls an API older than itself.

## 9. Backfill: apply

After the new API is serving (step 8): the old API would show `OFFICIAL_NOTICE` rows as
ordinary downloadable documents, so the backfill is applied only once no old code is serving.

```
$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py --apply --confirm BACKFILL_OFFICIAL_NOTICES
$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py   # re-run report: created 0
```

The apply counts must match the report from step 7 (source refresh may have created a few in
between). A second run creates nothing.

With `pilot/d1-04-freshness` the notice header prints the deadline as published ("17:00 local
time (as published)" instead of "17:00 UTC"), so the apply *updates* every existing notice
once (locally: 577 updated, 1 unchanged because that EBRD notice has no deadline line, 0 created) and analysis runs sealed on the old text show the
"inputs changed" banner. That is expected.

## 10. Smoke

```
$ scripts/ops/smoke.sh --target production --expect-sha $SHA \
    --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
# End to end, one real provider call, only in the dedicated single-member test organization
# (the script refuses anything else); the token is read from the environment, never argv:
$ ANALYSIS_SMOKE_TOKEN=<smoke user token> python3 backend/scripts/analysis_smoke.py --live --api-base https://<API_DOMAIN>/api/v1 --org-id <test org id> --org-name "<exact test org name>"
```

`smoke.sh` must report zero failures (health and build SHA, release metadata, readiness, frontend,
containers, Postgres, Redis, Alembic at head, all five queues consumed, Beat ticking, clamd PING,
signature age). `analysis_smoke.py` is read-only (no provider call): it prints the resolved
SHORT/LONG routes, budgets (run 900 s), whether a key is configured, and run health (no RUNNING
run with an expired lease, nothing queued for more than 15 minutes). Then by hand: sign in, open a
tender with an official notice, upload a small PDF to a test pursuit (CLEAN then READY), and on
staging run one pursuit analysis.

Staging: the same steps with `scripts/ops/compose-staging.sh` in place of
`scripts/compose-release.sh`, `--target staging` for the ops scripts, and the staging URLs.
Optionally refresh staging from production first (`scripts/ops/restore_to_staging.sh --migrate`),
which also rehearses step 6 on production data.

## 11. Rollback

Decide within 15 minutes of a failed smoke or a customer-visible error.

**Code rollback (default).** The schema change is additive, so the previous build runs on the new
schema.

```
$ scripts/compose-release.sh rollback $PREV_SHA      # retags plasma-<service>:$PREV_SHA to :latest, up -d --no-build
$ git checkout $PREV_SHA                               # so a later build does not bring the release back
$ scripts/ops/smoke.sh --target production --expect-sha $PREV_SHA
```

Restore the previous `.env` too, or leave the D1 variables in place (older builds ignore them).
`OFFICIAL_NOTICE` rows written by the backfill stay; the previous build lists them as ordinary
tender documents. If that is not acceptable, use the database rollback below rather than deleting
them (sealed analysis packs may reference them).

**Schema rollback (rarely needed; the old build does not need it):** run it *before*
`rollback`, while `:latest` is still the new image, because older images do not contain the
migration file:
`$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261002_0001_p0_extraction_trust_gate`
(drops the index only).

**Database restore point (last resort; loses everything written since step 1):** stop the app
services, restore `RESTORE_POINT` (`pg_restore --clean --if-exists --no-owner` from
`backups/<RESTORE_POINT>.dump`, per `PRODUCTION_READINESS.md` section 10 D), then the code
rollback above. Never `docker compose down -v`.

## Expected durations

Measured on the local stack (developer laptop, Docker Desktop, 3.7 GB VM); migration and backfill on a disposable copy of the local database. Production will differ
with its data size and CPU; staging gives the real numbers.

| Step | Local measurement | Customer impact |
| --- | --- | --- |
| 1 Backup: database (112 MB dump) | 35 s | none |
| 1 Backup: document volumes (4.6 GB archive) | 8 min | none |
| 5 Build (all images, `compose-release.sh build`) | 11 min (648 s, while the release gate ran alongside; expect less on an idle host) | none |
| 6 Migration (`upgrade head`, 1,356 open tenders / 3,651 documents) | 2 s including interpreter start (downgrade 1 s) | none |
| 7 Backfill report | 21 s (would create 578: World Bank 564, GIZ 13, EBRD 1; UzEx 0 substantive) | none |
| 8 Restart sequence | about 3 min: containers 15 s, API ready 30 s, ClamAV healthy 130 s (signature load) | uploads wait for ClamAV (about 2 min); API/frontend blips of a few seconds |
| 9 Backfill apply | 28 s for 578 notices; confirming re-run 12 s, created 0 | none |
| 10 Smoke | about 1 min | none |
| Code rollback | about 1 min (no build) | a few seconds per service |
| Restore from backup | database ~1 min per 100 MB of dump, documents ~5 min per 5 GB | full outage |
