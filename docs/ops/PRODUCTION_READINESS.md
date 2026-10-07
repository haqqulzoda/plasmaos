# Production readiness checklist and deploy procedure

Scope: the Compose stack in `docker-compose.yml` (db, redis, clamav, backend, frontend, five Celery services), the optional TLS proxy (`docker-compose.proxy.yml` + `deploy/caddy/Caddyfile`), and an isolated staging stack (`docker-compose.staging.yml`, `.env.staging.example`). Tools live in `scripts/ops/`. Nothing here touches production by itself: every script that changes data has an explicit `--target`, and restore only ever writes to staging.

How to use this file: work top to bottom on a new host; re-run sections 2, 4 and 9 before every production deploy. Mark each item with the date and the evidence (command output, dashboard link, ticket).

Status legend: **[ ]** open, **[x]** done. Items marked **GAP** are things the repository does not provide today.

## 1. Environments and isolation

| | Production | Staging |
| --- | --- | --- |
| Compose project | directory name (default `plasmaos`) or your chosen name | `plasma_staging` (forced) |
| Compose files | `docker-compose.yml` [+ `docker-compose.proxy.yml`] | + `docker-compose.staging.yml` |
| Env file | `.env` | `.env.staging` (the staging stack never reads `.env`) |
| Containers, volumes, network | `plasma_*`, `<project>_*`, default network | `plasma_staging_*`, `plasma_staging_*`, `plasma_staging_net` |
| Host ports (loopback) | 6543, 6379, 8000, 3000 | 16543, 16379, 18000, 13000 |
| Public hosts | `APP_DOMAIN`, `API_DOMAIN` | different `APP_DOMAIN` / `API_DOMAIN` |
| Secrets and keys | its own | all different (see section 3) |

- [ ] Staging runs on its own host or VM. (Same-host staging is possible, see the note in `deploy/caddy/Caddyfile`, but shares CPU, disk and the 80/443 ports.)
- [ ] Docker Compose **>= 2.24** on every host (`docker compose version`): the staging file uses the `!override` merge tag.
- [ ] `python3 scripts/ops/verify_staging_isolation.py` passes on the staging host. It renders both stacks and fails on any shared project, container, volume, network, host port or `.env` file, on leftover `CHANGE_ME` placeholders, and (when a production `.env` is present) on reused secrets. `scripts/ops/compose-staging.sh` runs it before every `up`/`build`/`create`/`start`/`restart`/`run`.
- [ ] pgAdmin is behind the `tools` profile and is not running: `docker ps -a --format '{{.Names}}' | grep pgadmin` prints nothing (a container left over from before the profile must be removed: `docker rm -f plasma_pgadmin`); `smoke.sh` warns if it runs.
- [ ] **No admin UI or internal port is publicly bound.** `docker ps --format '{{.Names}} {{.Ports}}'` shows every published port as `127.0.0.1:...` (Caddy's 80/443 are the only `0.0.0.0` ports), and on the host `sudo ss -tlnp | grep -vE '127\.0\.0\.1|\[::1\]'` lists only sshd and Caddy. pgAdmin (5050), PostgreSQL (6543), Redis (6379), backend (8000) and frontend (3000) must never appear there.

### Local development stack (worktrees)

The shared local stack is the Compose project `plasmaos`. Compose and `scripts/ops/` otherwise derive the project from the checkout's directory name, so from any other worktree (for example `plasmaos-int`) a build or `up` would create a second `plasmaos-int` project that collides with the running `plasma_*` containers, and `smoke.sh` would report every container missing. In such a worktree:

- `export COMPOSE_PROJECT_NAME=plasmaos` before `scripts/compose-release.sh` (build, build-only, use, run, up, stop).
- `OPS_LOCAL_PROJECT=plasmaos scripts/ops/smoke.sh --target local [--expect-sha <SHA>]`.

The frontend build also needs these values, which the backend-only `.env` of a fresh worktree does not have. Put them in the worktree's `.env` or export them for the build (names only here; take the values from the developer's existing local frontend environment, never from production):

