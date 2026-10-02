# Rollout: pilot/week1 (D1-01 analyzer, D1-03 official notices, D1-04/05 freshness and deadline truth, D1-06 one door, D1-09 ops, OPS-1 host safety, integration fixes)

Status: prepared, **not executed**. Run staging first; production only after staging passes every
step.

**Deploy 1 (first production release from `a275357`) uses `DEPLOY_1_RUNBOOK.md`**: the
`a275357` checkout has no `scripts/ops/` and no `compose-release.sh tag|import`, so there the
checkout (files only) must come before the backup, the tag and the import; there is no staging
VM (the owner's PC is the build host) and no Storage Box yet (the backup goes to the laptop).
This document stays the reference for later releases, when production already runs this tooling. All commands run from the repository checkout on the target host, in order. `$` lines are
commands; everything else is a check you must see before going on.

Hosts: **production** is the Hetzner VM (checkout `/opt/plasma-console/plasmaos`, today `main` at
`a275357`, 2 vCPU / 3.7 GiB / 38 GB). **Production never builds images** (it has neither the memory
nor the disk: on-host builds pushed it into swap and left ~14 GB of old images and build cache).
Images are built on the **build host** (staging, or a developer machine with Docker) and streamed
to production with `scripts/compose-release.sh export | ssh prod ... import`.

What ships:

| Change | Runtime effect | Schema / data |
| --- | --- | --- |
| D1-03 official notice | Tenders with a substantive notice get one shared `OFFICIAL_NOTICE` tender document (created by source refresh and by the backfill) | Migration `20261003_0001_d1_03_official_notice_unique`: one partial unique index on `tender_documents`; additive, reversible, no data change. Backfill writes rows. |
| D1-01 analyzer | Pursuit analysis: length-based model routing, retries, budgets, provider error classes, exact-source contexts, worker concurrency 2 | None (new runs record `pursuit_analysis_pipeline_d1_v3`) |
| D1-09 ops | Staging stack, Caddy, backup/restore/smoke scripts, pgAdmin only with `--profile tools`, ClamAV watchdog, SHA-tagged release images | None |
| D1-04 / D1-05 freshness and deadline truth | Scheduled source refresh (Beat, `SOURCE_REFRESH_SCHEDULE`); ADB hidden from customers; "Not published" budgets; deadlines shown as published with their time basis; open/closed derived from the deadline | None (no migration; the notice header text changes, so step 9 updates notices) |
| D1-06 one door | One "Open workspace" action on Explorer, Tender Details and the dashboard (Prepare Bid and score strings removed); fact chips with truthful days left | None |
| OPS-1 host safety | Memory limits and OOM priorities per service (host profile 4gb/8gb), Celery per-child memory caps, Postgres memory settings, pursuit worker concurrency 1 on 4gb; off-host image build/transfer; streaming off-host backup; disk report and safe prune | None. The new `command`/`oom_score_adj` for `db` and `redis` recreate them (a few seconds of downtime); **Deploy 1 leaves them untouched** and applies this later as Deploy 1b (`DEPLOY_1_RUNBOOK.md`). |
| Integration fixes | (a) A deadline published without a zone uses the capital zone of the tender's country ("country-inferred"); with no country it stays open as "Closing — verify on source" until the latest possible instant (UTC−12) has passed (locally 684 → 694 open). (b) A refresh that saved rows and then lost the connection is recorded `partial` with its true counts and counts as fresh data ("Partial refresh"); World Bank and GIZ retry a connection error once. (c) A provider account error fails the analysis run at once (no retries). (d) "Matches your profile" leaves out tenders the organization dismissed; the Explorer service filter uses the same whole-word rule. (e) 4gb profile: `worker_private_documents` 384m, `worker_heavy` 256m. Frontend: next 16.3.8, axios 1.20.0 (security advisories). `smoke_account.py` for the live smoke. | None |

Alembic head after this release: `20261003_0001_d1_03_official_notice_unique` (single head).

## 0. Before the window (both environments)

1. **Publish the release (owner-approved).** The owner reviews and approves the merge of the pilot
   branches into `pilot/week1` and its push; nothing is merged or pushed without that approval.
   `$ git push origin pilot/week1` (from the machine that holds the approved merge), then everywhere:
   `$ git fetch origin && SHA=$(git rev-parse origin/pilot/week1) && echo $SHA`
   The release gate passed on exactly `$SHA` (`scripts/run_release_gate.sh all`).
2. Check which build is running now and record it in the deploy ticket as the rollback point:
   `$ PREV_SHA=$(curl -fsS http://127.0.0.1:8000/health | python3 -c 'import json,sys; print(json.load(sys.stdin)["build_sha"])') && echo $PREV_SHA`
   (production today: `a275357...`).
3. Check the database is at the revision this release expects to upgrade from:
   `$ docker compose exec -T backend alembic current` → `20261002_0001_p0_extraction_trust_gate (head)`.
   If it shows anything else, stop: the release was built against that revision.
4. **Host checks (production)**. All must hold before going on:
   ```
   $ free -m                                   # "available" >= 700 MiB; swap used not growing
   $ scripts/ops/disk_report.sh --threshold 80 # exit 0: / at most 80 % used (after any prune)
   $ scripts/ops/prune_safe.sh                 # dry run: review; it keeps the running and previous release
   $ scripts/ops/prune_safe.sh --apply --keep $PREV_SHA   # only if disk_report failed
   $ docker inspect -f '{{.State.Health.Status}} oom={{.State.OOMKilled}}' plasma_clamav   # healthy oom=false
   $ docker ps --format '{{.Names}} {{.Ports}}' | grep -v '127.0.0.1' | grep -E -- '->' ; echo "public ports above: expected none (Caddy 80/443 only)"
   $ docker ps --format '{{.Names}}' | grep -c pgadmin                    # 0 is the target; step 8 removes it if it runs
   ```
   The import in step 5 needs about 5 GB free for a new release's layers (shared layers are not
   duplicated); disk must stay at or below 80 % afterwards.
