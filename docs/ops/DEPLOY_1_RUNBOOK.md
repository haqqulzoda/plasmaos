# Deploy 1 runbook: production a275357 → pilot/week1 0bea1f1

For the owner, copy-paste on the production host. Every step has the command, what you must
see, and a **STOP** condition. On a STOP: do not continue; if the stack was already restarted
(step 11 or later), go to **Rollback**; otherwise nothing has changed for customers.

| | |
| --- | --- |
| Release | `pilot/week1` @ `0bea1f1ffc624b58a49b429c50055962e2cf47cd` (release gate green at 460ba6d; 0bea1f1 adds only the celery_worker pool size, verified) |
| Running today | `main` @ `a2753573191fc82ff9b403148c2183291bda94bf` |
| Host | Hetzner 2 vCPU / 3.7 GiB / 38 GB, checkout `/opt/plasma-console/plasmaos`, **HOST_PROFILE=4gb** (no resize in Deploy 1) |
| Images | built on the owner's PC, bundle `plasma-release-0bea1f1.tar.gz`, **1,494,896,613 bytes (1.4 GiB)**, sha256 `73cc838f91fd1a99f2f2be1d7e3f2843da5d5234e7668c37165a57191d80d1d4` |
| Migration | one additive index, `20261003_0001_d1_03_official_notice_unique` |
| Customer impact | a few seconds of database restart and API/frontend blips in step 11; uploads wait ~2 min for ClamAV |
| Window | about 30 minutes plus the transfer (step 6) |

Conventions: `prod$` runs on the production host in `/opt/plasma-console/plasmaos` as the user
that owns the stack (the one that runs `docker`). `laptop$` runs on the owner's PC in Git Bash.
Replace `<prod>` with the ssh target of the server (e.g. `root@203.0.113.10`), `<APP_DOMAIN>` and
`<API_DOMAIN>` with the public domains.

**Order differs from ROLLOUT_WEEK1.md on purpose:** production's `a275357` checkout has no
`scripts/ops/` and its `compose-release.sh` has no `tag`/`import`, so the checkout (files only;
nothing restarts) comes before the backup and the import.

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ SHA=0bea1f1ffc624b58a49b429c50055962e2cf47cd
prod$ PREV_SHA=a2753573191fc82ff9b403148c2183291bda94bf
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```
Expect: `"build_sha":"a2753573191fc82ff9b403148c2183291bda94bf"`.
**STOP** if the build SHA is anything else: production is not the state this runbook was written for.

## 1. Pre-checks (nothing changes)

```
prod$ git status --porcelain; git rev-parse HEAD
```
Expect: no file lines, then `a2753573…`. **STOP** if files are listed (local edits on the host;
save `git diff` and ask) or the SHA differs.

```
prod$ free -h
```
Expect: `available` of at least ~700Mi. **STOP** if below 500Mi (find what is using memory first).

```
prod$ df -h /
```
Expect: `Avail` ≥ 10G (bundle ~2 GB + loaded images ~5 GB + backup). If less, remove build
cache and dangling images only, then check again:
`prod$ docker builder prune -f && docker image prune -f && df -h /`
**STOP** if still below 10G.

```
prod$ docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}} {{.Config.Image}}' plasma_backend
```
Expect: `plasmaos plasmaos-backend`. **STOP** if the project is not `plasmaos` (all scripts
address the stack by that name).

```
prod$ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' plasma_frontend | grep '^NEXT_PUBLIC_API_URL='
```
Expect: `NEXT_PUBLIC_API_URL=/api/v1`. **STOP** if different (the bundle's frontend is built for `/api/v1`).

```
prod$ docker exec plasma_backend alembic current
```
Expect: `20261002_0001_p0_extraction_trust_gate (head)`. **STOP** otherwise.

```
prod$ docker inspect -f '{{.State.Health.Status}} oom={{.State.OOMKilled}}' plasma_clamav
```
Expect: `healthy oom=false`. If `unhealthy`/`starting`: note it and continue (step 11 replaces
ClamAV's entrypoint with the watchdog and gives it 1.5 GiB).

```
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
```
Expect: `7` (rollback tags already present) or less; step 3 creates the missing ones. Not a stop here.

```
prod$ docker ps -a --format '{{.Names}}' | grep pgadmin; docker rm -f plasma_pgadmin 2>/dev/null; docker ps -a --format '{{.Names}}' | grep -c pgadmin
```
Expect: last line `0` (pgAdmin is never started in production; it now needs `--profile tools`).

```
prod$ docker exec plasma_backend du -sh /app/private-data
```
Expect: a small size (~200K today). Note it; the backup in step 4 writes it to disk once.

## 2. Check out the release (files only, nothing restarts)

```
prod$ git fetch origin pilot/week1
prod$ git checkout -B pilot/week1 "$SHA"
prod$ test "$(git rev-parse HEAD)" = "$SHA" && echo CHECKOUT_OK
prod$ ls scripts/ops/backup.sh scripts/ops/smoke.sh deploy/host-profiles/4gb.env
prod$ docker ps --format '{{.Names}} {{.Status}}' | head -3
```
Expect: `CHECKOUT_OK`, the three paths, and containers still showing their old uptime.
**STOP** if the fetch fails or `CHECKOUT_OK` is missing (go back: `git checkout main`).

## 3. Rollback tags for the running build

```
prod$ scripts/compose-release.sh tag "$PREV_SHA"
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
```
Expect: `tagged plasma-<service>:a2753573…` lines, then `7`. `tag` reads the SHA recorded in
each running image; `$PREV_SHA` is used only for an image that records none.
**STOP** if the count is below 7: there would be no complete rollback point.

## 4. Off-host backup: database + private documents → laptop

No Storage Box yet: the set is written to a directory on the host, then copied to the laptop
and verified there. Tender documents (public, re-downloadable) are skipped.

```
prod$ BACKUP_REMOTE=file:///var/backups/plasma scripts/ops/backup.sh --target production --skip-tender-documents
```
Expect: `remote sha256 verified` lines and a last line
`BACKUP_RESULT set=plasma_prod_<UTC>_<hash> seconds=… bytes=… tender_documents=skipped remote=file:///var/backups/plasma`.
**STOP** on any error. Record the set name:

```
prod$ SET=<the set= value>          # e.g. plasma_prod_20261002T090000Z_0123456789ab
prod$ ls -l /var/backups/plasma/$SET.*
```
Expect: `.dump`, `.private.tar.gz`, `.sha256`, `.manifest`.

On the laptop:
```
laptop$ PROD=<prod>; SET=<same set name>
laptop$ mkdir -p /d/plasma-backups && scp "$PROD:/var/backups/plasma/$SET.*" /d/plasma-backups/
laptop$ cd /d/plasma-backups && sha256sum -c "$SET.sha256"
```
Expect: `…dump: OK` and `…private.tar.gz: OK`. **STOP** if anything is not `OK` or scp fails:
without a verified off-host copy there is no database restore point.

## 5. Host size (decided: stay on 4gb)

Deploy 1 runs on the current 4 GB server with `HOST_PROFILE=4gb`. The resize to 8 GB is a
separate, later window (`ROLLOUT_WEEK1.md`, section "Resize to 8 GB / 80 GB"): stop the stack,
power off, Cloud Console → Rescale (8 GB type, leave "CPU and RAM only" unchecked to grow the disk),
power on, check `df -h /` and `free -m`, set `HOST_PROFILE=8gb`, `scripts/compose-release.sh up <running SHA>`.
Nothing to do in this window.

## 6. Transfer the image bundle

```
laptop$ scp /d/plasma-release/plasma-release-0bea1f1.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-0bea1f1.tar.gz
```
Expect: `73cc838f91fd1a99f2f2be1d7e3f2843da5d5234e7668c37165a57191d80d1d4`. **STOP** if it differs (copy again).

## 7. `.env` additions

Open `.env` (`prod$ nano .env`), keep everything that is there, remove any existing line for
`PURSUIT_ANALYSIS_WORKER_CONCURRENCY`, and append:

```
# --- Deploy 1 (pilot/week1) ---
# Host: production never builds images; memory profile for the 3.7 GiB server.
PLASMA_NO_BUILD=1
HOST_PROFILE=4gb
# Pool size of celery_worker (the 4gb profile sets the same value; never the CPU count).
CELERY_WORKER_CONCURRENCY=2

# Pursuit analysis (D1)
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

# Scheduled source refresh (D1-04)
SOURCE_REFRESH_SCHEDULE=world_bank=6h,uzex=6h,ebrd=24h,giz=24h
```

```
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit' | sort | uniq -c
```
Expect: `CONFIG_OK`, then exactly:
```
      3       - --concurrency=1          (worker_heavy, worker_private_documents, worker_pursuit_analysis)
      1       - --concurrency=2          (celery_worker)
      1     mem_limit: "134217728"       (frontend 128m)
      1     mem_limit: "1610612736"      (clamav 1.5 GiB)
      1     mem_limit: "167772160"       (celery_beat 160m)
      1     mem_limit: "268435456"       (worker_heavy 256m)
      1     mem_limit: "301989888"       (worker_pursuit_analysis 288m)
      1     mem_limit: "335544320"       (backend 320m)
      2     mem_limit: "402653184"       (celery_worker, worker_private_documents 384m)
```
**STOP** on any error (a missing variable is named in it) or different numbers (wrong `HOST_PROFILE`).

## 8. Import the images

```
prod$ scripts/compose-release.sh import --expect "$SHA" < /opt/plasma-console/plasma-release-0bea1f1.tar.gz
```
Expect: seven `Loaded image: plasma-<service>:0bea1f1…` lines, `import finished in N s`, then
`every service has plasma-<service>:0bea1f1…`. **STOP** on `import incomplete` or a load error
(corrupt copy: repeat step 6). Then free the disk:

```
prod$ rm /opt/plasma-console/plasma-release-0bea1f1.tar.gz && df -h /
```
Expect: `Use%` at most 80 %. **STOP** above 90 %.

## 9. Point the stack at the new images and migrate (no restart)

```
prod$ scripts/compose-release.sh use "$SHA"
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic current
```
Expect: `images switched to 0bea1f1…; nothing was restarted`, then
`Running upgrade 20261002_0001_p0_extraction_trust_gate -> 20261003_0001_d1_03_official_notice_unique`,
then `20261003_0001_d1_03_official_notice_unique (head)`. The old containers keep serving.
**STOP** if the upgrade fails (nothing to undo: it is one statement; old code runs on either schema).

## 10. Official-notice backfill: report only

```
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py
```
Expect: a per-source table (tenders, substantive notices, would create / update / unchanged)
and `Report only: nothing was written`. Record the totals. **STOP** on an exception.

## 11. Restart in order

Each line waits for the previous one. `up $SHA --no-deps <service>` recreates exactly those
services with the new image and the 4gb limits.

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps db redis
prod$ until docker exec plasma_db pg_isready -q; do sleep 2; done; echo DB_READY
```
Expect: `DB_READY` within ~30 s. **STOP → Rollback** if not ready after 2 minutes.

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps clamav
prod$ until [ "$(docker inspect -f '{{.State.Health.Status}}' plasma_clamav)" = healthy ]; do sleep 10; done; echo CLAMAV_HEALTHY
```
Expect: `CLAMAV_HEALTHY` within ~2-5 minutes (signature load). If it is not healthy after
10 minutes, check `docker inspect -f 'oom={{.State.OOMKilled}}' plasma_clamav`; uploads are
affected, browsing is not: continue, and report it.

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps celery_worker worker_heavy worker_private_documents worker_pursuit_analysis
prod$ scripts/compose-release.sh up "$SHA" --no-deps celery_beat
prod$ scripts/compose-release.sh up "$SHA" --no-deps backend
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
```
Expect: `"build_sha":"0bea1f1ffc624b58a49b429c50055962e2cf47cd"` within ~1 minute.
**STOP → Rollback** if `/health/ready` is not OK after 3 minutes.

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps frontend
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ docker inspect -f '{{.Name}} mem={{.HostConfig.Memory}} oom_adj={{.HostConfig.OomScoreAdj}} restarts={{.RestartCount}}' $(docker ps -q)
prod$ free -h
```
Expect: `FRONTEND_OK`; every app container with a non-zero `mem`, `restarts=0`; `available`
memory above ~400Mi. **STOP → Rollback** if a container keeps restarting
(`restarts` grows over two minutes).