- `AUTH_SECRET`
- `NEXTAUTH_URL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Without them `compose-release.sh` stops at interpolation (`required variable AUTH_SECRET is missing a value`). On a Docker Desktop VM of about 4 GB, build one service at a time (`build-only <service>`) and stop the old workers before the frontend build; a parallel build of every image can exhaust memory and end with `error reading from server: EOF`.

## 2. Environment variables

`.env.staging.example` lists every variable the stack reads, grouped by purpose; production's `.env` uses the same names. Required in production mode (`ENVIRONMENT=production`, enforced by `backend/app/core/config.py` and the compose `:?` guards):

| Variable | Rule |
| --- | --- |
| `ENVIRONMENT` | `production` (staging also uses `production` so it validates like production) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | strong, unique per environment |
| `SECRET_KEY` | >= 32 characters |
| `AUTH_SECRET` | frontend session secret, unique per environment |
| `AUTH_BRIDGE_SECRET` | >= 32 characters, identical for frontend and backend of the same environment |
| `NEXTAUTH_URL` | `https://<APP_DOMAIN>` |
| `BACKEND_CORS_ORIGINS` | JSON list of explicit `https://` origins, no paths or wildcards (release mode rejects anything else) |
| `TELEGRAM_BOT_TOKEN` | one bot per environment |
| `GEMINI_API_KEY` | one key per environment (section 3) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | one OAuth client per environment; redirect URI `https://<APP_DOMAIN>/api/auth/callback/google` |
| `PLASMA_ADMIN_EMAILS`, `PLASMA_OPERATOR_EMAILS` | allowlists |
| `APP_DOMAIN`, `API_DOMAIN`, `ACME_EMAIL` | when the Caddy layer is used |
| `GEMINI_PURSUIT_*`, `PURSUIT_ANALYSIS_*` | pursuit-analysis routing, timeouts and budgets (D1 build; ignored by older builds) |

Checklist:

- [ ] Production `.env` and staging `.env.staging` exist with mode `600`, owned by the deploy user, and are **not** in git (`.env`, `.env.staging`, `.env.production` are git-ignored).
- [ ] No placeholder values remain; secrets were generated (for example `openssl rand -base64 48 | tr -d '\n='`), not typed.
- [ ] `docker compose ... config --quiet` succeeds with the real env file (production: `scripts/compose-release.sh config --quiet`; staging: `scripts/ops/compose-staging.sh config --quiet`).
- [ ] Secrets are stored in a password manager or secret store, with a named owner and a rotation date. Rotating `AUTH_BRIDGE_SECRET` or `AUTH_SECRET` requires redeploying frontend and backend together and signs everyone out.
- [ ] `PLASMA_ENABLE_PSEUDO_LOCALE` and `DEMO_OCR_BYPASS` are unset (the release validator refuses them).

## 3. Separate API keys and budget alerts