5. The AI key for the environment has a budget alert (staging uses its own key).
6. `BACKUP_REMOTE` (Hetzner Storage Box or S3) is configured on production and a backup has
   succeeded off-host (see step 1 below and `PRODUCTION_READINESS.md` section 4).

## 1. Backup to the remote (restore point, before any migration)

```
$ BACKUP_REMOTE=ssh://uNNNNNN@uNNNNNN.your-storagebox.de:23/./plasma \
    scripts/ops/backup.sh --target production --skip-tender-documents   # staging: --target staging
```

`BACKUP_REMOTE` is normally set in the deploy user's environment (or cron line) rather than typed.
The script refuses to run without it. Database and private documents always go off-host;
`--skip-tender-documents` leaves out the 3.8 GB of public, re-acquirable tender documents (the
weekly scheduled run includes them). Only the database dump (~110 MB) touches local disk; the
archives stream straight to the remote and every component is re-hashed there.

Expect one `remote sha256 verified` line per component and a final
`BACKUP_RESULT set=plasma_prod_<UTC>_<hash> seconds=... bytes=...`. Record the set name as
`RESTORE_POINT` in the ticket; the dump is also kept locally as `backups/<RESTORE_POINT>.dump`.
If the production Compose project is not named after the checkout directory, prefix with
`PROD_COMPOSE_PROJECT=<name>`.

## 2. Pull the release (checkout only: compose file, profiles, scripts)

On production the checkout moves from `main` (`a275357`) to the approved `pilot/week1`. It must be
clean (`git status --porcelain` prints nothing), so the checkout matches the images.

```
$ git status --porcelain            # nothing
$ git fetch origin
$ git checkout -B pilot/week1 origin/pilot/week1
$ test "$(git rev-parse HEAD)" = "$SHA"
```

## 3. Tag the running images (first release with SHA tags only)

The running images predate SHA tagging. Nothing has been imported yet, so `:latest` is still the
running build; give it a tag so rollback is a tag switch:

```
$ scripts/compose-release.sh tag $PREV_SHA
$ scripts/compose-release.sh images                        # plasma-<service>:$PREV_SHA for all 7 built services
```

`tag` uses the SHA recorded inside each image; `$PREV_SHA` is only used for images that record
none (the old `worker_pursuit_analysis` image was built without the SHA build arguments).
`scripts/ops/prune_safe.sh` never removes these: they are in use, and after the release they are
the previous release in `.release-history` (pass `--keep $PREV_SHA` as well to be explicit).

## 4. Environment additions (`.env`)

