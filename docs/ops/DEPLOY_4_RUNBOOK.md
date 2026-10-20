# Deploy 4 runbook: production a83d575 / images 169d451 → pilot/p1-pilot-readiness, images <SHA4>

For the owner, copy-paste on the production host. Every step has the command, what you must
see, and a **STOP** condition. Same rules as Deploys 1-3: a short clean cut-over (the app is
stopped while the schema moves), every feature proven on production afterwards, problems fixed
forward first, two rollbacks, the **pre-stop gate** before every app stop
(docs/ops/RUNBOOK_TEMPLATE.md). New in this window: **S1** (award ledger filled on production, product
analytics, Loom previews) and **P1** (e-mail code sign-in, 30-day sessions, no manual user approval,
organization access explore | pilot | paid | disabled, pilot setup, library import). Do the e-mail/DNS and
Gemini work in **"Before the window"** a day ahead.

| | |
| --- | --- |
| Checkout | `pilot/p1-pilot-readiness` @ its newest commit (= `pilot/s1-release` + P1; pushed by the owner before the window; local only until then). **Never deploy or push `pilot/s1-int`**: its history is not clean |
| Images | **built from the release commit before the window**: `plasma-<service>:<SHA4>`, bundle `plasma-release-<short4>.tar.gz`, `<bytes>`, sha256 `<…>`; `/health` reports `build_sha` `<SHA4>`. Fill these four values from `scripts/compose-release.sh export` |
| Running today | Deploy 3: checkout `a83d575` (Deploy 3 runbook commit), images `169d45179bf41786e8f8e305a7379e48f19238f5`, schema `20261011_0001_r3_organization_record_events` (step 1 checks all three) |
| Host | Hetzner 2 vCPU / 3.7 GiB, `/opt/plasma-console/plasmaos`, `HOST_PROFILE=4gb`, `PLASMA_NO_BUILD=1` |
| Migrations | **four, in order** (step 10), all additive for the schema (the Deploy 3 build runs on the new schema: Rollback A): `20261012_0001_s1_award_ledger` (award ledger, append-only) → `20261012_0002_s1_product_analytics` (product events, AI cost ledger, append-only) → `20261016_0001_p1_email_sign_in` (sign-in challenges, refresh tokens; **every pending user approved**) → `20261016_0002_p1_organization_access` (organization access state, plan, admin alerts; **backfilled from the company approval**) |
| New tables | `award_notice_snapshots`, `award_outcomes`, `product_events`, `ai_call_costs`, `email_sign_in_challenges`, `auth_refresh_tokens`, `admin_alerts` |
| Data changes | P1 migration 1: every `pending` user → `approved` (one `USER_APPROVED` audit event each, actor SYSTEM, source `P1_MIGRATION`); a disabled user who was pending before the disable is restored as approved. P1 migration 2: `organizations.access_state` from the company approval (approved → `pilot`, pending → `explore`, rejected/disabled → `disabled`). Nothing else changes |
| New variables | **required**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `PUBLIC_APP_URL`, and a **production `GEMINI_API_KEY`** separate from development; **optional**: `ADMIN_ALERT_TELEGRAM_CHAT_ID`, `ADMIN_ALERT_TELEGRAM_BOT_TOKEN`, `PUBLIC_BOOK_CALL_URL`, `AI_PRICE_TABLE_JSON` (step 16). The sign-in code key is **derived from `SECRET_KEY`** (no new variable; step 7) |
| New in the release | **S1**: award ledger (World Bank contract awards, Uzbekistan, Kazakhstan, Kyrgyz Republic, Tajikistan, all groups, verbatim, append-only; read-time firm normalization; notice validation; `/admin/award-ledger`); product analytics and AI cost ledger (`/admin/metrics`); prospect/Loom previews (`seed_demo.py --from-ledger`, replay mode); coverage strip; legacy redirects. **P1**: sign-in with a 6-digit e-mail code next to Google; sessions of about 30 days (rotating refresh tokens, 90-day cap); no manual user approval (the organization gate decides access, now enforced on every organization-scoped route); Explore for organizations not yet in a pilot (feed, coverage, guided demo, "Start a pilot", "Book a call"); admin organization access editor and team alerts (Telegram or e-mail); `pilot_setup.py`; library import from a template; "Earlier bid drafts" under My Tenders |
| Gate | `8ef9613` plus this commit (the merged runbook and two test fixtures), from an LF export (end of this file) |
| **Not touched** | **`db`, `redis` and `clamav` keep their containers** (never `up`, `down`, `restart` or `rollback` them here) |
| Downtime | step 9 → step 11: **~75 s** expected (rehearsal: four migrations 6 s on a copy of the production-shaped database; Deploy 3 measured image switch 8 s, start to `/health/ready` 48 s, stop ~12 s) |
| Window | ~30 min to step 11 plus the transfer (step 6); sign-in test and pilot setup ~10 min (steps 12b, 19); ingestion and validation ~5 min (step 15); then ~45 min of checks |

**Rule for this whole window: every `up` names its services and has `--no-deps`.** Never run
`up` without a service list, `compose-release.sh rollback`, `docker compose up`, `down` or
`restart`: with this compose file those would recreate `db`/`redis`.

Conventions as before: `prod$` on the production host in `/opt/plasma-console/plasmaos`; `laptop$`
on the owner's PC (Git Bash). `<prod>`, `<APP_DOMAIN>`, `<API_DOMAIN>` as before.

APP services (the only ones this runbook recreates):
`celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend`

**One-off containers.** Ingestion, validation, the sign-in test, pilot setup and the Loom previews run in
**one-off backend containers** (`scripts/compose-release.sh run --rm --no-deps -T backend …`), never via
`exec` into `plasma_backend`: their peak counts against their own container, and the container is removed
when it ends. Check `free -h` shows `available` ≥ ~600Mi before each.

---

## Before the window (a day ahead): e-mail provider, DNS, production Gemini key

**E-mail.** Sign-in codes, invitations and admin alerts go out over SMTP from **`no-reply@plasmaos.uz`**. Any
transactional provider works; three that need no extra code:

| | Resend | Postmark (transactional only, fast delivery) | Amazon SES (eu-central-1) |
| --- | --- | --- | --- |
| `SMTP_HOST` | `smtp.resend.com` | `smtp.postmarkapp.com` | `email-smtp.eu-central-1.amazonaws.com` |
| `SMTP_PORT` / `SMTP_TLS` | `587` / `starttls` | `587` / `starttls` | `587` / `starttls` |
| `SMTP_USER` / `SMTP_PASSWORD` | `resend` / the Resend **API key** (`re_…`, sending access) | the Server API token (both fields) | the SES SMTP credentials (IAM, not the AWS keys) |
| Before going live | add and verify the domain `plasmaos.uz` in the Resend dashboard | approve the account (Postmark reviews new accounts) | leave the SES sandbox (request production access) |

