# Deploy 1 runbook (v3): production a275357 → pilot/week1, images 0bea1f1

For the owner, copy-paste on the production host. Every step has the command, what you must
see, and a **STOP** condition.

**Situation: no users yet; onboarding starts next week.** Success = the release runs on
production and every feature works. So this runbook trades availability for certainty: the
app is **down for ~10 minutes** during a clean cut-over (steps 9-11: old and new code never run
side by side), every feature is then **proven on production** (steps 12-15, including the
source refreshes and the onboarding path), and problems are **fixed forward** first; the
rollback is **A2, the exact previous state**, with its triggers under Rollback.

| | |
| --- | --- |
| Checkout | `pilot/week1` @ `f7c61fbd36dee77bd5621f5031da1ae6a0096045` (= images' code `0bea1f1` + the R1 4gb profile and docs; no code change) |
| Images | `plasma-<service>:0bea1f1ffc624b58a49b429c50055962e2cf47cd`, bundle `plasma-release-0bea1f1.tar.gz`, **1,494,896,613 bytes (1.4 GiB)**, sha256 `73cc838f91fd1a99f2f2be1d7e3f2843da5d5234e7668c37165a57191d80d1d4`; `/health` reports `build_sha` `0bea1f1…` |
| Running today | `main` @ `a2753573191fc82ff9b403148c2183291bda94bf` |
| Host | Hetzner 2 vCPU / 3.7 GiB / 38 GB, checkout `/opt/plasma-console/plasmaos`, **HOST_PROFILE=4gb** (no resize in Deploy 1) |
| Migration | one additive index, `20261003_0001_d1_03_official_notice_unique` |
| **Not touched** | **`db` and `redis` keep their current containers** (old command, no `oom_score_adj`, no restart). PostgreSQL tuning and their OOM priority are **Deploy 1b** (below), a later rehearsed window. |
| Downtime | the app is stopped from step 9 to step 11 (~10 min; no users yet); no database restart |
| Window | ~45 min to step 11 plus the transfer (step 6), then ~45 min of checks (steps 12-15) |

**Rule for this whole window: every `up` names its services and has `--no-deps`.** Never run
`up` without a service list, `compose-release.sh rollback`, `docker compose up`, `down` or
`restart` here: with the new compose file each of those would also recreate `db`/`redis`
(new `command`, `oom_score_adj`) — that is Deploy 1b. Steps 1, 11 and 16 check that the two
containers are still the original ones.

Conventions: `prod$` runs on the production host in `/opt/plasma-console/plasmaos` as the user
that owns the stack (the one that runs `docker`). `laptop$` runs on the owner's PC in Git Bash.
Replace `<prod>` with the ssh target of the server (e.g. `root@203.0.113.10`), `<APP_DOMAIN>` and
`<API_DOMAIN>` with the public domains.

**Order differs from ROLLOUT_WEEK1.md on purpose:** production's `a275357` checkout has no
`scripts/ops/` and its `compose-release.sh` has no `tag`/`import`/`use`, so the checkout (files
only; nothing restarts) comes before the backup and the import.

**Checkout ≠ image SHA is intended:** `compose-release.sh use|up <SHA>` points every service at
`plasma-<service>:<SHA>` and takes the build metadata from that image, whatever is checked out
(verified locally with checkout `f7c61fbd36dee77bd5621f5031da1ae6a0096045` and images `0bea1f1`: `/health` → `0bea1f1…`,
`smoke.sh --expect-sha 0bea1f1…` → 0 failures). One-off `run` containers simply use `:latest`.

APP services (the only ones this runbook ever recreates):
`clamav celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend`

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=f7c61fbd36dee77bd5621f5031da1ae6a0096045
prod$ SHA=0bea1f1ffc624b58a49b429c50055962e2cf47cd
prod$ PREV_SHA=a2753573191fc82ff9b403148c2183291bda94bf
prod$ APPS="clamav celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```
Expect: `"build_sha":"a2753573191fc82ff9b403148c2183291bda94bf"` (or its 12-character form `a2753573191f`) before step 9, `0bea1f1…` after step 11.
**STOP** before step 9 if it is anything else: production is not the state this runbook was written for.

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
Expect: `Avail` ≥ 10G (bundle ~1.4 GB + loaded images ~5 GB + backup). If less, remove build
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
prod$ grep -cE '^(GEMINI_API_KEY|GOOGLE_API_KEY)=.+' .env
```
Expect: `1` or more (the value is not printed). **STOP** if `0`: pursuit analysis has no key.
Production must use **its own** Gemini key (never the developer or staging key), and that key
must have a **budget alert** in Google AI Studio / Cloud Billing before the window.

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
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy1-dbredis.txt
```
Expect: two lines (today: db `cmd=[postgres]`, both `oom_adj=0`). This file is compared in
steps 11 and 16: the two containers must never change in this window.

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
prod$ git checkout -B pilot/week1 "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls scripts/ops/backup.sh scripts/ops/smoke.sh deploy/host-profiles/4gb.env
prod$ docker ps --format '{{.Names}} {{.Status}}' | head -3
```
Expect: `CHECKOUT_OK`, the three paths, and containers still showing their old uptime.
**STOP** if the fetch fails or `CHECKOUT_OK` is missing (go back: `git checkout main`).

## 3. Rollback tags for the running build

Tag the image each running app container uses with the full previous SHA (tags only; nothing
is restarted or removed). Do not rely on `compose-release.sh tag` here: production's a275357
images record their build SHA in the 12-character form (`a2753573191f`), so `tag` names six of
them `:a2753573191f` and only `worker_pursuit_analysis` (no recorded SHA) gets the full SHA —
seen in Deploy 1. Rollback A/A2 need all seven under the full `$PREV_SHA`.

```
prod$ for s in backend celery_beat celery_worker frontend worker_heavy worker_private_documents worker_pursuit_analysis; do
        docker tag "$(docker inspect -f '{{.Image}}' plasma_$s)" "plasma-$s:$PREV_SHA" && echo "tagged plasma-$s:$PREV_SHA"
      done
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
prod$ for s in backend celery_beat celery_worker frontend worker_heavy worker_private_documents worker_pursuit_analysis; do
        [ "$(docker inspect -f '{{.Image}}' plasma_$s)" = "$(docker image inspect -f '{{.Id}}' plasma-$s:$PREV_SHA)" ] && echo "$s OK" || echo "$s MISMATCH"
      done
```
Expect: seven `tagged …` lines, then `7`, then seven `… OK`.
**STOP** if the count is below 7 or any line says `MISMATCH`: there would be no complete rollback point.
(If `compose-release.sh tag` was already run, its extra `:a2753573191f` tags are harmless.)

## 4. Off-host backup: database + private documents → laptop

No Storage Box yet: the set is written to a directory on the host, then copied to the laptop
and verified there. Tender documents (public, re-downloadable) are skipped. The backup only
reads from the running `db`/`backend` containers.

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
separate, later window (`ROLLOUT_WEEK1.md`, section "Resize to 8 GB / 80 GB"). Nothing to do now.

## 6. Transfer the image bundle

```
laptop$ scp /d/plasma-release/plasma-release-0bea1f1.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-0bea1f1.tar.gz
```
Expect: `73cc838f91fd1a99f2f2be1d7e3f2843da5d5234e7668c37165a57191d80d1d4`. **STOP** if it differs (copy again).

## 7. `.env`: keep a copy, then add

First keep the exact current file (Rollback A2 restores it). It holds secrets: owner-only
permissions, and never `git add` it (it is not covered by `.gitignore`).

```
prod$ cp -p .env .env.pre-deploy1 && chmod 600 .env.pre-deploy1 && cmp .env .env.pre-deploy1 && echo ENV_SAVED
```
Expect: `ENV_SAVED`. **STOP** otherwise.

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
      1     mem_limit: "1610612736"      (clamav 1536m)
      1     mem_limit: "201326592"       (celery_beat 192m)
      2     mem_limit: "268435456"       (frontend 256m, worker_heavy 256m)
      2     mem_limit: "402653184"       (worker_private_documents 384m, worker_pursuit_analysis 384m)
      1     mem_limit: "469762048"       (backend 448m)
      1     mem_limit: "805306368"       (celery_worker 768m)
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

## 9. Stop the app (clean cut-over; db and redis keep running)

No users: stop every app service so old and new code never run side by side, and the
migration and notice backfill run while nothing is serving.

```
prod$ date -u +%T                      # note the cut-over time (step 14 compares against it)
prod$ scripts/compose-release.sh stop $APPS
prod$ docker ps --format '{{.Names}}' | sort
```
Expect: eight `Stopped` lines, then only `plasma_db` and `plasma_redis` running.
**STOP** if `plasma_db` or `plasma_redis` is not running (start them unchanged with
`docker start plasma_db plasma_redis`; never `up` them).
To abort from here without deploying (old containers, old images: exactly as before):
`prod$ for s in $APPS; do docker start plasma_$s; done`

## 10. Switch images, migrate, backfill the official notices

```
prod$ scripts/compose-release.sh use "$SHA"
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic current
```
Expect: `images switched to 0bea1f1…; nothing was restarted`, then
`Running upgrade 20261002_0001_p0_extraction_trust_gate -> 20261003_0001_d1_03_official_notice_unique`,
then `20261003_0001_d1_03_official_notice_unique (head)`.
**STOP → Rollback A2** if the upgrade fails (nothing to undo: it is one additive statement).

```
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py --apply --confirm BACKFILL_OFFICIAL_NOTICES
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/backfill_official_notices.py
```
Expect: a per-source report (would create / update / unchanged; locally ~578 notices, mostly
World Bank), then the apply with the same numbers, then a report with `would create 0` and
`would update 0`. Record the counts. **STOP** on an exception (fix forward: the notices are
an extra document per tender; the release works without them, so you may continue and fix later).

## 11. Start the release (all app services at once)

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ until [ "$(docker inspect -f '{{.State.Health.Status}}' plasma_clamav)" = healthy ]; do sleep 10; done; echo CLAMAV_HEALTHY
```
Expect: eight containers `Recreated`/`Started` (never `plasma_db`/`plasma_redis`); within ~1
minute `"build_sha":"0bea1f1ffc624b58a49b429c50055962e2cf47cd"` and `FRONTEND_OK`;
`CLAMAV_HEALTHY` within ~2-5 minutes (signature load).
**STOP → Rollback A2** if `/health/ready` is not OK after 5 minutes and the backend log
(`docker logs --tail 50 plasma_backend`) does not show an obvious configuration fix.
If ClamAV is not healthy after 10 minutes: continue (only uploads wait), check
`docker inspect -f 'oom={{.State.OOMKilled}}' plasma_clamav`, fix forward.

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy1-dbredis.txt && echo DBREDIS_UNCHANGED
prod$ docker inspect -f '{{.Name}} mem={{.HostConfig.Memory}} oom_adj={{.HostConfig.OomScoreAdj}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ free -h
```
Expect: `DBREDIS_UNCHANGED`; the eight app containers with the step 7 limits and `restarts=0`
(db/redis `mem=0 oom_adj=0`, as before); `available` above ~400Mi.
**STOP** if `DBREDIS_UNCHANGED` is missing (report it; data is safe on its volume).
**STOP → fix forward or Rollback A2** if a container keeps restarting (`restarts` grows over
two minutes): `docker logs --tail 80 plasma_<service>` first.

## 12. Smoke

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
```
Expect: `Result: N ok, M warning(s), 0 failure(s)` (a disk warning is acceptable), and
`analysis smoke: OK` with `API key configured: yes` and `budgets … run 900 s`.
On a failure: the line names the check; fix forward (container, queue, Beat, ClamAV, public URL).

## 13. Live analysis smoke (one real provider call)

```
prod$ scripts/compose-release.sh run --rm --no-deps backend python scripts/smoke_account.py ensure --apply --confirm CREATE_SMOKE_ACCOUNT
```
Expect: `{"status": "created", … "organization_id": "<id>", "organization_name": "Plasma Smoke Test"}`.

`analysis_smoke.py --live` needs only the Python standard library (proven with
`python3 -I -S` on Python 3.10 and 3.14), so the host's `python3` runs it; the token is passed
in the environment only:

```
prod$ SMOKE_ORG_ID=<organization_id above>
prod$ export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 -I -S backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
prod$ unset ANALYSIS_SMOKE_TOKEN
```
If the host has no `python3`, run the same inside the backend container (token from the environment):
`prod$ scripts/compose-release.sh exec -T -e ANALYSIS_SMOKE_TOKEN backend python scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300`

Expect: one JSON line with `"status": "COMPLETED"`, `"quality_state": "READY_FOR_REVIEW"`,
`"requirements"` ≥ 5, then `live analysis smoke: OK` (locally: 7-22 requirements, 15-44 s).
A `FAIL` that names the provider (quota, key, timeout) is fixed in `.env` / the key's budget;
a failure inside Plasma (`failure_stage` other than the provider, or an API 5xx) is a
**STOP → fix forward or Rollback A2**.

## 14. Every source refreshes completely under the 4gb limits

The scheduler starts a refresh for each source whose latest attempt is older than its cadence
(checked every 5 minutes), so World Bank, UzEx, EBRD and GIZ refresh within ~10 minutes of
step 11 unless one ran recently. This is the heaviest memory case (a World Bank refresh peaks
at ~560 MiB in `celery_worker`; it never completed at the old 384m limit), so prove it now:

```
prod$ for i in $(seq 1 60); do
        docker exec plasma_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F " " -c "select distinct on (source_system) source_system, status, trigger_kind, created_at::timestamp(0), completed_at::timestamp(0) from source_refresh_jobs order by source_system, created_at desc"' > /tmp/refresh.txt
        echo; date -u +%T; cat /tmp/refresh.txt; docker inspect -f 'celery_worker oom={{.State.OOMKilled}} restarts={{.RestartCount}}' plasma_celery_worker
        grep -qE ' (queued|running) ' /tmp/refresh.txt || break; sleep 30
      done
```
Expect, within ~30 minutes: one line per source (`ebrd`, `giz`, `uzex`, `world_bank`), each
`completed` with a `created_at` after the step 9 cut-over time (or a recent `completed` from
before), and `celery_worker oom=false restarts=0`. A source whose latest job predates the
cut-over: start one from the app's source refresh menu in step 15 and re-run the loop.
**STOP → fix forward** if a job stays `running` for more than 20 minutes or `oom=true`:
```
prod$ docker logs --since 30m plasma_celery_worker 2>&1 | grep -E 'SIGKILL|WorkerLostError|ERROR' | tail -20
prod$ PLASMA_MEM_CELERY_WORKER=1024m scripts/compose-release.sh up "$SHA" --no-deps celery_worker   # a shell variable overrides the profile
```
then watch the loop again and report the numbers (the profile is updated in the repository).
`source_unavailable` for a source means the source itself was unreachable: retry later, not a release problem.

## 15. Feature check in the browser (every customer path)

Use the admin Google account on `https://<APP_DOMAIN>` (a private window), and for the
onboarding path a second, personal test Google account. **Not** the demo account
`support.plasma@gmail.com`: the demo seed sets that one up later. Tick each line; on a failure
note the page and the time (`docker logs --since 10m plasma_backend` has the request).

| # | Feature | Do | Expect |
| --- | --- | --- | --- |
| 1 | Sign-in | Sign in with Google (admin) | Dashboard loads, no error banner |
| 2 | Languages | Switch EN → RU → UZ → AR | Texts change; Arabic is right-to-left |
| 3 | Explorer | Open Tenders; filter by source, country, a service | Lists and counts change; no ADB tenders anywhere |
| 4 | Deadlines | Look at deadline labels in the list | Countdown and status; "country-inferred" or "Closing — verify on source" labels where the source gave no zone |
| 5 | Matches your profile | Open the "Matches your profile" view | Only open tenders matching the profile; dismissing one removes it from this view |
| 6 | Tender details | Open a World Bank tender | Official notice listed and downloadable; source link opens; fact chips (days left, budget) |
| 7 | Source refresh menu | Open it on Tenders | Each source shows fresh / partial / stale correctly; "Refresh" on a source not refreshed in step 14 starts a job |
| 8 | One door | "Open workspace" on a tender | The pursuit workspace opens (no "Prepare bid" anywhere) |
| 9 | Private upload | In the workspace upload a small PDF | Status goes scanning → clean → ready within ~1 minute |
| 10 | Analysis | Start an analysis with the official notice (+ the PDF) | Completes as READY_FOR_REVIEW; requirements and gaps listed with their sources |
| 11 | My tenders | Open My tenders | The pursuit from 8 is there with its stage |
| 12 | Admin | Admin → approval queue, users | Lists load; "Plasma Smoke Test" user is listed (expected) |
| 13 | Onboarding (new user) | Second Google account in another private window: sign in | "Pending approval" screen |
| 14 | Approval | Admin approves that user | The user signs in again, completes company onboarding, sees the dashboard and Explorer |
| 15 | Sign-out | Sign out both accounts | Back to the sign-in page |

All 15 pass = Deploy 1 is done. A failing line: fix forward (no users), or **Rollback A2**
if sign-in (1), Explorer (3), tender details (6), workspace (8) or analysis (10) cannot be made
to work within an hour.

## 16. Done, and the 24-hour check

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy1-dbredis.txt && echo DBREDIS_UNCHANGED
prod$ scripts/ops/disk_report.sh --threshold 80; free -h; tail -n 8 .release-history
```
Record: `SET`, the step 10 counts, smoke and feature-check results.

24 hours later (and before onboarding):
```
prod$ docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ docker exec plasma_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select source_system, status, count(*) from source_refresh_jobs where created_at > now() - interval \$\$24 hours\$\$ group by 1,2 order by 1,2"'
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/ops/disk_report.sh --threshold 80; free -h
```
Expect: every container `oom=false restarts=0`; World Bank and UzEx `completed` about 4 times,
EBRD and GIZ about once, no `failed`; smoke `0 failure(s)`; disk ≤ 80 %. Then delete
`/var/backups/plasma/$SET.*` and `.env.pre-deploy1` (the laptop copy and `backups/$SET.dump` stay).

## Before onboarding next week

- [ ] **Deploy 1b** (below): with no users its downtime costs nothing; rehearse locally, then apply, so the database has its tuning and the lowest OOM priority before real load.
- [ ] **Scheduled off-host backups**: a Storage Box (or S3) as `BACKUP_REMOTE`, a daily cron of `scripts/ops/backup.sh --target production --skip-tender-documents` and a weekly one with tender documents; one restore rehearsed (`scripts/ops/restore_to_staging.sh` on the laptop stack).
- [ ] **Gemini**: production's own key, budget alert active, and a note of the monthly budget.
- [ ] **Demo**: the demo organization seeded for `support.plasma@gmail.com` (D3-04).
- [ ] **Feature check again** (step 15) on the release that is live at onboarding.

---

## Rollback

**Default: fix forward.** There are no users; a broken feature is fixed in the next release or
by configuration. Roll back only when one of these holds and cannot be fixed within an hour:
the API or frontend does not come up (step 11), sign-in, Explorer, tender details, the
workspace or analysis fail (steps 12-15), a container keeps restarting, or data looks wrong.

**A2. Exact return to a275357 (the default rollback: old images, old compose, old `.env`).**
Everything returns to the known-good state of this morning; the only remnants are the additive
index and the `OFFICIAL_NOTICE` rows, which the old build lists as ordinary documents.
Order matters: `use` exists only in the new script, so it runs before the checkout.

```
prod$ scripts/compose-release.sh use "$PREV_SHA"
prod$ git checkout main && test "$(git rev-parse HEAD)" = "$PREV_SHA" && echo MAIN_OK
prod$ cp -p .env.pre-deploy1 .env && echo ENV_RESTORED
prod$ scripts/compose-release.sh up -d --no-build --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
```
Expect: `images switched to a2753573…; nothing was restarted`, `MAIN_OK`, `ENV_RESTORED`, the
eight app containers `Recreated`/`Started` (no `Building`, no `plasma_db`/`plasma_redis` lines),
then `"build_sha":"a2753573…"` (or the short `a2753573191f`). Verified locally: the a275357
compose resolves every built service to `plasmaos-<service>:latest`, which `use` points at
`plasma-<service>:a2753573…` (step 3), and a `--dry-run` of the `up` line recreates exactly the
eight app services and builds nothing. `scripts/ops/` does not exist on `main`: check by hand
(sign in, open a tender). Then report what failed; the next attempt is a new release.

**A. Old images under the new compose file (only if A2 is impossible, e.g. `.env.pre-deploy1` is lost).**
```
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
```
(Not `compose-release.sh rollback`: it would recreate `db`/`redis`.)

**B. Schema rollback: not needed.** The old build runs on the new schema (one additive index).
If ever required, while `:latest` is still the new image:
`prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261002_0001_p0_extraction_trust_gate`

**C. Database restore (only if data is damaged; loses everything written since step 4).**
```
prod$ scripts/compose-release.sh stop frontend backend celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat
prod$ docker exec -i plasma_db sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v db="$POSTGRES_DB"' <<'SQL'
DROP DATABASE IF EXISTS :"db" WITH (FORCE);
CREATE DATABASE :"db";
SQL
prod$ docker exec -i plasma_db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' < /var/backups/plasma/$SET.dump
prod$ docker run --rm -i -v plasmaos_private_documents_data:/app/private-data alpine sh -c 'find /app/private-data -mindepth 1 -delete; tar -xzf - -C /app' < /var/backups/plasma/$SET.private.tar.gz
```
then A2. (If the host copy is gone: `laptop$ scp /d/plasma-backups/$SET.dump /d/plasma-backups/$SET.private.tar.gz "$PROD:/var/backups/plasma/"`.)
Never run `docker compose down -v`.

---

## Deploy 1b (before onboarding): PostgreSQL tuning and db/redis OOM priority

The new compose file gives `db` explicit memory settings (`shared_buffers=256MB`,
`effective_cache_size=1GB`, `work_mem=4MB`, `maintenance_work_mem=64MB`, `max_connections=100`
on 4gb) and `oom_score_adj` -800 (db) / -500 (redis), so the kernel never picks them first.
Applying it recreates both containers: seconds of database and Redis downtime and a PostgreSQL
restart with new settings. With no users this is cheap; do it once Deploy 1 has run cleanly:

1. Rehearse on the local stack: db/redis created from the a275357 compose, app services from
   the release (the state Deploy 1 leaves), then the step below; smoke; measure the downtime.
2. Off-host backup (step 4) right before.
3. `prod$ scripts/compose-release.sh up "$SHA" --no-deps db redis` then
   `until docker exec plasma_db pg_isready -q; do sleep 2; done`, then restart the app services
   so they reconnect cleanly (`up "$SHA" --no-deps --force-recreate $APPS`), then smoke.
4. Rollback of 1b: recreate `db redis` with PostgreSQL's defaults from the a275357 compose file:
   `prod$ git show a275357:docker-compose.yml > /tmp/compose-a275357.yml`
   `prod$ docker compose -p plasmaos -f /tmp/compose-a275357.yml --env-file .env --env-file frontend/.env up -d --no-deps db redis`