Add or replace these lines. The API key must be the environment's own key (production and
staging never share one). Nothing else in `.env` changes.

```
# Host (OPS-1). Production only: this host never builds images.
PLASMA_NO_BUILD=1
# Memory profile: 4gb today, 8gb after the Hetzner resize (section "Resize" below).
# It sets the per-service memory limits, Celery per-child caps, Postgres memory settings
# PURSUIT_ANALYSIS_WORKER_CONCURRENCY (1 on 4gb, 2 on 8gb) and CELERY_WORKER_CONCURRENCY (2).
HOST_PROFILE=4gb

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
# PURSUIT_ANALYSIS_WORKER_CONCURRENCY comes from the host profile; remove any line for it here.

# Scheduled source refresh (D1-04).
# <source>=<N>m|h|d, comma separated; unset = this default; empty = disabled. An unknown,
# hidden (adb) or repeated source stops worker, Beat and API at startup.
# Production:
SOURCE_REFRESH_SCHEDULE=world_bank=6h,uzex=6h,ebrd=24h,giz=24h
# Staging (.env.staging): every source once a day, to spare the live sources:
# SOURCE_REFRESH_SCHEDULE=world_bank=24h,uzex=24h,ebrd=24h,giz=24h
# Optional: wait before the single retry of a World Bank / GIZ connection error
# (0-30 s, default 5, plus up to 1 s jitter). Leave unset.
# SOURCE_CONNECT_RETRY_BACKOFF_SECONDS=5
```

`PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS=900` overrides the code default of 480. It is safe with
the lease: the worker renews its 300 s lease every 60 s for the whole run, and the Celery
task has no time limit (acks late, Redis visibility timeout 3600 s).
`PURSUIT_ANALYSIS_WORKER_CONCURRENCY` is read by Compose (worker command line). It comes from
`deploy/host-profiles/<HOST_PROFILE>.env`, which `compose-release.sh` passes after `.env`, so the
profile wins over a stale `.env` line. Staging sets `HOST_PROFILE` in `.env.staging` (and never
`PLASMA_NO_BUILD`, since staging is the build host).
`SOURCE_REFRESH_SCHEDULE` is read by Beat, the workers and the API (they share `.env`). Beat
ticks every `SOURCE_REFRESH_SCHEDULE_TICK_SECONDS` (default 300) per source and starts a
refresh only when that source's latest attempt is one cadence old, through the same durable
job path as the refresh buttons (`trigger_kind = scheduled`, no requesting user). A source
whose last success is older than twice its cadence shows "Stale" in the refresh menu.

Check the configuration renders and the profile applies:

```
$ scripts/compose-release.sh config --quiet
$ scripts/compose-release.sh config | grep -E 'mem_limit|concurrency=' | head    # 4gb: worker_pursuit_analysis --concurrency=1
```

## 5. Build on the build host, import on production (no restart yet)

On the **build host** (staging, or a developer machine), from a clean checkout of `$SHA`:

```
build$ git checkout $SHA && git status --porcelain            # nothing
build$ scripts/compose-release.sh build-only                  # "built and tagged plasma-<service>:$SHA"
build$ scripts/compose-release.sh export $SHA \
         | ssh deploy@<prod-host> 'cd /opt/plasma-console/plasmaos && scripts/compose-release.sh import --expect $SHA'
```

`export` streams `docker save` of the seven images through gzip (shared layers once: about 1.5-2 GB
compressed); `import` runs `docker load`, which verifies every layer digest, then checks that every
service has `plasma-<service>:$SHA`. Nothing is written to disk on either side except Docker's own
image store. From a staging VM in the same Hetzner location the transfer takes a few minutes; from
a developer laptop it depends on the uplink (export to a file first and `rsync --partial` it if the
link is unreliable: `export $SHA > r.tgz`, then `ssh prod '... import --expect $SHA' < r.tgz`).

On **production**, point the stack at the imported images without restarting anything:

```
$ scripts/compose-release.sh images                           # plasma-<service>:$SHA and :$PREV_SHA
$ scripts/compose-release.sh use $SHA                         # "images switched to $SHA; nothing was restarted"
```

The running containers keep their old images until step 8 recreates them. With `PLASMA_NO_BUILD=1`
any `build`/`--build` is refused, and `up`/`run` refuse if an image is missing instead of building it.