DNS records in the plasmaos.uz zone (copy the exact values from the provider's domain page; do not retype):

| Purpose | Name | Type | Value |
| --- | --- | --- | --- |
| **Resend: DKIM** | `resend._domainkey.plasmaos.uz` | TXT | the `p=…` public key shown in the Resend dashboard (Domains → plasmaos.uz) |
| **Resend: bounce MX** | `send.plasmaos.uz` | MX | the host and priority shown in the Resend dashboard |
| **Resend: SPF** | `send.plasmaos.uz` | TXT | the `v=spf1 include:…` value shown in the Resend dashboard (on the `send` subdomain, so an existing root SPF record stays as it is) |
| **SPF** (root; Postmark or SES only) | `plasmaos.uz` | TXT | `v=spf1 include:spf.mtasv.net ~all` (Postmark) **or** `v=spf1 include:amazonses.com ~all` (SES). **Only one SPF record may exist**: if the root already has `v=spf1 …` (e.g. `include:_spf.google.com`), add the `include:` to it instead of creating a second one |
| **DKIM** (Postmark or SES) | Postmark: `<date>pm._domainkey.plasmaos.uz` · SES: three `<token>._domainkey.plasmaos.uz` | Postmark: TXT · SES: CNAME | Postmark: the `k=rsa; p=…` key from the Sender Signature / Domain page · SES: `<token>.dkim.amazonses.com` for each token (Easy DKIM) |
| **Return-Path / MAIL FROM** (Postmark or SES; Resend uses the `send` records above) | Postmark: `pm-bounces.plasmaos.uz` · SES: `bounce.plasmaos.uz` | Postmark: CNAME `pm.mtasv.net` · SES: MX `10 feedback-smtp.eu-central-1.amazonses.com` and TXT `v=spf1 include:amazonses.com ~all` | as on the provider page |
| **DMARC** (every provider) | `_dmarc.plasmaos.uz` | TXT | `v=DMARC1; p=none; rua=mailto:dmarc@plasmaos.uz; fo=1; adkim=r; aspf=r` (reports only); after two weeks of clean reports `p=quarantine`, later `p=reject` |

`dmarc@plasmaos.uz` must exist (or use the provider's DMARC reporting address). **Go/no-go**: the provider shows
SPF, DKIM and Return-Path (Resend: DKIM, MX and SPF of the domain) **verified**. Without it the window can still run, but e-mail sign-in, invitations and
alerts are not proven until step 12b passes.

**Production Gemini key.** Use a key from a Google Cloud project / billing account **separate from development**
(the development key returned HTTP 402, billing, from 2026-10-16: every analysis failed). Prove it before the
window (one tiny call, a fraction of a cent):
```
laptop$ curl -s -o /dev/null -w '%{http_code}\n' -H "x-goog-api-key: <PRODUCTION_GEMINI_KEY>" -H 'Content-Type: application/json' \
          -d '{"contents":[{"parts":[{"text":"Reply OK"}]}]}' \
          "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
```
Expect `200`. **No-go for the window** on `402` (billing), `403` (key or API not enabled) or `429` (quota): every
analysis, the live smoke (step 13) and the Loom previews would fail.

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<the newest commit of pilot/p1-pilot-readiness>
prod$ SHA=<SHA4, full 40 characters>
prod$ PREV_COMMIT=a83d575<full SHA from `git rev-parse HEAD` in step 1>
prod$ PREV_SHA=169d45179bf41786e8f8e305a7379e48f19238f5
prod$ APPS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ SMOKE_ORG_ID=<"Plasma Smoke Test" organization_id, as in Deploy 3>
prod$ RUN="scripts/compose-release.sh run --rm --no-deps -T backend"
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```
Expect `"build_sha":"169d4517…"` before step 9, `<SHA4>` after step 11. **STOP** before step 9 otherwise.

## 1. Pre-checks (nothing changes)

```
prod$ git status --porcelain; git rev-parse HEAD
prod$ free -h; df -h /
prod$ docker exec plasma_backend alembic current
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy4-dbredis.txt
prod$ docker inspect -f '{{.State.Health.Status}} oom={{.State.OOMKilled}}' plasma_clamav
```
Expect: no file lines (untracked `.env.pre-deploy*` are fine), `a83d575…`; `available` ≥ ~700Mi;
`20261011_0001_r3_organization_record_events (head)`; `7`; two fingerprint lines (compared in steps
11 and 18); ClamAV `healthy oom=false`. **STOP** if any differs (in particular: if Deploy 3 is not
what runs, this runbook does not apply).

**Disk pre-step** (removes the 4f09b8e images; keeps 169d451, the rollback point):
```
prod$ scripts/ops/prune_safe.sh --keep 169d451 --min-releases 1
prod$ scripts/ops/prune_safe.sh --keep 169d451 --min-releases 1 --apply
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"; df -h /
```
The dry run lists `4f09b8e…` tags under "release tags to remove", never `169d451`. **STOP** if a
`169d451` tag is listed. After `--apply`: `7` again and the `PRUNE_RESULT` line. Expect `Avail` ≥
**12G**. **STOP** below 12G.

## 2. Check out the release (files only, nothing restarts)

```
prod$ git fetch origin pilot/p1-pilot-readiness
prod$ git checkout -B pilot/p1-pilot-readiness "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls backend/scripts/ingest_award_ledger.py backend/scripts/validate_award_ledger.py backend/scripts/demo/seed_demo.py \
         backend/scripts/pilot_setup.py backend/scripts/send_test_sign_in_code.py docs/ops/DEPLOY_4_RUNBOOK.md
```
Expect `CHECKOUT_OK` and the six paths. **STOP** otherwise (`git checkout -B pilot/week1 "$PREV_COMMIT"`).

## 3. Record Celery Beat memory (read-only)
```
prod$ scripts/ops/beat_memory.sh --target production | tee $HOME/deploy4-beat.txt
prod$ BEAT_RSS_KB=$(grep -o 'rss_kb=[0-9]*' $HOME/deploy4-beat.txt | cut -d= -f2); echo $BEAT_RSS_KB
```

## 4. Off-host backup: database + private documents → laptop
As Deploy 3 step 4 (or, if optional section A of Deploy 3 is installed, the R2 daily set of today):
```
prod$ BACKUP_REMOTE=file:///var/backups/plasma scripts/ops/backup.sh --target production --skip-tender-documents
prod$ SET=<the set= value of the last line>; ls -l /var/backups/plasma/$SET.*
laptop$ PROD=<prod>; SET=<same>; scp "$PROD:/var/backups/plasma/$SET.*" /d/plasma-backups/ && cd /d/plasma-backups && sha256sum -c "$SET.sha256"
```
Expect `BACKUP_RESULT set=… tier=none …` and `…dump: OK`, `…private.tar.gz: OK`. **STOP** without a verified copy.

**If off-host backups are configured** (Deploy 3 optional section A: `/etc/plasma/ops.env` exists with
`BACKUP_REMOTE` set), also take today's R2 set now, after the laptop copy:
```
prod$ sudo test -f /etc/plasma/ops.env && sudo grep -q '^BACKUP_REMOTE=.' /etc/plasma/ops.env && echo R2_CONFIGURED
prod$ sudo systemctl start plasma-backup-daily.service; journalctl -u plasma-backup-daily -n 20 -o cat | grep BACKUP_RESULT
```
With `R2_CONFIGURED`: expect a fresh `BACKUP_RESULT set=plasma_prod_… tier=daily … remote=r2:<bucket>/plasma/daily
via rclone …` line (the service runs in the foreground; a few minutes). **STOP before step 9** without that line
(`journalctl -u plasma-backup-daily -n 50 -o cat` shows why; the laptop copy alone is not enough when R2 is
configured). Without `R2_CONFIGURED` (no file, or no `BACKUP_REMOTE`): the laptop copy above is the backup, as
written.

## 5. Host size
Stay on 4gb. Memory limits are unchanged from Deploy 3 (step 7 shows them).

## 6. Transfer the image bundle
```
laptop$ scp /d/plasma-release/plasma-release-<short4>.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-<short4>.tar.gz
```
Expect `<sha256>`. **STOP** if it differs (copy again).

## 7. `.env`: keep a copy, add the P1 variables, the production Gemini key

```
prod$ cp -p .env .env.pre-deploy4 && chmod 600 .env.pre-deploy4 && cmp .env .env.pre-deploy4 && echo ENV_SAVED
prod$ grep -c '^SECRET_KEY=.' .env; grep -c '^PLASMA_ADMIN_EMAILS=.' .env; grep -c '^GEMINI_API_KEY=' .env
prod$ cat >> .env <<'EOF'
# --- Deploy 4 (P1) ---
# E-mail sign-in codes, invitations and admin alerts (provider from "Before the window")
SMTP_HOST=<provider host, e.g. smtp.resend.com>
SMTP_PORT=587
SMTP_TLS=starttls
SMTP_USER=<resend | token | SMTP user>
SMTP_PASSWORD=<Resend API key | token | SMTP password>
SMTP_FROM=Plasma <no-reply@plasmaos.uz>
PUBLIC_APP_URL=https://<APP_DOMAIN>
# Team alerts (new self sign-ups, pilot and call requests, AI provider failures): Telegram if set, else e-mail to PLASMA_ADMIN_EMAILS
ADMIN_ALERT_TELEGRAM_CHAT_ID=<chat id, e.g. -100…; optional>
# ADMIN_ALERT_TELEGRAM_BOT_TOKEN=<only if the alert bot differs from TELEGRAM_BOT_TOKEN>
# Explore "Book a call" (https scheduling link; optional, else the button sends a request)
PUBLIC_BOOK_CALL_URL=<https://cal.example/plasma; optional>
EOF
prod$ sed -i 's|^GEMINI_API_KEY=.*|GEMINI_API_KEY=<PRODUCTION_GEMINI_KEY>|' .env && grep -c '^GEMINI_API_KEY=.' .env
prod$ chmod 600 .env
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit' | sort | uniq -c
```
Expect `ENV_SAVED`; `1`, `1`, `1` (an existing `SECRET_KEY`, `PLASMA_ADMIN_EMAILS` and a `GEMINI_API_KEY` line
to replace; if the last is `0`, append `GEMINI_API_KEY=<PRODUCTION_GEMINI_KEY>` instead of the `sed`); `1` after
the `sed`; `CONFIG_OK`, and exactly the Deploy 3 lines:
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

- **Sign-in code key: no new variable.** The code HMAC, the per-address/IP limiter keys and the sealed copy of
  each code in the e-mail outbox are all derived from **`SECRET_KEY`**. Do **not** change `SECRET_KEY` in this
  window: rotating it later invalidates every open code (users just request a new one) and every session.
- `PLASMA_ADMIN_EMAILS` must list the people who receive e-mail alerts (set since Deploy 1).
- Telegram chat id: add the bot to the team group, send one message, then
  `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":-[0-9]*'`.
- `AI_PRICE_TABLE_JSON` stays **unset** in this window (step 16 decides).
- The frontend needs nothing new (`AUTH_SECRET`, `AUTH_BRIDGE_SECRET` and `BACKEND_INTERNAL_URL` as before).

## 8. Import the images
```
prod$ scripts/compose-release.sh import --expect "$SHA" < /opt/plasma-console/plasma-release-<short4>.tar.gz
prod$ rm /opt/plasma-console/plasma-release-<short4>.tar.gz && df -h /
```
Expect seven `Loaded image: plasma-<service>:<SHA4>…`, then `every service has plasma-<service>:<SHA4>…`;
`Use%` ≤ 85 %. **STOP** on `import incomplete` (repeat step 6).

## 8b. Proposals not linked to any pursuit (read-only SQL; informational)

The old Bid Preparation list (`/bid-preparation`, `/dashboard/bid-preparation`) redirects to My Tenders. P1
lists every proposal whose tender has no pursuit in the user's organizations under **My Tenders → "Earlier bid
drafts (N)"**, each opening its bid page, so the redirect hides nothing. Keep the counts for the step 17 check:
```
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -v ON_ERROR_STOP=1 <<'SQL' | tee $HOME/deploy4-unlinked.txt
with unlinked as (
  select p.id, p.user_id from proposals p
  where not exists (
    select 1 from organization_pursuits op
    join memberships m on m.organization_id = op.organization_id and m.state = 'ACTIVE'
    where op.source_tender_id = p.tender_id and m.user_id = p.user_id))
select 'TOTAL' as organization, count(distinct u.id) as unlinked_proposals, count(distinct m.organization_id) as organizations
from unlinked u left join memberships m on m.user_id = u.user_id and m.state = 'ACTIVE'
union all
select coalesce(o.display_name, '(user without an active organization)'), count(distinct u.id), null
from unlinked u
left join memberships m on m.user_id = u.user_id and m.state = 'ACTIVE'
left join organizations o on o.id = m.organization_id
group by 1 order by 2 desc;
SQL
```
No STOP. The TOTAL row is the number of drafts the "Earlier bid drafts" lists show across organizations
(rehearsal: 116 proposals across 4 organizations).

## 9. Pre-stop gate, then stop the app (db, redis and ClamAV keep running)

```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy4-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect `DNS_OK`, `"ready":true`, `DBREDIS_UNCHANGED`. **STOP, do not stop anything** without `DNS_OK`:
`docker restart plasma_db plasma_redis plasma_clamav; then restart app services`
(`for s in $APPS; do docker restart plasma_$s; done`), wait for `/health/ready`, gate again.

Counts before the migrations (kept for the step 10 and 12 checks):
```
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -At <<'SQL' | tee $HOME/deploy4-before-counts.txt
select 'users', approval_status, count(*) from users group by 2 order by 2;
select 'users_disabled_pre_pending', '', count(*) from users where approval_status = 'disabled' and pre_disabled_approval_status = 'pending';
select 'company_profiles', approval_status, count(*) from company_profiles group by 2 order by 2;
select 'organizations', '', count(*) from organizations;
SQL
```
Then stop the app:
```
prod$ date -u +%T
prod$ scripts/compose-release.sh stop $APPS
prod$ docker ps --format '{{.Names}}' | sort
```
Expect seven `Stopped`, then only `plasma_clamav`, `plasma_db`, `plasma_redis`.
Abort without deploying: `prod$ for s in $APPS; do docker start plasma_$s; done`.

## 10. Switch images, migrate (four migrations, in order)

```
prod$ scripts/compose-release.sh use "$SHA"
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic current
```
Expect (rehearsal on a copy of the production-shaped database: 6 s for the four migrations):
```
images switched to <SHA4>; nothing was restarted
INFO  [alembic.runtime.migration] Running upgrade 20261011_0001_r3_organization_record_events -> 20261012_0001_s1_award_ledger, Sprint 1: award ledger v0 (public award notices and one row per bidder).
INFO  [alembic.runtime.migration] Running upgrade 20261012_0001_s1_award_ledger -> 20261012_0002_s1_product_analytics, Sprint 1: server-side product events and the AI cost ledger.
INFO  [alembic.runtime.migration] Running upgrade 20261012_0002_s1_product_analytics -> 20261016_0001_p1_email_sign_in, P1: e-mail one-time-code sign-in, rotating refresh tokens, no manual user approval.
INFO  [alembic.runtime.migration] Running upgrade 20261016_0001_p1_email_sign_in -> 20261016_0002_p1_organization_access, P1: organization access state (explore | pilot | paid | disabled), the plan, admin alerts.
20261016_0002_p1_organization_access (head)
```
What they do, in order:
1. `20261012_0001_s1_award_ledger`: `award_notice_snapshots` (one row per notice version, raw text kept) and
   `award_outcomes` (one row per bidder per notice version), append-only (a trigger rejects UPDATE/DELETE).
2. `20261012_0002_s1_product_analytics`: `product_events` and `ai_call_costs`, append-only.
3. `20261016_0001_p1_email_sign_in`: `email_sign_in_challenges` and `auth_refresh_tokens`; two more e-mail
   outbox values (kind `SIGN_IN_CODE`, category `AUTH`). **The user-approval migration**: every `pending` user
   becomes `approved` with one `USER_APPROVED` audit event (actor SYSTEM, source `P1_MIGRATION`); a disabled
   user who was pending before the disable will be restored as approved; new users default to `approved`.
4. `20261016_0002_p1_organization_access`: six columns on `organizations` (`access_state`, its change time and
   author, plan start/end, success criteria), `admin_alerts`, one more e-mail kind (`ADMIN_ALERT`). Backfill:
   company approved → `pilot`, pending → `explore`, rejected/disabled → `disabled`.

**STOP → Rollback A2** if an upgrade fails (each migration is one transaction; the ones before it stay applied,
which the Deploy 3 build tolerates).

**After-check of the user-approval migration** (expected counts from step 9's `before-counts`):
```
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -At <<'SQL'
select 'users', approval_status, count(*) from users group by 2 order by 2;
select 'audit_p1', '', count(*) from admin_activity_events where action = 'USER_APPROVED' and source = 'P1_MIGRATION';
select 'organizations', access_state, count(*) from organizations group by 2 order by 2;
SQL
```
Expect: `users | pending | …` **absent** (0); `approved` = before approved + before pending; `rejected` and
`disabled` unchanged; `audit_p1` = before pending + `users_disabled_pre_pending`; organizations: `pilot` = companies
approved before, `explore` = pending, `disabled` = rejected + disabled, total = the before count. Rehearsal (copy of
the production-shaped database): before: users approved 15, pending 1, disabled-and-was-pending 0, company profiles approved 7, organizations 7; after: users approved 16, pending 0, audit events 1, organizations pilot 7. **STOP → Rollback A** on a count that does not add up.

## 11. Start the release

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; date -u +%T; curl -fsS http://127.0.0.1:8000/health; echo
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ docker inspect -f '{{.State.Health.Status}} started={{.State.StartedAt}}' plasma_clamav
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy4-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect `"build_sha":"<SHA4>"`, `FRONTEND_OK`, ClamAV `healthy` with its old start time,
`DBREDIS_UNCHANGED`. **STOP → Rollback A** if `/health/ready` is not OK after 5 minutes.

## 12. Smoke, Beat memory, organization access

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -c "select access_state, count(*) from organizations group by 1" -c "select count(*) as pending_users from users where approval_status='pending'"
```
Expect `Result: N ok, M warning(s), 0 failure(s)`, `analysis smoke: OK`, Beat `growth=…%` exit 0;
`access_state` as in step 10's after-check and `pending_users` **0**.

### What changes for users the moment the release is up (the organization gate)

- **Sign-in**: the page offers "Continue with Google" and "Work e-mail → E-mail me a code". Existing sessions keep
  working and get a refresh token at their next sign-in; from then on a user stays signed in about 30 days (90-day
  cap). Admins and operators keep signing in with Google only (they never get a code).
- **No user approval any more**: a verified e-mail (Google or code) is enough to sign in; the pending page is gone.
  Access is decided per **organization** (`organizations.access_state`), enforced by the backend on every
  organization-scoped route (pursuits, uploads, analyses, library, EOI, award data):
  - **pilot** / **paid** (every company that was approved): the full workspace, as today.
  - **explore** (every company that was pending, and every new self sign-up after onboarding): the Explore view
    only (opportunities feed, coverage strip, one guided demo analysis, "Start a pilot", "Book a call"); uploads,
    analyses, library, EOI and the award ledger answer 404/403. Each new self sign-up and each pilot/call request
    sends a team alert (Telegram if `ADMIN_ALERT_TELEGRAM_CHAT_ID`, else e-mail to `PLASMA_ADMIN_EMAILS`).
  - **disabled** (companies rejected or disabled): no workspace.
- **Admins** change an organization's state, plan dates and success criteria at **Admin → Organizations**
  (audited `ORGANIZATION_ACCESS_CHANGED`); approving a company there moves it to `pilot`.
- **Invited members** (R3 invitations, `pilot_setup.py`) join the inviting organization at their first sign-in, by
  Google or e-mail code, and never see Explore or onboarding.

## 12b. Prove e-mail sign-in end to end (one-off container)

```
prod$ $RUN python scripts/send_test_sign_in_code.py --to <a non-admin mailbox you can read> --confirm SEND_TEST_CODE
```
Expect `challenge … delivery=STAGED expires_at=…` then `outbox run {…}; this delivery: state=SENT error=None`
(rehearsal against a local mail catcher: 8 s, `state=SENT error=None`, the message arrived). Open the message: subject "Your Plasma sign-in code", the
6-digit code in the body, and in the headers (Gmail: ⋮ → Show original) **`spf=pass`, `dkim=pass`, `dmarc=pass`**.
`NOT SENT: SMTP_HOST / SMTP_FROM are not configured` → step 7's block is missing; `state=PENDING error=SMTP_AUTH`
→ wrong credentials (fix `.env`, recreate the APP services after the pre-stop gate, re-run). Admin/operator
addresses never get a code: for them use `--direct` (a sample with a code that does not work). Not a rollback
reason: sign-in with Google keeps working; fix forward.

## 13. Live analysis smoke

```
prod$ export ANALYSIS_SMOKE_TOKEN="$($RUN python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 -I -S backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
```
The auto-pick takes the first open World Bank REOI whose official notice has at least 5,000
characters; if none, it fails asking for `--tender-id`. Expect `"status": "COMPLETED"`,
`"quality_state": "READY_FOR_REVIEW"`, `live analysis smoke: OK`. The run writes one `ai_call_costs` row per
provider call (step 16 reads them). `FAILED` with a provider HTTP 402/403 means the production Gemini key
("Before the window") is not working: fix the key/billing, nothing else (the team also gets an AI-provider alert,
at most once an hour).

## 14. EOI smoke (same token)
```
prod$ python3 -I -S backend/scripts/eoi_smoke.py --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test"
prod$ unset ANALYSIS_SMOKE_TOKEN
```
Expect `eoi smoke: OK` with `"sha_ok": true, "signature_ok": true` for DOCX and PDF.

## 15. Fill the award ledger (all categories, four countries; one-off containers)

The ledger starts empty on production. One run fetches every World Bank contract-award notice of
the last 24 months for Uzbekistan, Kazakhstan, Kyrgyz Republic and Tajikistan, **all procurement
groups** (Consultant Services, Goods, Works, Non-consulting Services), from the public procnotices
API, and appends every bidder row. It is append-only and idempotent: a second run stores nothing
new unless the World Bank re-published a notice with changed text (a new version, kept next to the
old one). It writes nothing else and contacts no one.

```
prod$ free -h
prod$ time $RUN python scripts/ingest_award_ledger.py --confirm INGEST_AWARD_LEDGER | tee $HOME/deploy4-ingest.json
```
Expect (rehearsal 2026-10-20: 96 s, peak ~80 MiB) a JSON summary with `notices_seen` ≈ 3,326,
`snapshots_created` = `notices_seen` (first run), `rows_inserted` ≈ 11,236, `notices_undated` 0, `truncated_passes`
`[]`, and `rows_by_country_group` matching the table below. Then the counts per country × group:
```
prod$ docker exec plasma_db psql -U plasma -d plasma_ai -c "select country, procurement_group, count(distinct notice_id) as notices, count(*) as bidder_rows from award_outcomes group by 1,2 order by 1,2"
```
Expected (rehearsal 2026-10-20; production differs by the notices published or dropped out of the 24-month
window since):

| Country | Consultant Services | Goods | Works | Non-consulting Services | Total |
| --- | --- | --- | --- | --- | --- |
| Uzbekistan | 247 / 483 | 290 / 819 | 571 / 2,954 | 413 / 1,603 | **1,521 / 5,859** |
| Kazakhstan | 40 / 40 | 25 / 29 | 19 / 56 | 6 / 8 | **90 / 133** |
| Kyrgyz Republic | 287 / 1,024 | 572 / 1,657 | 127 / 638 | 15 / 40 | **1,001 / 3,359** |
| Tajikistan | 227 / 472 | 266 / 768 | 191 / 590 | 27 / 55 | **711 / 1,885** |
| **All** | 801 / 2,019 | 1,153 / 3,273 | 908 / 4,238 | 461 / 1,706 | **3,323 / 11,236** |

Each cell: notices / bidder rows.

**STOP** (do not go on to step 16; nothing needs undoing, the app is unaffected) if a country has
no rows, a cell is 0 where the table has more than 20, or the total is more than 10 % off.
Re-run the same command first: a World Bank API hiccup leaves notices unfetched, and the re-run
fills them (`unchanged` for the ones already stored).

Second run (idempotency) and the notice-country validation (World Bank Projects API, one request
per project, cached in `projects` for 30 days):
```
prod$ time $RUN python scripts/ingest_award_ledger.py --confirm INGEST_AWARD_LEDGER | tail -n 5
prod$ time $RUN python scripts/validate_award_ledger.py --confirm VALIDATE_AWARD_LEDGER | tee $HOME/deploy4-validate.json
```
Expect the second ingest to report `snapshots_created` 0 (or a handful of re-published notices) and
`rows_inserted` 0 or a few (rehearsal: 77 s, 0 created, 3,326 unchanged), and the validation (rehearsal: 58 s; 83 projects; FOREIGN_BIDDER_SECTION 9, DUPLICATE_AWARD_NOTICE 20, PROJECT_NOT_RESOLVABLE 15) to report the
projects resolved and `by_flag` with `FOREIGN_BIDDER_SECTION`, `DUPLICATE_AWARD_NOTICE` and `PROJECT_NOT_RESOLVABLE`
counts near the rehearsal's. Flagged notices stay in the ledger; `PROJECT_COUNTRY_MISMATCH`, `FOREIGN_BIDDER_SECTION`
and `DUPLICATE_AWARD_NOTICE` notices are left out of market sizing, the target lists and the Loom previews'
references; `PROJECT_NOT_RESOLVABLE` ones are kept (the Projects API does not return a few new projects).
**STOP** (and send the JSON) if `PROJECT_COUNTRY_MISMATCH` appears or a count is more than double the rehearsal's.

Check in the browser (an operator account): **Admin → Award ledger** shows the four countries with
totals per status; filter Uzbekistan + Consultant Services; a row opens its World Bank notice.

## 16. AI price table

The AI cost ledger estimates each provider call from a price table (USD per million tokens). The
release default (`backend/app/core/ai_pricing.py`, version `gemini-api-pricing-2026-10-09`) is
taken **only** from Google's official page, https://ai.google.dev/gemini-api/docs/pricing ("Last
updated 2026-10-09 UTC", read 2026-10-12), paid tier, Standard, text input; output includes thinking:

| Model (as the app calls it) | Input | Output | Note on the page |
| --- | --- | --- | --- |
| `gemini-3.8-flash` (analysis, default) | 0.75 | 3.75 | through 2026-12-31; **1.50 / 7.50 from 2027-01-01** |
| `gemini-3.6-flash` | 0.75 | 3.75 | same introductory note |
| `gemini-3.1-pro-preview` (long notices, fallback) | 2.00 | 12.00 | prompts ≤ 200k tokens (4.00 / 18.00 above) |
| `gemini-3-flash-preview` | 0.50 | 3.00 | |
| `gemini-2.5-flash` | 0.30 | 2.50 | |
| `gemini-2.5-flash-lite` | 0.10 | 0.40 | |
| `gemini-3.7-flash` (configured analysis fallback) | — | — | **not on the page: no estimate** (the row keeps tokens, `estimated_cost_usd` NULL) |

Task for the owner, before relying on the totals in **Admin → Metrics**:
1. Open the page above; compare each row. If all match, leave `AI_PRICE_TABLE_JSON` unset.
2. If a price differs, or after 2026-12-31 for the Flash models, set the table from the page (only
   from the page; a model you cannot find there stays out, it is never guessed), then recreate the
   APP services (pre-stop gate first):
   ```
   prod$ cp -p .env .env.pre-prices
   prod$ printf '\n# AI price table (https://ai.google.dev/gemini-api/docs/pricing, read <YYYY-MM-DD>)\nAI_PRICE_TABLE_JSON={"version":"gemini-api-pricing-<YYYY-MM-DD>","models":{"gemini-3.8-flash":{"input":"<in>","output":"<out>"},"gemini-3.1-pro-preview":{"input":"<in>","output":"<out>"}}}\n' >> .env
   prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
   prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
   ```
   The table applies to new calls; rows already written keep their estimate and `price_table_version`.
   An invalid JSON value is logged (`ai_price_table_invalid`) and the default is used.
3. Check: `docker exec plasma_db psql -U plasma -d plasma_ai -c "select model_name, price_table_version, count(*), sum(estimated_cost_usd) from ai_call_costs group by 1,2"`
   lists the step 13 smoke calls with the expected version.

## 17. Feature check (owner, browser, `https://<APP_DOMAIN>`)

S1:
1. **Admin → Metrics** (admin): weekly active organizations, funnel, median/p90 analysis time and
   cost per analysis (the step 13 run is there; demo organizations are excluded unless asked for).
2. **Admin → Award ledger** (step 15) and its CSV download; market sizing `.md`/`.csv` downloads (admin).
3. **Opportunities**: the coverage strip above the list (sources and countries covered).
4. Legacy URLs redirect (e.g. the old bid-preparation list → My Tenders; the vault → Company & Experience).
5. Deploy 3's R3 feature check (shared profile, invitations, CV draft, admin panels) still passes.
6. **Admin data is closed to members.** Sign in as a **non-admin member** (an approved pilot user who is not
   admin or operator, e.g. `plasmatest0@gmail.com`) in a private window and open `https://<APP_DOMAIN>/admin/award-ledger`
   and `/admin/metrics`: the admin layout never renders them and sends you to `/dashboard` (the pages are client
   routes; the data behind them is what must be refused). Then, with that member's API token (as in step 13:
   `scripts/smoke_account.py token` prints the smoke member's, also a non-admin), every endpoint returns **403**:
   ```
   prod$ T="$($RUN python scripts/smoke_account.py token | tail -n 1)"
   prod$ for p in award-ledger/summary award-ledger/outcomes award-ledger/outcomes.csv award-ledger/firms.csv award-ledger/market-sizing.csv award-ledger/market-sizing.md metrics; do printf '%s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $T" "http://127.0.0.1:8000/api/v1/admin/$p"; done; unset T
   ```
   Expect seven `403`. **STOP and roll back (A)** on any `200`: member access to admin data is a release blocker.
   Rehearsal (local, non-admin pilot user): seven `403`; the member's own pursuits `200`; a member of an `explore` organization gets `404` on `/pursuits` and `200` on `/explore/overview`.

P1:
7. **Sign-in page** shows "Continue with Google" and "Work e-mail → E-mail me a code".
8. **E-mail code, new address** (a personal mailbox, not an admin): the code arrives within a minute; signing in
   opens onboarding; after the company form the **Explore** view opens (feed, coverage, guided demo, "Start a pilot",
   "Book a call"). The team receives a **new sign-up alert** (Telegram, else e-mail). "Start a pilot" sends a second.
9. **Same address with Google** (if it is a Google account) reaches the **same** user (Admin → Accounts: one row).
10. **Wrong code** five times → "This code has expired or was used up"; a new code works.
11. **Admin → Organizations**: the test organization shows `explore`; "Access" → `pilot` with dates → the user's next
    page load opens the full workspace. Set it back to `disabled` (or archive it) afterwards.
12. **My Tenders** of a user from step 8b's counts: "Earlier bid drafts (N)" lists their drafts.
13. **Import** (Partners & Experts → Import from template): preview a filled template, import, check the library.
14. **Explore enforcement**: as the step 8 test user (state `explore`), open `/dashboard/pursuits`: the shell shows only
    Explore; the API refuses pursuits and uploads (403/404).

## 18. Done, and the 24-hour check

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy4-dbredis.txt && echo DBREDIS_UNCHANGED
prod$ scripts/ops/disk_report.sh --threshold 85; free -h; tail -n 4 .release-history
```
24 hours later:
```
prod$ docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -c "select kind, state, count(*) from email_deliveries where created_at > now() - interval '1 day' group by 1,2" -c "select kind, state, count(*) from admin_alerts where created_at > now() - interval '1 day' group by 1,2"
```
Expect `oom=false restarts=0`, smoke `0 failure(s)`, Beat exit 0, e-mail deliveries `SENT` (no growing `PENDING`/
`FAILED`), alerts delivered. Then delete `/var/backups/plasma/$SET.*` and `.env.pre-deploy4`.

The ledger is **not** refreshed by Beat in this release. To add newer notices later, re-run the
step 15 ingest and validation (idempotent; about 2–3 minutes each).

## 19. Pilot setup for the first two pilot firms (one-off container)

For each firm (placeholders: `<Firm A>`, `<Firm B>`; the exact organization name as the firm writes it):
```
prod$ $RUN python scripts/pilot_setup.py --target production --firm "<Firm A exact name>" \
        --owner <owner@firm-a> [--owner <second owner>] --member <user@firm-a> [--member …] \
        --start <YYYY-MM-DD> --months 3 --country Uzbekistan \
        --success-criteria "<what success means for this pilot>" --dry-run
prod$ $RUN python scripts/pilot_setup.py --target production --firm "<Firm A exact name>" \
        --owner <owner@firm-a> --member <user@firm-a> --start <YYYY-MM-DD> --months 3 --country Uzbekistan \
        --success-criteria "<…>" --confirm PILOT_SETUP --send-invitations
prod$ $RUN python scripts/pilot_setup.py --target production --firm "<Firm A exact name>" --list
```
Then the same three commands for `<Firm B>` (`--country Kyrgyz Republic` if it is Kyrgyz). Expect the dry run to
print the organization it will create (state `pilot`, plan start/end, criteria) and the invitations; the write to
print the invitation links (and e-mail them with `--send-invitations`); `--list` to show the organization, plan
and invitations (rehearsal: dry run 7 s, write 6 s with the invitation e-mails queued and sent by the next outbox run, `--list` 4 s, a re-run `ALREADY_INVITED`). It refuses preview/demo names and any existing organization it did not
create. Each invitation binds at that address's first sign-in, by Google or by e-mail code; the invited owner lands
in the firm's workspace (no onboarding, no Explore). Re-running adds new addresses only; `--resend` renews open
invitations. Plan, dates and success criteria stay editable at **Admin → Organizations**.

**Done-for-you onboarding**: fill `docs/ops/p1/plasma-library-import-template.xlsx` with the firm's references and
experts (see `plasma-library-import-sample.xlsx`), then in the firm's workspace (signed in as its owner, or as an
admin added as a member) Partners & Experts → Import from template.

---

## Owner section: Create Loom previews on production

A Loom preview is a private organization "<Firm> — Plasma preview" owned by the demo user
(`plasmatest0@gmail.com`), built **only from the firm's own consulting awards in the ledger**
(evaluated or rejected bids never become references), with one pursuit on an open World Bank REOI,
its analysis, and an English EOI version marked **"Draft — not reviewed by your team"**. It
contacts no one: no e-mail, no invitation, no notification to the firm.

Rules the command enforces:
- The firm name is the **normalized name** as in the target list (`normalized_name` column), e.g.
  `KRESTON TASHKENT`. A firm published with several countries needs `--country`.
- **Pools, in this order** (each firm-level World Bank consulting REOI; inside a pool the firm's own bid
  countries come first, then the rest of Central Asia, then by the distinctive words of its awards):
  1. **open** Central Asian REOIs closing ≥ 7 days after the demo date, official notice ≥ **2,500**
     characters;
  2. **replay**: CLOSED Central Asian REOIs published within `--replay-days N` (default **120**) of the demo
     date, notice ≥ 2,500 characters (stored, or derived from the tender as a refresh would; the seed stores it);
  3. only with `--allow-global`: open REOIs outside Central Asia sharing a word with the firm's awards,
     notice ≥ 5,000 characters.
  If no pool has a candidate, the command **says so and stops; it never falls back** to anything else.
- **Short notices**: a run on a notice under 5,000 characters is kept only if its analysis extracts at
  least **4 requirements**; otherwise it is archived, and when no run of a pool is acceptable the next pool
  is tried.
- `--candidates N` (default 3) analyses the top N REOIs of the pool, keeps the acceptable one with the most
  shortlisting criteria matched by the firm's references, archives the others, and prints a table (tender,
  country, open / closed <date>, criteria matched/total, requirements, AI cost from the AI cost ledger,
  seconds; `no*` = refused short notice). Each candidate is one full analysis (~20-80 s, USD 0.02-0.09 at
  the default prices).
- **A replay is labelled everywhere**: the preview organization is named "<Firm> — Plasma preview · Replay on
  a closed notice (closed <date>) — for illustration", the pursuit shows the same sentence under its title,
  and the EOI cover (DOCX and PDF) prints it above "Draft — not reviewed by your team". **Never present a
  replay as an open opportunity or imply the firm can still submit**; say "this notice closed on <date>; this
  is what Plasma would have produced" in the recording.
- Exclusive: the demo user's other active previews are archived first (`--keep-others` keeps them).

Each command runs in a one-off container (`$RUN` from step 0). **1. Plan (read-only):**
```
prod$ $RUN python scripts/demo/seed_demo.py --target production --from-ledger "KRESTON TASHKENT" --dry-run
```
Shows the firm's bid countries, the pool (`open`, `replay`, `global`), the candidates with their scope
tier (0 = own bid country, 1 = rest of Central Asia, 2 = outside) and closing date for a replay, the pick
reason, and `replay` when the pick is a closed notice; or the "no Central Asian World Bank REOI is open …"
message.

**2a. Create, best of 3 (Central Asia, open first, then replay):**
```
prod$ $RUN python scripts/demo/seed_demo.py --target production --from-ledger "KRESTON TASHKENT" --confirm SEED_DEMO
```
**2b. Create on a tender you chose** (pinning bypasses the scope and the short-notice rule; one analysis; a
closed tender can be pinned while `--replay-days` > 0 and is labelled as a replay):
```
prod$ $RUN python scripts/demo/seed_demo.py --target production --from-ledger "KRESTON TASHKENT" --tender-external world_bank:OP00470252 --candidates 1 --confirm SEED_DEMO
```
**2c. Never replay** (open notices only): add `--replay-days 0` to 2a.

**2d. Outside Central Asia, explicitly** (only when neither an open nor a replayable Central Asian REOI
exists; say so in the recording):
```
prod$ $RUN python scripts/demo/seed_demo.py --target production --from-ledger "KRESTON TASHKENT" --allow-global --candidates 3 --confirm SEED_DEMO
```
Expect a JSON summary (2a, 2c, 2d: plus the candidates table on stderr) with `organization_id`,
`pursuit_id`, `label` (`pv<yyyymmdd>-<n>`), `eoi_draft_status` `NOT_REVIEWED_BY_TEAM`,
`archived_other_previews`, and `replay` / `kept.status` (`open` or `closed <date>`). Allow ~1-3 min per
candidate (the worker analyses). If a run stops on the analysis wait, finish that candidate with `--resume
<label> --tender-external world_bank:<its OP id> --candidates 1` (the label is printed per candidate), then
archive the candidates you do not keep (step 4).

**3. Record.** Sign in as `plasmatest0@gmail.com` (private window), pick "<Firm> — Plasma preview":
Partners & Experts → own experience (each reference says "From public records, unverified" with
its World Bank notice link), the pursuit → Requirements → EOI package (the draft badge shows on the
version). For a replay, show the replay line under the pursuit title and on the EOI cover.

**4. List and archive — every preview must be archived right after recording.** A preview
carries a real firm's name and public award data in an account you control; leaving it active
risks showing it to the wrong viewer and keeps the demo user inside it.
```
prod$ $RUN python scripts/demo/seed_demo.py --target production --list-previews
prod$ $RUN python scripts/demo/seed_demo.py --target production --archive-preview <organization_id> --confirm SEED_DEMO
prod$ $RUN python scripts/demo/seed_demo.py --target production --list-previews
```
Archiving revokes the demo user's membership and renames the organization "… (archived <date>)";
the records stay (nothing is deleted). The last list must show every preview `archived: true`.

---

## Rollback

ClamAV, db and redis are not part of any rollback. **Default: fix forward.** Roll back only if the
API/frontend do not come up (step 11), sign-in, Explorer, tender details, the workspace or analysis
fail (steps 12-14) and cannot be fixed within an hour, a container keeps restarting, or data looks
wrong. A failed or partial ingest (step 15), a failing test code (step 12b: Google sign-in still works) or a
Gemini key problem are **not** reasons to roll back: fix forward. Every rollback starts with the pre-stop gate
(step 9's three commands).

**A. Deploy 3 images on the new schema (first choice).** All four migrations only add tables and columns (and
change data the Deploy 3 build reads the same way: approved users, an ignored `access_state`).
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect `build_sha` `169d4517…` and smoke with one expected failure: `database schema is not at the
Alembic head: … Can't locate revision identified by '20261016_0002_p1_organization_access'`. Remnants while on A:
the ledger, product events, AI cost rows, sign-in challenges, refresh tokens and alerts stay, unused; **users the
migration approved stay approved** (by design; the old build then lets them sign in with Google, and the company
approval still gates the workspace); e-mail sign-in and Explore disappear with the new images; preview organizations
stay (archive them first if you can).

**A2. Exact return to Deploy 3 (old images, checkout, `.env`).**
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh use "$PREV_SHA"
prod$ git checkout -B pilot/week1 "$PREV_COMMIT" && test "$(git rev-parse HEAD)" = "$PREV_COMMIT" && echo CHECKOUT_OK
prod$ cp -p .env.pre-deploy4 .env && echo ENV_RESTORED
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect `DNS_OK` (STOP without it), `CHECKOUT_OK`, `ENV_RESTORED` (the previous Gemini key and no SMTP come back),
`build_sha` `169d4517…`, the same single expected smoke failure.

**B. Schema rollback (not needed; only while `:latest` is still the new image).** Drops the P1 and S1 tables and
columns, **including the ingested ledger, the AI cost rows, sign-in challenges, refresh tokens and alerts**; the
approvals made by the P1 migration stay (an approved account is not made pending again):
`prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261011_0001_r3_organization_record_events`

**C. Database restore** (loses everything since step 4): Deploy 1 Rollback C with `$SET` from
step 4 (pre-stop gate first), then A2. Never `docker compose down -v`.

---

## Gate and rehearsal (evidence)

**Gate** (`8ef9613` = the release before this runbook commit; LF `git archive` export; backend groups in 700 MB
one-off containers on `plasma_db`'s loopback with a disposable database and Redis, the local staging stack stopped
for memory; frontend and browser groups on Windows):

| Group | Result |
| --- | --- |
| backend (12 batches, a fresh process each) | **1,207 passed**, 1 skipped, **1 failed**: `test_s1_prospect_seed.py::test_prospect_preview_end_to_end`, a test fixture whose "open" tender had a fixed deadline of 2026-10-20 (the seed checks deadlines against the database clock). Fixed in this commit (open fixture deadlines one year ahead, with the matching demo date); the five affected files re-run: **26 passed** |
| security | **118 passed** (incl. the 20 MB upload case) |
| analysis / connectors | 50 / 198 passed |
| migrations | heads, current, check, schema preflight: **PASS** (head `20261016_0002_p1_organization_access`) |
| performance | **PASS** |
| config-dependencies | 24 passed, `pip check` clean; `npm audit --omit=dev` 0 |
| frontend | npm ci, typecheck, lint, **406/406** node tests, RTL audit, production build: **PASS** |
| browser (`release-hardening-browser.py`) | **214 passed, 0 failed** (the fixture ports 8114/8124 and 3114 sat in Windows-reserved ranges that day, so a temporary copy used 8314/8324 and 3314; nothing else changed). P1's new screens are covered by node tests and the P1 E2E screenshots, not by browser cases |

**Rehearsal** (2026-10-20, a fresh copy of the production-shaped database at the Deploy 3 head, the release code in
one-off capped containers, Mailpit as the mail catcher; times include each container's start; the app cut-over
itself (steps 6-11) was not rehearsed: it needs the release images and would stop the shared local stack, and
Deploy 3 proved it):

| Step | Result |
| --- | --- |
| copy of the database | 64 s |
| step 8b SQL | 1 s; `TOTAL 116 \| 4` (116 proposals without a pursuit across 4 organizations: what "Earlier bid drafts" lists) |
| step 9 counts | users approved 15, pending 1, disabled-and-was-pending 0; company profiles approved 7; organizations 7 |
| four migrations (step 10) | **6 s**; output exactly as in step 10; `20261016_0002_p1_organization_access (head)` |
| user-approval after-check | users approved **16**, pending **0**; `USER_APPROVED`/`P1_MIGRATION` audit events **1**; organizations `pilot` **7** (all companies were approved) |
| send_test_sign_in_code.py (step 12b) | 8 s; `delivery=STAGED`, then `outbox run {'leased': 1, 'SENT': 1, …}; this delivery: state=SENT error=None`; the catcher received "Your Plasma sign-in code" |
| pilot_setup.py, firm A (step 19) | dry run 7 s; write with `--send-invitations` 6 s (state `pilot`, plan 2026-11-01 → 2027-02-01, two invitations, e-mails queued); `--list` 4 s (two OPEN invitations); re-run 5 s (`ALREADY_INVITED`, nothing duplicated) |
| pilot_setup.py, firm B | 7 s; one owner invitation |
| e-mail outbox run (what Beat does) | 3 s; `{'leased': 3, 'SENT': 3, …}`: the three invitation e-mails arrived in the catcher |
| one-off API on the migrated copy | ready in 20 s |
| admin data as a non-admin member (step 17.6) | seven **403**; the member's own pursuits **200** |
| an organization set to `explore` (as an admin would) | its member: `/pursuits` **404**, `/explore/overview` **200** |
| first ingest (step 15) | **96 s**, 54 pages, 3,326 notices, 11,236 bidder rows, 0 undated, no truncated pass |
| second ingest | 77 s, 0 created, 3,326 unchanged, 0 rows |
| validation | 58 s; 83 projects (57 fetched, 20 cached, 6 not returned); `FOREIGN_BIDDER_SECTION` 9, `DUPLICATE_AWARD_NOTICE` 20, `PROJECT_NOT_RESOLVABLE` 15 |