- [ ] **Gemini**: a dedicated key for production and another for staging (and a third for local development and benchmarking). Never copy the production key into `.env.staging`; the isolation check fails if they match.
- [ ] Budget alerts on each key's billing account at 50 %, 80 % and 100 % of the monthly budget, delivered to a monitored address. Add a hard spend cap or quota limit on staging and on any key used for benchmarks.
- [ ] Rate/quota alerts for HTTP 429. A depleted key surfaces as HTTP 402/403: in the D1 analyzer build this is a distinct `PROVIDER_ACCOUNT` failure ("The analysis provider is temporarily unavailable. Plasma has been notified.") with an operator log line `pursuit_analysis_provider_account_error status=<code>`; alert on that log line. (During D1 benchmarking a shared key ran out of credit mid-run, which is exactly why staging and benchmarks must not share production's key.)
- [ ] Google OAuth client, Telegram bot and any other third-party credential are separate per environment.
- [ ] Model settings (`GEMINI_PURSUIT_*`) are pinned explicitly in `.env`; routing defaults are documented in `docs/audits/d1/d1-01-analyzer-reliability.md`.

## 4. Backups and restore

Tools: `scripts/ops/backup.sh` and `scripts/ops/restore_to_staging.sh`. Every backup run sends one set off-host (`BACKUP_REMOTE`; the script refuses to run without it):

| Component | Content | When | Local disk |
| --- | --- | --- | --- |
| `.dump` | `pg_dump -Fc`, verified with `pg_restore --list` (~110 MB) | every run | written locally first (kept `BACKUP_LOCAL_KEEP_DAYS`, default 7, as a fast restore point) |
| `.private.tar.gz` | `/app/private-data` (organization-private uploads, ~200 KB today) | every run | none: streamed |
| `.tender.tar.gz` | `/app/data` (public tender documents, ~3.8 GB, re-acquirable) | unless `--skip-tender-documents` | none: streamed |
| `.sha256`, `.manifest` | checksums; sizes, source commit; the manifest is uploaded last and marks the set complete | every run | none |

The archives are streamed from the backend container straight to the remote; on the way they are hashed, counted and gzip/tar-verified through FIFOs, never stored locally. After each upload the remote copy is re-hashed (`sha256sum` on ssh and mounted remotes) or its size compared (S3/rclone; `BACKUP_VERIFY_DOWNLOAD=1` re-hashes by download). A mismatch deletes the remote object and fails the run. The last output line is `BACKUP_RESULT set=... seconds=... bytes=...` for monitoring.

- [ ] **`BACKUP_REMOTE` configured** on production, for example a Hetzner Storage Box over ssh (port 23), with a dedicated key: `BACKUP_REMOTE=ssh://uNNNNNN@uNNNNNN.your-storagebox.de:23/./plasma`, `BACKUP_SSH_OPTS="-i /home/deploy/.ssh/plasma_backup_ed25519"`. The ssh remote only uses `mkdir`, `ls`, `rm`, `mv`, `sha256sum` and `dd`, which the Storage Box restricted shell provides; confirm with a first manual run. Alternatives: `s3://bucket/prefix` (aws CLI; `AWS_ENDPOINT_URL` for Hetzner Object Storage), `rclone:remote:path`.
- [ ] Backups run on a schedule on the production host (as the deploy user), database and private documents daily, tender documents weekly:
  ```
  15 2 * * 1-6  cd /opt/plasma-console/plasmaos && scripts/ops/backup.sh --target production --skip-tender-documents >> /var/log/plasma-backup.log 2>&1
  15 2 * * 0    cd /opt/plasma-console/plasmaos && scripts/ops/backup.sh --target production >> /var/log/plasma-backup.log 2>&1
  ```
  (with `BACKUP_REMOTE` and `BACKUP_SSH_OPTS` in the crontab's environment or a sourced file readable only by the deploy user).
- [ ] Before every migration: an on-demand backup to the remote (`ROLLOUT_WEEK1.md` step 1).
- [ ] Off-host copies are encrypted at rest (bucket encryption, or a Storage Box that only this host can reach plus disk encryption on restore hosts): dumps contain customer data and private documents.
- [ ] Retention on the remote matches your policy: complete sets older than `BACKUP_KEEP_DAYS` (default 14) are deleted, but the newest `BACKUP_MIN_KEEP` (3) are always kept; only the newest `BACKUP_TENDER_KEEP` (2) tender archives are kept; incomplete sets older than a day are removed. Size the remote for about 14 × 115 MB + 2 × 4 GB today.
- [ ] Restore to staging needs the set on the staging host: `BACKUP_FETCH_CMD="rsync -a -e 'ssh -p 23 -i <key>' uNNNNNN@uNNNNNN.your-storagebox.de:plasma/ ./backups/"`. `restore_to_staging.sh` reads the new layout (and older `.files.tar.gz` sets); a set without a tender archive restores the database and private documents and leaves staging's tender documents in place.
- [ ] Backup failures alert someone (cron mail or a heartbeat monitor that expects a ping after each success).
- [ ] **Tested restore**: at least monthly, and before the first production deploy, run the drill and record the result:
  1. copy the latest production backup set to the staging host's `BACKUP_SRC_DIR` (or set `BACKUP_FETCH_CMD`);
  2. `scripts/ops/restore_to_staging.sh --migrate --yes`;
  3. `scripts/ops/smoke.sh --target staging`;
  4. sign in on staging and open a restored pursuit and a stored document.
  Record RPO (age of the newest backup) and RTO (time the drill took): RPO ____ , RTO ____.
- [ ] Decide whether staging may hold real customer data. If not, supply `STAGING_POST_RESTORE_SQL` to scrub it; if so, give staging the same access controls as production.
- Redis is not backed up: it stores authentication-replay keys and queue state that the application rebuilds (AOF persistence only survives restarts).

## 5. Monitoring and alerting

- [ ] **Uptime check on `/health`**: an external monitor requests `https://<APP_DOMAIN>/health` (served by the backend through Caddy) every minute, expects HTTP 200 and the body text `"status":"ok"`, and alerts after 2 consecutive failures. Add a second check on `https://<API_DOMAIN>/health/ready`: it returns 503 when PostgreSQL or Redis is unreachable.
- [ ] Release identity is visible: `/health` reports `build_sha` and `build_time`; deploys set `PLASMA_BUILD_SHA` (via `scripts/compose-release.sh` or `compose-staging.sh`).
- [ ] **Error tracking: GAP.** The repository has no Sentry/OpenTelemetry integration; errors exist only in container logs. Before go-live either add an error tracker per environment (separate DSN for production and staging, backend + Celery + frontend) or ship container logs to a searchable store with alerts on `ERROR`/`Traceback`.
- [ ] Container logs are rotated (Docker daemon `log-opts` `max-size` and `max-file`) so they cannot fill the disk.
- [ ] Alert on: a container not running, Celery queue depth growing, Beat silent, backup age, disk, certificate expiry (Caddy renews automatically; still alert at 14 days), and provider 402/403/429.

## 6. Malware scanning (ClamAV)

Private-document uploads are scanned by ClamAV; the backend reaches it over TCP (`PRIVATE_DOCUMENT_SCAN_HOST`/`PORT`, default `clamav:3310`). If it is down, uploads cannot be scanned.

- [ ] `scripts/ops/smoke.sh` passes the ClamAV checks: `clamd` answers `PING` from the backend container, and the signature date (`freshclam --version`) is at most 3 days old (`SMOKE_CLAMAV_MAX_AGE_DAYS`).
- [ ] The container healthcheck is healthy (`docker ps`), and `docker inspect -f '{{.State.OOMKilled}} {{.State.Health.Status}}' plasma_clamav` does not show `true`. On the developer machine `clamd` had been OOM-killed (3.7 GB Docker VM, swap full) while the container stayed "Up (unhealthy)": the image's `/init` blocks on `tail -f /dev/null`, so nothing restarted it. Since pilot/week1 the service runs `deploy/clamav/supervise.sh`, which exits after 5 missed PINGs (30 s apart) so `restart: always` restarts it (tested: back to healthy about 4 minutes after `clamd` was killed), and `ConcurrentDatabaseReload no` keeps one signature set in memory during reloads.
- [ ] Memory headroom for `clamd`: about 0.85-0.95 GiB resident after loading signatures and ~1.3 GiB during a signature reload (even with `ConcurrentDatabaseReload no`). Its container limit is 1.5 GiB on the 4gb profile and 2 GiB on 8gb (section 8); do not lower it below the reload peak, or reloads end in an OOM kill and a restart.
- [ ] Signature freshness is alerted on (the official image runs `freshclam` itself, which needs outbound access to the ClamAV mirrors).

## 7. Celery Beat and workers

- [ ] Exactly **one** Beat instance runs per environment (two would duplicate every schedule). `smoke.sh` requires recent "Sending due task" lines in its log.
- [ ] Every queue has a live consumer: `celery`, `ai_fast_queue`, `heavy_dl_queue`, `private_documents`, `pursuit_analysis` (`smoke.sh` runs `celery inspect active_queues`).
- [ ] Beat drives the pursuit-analysis and private-document dispatch sweeps (every 10 s), notifications and source refresh; an alert fires when Beat is silent for 5 minutes.
- [ ] The pursuit-analysis worker's concurrency is set on purpose: the host profile sets `PURSUIT_ANALYSIS_WORKER_CONCURRENCY` (1 on 4gb, 2 on 8gb); it must also match the provider's rate limits.
- [ ] No worker pool follows the CPU count: `celery_worker` runs `CELERY_WORKER_CONCURRENCY` (2 in both profiles), `worker_heavy` and `worker_private_documents` run 1. Celery's default (one child per CPU) overflows the memory limit on a many-core host.
- [ ] Celery workers recycle pool processes: `--max-tasks-per-child=10` where it was set before, plus `--max-memory-per-child` from the host profile (a pool process above the cap is replaced after its current task, not killed mid-task).

## 8. Disk, memory and host

### Host profiles

`HOST_PROFILE=4gb|8gb` in `.env` (and `.env.staging`) selects `deploy/host-profiles/<profile>.env`, which `scripts/compose-release.sh` and `scripts/ops/compose-staging.sh` load after `.env`. Every app service gets `mem_limit` = `memswap_limit` (it cannot swap); PostgreSQL and Redis get no limit but the lowest `oom_score_adj`.

| Service | Measured (prod, steady) | 4gb limit | 8gb limit | `oom_score_adj` |
| --- | --- | --- | --- | --- |
| clamav | 0.85 GiB (reload peak ~1.3) | 1536m | 2048m | 0 |
| celery_worker | 0.23 GiB (World Bank refresh peak ~0.55) | 768m (concurrency 2) | 768m (concurrency 2) | 600 |
| backend | 0.19 GiB (demo seed peak 0.39) | 512m | 768m | 100 |
| worker_pursuit_analysis | 0.18 GiB | 384m (concurrency 1) | 768m (concurrency 2) | 500 |
| worker_private_documents | 0.17 GiB | 384m | 768m | 400 |
| worker_heavy | 0.12 GiB | 256m | 512m | 800 |
| celery_beat | 0.10 GiB | 192m | 256m | 300 |
| frontend | 0.08 GiB | 256m | 384m | 200 |
| **sum of limits** | **2.2 GiB** all services incl. db/redis | **4.19 GiB** | **6.13 GiB** | |
| postgres | 0.25 GiB | none | none | -800 |
| redis | 0.02 GiB | none | none | -500 |

4gb limits are the measured steady state +~50 % (32 MiB steps), except ClamAV, which is sized for its reload peak, and the two document workers, raised after review to leave room for one large file: `worker_private_documents` 384m (parsing an uploaded pack) and `worker_heavy` 256m (downloading and unpacking tender archives). Before Deploy 1 (R1) three more were raised and proven under load on a 4gb-profile stack: `frontend` 256m (Next.js server rendering under concurrent page loads), `backend` 448m (list and detail requests in parallel with analysis; raised to 512m in INT-5 because the backend image also runs the demo seed in a one-off container, which peaked at 402 MiB in the Deploy 2 rehearsal), `worker_pursuit_analysis` 384m (a LONG-route pack, ≥ 60K characters; its per-child cap is 256 MiB), `celery_beat` 192m, and `celery_worker` 768m: one full World Bank refresh (565 notices, persist, enrichment, official notices) peaks at ~560 MiB for the container, so at 384m its pool child was OOM-killed at the end of every attempt and the job never completed. PostgreSQL settings per profile (`command` args; defaults without a profile are PostgreSQL's own): 4gb `shared_buffers=256MB`, `effective_cache_size=1GB`, `work_mem=4MB`, `maintenance_work_mem=64MB`; 8gb `512MB`, `3GB`, `8MB`, `128MB`; `max_connections=100` on both. Changing them recreates the `db` container (seconds of downtime), never the data.

**Why the 4gb sum (4.19 GiB + unlimited PostgreSQL/Redis, more than the 3.7 GiB host) may exceed what the 3.7 GiB host can give safely.** A limit is a ceiling for one container, not a reservation: nothing is set aside, and the services peak at different times (ClamAV during a signature reload, a worker while parsing one large document). Steady state is ~2.2 GiB. The limits bound each service so one runaway process cannot take the host; if several peaks do coincide, the kernel's OOM killer picks the process with the highest score, and `oom_score_adj` makes that a Celery worker (heavy downloads first, +800) rather than PostgreSQL (-800) or Redis (-500). A killed worker is restarted by Docker and its task is retried (acks late). What must not happen is the host swapping: container swap is disabled (`memswap_limit` = `mem_limit`), and builds no longer run on the host.

- [ ] `HOST_PROFILE` is set on production and staging; after a deploy `docker inspect -f '{{.Name}} {{.HostConfig.Memory}} {{.HostConfig.OomScoreAdj}}' $(docker ps -q)` shows the profile's values.
- [ ] Watch for OOM kills after the first days on 4gb: `docker inspect -f '{{.Name}} {{.State.OOMKilled}} {{.RestartCount}}' $(docker ps -aq)`. A worker that is killed repeatedly while parsing large documents needs a higher limit (edit the profile, redeploy with `up <SHA>`), or the 8gb host.

### Pre-deploy host checks (every production deploy)

- [ ] `free -m`: at least ~700 MiB available and swap use not growing.
- [ ] `scripts/ops/disk_report.sh --threshold 80` exits 0 (at most 80 % used) — run `scripts/ops/prune_safe.sh` (dry run, then `--apply`) first if needed. Leave room for the import (~5 GB for a release whose layers changed).
- [ ] ClamAV healthy and not OOM-killed: `docker inspect -f '{{.State.Health.Status}} {{.State.OOMKilled}}' plasma_clamav` → `healthy false`.
- [ ] No admin UI port publicly bound (section 1).

### Disk

- [ ] `scripts/ops/disk_report.sh` (read-only): file-system use, `docker system df`, per-volume sizes, the SHA-tagged release images (and which are in use), and the largest tender-document directories; exits 1 above `--threshold` (default 85).
- [ ] `scripts/ops/prune_safe.sh` (dry run by default, `--apply` to act): removes dangling images, the build cache, and release tags other than the running release, the previous release (from `.release-history`), a newer imported candidate, and any `--keep SHA` / `PLASMA_KEEP_SHAS` — always at least two releases present on the host. It never removes volumes, containers or images in use, and never runs `system prune` or `volume prune`.
- [ ] Volumes and their growth are known: `postgres_data`, `tender_documents_data`, `private_documents_data`, `redis_data`, the backup directory and Docker's image/layer store (the backend image is about 4 GB). `smoke.sh` warns at 80 % and fails at 90 % (`SMOKE_DISK_WARN_PERCENT`, `SMOKE_DISK_FAIL_PERCENT`, `SMOKE_DISK_PATH`).
- [ ] Disk alert below 20 % free and a dashboard for database size.
- [ ] Never run `docker volume prune` or `docker compose down -v` on production; they delete the database and documents.
- [ ] Firewall exposes only 80 and 443 (and SSH from known addresses). PostgreSQL, Redis, backend and frontend ports are bound to `127.0.0.1` in the compose files; keep it that way.
- [ ] OS security updates and a reboot plan; Docker restart policies (`always`) confirmed by a reboot test.

## 9. TLS and reverse proxy

- [ ] DNS A/AAAA records for `APP_DOMAIN` and `API_DOMAIN` point at the host; ports 80/443 reach Caddy.
- [ ] `docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d caddy` (staging: `scripts/ops/compose-staging.sh --proxy up -d caddy`); first certificates issued (use `ACME_CA` staging CA while testing to avoid rate limits, then switch back and clear `caddy_data`).
- [ ] `https://<APP_DOMAIN>/` loads, `https://<APP_DOMAIN>/health` returns the release JSON, `https://<API_DOMAIN>/docs` returns 404, HTTP redirects to HTTPS, HSTS header present.
- [ ] Upload path tested through the proxy (the request cap is 160 MB, above the 150 MB private-pack limit).
- [ ] `NEXTAUTH_URL` and the Google OAuth redirect URI use the public HTTPS host; a real login works.

## 10. Deploy procedure

All commands run from the repository checkout on the target host. Never skip a step; never deploy to production what has not passed on staging.

### A. Prepare

1. Merge to the release branch; CI green (`scripts/run_release_gate.sh`); note the commit SHA `SHA=$(git rev-parse HEAD)`.
2. Read the release notes for schema changes. Migrations are applied by hand (`alembic upgrade head`); nothing runs them automatically.

### B. Staging

3. Refresh staging with production data (if allowed): on production `scripts/ops/backup.sh --target production`, copy the set to staging, then `scripts/ops/restore_to_staging.sh --migrate --yes` (this also rehearses the release's migrations on real data).
4. Deploy the candidate: `git checkout $SHA && scripts/ops/compose-staging.sh --proxy up -d --build`.
5. If not already done by step 3: `scripts/ops/compose-staging.sh run --rm --no-deps backend alembic upgrade head`.
6. `scripts/ops/smoke.sh --target staging --expect-sha $SHA` must report zero failures.
7. Manual checks on the staging domain: Google sign-in, upload a PDF, run one pursuit analysis (uses the staging Gemini key), admin page, a stored-document read. Check container logs for errors.

### C. Production

8. Announce the window. Confirm the latest backup is recent and off-host, or take one now: `scripts/ops/backup.sh --target production`.
9. Record the rollback point: `PREV_SHA=$(curl -fsS http://127.0.0.1:8000/health | python3 -c 'import json,sys; print(json.load(sys.stdin)["build_sha"])')` and save it in the deploy ticket. Make sure every built service has a `plasma-<service>:$PREV_SHA` image: `scripts/compose-release.sh images`. If they are missing (the first release that uses this procedure), create them now from the running images: `scripts/compose-release.sh tag $PREV_SHA` (each image is tagged with the SHA recorded inside it; `$PREV_SHA` is used only for images that record none, such as `worker_pursuit_analysis` before this change, which was built without the SHA build arguments).
10. **No build on production** (`PLASMA_NO_BUILD=1` enforces it). On the build host (staging): `git checkout $SHA && scripts/compose-release.sh build-only`, then `scripts/compose-release.sh export $SHA | ssh <prod> 'cd /opt/plasma-console/plasmaos && scripts/compose-release.sh import --expect $SHA'`. On production: `git checkout $SHA && scripts/compose-release.sh use $SHA` (retag only; nothing restarts).
11. Apply migrations if the release has any (staging already rehearsed them): `scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head`, then restart in order with `scripts/compose-release.sh up $SHA --no-deps <services>` (`ROLLOUT_WEEK1.md` step 8), or all at once with `scripts/compose-release.sh up $SHA`. Each `up <SHA>`/`rollback` is recorded in `.release-history`, which `prune_safe.sh` uses to keep the previous release.
12. `scripts/ops/smoke.sh --target production --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN> --expect-sha $SHA` (run on the production host without `--http-only` to include container, queue, Beat and ClamAV checks; it addresses the stack by Compose label, so set `PROD_COMPOSE_PROJECT` if the project is not named after the checkout directory).
13. Verify by hand: sign in as an approved user and as an admin; open a customer page; do not start source refresh or analysis just to test a passive page.

### D. Rollback

Decide within 15 minutes of a failed smoke test or a customer-visible error.

14. **Code only** (no schema change, or the change is backward compatible): `scripts/compose-release.sh rollback $PREV_SHA`. It checks that `plasma-<service>:$PREV_SHA` exists for every built service (and aborts without changing anything if one is missing), points each `<project>-<service>:latest` at it, and runs `up -d --no-build`, which recreates only the containers whose image changed. No build, about 1 minute. Then `scripts/ops/smoke.sh --target production --expect-sha $PREV_SHA`. The checkout stays at `$SHA`; run `git checkout $PREV_SHA` too so a later `up --build` does not bring the bad release back.
15. **Schema changed and the old code cannot run on it**: stop the app services (`docker compose stop frontend backend celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat`), restore the pre-deploy database dump into the production database using your DBA procedure (`pg_restore --clean --if-exists --no-owner`), restore files only if they changed, start the previous images, run smoke. Data written after the backup is lost, so prefer forward fixes for small problems.
16. Do **not** roll back to an image that predates the authentication and customer-read guards (see `docs/PRODUCTION_RELEASE_PREFLIGHT.md`); keep affected traffic unavailable instead and fix forward.
17. Preserve volumes. Never use `docker compose down -v`.
18. Write the post-mortem note (what failed, detection time, decision) in the deploy ticket.

## 11. Sign-off

| Area | Owner | Date | Evidence |
| --- | --- | --- | --- |
| Isolation check and staging bring-up | | | |
| Env vars and secrets | | | |
| Separate keys and budget alerts | | | |
| Backup schedule and off-host copy | | | |
| Tested restore (RPO / RTO) | | | |
| Uptime and error tracking | | | |
| ClamAV, Beat, disk | | | |
| TLS and proxy | | | |
| Deploy and rollback rehearsal on staging | | | |

## 12. Known gaps at the time of writing

- No error-tracking integration (section 5).
- Release images are tagged `plasma-<service>:<SHA>` on the build host and moved to production with `compose-release.sh export | import` (no registry). A replaced production host needs the current release exported again from the build host (keep the last two releases there too). Old tags are removed with `scripts/ops/prune_safe.sh`. A private registry (GHCR) is optional, see `ROLLOUT_WEEK1.md` step 5.
- Redis is a single instance without backup or replication.
- Backups are file-and-dump based on the host; point-in-time recovery (WAL archiving) is not set up.
- `pgadmin/servers.json` is a template with the default `plasma` user; adjust before using the `tools` profile.