Optional registry path (not required): push `plasma-<service>:$SHA` to a private GHCR repository
from the build host (`docker login ghcr.io` with a token that has `write:packages`; tag
`ghcr.io/<org>/plasma-<service>:$SHA`), then on production `docker pull` with a read-only token and
`docker tag` back to `plasma-<service>:$SHA` before `use $SHA`. It adds a credential to manage on
production and is only worth it once several hosts need the same images.

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

`up $SHA --no-deps <service>` checks the images, keeps `:latest` on `$SHA`, and runs
`up -d --no-build --no-deps <service>`: exactly the named services are recreated, with the new
image and the host profile's memory limits. Each step waits for the previous one.

```
# pgAdmin must not run in production (it only starts with --profile tools now).
$ docker rm -f plasma_pgadmin 2>/dev/null; docker ps -a --format '{{.Names}}' | grep -c pgadmin    # 0

# Database and Redis: recreated once for the new command/oom_score_adj (OPS-1). The data volumes
# are untouched; the API and workers reconnect. Expect a few seconds of database downtime.
$ scripts/compose-release.sh up $SHA --no-deps db redis
$ until docker exec plasma_db pg_isready -q; do sleep 2; done

# ClamAV: new entrypoint (watchdog), ConcurrentDatabaseReload=no, 1.5 GiB limit on 4gb.
# Uploads wait for it while it loads signatures (about 2 minutes locally).
$ scripts/compose-release.sh up $SHA --no-deps clamav
$ until [ "$(docker inspect -f '{{.State.Health.Status}}' plasma_clamav)" = healthy ]; do sleep 10; done

# Workers
$ scripts/compose-release.sh up $SHA --no-deps celery_worker worker_heavy worker_private_documents worker_pursuit_analysis
# Beat (exactly one instance)
$ scripts/compose-release.sh up $SHA --no-deps celery_beat
# API
$ scripts/compose-release.sh up $SHA --no-deps backend
$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done
# Frontend
$ scripts/compose-release.sh up $SHA --no-deps frontend

# Limits and memory after the restart
$ docker inspect -f '{{.Name}} {{.HostConfig.Memory}} oom_adj={{.HostConfig.OomScoreAdj}}' $(docker ps -q)
$ docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' && free -m
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
```

**Dedicated smoke account (first release only; idempotent afterwards).** The live smoke writes
one pursuit and one analysis run, so it runs only in a single-member organization named
"Plasma Smoke Test". `smoke_account.py` creates it: an approved user
`plasma-smoke-test@plasma.invalid` that cannot sign in with Google (reserved domain, non-Google
subject), its approved company profile, and the profile's organization with that user as the
only member. Both approvals are written to the admin audit log (actor `SERVER_COMMAND`). The
account shows in the admin user list; leave it there for later smokes.

```
$ scripts/compose-release.sh run --rm --no-deps backend python scripts/smoke_account.py ensure
#   report only: {"status": "would_create", ...} (or "exists")
$ scripts/compose-release.sh run --rm --no-deps backend python scripts/smoke_account.py ensure --apply --confirm CREATE_SMOKE_ACCOUNT
#   {"status": "created", "organization_id": "<SMOKE_ORG_ID>", "organization_name": "Plasma Smoke Test"}
$ SMOKE_ORG_ID=<organization_id from the line above>
```

**Live analysis smoke (one real provider call).** The token lives 60 minutes, is captured into the
environment without being printed (`compose-release.sh` prints its settings first; the token is
the last line), and is never passed on the command line:

```
$ export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
$ python3 backend/scripts/analysis_smoke.py --live --api-base https://<API_DOMAIN>/api/v1 \
    --org-id $SMOKE_ORG_ID --org-name "Plasma Smoke Test"
$ unset ANALYSIS_SMOKE_TOKEN
```

