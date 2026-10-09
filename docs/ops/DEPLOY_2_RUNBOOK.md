# Deploy 2 runbook: production f7c61fb / images 0bea1f1 → pilot/week1, images 4f09b8e

For the owner, copy-paste on the production host. Every step has the command, what you must
see, and a **STOP** condition. Same rules as Deploy 1: a short clean cut-over (the app is
stopped while the schema moves), every feature proven on production afterwards, problems fixed
forward first, and two proven rollbacks.

| | |
| --- | --- |
| Checkout | `pilot/week1` @ the commit that updates this file (given with the runbook; = images' code `4f09b8e` + this file, no code change) |
| Images | `plasma-<service>:4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d`, bundle `plasma-release-4f09b8e.tar.gz`, **1,530,311,016 bytes (1.43 GiB)**, sha256 `bd2948ee9faf14e91538e244799513ff8f68d1d19701d3887d17ca0e7e634cbd`; `/health` reports `build_sha` `4f09b8e…`. The six backend-family services share one image (one build); the frontend is the unchanged `d10bb82` image retagged (its own `PLASMA_BUILD_SHA` still says `d10bb82…`; only the backend's `/health` is checked) |
| Running today | checkout `f7c61fbd36dee77bd5621f5031da1ae6a0096045`, images `0bea1f1ffc624b58a49b429c50055962e2cf47cd`, schema `20261003_0001_d1_03_official_notice_unique` |
| Host | Hetzner 2 vCPU / 3.7 GiB, `/opt/plasma-console/plasmaos`, `HOST_PROFILE=4gb`, `PLASMA_NO_BUILD=1` (from Deploy 1) |
| Migrations | `20261004_0001_d2_01_own_experience` (own firm, non-destructive reference edits: nullable columns, constraints, a reference-facts immutability trigger) and `20261005_0001_d2_05_eoi_drafts` (two new tables). Additive: the old build runs on the new schema (proven, Rollback A). |
| New in the release | D2-01 own experience in analysis; D2-02 Partners & Experts library; D2-05 EOI package (DOCX/PDF) and grouped Requirements; two-pass SHORT-route analysis (`pursuit_analysis_pipeline_d2_v2`, prompt `pursuit_analysis_d2_v2`; the run succeeds when at least one of the two passes succeeds); D3-04 demo seed (one-off container); Beat heartbeat in `smoke.sh`; `beat_memory.sh`; `eoi_smoke.py`; ClamAV watchdog startup grace (15 min); backend limit 512m in the 4gb profile; `prune_safe.sh --min-releases` |
| Gate | re-run at `4f09b8e` (INT-5, disposable DB): backend 1090 passed / 1 skipped, security 118, analysis 50, config-dependencies 24 + `pip check` + `npm audit --omit=dev` found 0 (full audit reported: 5 high, dev-only); the other groups unchanged since the INT-4 gate at `d10bb82` (frontend code identical); the dependency gate blocks on production npm dependencies under the dated exception in `docs/ops/DEPENDENCY_EXCEPTIONS.md` (dev-only `braces` chain, expires 2026-11-08) |
| **Not touched** | **`db`, `redis` and `clamav` keep their containers** (never `up`, `down`, `restart` or `rollback` them here; ClamAV: see below) |
| Downtime | step 9 → step 11: **134 s** in the local rehearsal (stop 12 s, image switch + both migrations 45 s, start to `/health/ready` 62 s) |
| Window | ~30 min to step 11 plus the transfer (step 6), then ~60 min of checks (steps 12-16) |

**Rule for this whole window: every `up` names its services and has `--no-deps`.** Never run
`up` without a service list, `compose-release.sh rollback`, `docker compose up`, `down` or
`restart`: with this compose file those would recreate `db`/`redis`.

Conventions as in Deploy 1: `prod$` on the production host in `/opt/plasma-console/plasmaos`;
`laptop$` on the owner's PC (Git Bash). `<prod>`, `<APP_DOMAIN>`, `<API_DOMAIN>` as before.

APP services (the only ones this runbook ever recreates):
`celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend`

**ClamAV stays running, untouched (decision).** Between `f7c61fb` and this release ClamAV's compose
definition, image (`clamav/clamav:1.4`) and 4gb limit (1536m) are unchanged; the only change is its
bind-mounted `deploy/clamav/supervise.sh` (the startup grace: exit when clamd has not answered PING
within 15 minutes, so `restart: always` brings it back). That fix only matters when the container
starts, while recreating ClamAV in the cut-over repeats the first-boot signature load that crossed the
1.5 GiB limit in the rehearsal and pauses upload scanning. So Deploy 2 leaves the running ClamAV alone:
it is not in `$APPS` (stop, up, Rollback A/A2). The running wrapper keeps its old copy (the checkout
replaces the file; the container still holds the old one); the new script takes effect at the
container's next start, by its restart policy or by the optional restart in step 16.

**Rehearsed locally** (an isolated `plasma_rehearsal` copy: the pre-Deploy-2 local database
restored at schema `20261003_0001`, Deploy 1 images, `HOST_PROFILE=4gb`, then every step below,
then Rollback A): results are quoted at each step. Peak memory in the rehearsal: ClamAV 1,497 MiB
(limit 1,536), celery_worker 639 MiB (768), backend 402 MiB (448, during the demo seed),
whole app 2.7 GiB. The backend limit is now 512 MiB (was 448): the demo seed runs in its own
one-off backend container (step 15), which gets the same limit.

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<this runbook's commit on pilot/week1>
prod$ SHA=4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d
prod$ PREV_COMMIT=f7c61fbd36dee77bd5621f5031da1ae6a0096045
prod$ PREV_SHA=0bea1f1ffc624b58a49b429c50055962e2cf47cd
prod$ APPS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```
Expect: `"build_sha":"0bea1f1ffc624b58a49b429c50055962e2cf47cd"` before step 9, `4f09b8e…` after step 11.
**STOP** before step 9 if it is anything else.

## 1. Pre-checks (nothing changes)

```
prod$ git status --porcelain; git rev-parse HEAD
```
Expect: no file lines (an untracked `.env.pre-deploy1` is fine), then `f7c61fbd…`. **STOP** otherwise.

```
prod$ free -h
```
Expect: `available` ≥ ~700Mi.

**Disk pre-step** (removes only the a275357 images and, if verified off-host, the Deploy 1 backup):
```
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
prod$ df -h /; docker system df
prod$ scripts/ops/prune_safe.sh --keep 0bea1f1 --min-releases 1
```
Expect: `7` (the Deploy 1 images, the rollback point; **STOP** below 7: do not prune). The dry run
lists under "release SHAs kept" `0bea1f1…` only (used by a container, `.release-history`, `--keep`),
and under "release tags to remove" exactly the `plasma-<service>:a2753573…` tags (seven, plus six
`:a2753573191f` tags if `compose-release.sh tag` ran in Deploy 1). **STOP** if a `0bea1f1` tag is
listed for removal. If `.release-history` keeps a275357, put `RELEASE_HISTORY=/dev/null` in front of
the command (the in-use and `--keep` rules still protect 0bea1f1). `--min-releases 1` is needed
because no newer release is on the host yet (the default 2 would keep a275357 as the second one).
Then:
```
prod$ scripts/ops/prune_safe.sh --keep 0bea1f1 --min-releases 1 --apply
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"; df -h /
```
Expect: `7` again and about **4-5 GB freed**: the a275357 set (a backend-family image of ~4.3 GB
shared by six services plus the ~1.2 GB frontend, less the base layers it shares with 0bea1f1; Deploy 1
loaded ~5 GB per release), plus the build cache and dangling images the dry run showed.

Only if the laptop copy of the Deploy 1 backup was verified (`sha256sum -c` OK in Deploy 1 step 4):
```
prod$ ls -l /var/backups/plasma/
prod$ rm /var/backups/plasma/<Deploy 1 SET>.*; df -h /
```
This frees the Deploy 1 dump and private-document archive (their sizes as listed). Otherwise keep them.

Expect `Avail` ≥ **12G** (bundle 1.5 GB + loaded images ~5.6 GB + the step 4 backup and headroom;
the Deploy 1 images stay as the rollback point). **STOP** below 12G (never `docker system prune`,
never images tagged `:$PREV_SHA`).

```
prod$ docker exec plasma_backend alembic current
prod$ docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' plasma_backend
prod$ grep -cE '^(GEMINI_API_KEY|GOOGLE_API_KEY)=.+' .env
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
```
Expect: `20261003_0001_d1_03_official_notice_unique (head)`; `plasmaos`; `1` or more; `7` (the
Deploy 1 images are the rollback point). **STOP** if any differs.

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy2-dbredis.txt
prod$ docker inspect -f '{{.State.Health.Status}} oom={{.State.OOMKilled}}' plasma_clamav
```
Expect: two lines (compared in steps 11 and 16); ClamAV `healthy oom=false` (if not, note it).

## 2. Check out the release (files only, nothing restarts)

```
prod$ git fetch origin pilot/week1
prod$ git checkout -B pilot/week1 "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls scripts/ops/beat_memory.sh backend/scripts/eoi_smoke.py backend/scripts/demo/seed_demo.py
```
Expect: `CHECKOUT_OK` and the three paths. **STOP** otherwise (go back: `git checkout -B pilot/week1 "$PREV_COMMIT"`).

## 3. Record Celery Beat memory (read-only; compared in steps 12 and 16)

```
prod$ scripts/ops/beat_memory.sh --target production | tee $HOME/deploy2-beat.txt
prod$ BEAT_RSS_KB=$(grep -o 'rss_kb=[0-9]*' $HOME/deploy2-beat.txt | cut -d= -f2); echo $BEAT_RSS_KB
```
Expect: `celery_beat rss_kb=… limit_kb=196608 of_limit=…%` (rehearsal: 137,872 kB, 70 %; local
long-running Beat: 142,224 kB, 72 %). Exit 1 (above 80 % of the limit) is a note, not a stop:
the new Beat container starts fresh in step 11.

## 4. Off-host backup: database + private documents → laptop

```
prod$ BACKUP_REMOTE=file:///var/backups/plasma scripts/ops/backup.sh --target production --skip-tender-documents
prod$ SET=<the set= value of the last line>; ls -l /var/backups/plasma/$SET.*
laptop$ PROD=<prod>; SET=<same>; scp "$PROD:/var/backups/plasma/$SET.*" /d/plasma-backups/ && cd /d/plasma-backups && sha256sum -c "$SET.sha256"
```
Expect: `BACKUP_RESULT set=…`, the four files, then `…dump: OK` and `…private.tar.gz: OK`.
**STOP** without a verified off-host copy.

## 5. Host size

Stay on 4gb. Nothing to do.

## 6. Transfer the image bundle

```
laptop$ scp /d/plasma-release/plasma-release-4f09b8e.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-4f09b8e.tar.gz
```
Expect: `bd2948ee9faf14e91538e244799513ff8f68d1d19701d3887d17ca0e7e634cbd`. **STOP** if it differs (copy again).

## 7. `.env`: keep a copy, then add one line

```
prod$ cp -p .env .env.pre-deploy2 && chmod 600 .env.pre-deploy2 && cmp .env .env.pre-deploy2 && echo ENV_SAVED
prod$ printf '\n# --- Deploy 2 (pilot/week1) ---\n# Independent extraction passes on the SHORT analysis route (default 2; the LONG route always runs 1).\nPURSUIT_ANALYSIS_SHORT_PASSES=2\n' >> .env
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit|PURSUIT_ANALYSIS_SHORT_PASSES' | sort | uniq -c
```
Expect: `ENV_SAVED`, `CONFIG_OK`, then exactly these `--concurrency`/`mem_limit` lines (only the
backend changes against `f7c61fb`: 448m → **512m**, `469762048` → `536870912`; ClamAV's 1536m line
is still there although ClamAV is not recreated), plus `PURSUIT_ANALYSIS_SHORT_PASSES: "2"` on the
services that read `.env`:
```
      3       - --concurrency=1          (worker_heavy, worker_private_documents, worker_pursuit_analysis)
      1       - --concurrency=2          (celery_worker)
      1     mem_limit: "1610612736"      (clamav 1536m)
      1     mem_limit: "201326592"       (celery_beat 192m)
      2     mem_limit: "268435456"       (worker_heavy, frontend 256m)
      2     mem_limit: "402653184"       (worker_private_documents, worker_pursuit_analysis 384m)
      1     mem_limit: "536870912"       (backend 512m)
      1     mem_limit: "805306368"       (celery_worker 768m)
```
**STOP** on different numbers (wrong `HOST_PROFILE`, or `deploy/host-profiles/4gb.env` not from this checkout).

4gb profile after Deploy 2 (sum of limits 4,288 MiB = 4.19 GiB, plus PostgreSQL and Redis unlimited):

| Service | Limit | Change |
| --- | --- | --- |
| clamav | 1536m | — (container not recreated) |
| celery_worker | 768m | — |
| backend | **512m** | was 448m; the demo seed's one-off container peaked at 402 MiB |
| worker_pursuit_analysis | 384m | — |
| worker_private_documents | 384m | — |
| worker_heavy | 256m | — |
| frontend | 256m | — |
| celery_beat | 192m | — |

Variables the merged code reads that `f7c61fb` did not (all with defaults):

| Variable | Default | Read by | Set in Deploy 2 |
| --- | --- | --- | --- |
| `PURSUIT_ANALYSIS_SHORT_PASSES` | `2` (minimum 1) | pursuit analyzer | yes, explicit `2` |
| `BEAT_HEARTBEAT_MAX_AGE` | `60` (seconds) | `scripts/ops/smoke.sh` only | no |

No other new variable: the Beat heartbeat uses the existing `CELERY_BROKER_URL`, the demo seed
the existing `ENVIRONMENT`. The Deploy 1 additions in `.env` (models, budgets, schedule) stay.

## 8. Import the images

```
prod$ scripts/compose-release.sh import --expect "$SHA" < /opt/plasma-console/plasma-release-4f09b8e.tar.gz
prod$ rm /opt/plasma-console/plasma-release-4f09b8e.tar.gz && df -h /
```
Expect: seven `Loaded image: plasma-<service>:4f09b8e…`, then `every service has plasma-<service>:4f09b8e…`;
`Use%` ≤ 85 %. **STOP** on `import incomplete` (repeat step 6).

## 9. Stop the app (db and redis keep running)

**Pre-stop gate** ([RUNBOOK_TEMPLATE.md](RUNBOOK_TEMPLATE.md), added in R3; right before the cut-over stop):
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/prestop-dbredis.txt
```
Expect `DNS_OK` (a fresh one-off container resolves `db`, `redis`, `clamav`) and `"ready":true`.
**STOP** without `DNS_OK`: `docker restart plasma_db plasma_redis plasma_clamav; then restart app services`,
then run the gate again. Never stop the app while a new container cannot resolve the database.

```
prod$ date -u +%T
prod$ scripts/compose-release.sh stop $APPS
prod$ docker ps --format '{{.Names}}' | sort
```
Expect: seven `Stopped`, then only `plasma_clamav`, `plasma_db` and `plasma_redis` (rehearsal: 12 s).
Abort without deploying: `prod$ for s in $APPS; do docker start plasma_$s; done`.

## 10. Switch images, migrate

```
prod$ scripts/compose-release.sh use "$SHA"
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic current
```
Expect (rehearsal: 45 s for the three commands):
```
images switched to 4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d; nothing was restarted
INFO  [alembic.runtime.migration] Running upgrade 20261003_0001_d1_03_official_notice_unique -> 20261004_0001_d2_01_own_experience, D2-01 the organization's own firm and non-destructive project reference edits.
INFO  [alembic.runtime.migration] Running upgrade 20261004_0001_d2_01_own_experience -> 20261005_0001_d2_05_eoi_drafts, D2-05 Expression of Interest drafts and their rendered artifacts.
20261005_0001_d2_05_eoi_drafts (head)
```
**STOP → Rollback A2** if the upgrade fails (each migration is one transaction; a failed one leaves
the schema at its previous revision).

## 11. Start the release (all app services at once)

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ docker inspect -f '{{.State.Health.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}}' plasma_clamav
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy2-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect: `"build_sha":"4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d"` within ~1 minute (rehearsal:
62 s; whole cut-over 134 s), `FRONTEND_OK`, ClamAV `healthy` with its old start time (it was not
recreated), `DBREDIS_UNCHANGED`. If `up` printed a `plasma_clamav` line, ClamAV was recreated after
all: wait for `healthy` (~1-4 min; if not healthy after 10 minutes and `oom=true`, `docker restart
plasma_clamav`; from this release the watchdog also exits by itself after 15 minutes without a PING).
**STOP → Rollback A** if `/health/ready` is not OK after 5 minutes.

## 12. Smoke and Beat memory

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
```
Expect: `Result: N ok, M warning(s), 0 failure(s)` including the new line
`beat is dispatching (a worker received its 10-second task Ns ago)` (Beat liveness no longer reads
`docker logs`); `pipeline pursuit_analysis_pipeline_d2_v2  prompt pursuit_analysis_d2_v2` and
`analysis smoke: OK`; Beat `growth=…%` exit 0 (rehearsal: +7 %, 75 % of the limit).

## 13. Live analysis smoke (two passes)

```
prod$ SMOKE_ORG_ID=<"Plasma Smoke Test" organization_id from Deploy 1 step 13>
prod$ export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 -I -S backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
```
Expect: `"status": "COMPLETED"`, `"quality_state": "READY_FOR_REVIEW"`,
`"pipeline": "pursuit_analysis_pipeline_d2_v2"`, then `live analysis smoke: OK`. Check that both passes ran:
```
prod$ RUN=<run_id above>
prod$ docker exec plasma_db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"select extraction_diagnostics->>'route', extraction_diagnostics->>'pass_count', extraction_diagnostics->>'passes_completed', extraction_diagnostics->>'union_gain', extraction_diagnostics->>'passes_succeeded', extraction_diagnostics->>'passes_failed' from pursuit_analysis_runs where id='$RUN'\""
```
Expect: `SHORT|2|2|<n>|[1, 2]|[]`. `SHORT|2|1|0|[2]|[{"pass": 1, "failure_class": "…"}]` (or the
mirror) is also a pass: from this release a SHORT run succeeds when at least one of its two passes
succeeds and uses that pass's verified facts; the diagnostics record which pass failed and why
(quality-state rules unchanged; the LONG route still runs one pass). Local check of this image
(INT-5, shared local stack): `SHORT`, both passes completed (30 s and 27 s), 30.7 s end to end,
6 requirements + 2 notes. Rehearsal (previous image): 14 requirements, provider time 38 s per
pass, but pass 1 hit two 90 s Gemini read timeouts and the whole run was redelivered (281 s); with
this release such a run completes on pass 2 instead. `--max-latency 300` stays. A provider-only failure (quota, key, timeout) is fixed in `.env`/the
key; a failure inside Plasma is a **STOP → fix forward or Rollback A**.

## 14. EOI smoke (smoke organization)

Same token, still exported:
```
prod$ python3 -I -S backend/scripts/eoi_smoke.py --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test"
prod$ unset ANALYSIS_SMOKE_TOKEN
```
It creates the smoke organization's own firm and two synthetic references (once), reads the EOI
suggestions of the step 13 analysis twice (and fails if reading created a draft), generates one
English draft and downloads both files. Expect one JSON line with `"files": {"DOCX": {… "sha_ok": true,
"signature_ok": true}, "PDF": {…}}` and `eoi smoke: OK` (rehearsal: 12 criteria, draft 4.1 s, DOCX
39,763 B, PDF 32,776 B, 11 s in all). **STOP → fix forward** on `FAIL`.

## 15. Demo seed (production)

Runs in a **one-off backend container** (`compose-release.sh run --rm --no-deps -T backend …`),
never via `exec` into `plasma_backend`: the seed's ~400 MiB peak then counts against its own 512m
limit instead of the serving API's, and the container is removed when it ends. It uses the release
image and `.env` like the API. Check `free -h` shows `available` ≥ ~600Mi first (the one-off
container runs next to the stack; local check: the dry run took 24 s and left no container).
It writes only into a new organization "Demo Consulting LLC —
<yyyymmdd-n>", makes `plasmatest0@gmail.com` its OWNER (pre-provisioning or approving that user
if needed; the first Google sign-in binds a pre-provisioned record), and revokes that user's
membership in older demo organizations. No broadcasts; the only notification is the demo user's own
approval when the run creates/approves the account. Pursuit B (first `--tender-external`) is
analysed, bulk-confirmed and gets an English EOI with suggested references and one JV partner;
pursuit A is saved.

**OP00468882 (Mongolia, LOT-4 SHINE) closes 2026-10-16 17:00 Ulaanbaatar; after that date it can no
longer be seeded** (the seed refuses closed tenders).

First the plan (read-only): it prints the five best candidates for the second pursuit with reasons:
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python scripts/demo/seed_demo.py --target production --dry-run --tender-external world_bank:OP00468882
```
The second pursuit is auto-picked with this selection (`seed_demo.candidate_condition`): World Bank,
consulting procurement group, firm-level (no "Individual Consultant Selection", no "Individual
Consultant"/"Specialist"/"Officer" titles, no awards), open by its deadline-derived status, closing on
or after the demo date + 7 days, OFFICIAL_NOTICE ≥ 2,000 characters; ranked by sector match with the
seeded references (energy, water, transport, urban), then region (Central Asia, Mongolia, Caucasus,
Türkiye, South Asia), then latest deadline. In the rehearsal (local data of 2 October) it picked
`OP00472724` (Pakistan, PLIOF consultancy firm, closes 2026-10-20); production data may differ.
Review the five; to keep the auto-pick run the same command without `--dry-run`, or pin your choice:
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python scripts/demo/seed_demo.py --target production --confirm SEED_DEMO --tender-external world_bank:OP00468882 [--tender-external world_bank:<chosen OP id>]
```
Expect (rehearsal, 109 s): a JSON summary with `"label": "<yyyymmdd-1>"`, `"organization_name":
"Demo Consulting LLC — <label>"`, `"counts": {"own_references": 18, "own_references_reviewed": 6,
"partner_firms": 6, "partner_references": 22, "experts": 12, "cv_versions": 12}`,
`"analysis": {… "status": "COMPLETED", "quality_state": "READY_FOR_REVIEW"}`, `"reviews"` with confirmed
requirements and gaps, `"eoi_draft_id"`, `"eoi_summary"` (rehearsal: 4 criteria, 12 own references,
1 partner, notes 10 kept / 3 dropped), `"broadcasts_emitted": 0`. Record the ids.
If it stops on the analysis wait (worker busy or provider slow): re-run with `--resume <label>`;
every step is idempotent within a run.

Owner sign-in check (a private window, `https://<APP_DOMAIN>`, Google account `plasmatest0@gmail.com`):
1. The dashboard shows **Demo Consulting LLC — <label>** (pick it in the organization picker if asked).
2. Partners & Experts: 18 own references, 6 partner firms, 12 experts.
3. Pursuit B (OP00468882) → Requirements: grouped list, items confirmed; → **EOI package**: version 1
   (English, current) with DOCX and PDF downloads that open.
4. Pursuit A is listed under Pursuits.

## 16. Feature check, done, and the 24-hour check

Deploy 1's feature check (step 15) plus: Requirements grouped (needs attention / partly addressed /
notes / later-stage), quotes and locators visible, "Confirm all in this group"; EOI builder (3 steps)
→ generate EN and RU → both downloads open; Partners & Experts (own experience, partners, experts);
the workspace header shows the pursuit stage.

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy2-dbredis.txt && echo DBREDIS_UNCHANGED
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
prod$ scripts/ops/disk_report.sh --threshold 85; free -h; tail -n 4 .release-history
```
24 hours later:
```
prod$ docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
```
Expect: `oom=false restarts=0` everywhere; smoke `0 failure(s)`; Beat growth exit 0 (≤ 50 % since
step 3 and ≤ 80 % of its 192 MiB limit). Beat at exit 1: note the numbers and raise
`PLASMA_MEM_CELERY_BEAT` in the next window. Then delete `/var/backups/plasma/$SET.*` and `.env.pre-deploy2`.

**Optional, at a quiet time (no uploads expected; not part of the cut-over): give ClamAV the new
watchdog.** ClamAV still runs the `f7c61fb` wrapper (no startup grace) until its next start. To load
the new `deploy/clamav/supervise.sh` without recreating the container:
```
prod$ docker restart plasma_clamav
prod$ until [ "$(docker inspect -f '{{.State.Health.Status}}' plasma_clamav)" = healthy ]; do sleep 10; done; echo CLAMAV_HEALTHY
prod$ docker exec plasma_clamav grep -c STARTUP_GRACE /plasma/supervise.sh
```
Expect `CLAMAV_HEALTHY` in ~1-4 minutes and `4` (the new wrapper; the old one prints `0`). Uploads are queued for scanning meanwhile. Fallback
(manual restart, as in the Deploy 2 rehearsal): if it is not healthy after 10 minutes, check
`docker inspect -f 'oom={{.State.OOMKilled}} restarts={{.RestartCount}}' plasma_clamav`; with the new
wrapper the container restarts itself after 15 minutes without a PING; if it does not, run
`docker restart plasma_clamav` once more. Never `up`/recreate it in this window. Skipping this step is
safe: the restart policy loads the new wrapper the next time the container starts for any reason.

---

## Demo refresh routine (before each demo week)

3-5 days before the demo week, with the first demo day as `--demo-date`:
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python scripts/demo/seed_demo.py --target production --confirm SEED_DEMO --demo-date <YYYY-MM-DD> --dry-run
```
Review the five candidates (auto-picked tenders close at least 7 days after the demo date). Then run
it for real, pinning your choice (first = analysed pursuit with the EOI, second = saved):
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python scripts/demo/seed_demo.py --target production --confirm SEED_DEMO --demo-date <YYYY-MM-DD> --tender-external world_bank:<B> --tender-external world_bank:<A>
```
Expect the step 15 summary with a new `label` and `"revoked_in_older_organizations": ["<previous demo organization id>"]`.
Notes: each run creates a fresh "Demo Consulting LLC — <yyyymmdd-n>"; the demo user's membership in
the previous demo organization is revoked automatically (its data stays, owned by that run's steward);
reseeding ends the demo user's current session, so sign in again as `plasmatest0@gmail.com` and do
the step 15 sign-in check. A pinned tender that is missing, closed or has no OFFICIAL_NOTICE is
refused with that reason.

---

## Rollback

ClamAV is not part of any rollback (not in `$APPS`): it keeps running whatever the app build.

**Default: fix forward.** Roll back only if the API/frontend do not come up (step 11), sign-in,
Explorer, tender details, the workspace or analysis fail (steps 12-16) and cannot be fixed within an
hour, a container keeps restarting, or data looks wrong. Keep the schema: the old build runs on it.

**A. Deploy 1 images on the new schema (proven in the rehearsal; first choice).**
**Pre-stop gate** ([RUNBOOK_TEMPLATE.md](RUNBOOK_TEMPLATE.md), added in R3; Rollback A recreates every app service):
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/prestop-dbredis.txt
```
Expect `DNS_OK` (a fresh one-off container resolves `db`, `redis`, `clamav`) and `"ready":true`.
**STOP** without `DNS_OK`: `docker restart plasma_db plasma_redis plasma_clamav; then restart app services`,
then run the gate again. Never stop the app while a new container cannot resolve the database.

