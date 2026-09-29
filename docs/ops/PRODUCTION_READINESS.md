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
- [ ] pgAdmin is behind the `tools` profile and is not running: `docker compose ps` shows no `pgadmin`; `smoke.sh` warns if it is.

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

Tools: `scripts/ops/backup.sh` (PostgreSQL `pg_dump -Fc` verified with `pg_restore --list`, plus a tarball of the backend's `private-data` and `data` volumes, SHA-256 manifest, timestamped `plasma_<label>_<UTC>_<hash12>.*`, retention) and `scripts/ops/restore_to_staging.sh`.

- [ ] Backup runs on the production host on a schedule, for example (as the deploy user):
  `15 2 * * *  cd /srv/plasmaos && BACKUP_REMOTE=user@backup-host:/srv/plasma-backups/ scripts/ops/backup.sh --target production >> /var/log/plasma-backup.log 2>&1`
- [ ] `BACKUP_REMOTE` (rsync target or `s3://` bucket) is configured and the off-host copy succeeded (the script warns loudly if it is not set). Keep at least one copy in a different failure domain.
- [ ] Off-host copies are encrypted at rest (bucket encryption, or encrypt with `age`/`gpg` before upload): dumps contain customer data and private documents.
- [ ] Retention set to your policy (`BACKUP_KEEP_DAYS`, default 14; the newest 3 sets are always kept) and disk use of the backup directory is monitored. The document volumes are large (the developer stack's exceed 3 GB and archiving them took several minutes), so size the backup disk and the off-host bandwidth accordingly.
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
- [ ] Memory headroom for `clamd`: about 1 GB resident after loading signatures (measured 0.94 GB), more while loading. The host must hold it next to Postgres, the API, five Celery workers and Next.js without swapping.
- [ ] Signature freshness is alerted on (the official image runs `freshclam` itself, which needs outbound access to the ClamAV mirrors).

## 7. Celery Beat and workers

- [ ] Exactly **one** Beat instance runs per environment (two would duplicate every schedule). `smoke.sh` requires recent "Sending due task" lines in its log.
- [ ] Every queue has a live consumer: `celery`, `ai_fast_queue`, `heavy_dl_queue`, `private_documents`, `pursuit_analysis` (`smoke.sh` runs `celery inspect active_queues`).
- [ ] Beat drives the pursuit-analysis and private-document dispatch sweeps (every 10 s), notifications and source refresh; an alert fires when Beat is silent for 5 minutes.
- [ ] The pursuit-analysis worker's concurrency is set on purpose (`PURSUIT_ANALYSIS_WORKER_CONCURRENCY`, D1 build) and matches the provider's rate limits.

## 8. Disk, memory and host

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
10. `git checkout $SHA && scripts/compose-release.sh up -d --build`. After a successful build the script tags every built image `plasma-<service>:$SHA` (backend, frontend, the four workers and Beat), so this release is itself a rollback point for the next one.
11. Apply migrations if the release has any (staging already rehearsed them): `docker compose exec backend alembic upgrade head`.
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
- Release images are tagged `plasma-<service>:<SHA>` on the host that built them only (no registry). A rebuilt or replaced host has no rollback images; old tags also keep their layers on disk (about 4 GB per backend release, shared layers aside), so remove tags older than the last two or three releases with `docker image rm`.
- Redis is a single instance without backup or replication.
- Backups are file-and-dump based on the host; point-in-time recovery (WAL archiving) is not set up.
- `pgadmin/servers.json` is a template with the default `plasma` user; adjust before using the `tools` profile.