The live smoke refuses to run unless the token's user belongs to exactly that one organization
and is its only active member; `smoke_account.py` refuses to mint a token or change anything if
someone else was added to it, or if the e-mail belongs to an account it did not create. It picks
the first open World Bank REOI with an official notice and must end
`live analysis smoke: OK` (COMPLETED, READY_FOR_REVIEW, at least 5 requirements).

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
$ scripts/ops/smoke.sh --target production --expect-sha $PREV_SHA
```

Keep the `pilot/week1` checkout: its compose file and host profile apply the memory limits to the
old images too, and its `compose-release.sh` is what performs the no-build rollback. Returning the
checkout to `main` (`a275357`) would drop the limits and the no-build guard; do not do it as part
of a rollback.

Leave `.env` as it is (older builds ignore the D1 and OPS-1 variables).
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

## Resize to 8 GB / 80 GB (Hetzner), when the owner decides

The configuration works on both sizes; only `HOST_PROFILE` changes. Plan a 15-30 minute window.

1. Off-host backup including tender documents: `$ scripts/ops/backup.sh --target production`
   (expect `BACKUP_RESULT ... tender_documents=included`). Record the set.
2. Stop the stack cleanly: `$ scripts/compose-release.sh stop` (containers keep their volumes).
3. Power off: `$ sudo shutdown -h now`, and wait until the Cloud Console shows the server **off**.
4. Cloud Console → server → **Rescale**: choose the 8 GB type and leave **"CPU and RAM only"
   unchecked** so the disk grows to 80 GB. A disk upgrade is permanent (the server can never be
   rescaled back to a smaller disk); "CPU and RAM only" keeps 38 GB and stays reversible.
5. Power on. Check the root file system grew: `$ df -h /` (≈ 75-80 GB). If it did not:
   `$ sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1`.
   Check memory: `$ free -m` (≈ 7.6 GiB total).
6. Set `HOST_PROFILE=8gb` in `.env`, then recreate with the new limits (same images, no build):
   `$ scripts/compose-release.sh up $(tail -n 1 .release-history | cut -d' ' -f2)` (the running SHA).
   The containers restart with `restart: always` at boot anyway; this step applies the 8gb limits,
   Postgres settings and pursuit concurrency 2.
7. Smoke (step 10) and `$ scripts/ops/disk_report.sh`.

To go back to 4gb before rescaling down (only possible with "CPU and RAM only"), set
`HOST_PROFILE=4gb` and repeat step 6 first.

## Final command list (production, 4gb, no build on the host)

The same commands as the steps above, in order, for the operator's terminal. `prod$` runs in
`/opt/plasma-console/plasmaos` on production; `build$` on the build host. Times are local
measurements or estimates (see the table below); the production window from step 1 to step 10
is about 20 minutes, plus the transfer in step 5.

```
# 0. Before the window                                                         ~3 min
prod$  git fetch origin && SHA=$(git rev-parse origin/pilot/week1) && echo $SHA
prod$  PREV_SHA=$(curl -fsS http://127.0.0.1:8000/health | python3 -c 'import json,sys; print(json.load(sys.stdin)["build_sha"])') && echo $PREV_SHA
prod$  docker compose exec -T backend alembic current          # 20261002_0001_p0_extraction_trust_gate (head)
prod$  free -m && scripts/ops/disk_report.sh --threshold 80 && scripts/ops/prune_safe.sh
prod$  docker ps --format '{{.Names}}' | grep -c pgadmin        # expect 0 (removed in step 8 otherwise)
# 1. Off-host backup (DB + private documents)                                  ~1-2 min
prod$  scripts/ops/backup.sh --target production --skip-tender-documents     # BACKUP_REMOTE from the environment; record RESTORE_POINT
# 2. Checkout                                                                  seconds
prod$  git status --porcelain && git checkout -B pilot/week1 origin/pilot/week1 && test "$(git rev-parse HEAD)" = "$SHA"
# 3. Tag the running images                                                    seconds
prod$  scripts/compose-release.sh tag $PREV_SHA && scripts/compose-release.sh images
# 4. .env: PLASMA_NO_BUILD=1, HOST_PROFILE=4gb, pursuit variables, SOURCE_REFRESH_SCHEDULE  ~2 min
prod$  scripts/compose-release.sh config --quiet
prod$  scripts/compose-release.sh config | grep -E 'mem_limit|concurrency=' | head
# 5. Build elsewhere, import, point at the new images                         ~11 min build + transfer
build$ git checkout $SHA && scripts/compose-release.sh build-only
build$ scripts/compose-release.sh export $SHA | ssh deploy@<prod-host> 'cd /opt/plasma-console/plasmaos && scripts/compose-release.sh import --expect $SHA'
prod$  scripts/compose-release.sh use $SHA
# 6. Migration                                                                 ~15 s
prod$  scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$  scripts/compose-release.sh run --rm --no-deps backend alembic current   # 20261003_0001_d1_03_official_notice_unique (head)
# 7. Backfill report                                                           ~30 s
prod$  scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py
# 8. Restart in order (pgAdmin removed, never started)                         ~3-4 min
prod$  docker rm -f plasma_pgadmin 2>/dev/null; docker ps -a --format '{{.Names}}' | grep -c pgadmin   # 0
prod$  scripts/compose-release.sh up $SHA --no-deps db redis && until docker exec plasma_db pg_isready -q; do sleep 2; done
prod$  scripts/compose-release.sh up $SHA --no-deps clamav && until [ "$(docker inspect -f '{{.State.Health.Status}}' plasma_clamav)" = healthy ]; do sleep 10; done
prod$  scripts/compose-release.sh up $SHA --no-deps celery_worker worker_heavy worker_private_documents worker_pursuit_analysis
prod$  scripts/compose-release.sh up $SHA --no-deps celery_beat
prod$  scripts/compose-release.sh up $SHA --no-deps backend && until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done
prod$  scripts/compose-release.sh up $SHA --no-deps frontend
# 9. Backfill apply (only now: the new API is serving)                          ~45 s
prod$  scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py --apply --confirm BACKFILL_OFFICIAL_NOTICES
prod$  scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py   # created 0
# 10. Smoke                                                                    ~5 min
prod$  scripts/ops/smoke.sh --target production --expect-sha $SHA --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$  scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$  scripts/compose-release.sh run --rm --no-deps backend python scripts/smoke_account.py ensure --apply --confirm CREATE_SMOKE_ACCOUNT
prod$  SMOKE_ORG_ID=<organization_id printed above>
prod$  export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
prod$  python3 backend/scripts/analysis_smoke.py --live --api-base https://<API_DOMAIN>/api/v1 --org-id $SMOKE_ORG_ID --org-name "Plasma Smoke Test"
prod$  unset ANALYSIS_SMOKE_TOKEN
prod$  scripts/ops/disk_report.sh --threshold 80 && free -m
# Rollback, if needed (section 11)                                             ~1 min
prod$  scripts/compose-release.sh rollback $PREV_SHA && scripts/ops/smoke.sh --target production --expect-sha $PREV_SHA
```

The Hetzner resize to 8 GB (section "Resize" above) is optional and separate: not in this window.

## Expected durations

Measured on the local stack (developer laptop, Docker Desktop, 3.7 GB VM); migration and backfill on a disposable copy of the local database. Production will differ
with its data size and CPU; staging gives the real numbers.

| Step | Local measurement | Customer impact |
| --- | --- | --- |
| 1 Backup: database (112 MB dump) | 35 s | none |
| 1 Backup: document volumes (4.6 GB archive) | 8 min | none |
| 5 Build on the build host (`build-only`) | 11 min (648 s, while the release gate ran alongside; expect less on an idle host) | none |
| 5 Export → import (seven images, shared layers) | minutes from a same-location staging VM; depends on the uplink from elsewhere | none |
| 6 Migration (`upgrade head`, 1,356 open tenders / 3,651 documents) | 2 s including interpreter start (downgrade 1 s) | none |
| 7 Backfill report | 21 s (would create 578: World Bank 564, GIZ 13, EBRD 1; UzEx 0 substantive) | none |
| 8 Restart sequence | about 3 min: containers 15 s, API ready 30 s, ClamAV healthy 130 s (signature load) | uploads wait for ClamAV (about 2 min); API/frontend blips of a few seconds |
| 9 Backfill apply | 28 s for 578 notices; confirming re-run 12 s, created 0 | none |
| 10 Smoke (`smoke.sh`, read-only `analysis_smoke.py`) | about 1 min | none |
| 10 Smoke account (`smoke_account.py ensure --apply`, `token`) | about 10 s each (container start) | none |
| 10 Live analysis smoke (one run) | 1-2 min (fails above `--max-latency`, default 60 s of analysis) | none; one provider call billed to the environment's key |
| Code rollback | about 1 min (no build) | a few seconds per service |
| Restore from backup | database ~1 min per 100 MB of dump, documents ~5 min per 5 GB | full outage |