```
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ docker logs --since 2m plasma_celery_beat 2>&1 | grep -c 'Sending due task'
```
Expect: `"build_sha":"0bea1f1…"` (rehearsal: 43 s to frontend) and smoke with exactly **two expected
failures**: `database schema is not at the Alembic head: … Can't locate revision identified by
'20261005_0001_d2_05_eoi_drafts'` (the old image does not know the new revisions) and `beat heartbeat
is …s old` (the old workers do not write the heartbeat); every other line OK, and a Beat dispatch count
above 0 from its fresh container's log. Proven in the rehearsal: old API reads and writes on the
new schema (library, firm and project-reference creation, pursuits) and an old-pipeline live analysis
(`pursuit_analysis_pipeline_d1_v3`, 17 requirements, 56 s). Remnants while on A: EOI drafts and the
own firm exist in the database but the old UI does not show the EOI tab (the own firm appears in the
old partner list).

**A2. Exact return to Deploy 1 (old images, old checkout, old `.env`).** Not rehearsed separately: the
same images and schema as A (proven), plus the Deploy 1 checkout and `.env`.
**Pre-stop gate** ([RUNBOOK_TEMPLATE.md](RUNBOOK_TEMPLATE.md), added in R3; Rollback A2 recreates every app service):
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/prestop-dbredis.txt
```
Expect `DNS_OK` (a fresh one-off container resolves `db`, `redis`, `clamav`) and `"ready":true`.
**STOP** without `DNS_OK`: `docker restart plasma_db plasma_redis plasma_clamav; then restart app services`,
then run the gate again. Never stop the app while a new container cannot resolve the database.

```
prod$ scripts/compose-release.sh use "$PREV_SHA"
prod$ git checkout -B pilot/week1 "$PREV_COMMIT" && test "$(git rev-parse HEAD)" = "$PREV_COMMIT" && echo CHECKOUT_OK
prod$ cp -p .env.pre-deploy2 .env && echo ENV_RESTORED
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect: `CHECKOUT_OK`, `ENV_RESTORED`, `build_sha` `0bea1f1…`; the Deploy 1 `smoke.sh` then reports
one expected failure (the Alembic head line, as in A); Beat is checked from its log. The schema stays
at `20261005_0001` (B is not needed for the old build).

**B. Schema rollback (not needed; only if ever required, while `:latest` is still the new image).**
Drops the EOI tables (drafts and their files' records) and the own-firm/supersede columns:
`prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261003_0001_d1_03_official_notice_unique`

**C. Database restore** (loses everything since step 4): as Deploy 1 Rollback C with
`$SET` from step 4, then A2. Never run `docker compose down -v`.