## 12. Official-notice backfill: apply (the new API is serving)

```
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py --apply --confirm BACKFILL_OFFICIAL_NOTICES
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py
```
Expect: apply counts close to step 10 (source refresh may add a few); the deadline header text
changed, so most existing notices are *updated* once. The second run: `would create 0`.
**STOP** on an exception (customers are unaffected; investigate before continuing).

## 13. Smoke

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
```
Expect: `Result: N ok, M warning(s), 0 failure(s)` (a disk warning is acceptable), and
`analysis smoke: OK` with `API key configured: yes` and `budgets … run 900 s`.
**STOP → Rollback** on any smoke failure that is not fixed within 15 minutes.

## 14. Live analysis smoke (one real provider call)

```
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/smoke_account.py ensure --apply --confirm CREATE_SMOKE_ACCOUNT
```
Expect: `{"status": "created", … "organization_id": "<id>", "organization_name": "Plasma Smoke Test"}`.

```
prod$ SMOKE_ORG_ID=<organization_id above>
prod$ export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
prod$ unset ANALYSIS_SMOKE_TOKEN
```
Expect: one JSON line with `"status": "COMPLETED"`, `"quality_state": "READY_FOR_REVIEW"`,
`"requirements"` ≥ 5, then `live analysis smoke: OK` (locally: 21 requirements, 34 s).
A `FAIL` that names the provider (quota, key, timeout) is not a code failure: fix the key or
budget, do not roll back. **STOP → Rollback** if the run fails inside Plasma (a `failure_stage`
other than the provider) or the API returns 5xx.

## 15. Done

```
prod$ scripts/ops/disk_report.sh --threshold 80; free -h; tail -n 3 .release-history
```
Record in the ticket: `SET`, step 10/12 counts, smoke results. Keep `/var/backups/plasma/$SET.*`
until the release has run for a day, then `rm` them (the laptop copy and `backups/$SET.dump` stay).

---

## Rollback

Triggers (decide within 15 minutes): database or API not ready (step 11), a container that
keeps restarting, any `smoke.sh` failure, a live-smoke failure inside Plasma, or a
customer-visible error that did not exist before.

**A. Code rollback (default; the schema change is additive, so the old build runs on it).**
Keep the `pilot/week1` checkout: its compose file applies the memory limits to the old images too.

```
prod$ scripts/compose-release.sh rollback "$PREV_SHA"
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect: `"build_sha":"a2753573…"` and `0 failure(s)`. The `OFFICIAL_NOTICE` rows stay; the
old build lists them as ordinary documents.

**B. Schema rollback (only if the old build fails on the new schema; it should not).**
Run *before* A, while `:latest` is still the new image:
```
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261002_0001_p0_extraction_trust_gate
```

**C. Database restore (last resort; loses everything written since step 4).**
```
prod$ scripts/compose-release.sh stop frontend backend celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat
prod$ docker exec -i plasma_db sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v db="$POSTGRES_DB"' <<'SQL'
DROP DATABASE IF EXISTS :"db" WITH (FORCE);
CREATE DATABASE :"db";
SQL
prod$ docker exec -i plasma_db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' < /var/backups/plasma/$SET.dump
prod$ docker run --rm -i -v plasmaos_private_documents_data:/app/private-data alpine sh -c 'find /app/private-data -mindepth 1 -delete; tar -xzf - -C /app' < /var/backups/plasma/$SET.private.tar.gz
prod$ scripts/compose-release.sh rollback "$PREV_SHA"
```
(If the host copy is gone: `laptop$ scp /d/plasma-backups/$SET.dump /d/plasma-backups/$SET.private.tar.gz "$PROD:/var/backups/plasma/"`.)
Then smoke as in A. Never run `docker compose down -v`.
