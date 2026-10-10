# Deploy 3 runbook: production 25ffb02 / images 4f09b8e → pilot/week1, images 169d451

For the owner, copy-paste on the production host. Every step has the command, what you must
see, and a **STOP** condition. Same rules as Deploys 1 and 2: a short clean cut-over (the app is
stopped while the schema moves), every feature proven on production afterwards, problems fixed
forward first, two rollbacks. New in this runbook: the **pre-stop gate** before every app stop
(docs/ops/RUNBOOK_TEMPLATE.md).

| | |
| --- | --- |
| Checkout | `pilot/week1` @ the commit that adds this file (= images' code `169d451` + this file, no code change) |
| Images | `plasma-<service>:169d45179bf41786e8f8e305a7379e48f19238f5`, bundle `plasma-release-169d451.tar.gz`, **1,609,577,713 bytes (1.50 GiB)**, sha256 `ca78cfdbdd76a100b1fa086fd57d17d461d3d6a60be9151414e0b7b6a5c0176e`; `/health` reports `build_sha` `169d451…` |
| Running today | checkout `25ffb02` (Deploy 2 runbook commit), images `4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d`, schema `20261005_0001_d2_05_eoi_drafts` |
| Host | Hetzner 2 vCPU / 3.7 GiB, `/opt/plasma-console/plasmaos`, `HOST_PROFILE=4gb`, `PLASMA_NO_BUILD=1` |
| Migrations | four, all additive (the Deploy 2 build runs on the new schema: Rollback A): `20261008_0001_r3_pending_invitations`, `20261009_0001_r3_cv_library_drafts`, `20261010_0001_r3_email_notifications`, `20261011_0001_r3_organization_record_events` (step 10) |
| New in the release | **Product R3**: invite teammates by e-mail (R3-1); "your experience changed" banner (R3-2); CV upload → reviewed CV draft (R3-3); e-mail notifications over SMTP, off until configured (R3-4); admin/operator panels for sources, analysis runs and organizations (R3-5); **one organization-level company profile for every member** (R3-6, see below); localized sign-in error page. **Ops R3**: DNS guard in `smoke.sh`; World Bank refresh streamed page by page (worker peak 591 → 406 MiB); a SHORT analysis with one failed pass and an empty other pass is retried, not completed; hardened public invitation preview (generic 404, 5 fields, no-store/noindex, 30 requests/10 min per IP); Sentry, R2 backups, host monitor (all off until enabled, optional sections A-D); demo seed default `plasmatest0@gmail.com` |
| Gate | `169d451`, from an LF export (details at the end): backend 1,138 passed / 1 skipped (4 batches), security 118, analysis 50, connectors 198, migrations, performance, config-dependencies 24 + `pip check` + `npm audit --omit=dev` 0; frontend typecheck, lint, 396 node tests, RTL audit, build; browser 232 cases |
| **Not touched** | **`db`, `redis` and `clamav` keep their containers** (never `up`, `down`, `restart` or `rollback` them here). PostgreSQL tuning is Deploy 1b, its own window 24 h after this one (docs/ops/DEPLOY_1B_RUNBOOK.md) |
| Downtime | step 9 → step 11: **~90 s** expected (local run: image switch 8 s + four migrations 13 s + start to `/health/ready` 48 s = 78 s, plus the ~12 s stop measured in Deploy 2) |
| Window | ~30 min to step 11 plus the transfer (step 6), then ~60 min of checks (steps 12-16) |

**Rule for this whole window: every `up` names its services and has `--no-deps`.** Never run
`up` without a service list, `compose-release.sh rollback`, `docker compose up`, `down` or
`restart`: with this compose file those would recreate `db`/`redis`.

Conventions as before: `prod$` on the production host in `/opt/plasma-console/plasmaos`; `laptop$`
on the owner's PC (Git Bash). `<prod>`, `<APP_DOMAIN>`, `<API_DOMAIN>` as before.

APP services (the only ones this runbook recreates):
`celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend`

**Invited members now share the organization profile (R3-6).** Until now every profile-dependent
view read "the user's own company profile". From this release every member of an organization
(owners and invited members alike) reads and edits **the organization's** company profile,
Readiness Vault and readiness records; Explorer matches, My Tenders, tender details and bid
preparation use it. Approval and pilot status stay admin-only. Every member edit is recorded in
the append-only `organization_record_events` (who, which record, which field names, never values),
readable by OWNERs at `GET /api/v1/organizations/{id}/record-events`. Users in several
organizations get a switcher in the top bar. Nothing to migrate: each organization already points at
its owner's profile (`legacy_company_profile_id`).

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<this runbook's commit on pilot/week1>
prod$ SHA=169d45179bf41786e8f8e305a7379e48f19238f5
prod$ PREV_COMMIT=25ffb02<full SHA from `git rev-parse HEAD` in step 1>
prod$ PREV_SHA=4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d
prod$ APPS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ SMOKE_ORG_ID=<"Plasma Smoke Test" organization_id, as in Deploy 2 step 13>
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```
Expect `"build_sha":"4f09b8e1…"` before step 9, `169d451…` after step 11. **STOP** before step 9 otherwise.

## 1. Pre-checks (nothing changes)

```
prod$ git status --porcelain; git rev-parse HEAD
prod$ free -h; df -h /
prod$ docker exec plasma_backend alembic current
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy3-dbredis.txt
prod$ docker inspect -f '{{.State.Health.Status}} oom={{.State.OOMKilled}}' plasma_clamav
```
Expect: no file lines (untracked `.env.pre-deploy*` are fine), `25ffb02…`; `available` ≥ ~700Mi;
`20261005_0001_d2_05_eoi_drafts (head)`; `7`; two fingerprint lines (compared in steps 11 and 16);
ClamAV `healthy oom=false`. **STOP** if any differs.

**Disk pre-step** (removes the 0bea1f1 images; keeps 4f09b8e, the rollback point):
```
prod$ scripts/ops/prune_safe.sh --keep 4f09b8e --min-releases 1
prod$ scripts/ops/prune_safe.sh --keep 4f09b8e --min-releases 1 --apply
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"; df -h /
```
The dry run lists `0bea1f1…` tags under "release tags to remove", never `4f09b8e`, and now also
prints the space they really free (shared layers stay; expect ~2 GB, not the 5.5 GB `docker images`
shows). **STOP** if a `4f09b8e` tag is listed. After `--apply`: `7` again, and the `PRUNE_RESULT`
line with the measured freed bytes. Expect `Avail` ≥ **12G** (bundle ~1.5 GB + loaded images +
backup). **STOP** below 12G.

## 2. Check out the release (files only, nothing restarts)

```
prod$ git fetch origin pilot/week1
prod$ git checkout -B pilot/week1 "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls scripts/ops/monitor.sh scripts/ops/restore_drill.sh deploy/systemd/plasma-monitor.timer docs/ops/RUNBOOK_TEMPLATE.md
```
Expect `CHECKOUT_OK` and the four paths. **STOP** otherwise (`git checkout -B pilot/week1 "$PREV_COMMIT"`).

## 3. Record Celery Beat memory (read-only)
```
prod$ scripts/ops/beat_memory.sh --target production | tee $HOME/deploy3-beat.txt
prod$ BEAT_RSS_KB=$(grep -o 'rss_kb=[0-9]*' $HOME/deploy3-beat.txt | cut -d= -f2); echo $BEAT_RSS_KB
```

## 4. Off-host backup: database + private documents → laptop
As Deploy 2 step 4 (the R2 timers are optional section A, not yet installed):
```
prod$ BACKUP_REMOTE=file:///var/backups/plasma scripts/ops/backup.sh --target production --skip-tender-documents
prod$ SET=<the set= value of the last line>; ls -l /var/backups/plasma/$SET.*
laptop$ PROD=<prod>; SET=<same>; scp "$PROD:/var/backups/plasma/$SET.*" /d/plasma-backups/ && cd /d/plasma-backups && sha256sum -c "$SET.sha256"
```
Expect `BACKUP_RESULT set=… tier=none …` and `…dump: OK`, `…private.tar.gz: OK`. **STOP** without a verified copy.

## 5. Host size
Stay on 4gb. Memory limits are unchanged from Deploy 2 (step 7 shows them).

## 6. Transfer the image bundle
```
laptop$ scp /d/plasma-release/plasma-release-169d451.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-169d451.tar.gz
```
Expect `ca78cfdbdd76a100b1fa086fd57d17d461d3d6a60be9151414e0b7b6a5c0176e`. **STOP** if it differs (copy again).

## 7. `.env`: keep a copy, add the links origin
```
prod$ cp -p .env .env.pre-deploy3 && chmod 600 .env.pre-deploy3 && cmp .env .env.pre-deploy3 && echo ENV_SAVED
prod$ printf '\n# --- Deploy 3 (R3) ---\n# Absolute app origin for invitation and e-mail links (unset: invitation links are relative paths).\nPUBLIC_APP_URL=https://<APP_DOMAIN>\n' >> .env
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit' | sort | uniq -c
```
Expect `ENV_SAVED`, `CONFIG_OK`, and exactly the Deploy 2 lines (no limit changes in this release):
```
      3       - --concurrency=1
      1       - --concurrency=2
      1     mem_limit: "1610612736"
      1     mem_limit: "201326592"
      2     mem_limit: "268435456"
      2     mem_limit: "402653184"
      1     mem_limit: "536870912"
      1     mem_limit: "805306368"
```
**STOP** on different numbers.

Variables the release reads that the running build did not (all have safe defaults; only
`PUBLIC_APP_URL` is set in this window):

| Variable | Default | Effect | Set in Deploy 3 |
| --- | --- | --- | --- |
| `PUBLIC_APP_URL` | unset | absolute links in invitations and e-mails (unset: relative invite paths, no e-mail links) | **yes**, `https://<APP_DOMAIN>` |
| `SMTP_HOST` | unset | e-mail channel off unless `SMTP_HOST` **and** `SMTP_FROM` are set | no (section D) |
| `SMTP_PORT` | `587` | | no |
| `SMTP_USER` / `SMTP_PASSWORD` | unset | | no |
| `SMTP_FROM` | unset | e.g. `Plasma <noreply@<domain>>` | no |
| `SMTP_TLS` | `starttls` | `starttls` (587) or `ssl` (465); `none` is refused in production | no |
| `SMTP_TIMEOUT_SECONDS` | `20` | | no |
| `CV_EXTRACTION_BUDGET_SECONDS` | `150` | CV draft extraction time budget | no |
| `CV_EXTRACTION_MAX_OUTPUT_TOKENS` | `16384` | | no |
| `BACKEND_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | the only peers whose `X-Forwarded-For` the backend trusts (Caddy and Next.js on the Docker networks); uvicorn takes the rightmost untrusted address, so a forged prefix is ignored. Replaces the image's `*` via the compose `command:` | no (default) |
| `SENTRY_DSN_BACKEND` | unset | error tracking off (section C) | no |
| `SENTRY_DSN_FRONTEND` | unset | error tracking off; compose passes it and `ENVIRONMENT` to the frontend | no |
| `BACKUP_*`, `OPS_TELEGRAM_*`, `MONITOR_*` | unset | read only from `/etc/plasma/ops.env` by the optional timers (sections A, B), never from `.env` | no |

## 8. Import the images
```
prod$ scripts/compose-release.sh import --expect "$SHA" < /opt/plasma-console/plasma-release-169d451.tar.gz
prod$ rm /opt/plasma-console/plasma-release-169d451.tar.gz && df -h /
```
Expect seven `Loaded image: plasma-<service>:169d451…`, then `every service has plasma-<service>:169d451…`;
`Use%` ≤ 85 %. **STOP** on `import incomplete` (repeat step 6).

## 9. Pre-stop gate, then stop the app (db, redis and ClamAV keep running)

```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy3-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect `DNS_OK`, `"ready":true`, `DBREDIS_UNCHANGED`. **STOP, do not stop anything** without `DNS_OK`:
`docker restart plasma_db plasma_redis plasma_clamav; then restart app services`
(`for s in $APPS; do docker restart plasma_$s; done`), wait for `/health/ready`, gate again.
```
prod$ date -u +%T
prod$ scripts/compose-release.sh stop $APPS
prod$ docker ps --format '{{.Names}}' | sort
```
Expect seven `Stopped`, then only `plasma_clamav`, `plasma_db`, `plasma_redis`.
Abort without deploying: `prod$ for s in $APPS; do docker start plasma_$s; done`.

## 10. Switch images, migrate

```
prod$ scripts/compose-release.sh use "$SHA"
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic current
```
Expect (local run on the production-shaped database: 13 s for the four migrations):
```
images switched to 169d45179bf41786e8f8e305a7379e48f19238f5; nothing was restarted
INFO  [alembic.runtime.migration] Running upgrade 20261005_0001_d2_05_eoi_drafts -> 20261008_0001_r3_pending_invitations, R3 Task 1: e-mail invitations to an organization.
INFO  [alembic.runtime.migration] Running upgrade 20261008_0001_r3_pending_invitations -> 20261009_0001_r3_cv_library_drafts, R3 Task 3: organization-library CV documents and reviewable CV drafts.
INFO  [alembic.runtime.migration] Running upgrade 20261009_0001_r3_cv_library_drafts -> 20261010_0001_r3_email_notifications, R3 Task 4: the e-mail channel of the notification outbox and per-user preferences.
INFO  [alembic.runtime.migration] Running upgrade 20261010_0001_r3_email_notifications -> 20261011_0001_r3_organization_record_events, R3 Task 6: audit of member changes to the organization's company profile and readiness.
20261011_0001_r3_organization_record_events (head)
```
What they do: `pending_invitations` (new table; tokens stored only as SHA-256), library CV
documents (`private_documents.library_kind`; `pursuit_id` becomes nullable on `private_documents`
and `private_document_batches`) and `cv_drafts`, `email_deliveries` and
`email_notification_preferences`, `organization_record_events` (append-only, a trigger rejects
UPDATE/DELETE). **STOP → Rollback A2** if the upgrade fails (each migration is one transaction).

## 11. Start the release

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; date -u +%T; curl -fsS http://127.0.0.1:8000/health; echo
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ docker inspect -f '{{.State.Health.Status}} started={{.State.StartedAt}}' plasma_clamav
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy3-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect `"build_sha":"169d45179bf41786e8f8e305a7379e48f19238f5"` (local run: 48 s from `up` to ready),
`FRONTEND_OK`, ClamAV `healthy` with its old start time, `DBREDIS_UNCHANGED`.
**STOP → Rollback A** if `/health/ready` is not OK after 5 minutes.

## 12. Smoke and Beat memory

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
```
Expect `Result: N ok, M warning(s), 0 failure(s)` including the new line
`a fresh one-off container resolves db, redis, clamav (…)`, `analysis smoke: OK`, Beat `growth=…%` exit 0.

## 13. Live analysis smoke

```
prod$ export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 -I -S backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
```
If the run is `COMPLETED / READY_FOR_REVIEW` but fails only on `requirements < 5`, check the
auto-picked tender's notice length: a short notice (local run: OP00473886, 2,555 characters) gives
few requirements by nature. Re-run with a long REOI pinned, e.g. the one the demo seed uses:
`--tender-id <tender id of an open World Bank REOI with a long notice>`. Any `FAILED` status or a
quality other than READY_FOR_REVIEW on a long notice is a real failure.
Expect `"status": "COMPLETED"`, `"quality_state": "READY_FOR_REVIEW"`, `live analysis smoke: OK`
(local run: OP00472554, 6 requirements, 14 positions, READY_FOR_REVIEW, 80 s). New behaviour: if one SHORT pass fails and the other finds too little,
the run is retried (status goes back to queued, `failure_code` `DEGRADED_PASS_RESULT`) instead of
completing as "no gaps"; the smoke waits for the retry within `--max-wait`.

## 14. EOI smoke (same token)
```
prod$ python3 -I -S backend/scripts/eoi_smoke.py --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test"
prod$ unset ANALYSIS_SMOKE_TOKEN
```
Expect `eoi smoke: OK` with `"sha_ok": true, "signature_ok": true` for DOCX and PDF (local run: 3 criteria, draft 0.1 s, DOCX 39,181 B, PDF 30,470 B).

## 15. R3 feature check (owner, browser, `https://<APP_DOMAIN>`)

1. **Shared profile (R3-6):** Settings → Company profile shows the organization's profile; edit one
   field and save; `GET /api/v1/organizations/<id>/record-events` (as OWNER) lists the change
   (field name only).
2. **Invitations (R3-1):** Settings → Team → invite a test address you control; open the link in a
   private window: organization, inviter, role, masked e-mail and expiry are shown. Revoke it and
   reload the link: "invitation not found" (expired, revoked and used links all read the same).
   The preview answers `Cache-Control: no-store` and `X-Robots-Tag: noindex`:
   `prod$ curl -sS -D - -o /dev/null -X POST -H 'Content-Type: application/json' -d '{"token":"x"}' http://127.0.0.1:8000/api/v1/invitations/preview | grep -iE 'HTTP/|cache-control|x-robots'`
   → `404`, `no-store`, `noindex`.
   **Forged client addresses are ignored** (the preview's rate limit keys on the client address):
   ```
   prod$ docker inspect -f '{{.Config.Cmd}}' plasma_backend
   prod$ for i in 1 2 3; do curl -s -o /dev/null -w '%{http_code} ' -X POST -H 'Content-Type: application/json' -H 'X-Forwarded-For: 6.6.6.6' -d '{"token":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}' https://<APP_DOMAIN>/api/v1/invitations/preview; done; echo
   prod$ docker exec plasma_redis sh -c 'for k in $(redis-cli --scan --pattern "plasma:ratelimit:invitation_preview:*"); do echo "$k -> $(redis-cli get $k)"; done'
   ```
   Expect `--forwarded-allow-ips 127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` (never `*`),
   `404 404 404`, and the requests counted under **your own public address** (the one your laptop
   has), never under `6.6.6.6`. Local run through a Caddy 2.8 in front of the frontend: all counted
   under the address Caddy saw, the forged `6.6.6.6` never.
3. **CV draft (R3-3):** Partners & Experts → upload a CV (PDF) → a draft appears (worker
   `worker_pursuit_analysis`), review, confirm.
4. **Admin panels (R3-5):** Admin → Sources, Analysis runs, Organizations open.
5. **E-mail (R3-4):** Settings → Notifications shows the e-mail switches; with SMTP not configured
   nothing is sent (section D enables it).
6. Deploy 2's feature check (Requirements, EOI builder, Partners & Experts) still passes.

## 16. Done, and the 24-hour check

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy3-dbredis.txt && echo DBREDIS_UNCHANGED
prod$ scripts/ops/disk_report.sh --threshold 85; free -h; tail -n 4 .release-history
```
24 hours later:
```
prod$ docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
```
Expect `oom=false restarts=0`, smoke `0 failure(s)`, Beat exit 0. Then delete
`/var/backups/plasma/$SET.*` and `.env.pre-deploy3`, and plan Deploy 1b (docs/ops/DEPLOY_1B_RUNBOOK.md).

---

## Optional enablement (separate, any time after step 16; each is reversible)

Each section changes only what it names. Where app services are recreated, run the **pre-stop gate**
(step 9's three commands) first, then `scripts/compose-release.sh up "$SHA" --no-deps $APPS`.

**A. Off-host backups to Cloudflare R2** (docs/ops/BACKUPS.md): R2 bucket + write token,
`sudo apt-get install -y rclone`, `/etc/plasma/ops.env` from `deploy/systemd/ops.env.example`
(BACKUP_* lines), install the units (docs/ops/HOST_SETUP.md section 4), first run
`sudo systemctl start plasma-backup-daily.service` → `BACKUP_RESULT … tier=daily`. Monthly:
`scripts/ops/restore_drill.sh` on the laptop with the read-only token. No app restart.

**B. Host monitor + Telegram** (docs/ops/HOST_SETUP.md sections 2-6): bot token and chat id in
`/etc/plasma/ops.env`, `scripts/ops/notify.sh "test"`, enable `plasma-monitor.timer`, check
`journalctl -u plasma-monitor -n 20 -o cat` shows seven `ok` lines; add the two UptimeRobot
monitors. No app restart.

**C. Sentry** (docs/ops/ERROR_TRACKING.md): two DSNs into `.env` (`cp -p .env .env.pre-sentry` first),
pre-stop gate, recreate the APP services with the running images, check the logs for
`error_tracking_enabled`. Undo: restore `.env.pre-sentry`, recreate again.

**D. E-mail (SMTP)**: `cp -p .env .env.pre-smtp`, then append
`SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (`Plasma <noreply@<domain>>`),
`SMTP_TLS=starttls` (keep `PUBLIC_APP_URL` from step 7); `scripts/compose-release.sh config --quiet`;
pre-stop gate; recreate the APP services. Check: invite your own address (Settings → Team) and
receive the e-mail; `docker logs --since 5m plasma_celery_worker 2>&1 | grep -i email` shows the
delivery id and `SENT` (never addresses or content). The daily digest goes out at 08:00
Asia/Tashkent to approved pilot organizations with new matching tenders (users can switch it off in
Settings → Notifications). Undo: restore `.env.pre-smtp`, recreate the APP services.

---

## Rollback

ClamAV, db and redis are not part of any rollback. **Default: fix forward.** Roll back only if the
API/frontend do not come up (step 11), sign-in, Explorer, tender details, the workspace or analysis
fail (steps 12-15) and cannot be fixed within an hour, a container keeps restarting, or data looks
wrong. Every rollback starts with the pre-stop gate (step 9's three commands).

**A. Deploy 2 images on the new schema (first choice).** The four migrations only add tables and
columns (and relax two `pursuit_id` NOT NULLs), so the old build runs on them.
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect `build_sha` `4f09b8e…` and smoke with one expected failure: `database schema is not at the
Alembic head: … Can't locate revision identified by '20261011_0001_r3_organization_record_events'`
(the old image does not know the new revisions). Remnants while on A: invitations, CV drafts,
e-mail deliveries and record events stay in the database, unused; members see their own profile
again (the R3-6 rule is in the code, not the data).

**A2. Exact return to Deploy 2 (old images, checkout, `.env`).**
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh use "$PREV_SHA"
prod$ git checkout -B pilot/week1 "$PREV_COMMIT" && test "$(git rev-parse HEAD)" = "$PREV_COMMIT" && echo CHECKOUT_OK
prod$ cp -p .env.pre-deploy3 .env && echo ENV_RESTORED
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect `DNS_OK` (STOP without it, as in step 9), `CHECKOUT_OK`, `ENV_RESTORED`, `build_sha` `4f09b8e…`,
the same single expected smoke failure.

**B. Schema rollback (not needed; only while `:latest` is still the new image).** Drops the four
R3 tables/columns, **and fails once library CV documents exist** (`pursuit_id` cannot become
NOT NULL again over them):
`prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261005_0001_d2_05_eoi_drafts`

**C. Database restore** (loses everything since step 4): Deploy 1 Rollback C with `$SET` from
step 4 (pre-stop gate first), then A2. Never `docker compose down -v`.

---

## Gate and local run (evidence)

**Gate** (`169d451`, LF `git archive` exports; the frontend/browser groups run on Windows):

| Group | Where | Result |
| --- | --- | --- |
| backend (pytest, 4 batches of ~1/4 of the test files each, fresh process per batch) | WSL Ubuntu, disposable `plasma_s05b4b_r3_gate` | 354 + 338 + 217 + 229 = **1,138 passed**, 1 skipped, 0 failed (incl. the migration-hash test, LF) |
| security / analysis / connectors | WSL | 118 / 50 / 198 passed |
| migrations / performance | WSL | pass |
| config-dependencies | WSL + Windows | 24 passed, `pip check` clean, `npm audit --omit=dev` 0 (full audit: 5 high, dev-only, under the dated exception) |
| frontend | Windows | typecheck, lint, **396/396** node tests, RTL audit, release build |
| browser | Windows | **232 passed, 0 failed** (the gate's fixed fixture ports 8114/8124 sit in a Windows-reserved range, so a temporary copy used 8314/8324; nothing else changed) |

After the gate: `46ac3b8` (configuration only: the compose `command:` with `BACKEND_FORWARDED_ALLOW_IPS`, plus its test) and this runbook; the images are unchanged.

**Images**: one backend image for the six backend services (`sha256:2d91e155…`) + the frontend (`sha256:9ff895ec…`): 7 release tags, 2 image ids; the frontend bakes `NEXT_PUBLIC_API_URL=/api/v1`.

**Local run on the shared stack** (production-shaped database at `20261005_0001`, 4gb profile, the app and ClamAV stopped beforehand for the frontend image build):

| Step | Result |
| --- | --- |
| pre-stop gate | `DNS_OK` (one-off container); db/redis fingerprints recorded |
| `use` | 8 s |
| four migrations | **13 s**, output exactly as in step 10; `20261011_0001_r3_organization_record_events (head)` |
| `up` → `/health/ready` | 48 s; `build_sha` `169d451…`; `FRONTEND_OK`; `DBREDIS_UNCHANGED` |
| backend command | `--forwarded-allow-ips 127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` |
| ClamAV | started, `healthy` within 10 s, restarts 0, oom false |
| smoke | **28 ok, 0 failures** (DNS line, Beat heartbeat, clamd PING all OK; one warning: the laptop's own disk) |
| analysis report | `analysis smoke: OK` |
| live analysis | auto-pick OP00473886 (2,555-character notice): COMPLETED / READY_FOR_REVIEW but 2 requirements (< 5); OP00472554 (44,847 characters): 6 requirements, 14 positions, READY_FOR_REVIEW, 80 s, **OK** |
| EOI smoke | on the OP00472554 analysis: 3 criteria, DOCX 39,181 B / PDF 30,470 B, sha and signature OK, **OK** |
| preview rate limit through Caddy | forged `X-Forwarded-For: 6.6.6.6` ignored; counted under the address Caddy saw |
| bundle | `plasma-release-169d451.tar.gz`, 1,609,577,713 bytes, sha256 `ca78cfdb…0176e`, export 117 s |

