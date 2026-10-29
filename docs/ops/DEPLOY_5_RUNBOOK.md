# Deploy 5 runbook: production → pilot/b1-billing (P2 partner finder, P3 plans, B1 billing), images 640e9be

For the owner, copy-paste on the production host. Same rules as Deploys 1-4: every step has the command, what you
must see and a **STOP** condition; a short clean cut-over (the app is stopped while the schema moves); every feature
proven on production afterwards; problems fixed forward first; the **pre-stop gate** before every app stop
(docs/ops/RUNBOOK_TEMPLATE.md). Window: **Monday 26 Oct 2026, ~22:00 Tashkent**.

New in this window: **P2** (partner finder: firms that won similar awards, introduction requests, the team queue),
**P3** (plans Explore / Pilot / Pursuit Desk / Agent / Enterprise / per-tender, the pursuit counter, limits and
gates), **B1** (online checkout: card through Polar, bank transfer by invoice; the Plasma Pilot and Subscription
Terms v1; activation, renewal, the admin billing console). **If production is still on Deploy 3** (step 1 decides),
this window also brings S1 and P1: the marked **[D3]** steps then come from `docs/ops/DEPLOY_4_RUNBOOK.md`.

> **Corrected after Deploy 5 (30 Oct 2026, see `docs/ops/DEPLOY_5_1_RUNBOOK.md`).** Production has **no API
> domain**: the app is `https://console.plasmaos.uz`, which serves `/api/v1/*` from the backend (Next.js rewrite); on the
> host the backend is `http://127.0.0.1:8000`. Smoke, the webhook URL and the Polar event list below are corrected.
> The Deploy 5 frontend refused the webhook at that URL (401: the route was not public in `proxy.ts`), the
> `worker_pursuit_analysis` service had no `ENVIRONMENT` line (crash loop with `POLAR_ENV=production`), and the
> webhook was subscribed to `checkout.*` only. Deploy 5.1 fixes these; `.env` now also sets
> **`ENVIRONMENT=production`** explicitly (step 7).

> **Night rollback rule.** If the owner's live test (step 14) fails and the fix is not obvious **within 20 minutes**,
> take **Rollback A** and **leave the landing on its old version** (step 15 is not done). Nothing else is decided at
> night.

| | |
| --- | --- |
| Checkout | `pilot/b1-billing` @ its newest commit (this runbook's commit; pushed by the owner before the window) = P1 → P2 → P3 → B1 → RC-5 |
| Images | built from the release commit **`640e9be4a6af42f32ff55e65579c486dfee40bae`** (the runbook commit adds documentation only): `plasma-<service>:640e9be`, bundle `plasma-release-640e9be.tar.gz`, **`1,571,871,993` bytes**, sha256 **`7984b5363d26db7d0a471f2c381a743717aba93e3795225af88cc3c976d7e995`**; `/health` reports `build_sha` `640e9be` |
| Running today | **decided in step 1**: Deploy 4 (images: the `build_sha` that `/health` reports, recorded as `PREV_SHA` in step 1; the Deploy 4 runbook never recorded it; schema `20261016_0002_p1_organization_access`) **or** still Deploy 3 (checkout `a83d575`, images `169d45179bf41786e8f8e305a7379e48f19238f5`, schema `20261011_0001_r3_organization_record_events`). The repository has no record that Deploy 4 ran |
| Host | Hetzner 2 vCPU / 3.7 GiB, `/opt/plasma-console/plasmaos`, `HOST_PROFILE=4gb`, `PLASMA_NO_BUILD=1` |
| Migrations | from Deploy 4: **three** (`20261023_0001_p2_partner_finder` → `20261024_0001_p3_plans_limits` → `20261025_0001_b1_billing`); from Deploy 3: **seven** (Deploy 4's four first). All additive for the schema (the previous build runs on the new schema: Rollback A). Rehearsal: three in **26 s**, seven in **24 s** (step 10) |
| New tables | P2: `partner_requests`, `partner_request_events`, `team_scenario_prospective_members`; P3: `organization_pursuit_usage`, `organization_plan_grants`; B1: `billing_customers`, `terms_acceptances`, `billing_orders`, `billing_invoice_counters`, `billing_invoices`, `billing_payments`, `billing_events`, `billing_pilot_credits`, `billing_fx_rates`, `billing_onboarding_tasks`, `billing_offers` |
| Data changes | P3: `organizations.plan` from the access state (pilot → **Pilot**, paid → Pursuit Desk, explore/disabled → Explore) and one usage row per pursuit that already had an analysis (counted at its first run). B1: none. **Data step (10b)**: `pilot_setup.py` pilots get end date = start + 3 months |
| New behaviour that acts on data | the hourly Beat job `run-billing-schedule` (from step 11): **every Pilot whose end date has come moves to Explore** (terms §7), bank-transfer invoice reminders (days 3, 6), Explore on day 10 unpaid, bank-transfer Pursuit Desk renewals |
| New variables | step 7, one block, each key **added only if missing**: **P1** (Deploy 4's block; Case D4 has them): `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD` (Resend), `SMTP_FROM`, `PUBLIC_APP_URL`, `PUBLIC_BOOK_CALL_URL`, `ADMIN_ALERT_TELEGRAM_CHAT_ID`; **B1**: `POLAR_ENV`, `POLAR_ACCESS_TOKEN`, `POLAR_WEBHOOK_SECRET`, `POLAR_PRODUCT_IDS`, `INVOICE_SELLER_NAME`, `INVOICE_SELLER_ADDRESS`, `INVOICE_SELLER_TIN`, `INVOICE_SELLER_EMAIL`, `INVOICE_SELLER_PHONE`, `INVOICE_BANK_DETAILS_UZS`, `INVOICE_USD_ENABLED=false`, `BILLING_KICKOFF_URL`. **Replaced**: `GEMINI_API_KEY` (only if the key in `.env` does not answer `200`), `TELEGRAM_BOT_TOKEN` (rotated). Landing (Vercel): step 15 |
| Gate | `640e9be` from an LF export (end of this file) |
| **Not touched** | **`db`, `redis` and `clamav` keep their containers** (never `up`, `down`, `restart` or `rollback` them here) |
| Downtime | step 9 → step 11: **~2 min** expected (rehearsal: migrations 24-26 s, data step 4 s; Deploy 3 measured image switch 8 s, start to `/health/ready` 48 s, stop ~12 s) |
| Window | ~35 min to step 11 plus the transfer (step 6); live test ~30 min (step 14); landing ~5 min |

**Rule for this whole window: every `up` names its services and has `--no-deps`.** Never run `up` without a service
list, `compose-release.sh rollback`, `docker compose up`, `down` or `restart`: with this compose file those would
recreate `db`/`redis`.

Conventions as before: `prod$` on the production host in `/opt/plasma-console/plasmaos`; `laptop$` on the owner's PC
(Git Bash). `<prod>` as before. **Domains**: the app is `https://console.plasmaos.uz`; there is **no API domain**
(`/api/v1/*` on the app domain reaches the backend through the Next.js rewrite; on the host: `http://127.0.0.1:8000`).

APP services (the only ones this runbook recreates):
`celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend`

**One-off containers** (`scripts/compose-release.sh run --rm --no-deps -T backend …`) for the data step and every
script; never `exec` into `plasma_backend`. Check `free -h` shows `available` ≥ ~600Mi before each.

---

## Before the window (Monday, by 18:00)

1. **Release artifacts** (done by the release session): images, bundle, this runbook with the values above.
2. **Polar live**: section "Polar live switch" below, items 1-4 (products, token, webhook with its secret, the
   one-use 100% test code). If the live account is not ready by 21:00, run the window with **`POLAR_ENV=sandbox`**
   and the sandbox values (card test with 4242 4242 4242 4242 instead of the code); switch to live later with the
   same section.
3. **Bank details**: UZS account at **Aloqa Bank** (MFO 00401, beneficiary Plasma AI Solutions) in step 7. **USD
   account: not yet**, so `INVOICE_USD_ENABLED=false`: non-resident customers are offered **card only**.
4. **Terms**: `docs/legal/PILOT_TERMS_v1.md` / `.pdf` (owner-approved, effective 26 Oct 2026) are in the release.
5. **Landing**: the R2 build with the checkout links (`landing/r2`, "Start a pilot" → `https://console.plasmaos.uz/billing/start?plan=pilot`)
   deployed as a **Vercel preview, not promoted**, with the Vercel variables of step 15 set. Step 15 promotes it
   after the live test.
6. **E-mail and Gemini**: **[D3]** Deploy 4's "Before the window" (Resend domain `plasmaos.uz` verified: DKIM, MX,
   SPF). Both cases: an app Resend API key and the production Gemini key (proven `200`) at hand for step 7, which
   uses them only where `.env` lacks them.
7. **Telegram**: access to @BotFather for the production bot. The token is revoked and replaced in step 7, not
   before.

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<the newest commit of pilot/b1-billing (this runbook's commit)>
prod$ SHA=640e9be4a6af42f32ff55e65579c486dfee40bae
prod$ PREV_COMMIT=<full SHA from `git rev-parse HEAD` in step 1>
prod$ PREV_SHA=<build_sha from `curl /health` in step 1, full>
prod$ APPS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ SMOKE_ORG_ID=<"Plasma Smoke Test" organization_id, as in Deploy 3>
prod$ RUN="scripts/compose-release.sh run --rm --no-deps -T backend"
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```

## 1. Pre-checks: which deploy runs today (nothing changes)

```
prod$ git status --porcelain; git rev-parse HEAD
prod$ free -h; df -h /
prod$ docker exec plasma_backend alembic current
prod$ tail -n 3 .release-history
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy5-dbredis.txt
prod$ docker inspect -f '{{.State.Health.Status}} oom={{.State.OOMKilled}}' plasma_clamav
```
Decide the case from `alembic current`:
- **`20261016_0002_p1_organization_access (head)`** → **Case D4** (Deploy 4 ran): three migrations; ignore every
  **[D3]** line.
- **`20261011_0001_r3_organization_record_events (head)`** → **Case D3** (Deploy 4 never ran): seven migrations;
  do the **[D3]** steps (Deploy 4 runbook steps named there).
- Anything else → **STOP** (this runbook does not apply).

Expect: no file lines (untracked `.env.pre-deploy*` are fine); `available` ≥ ~700Mi; the last `.release-history`
line names `PREV_SHA`; `7` images with `PREV_SHA`; two fingerprint lines (compared in steps 11 and 18); ClamAV
`healthy oom=false`.

**Disk pre-step** (keeps `PREV_SHA`, the rollback point):
```
prod$ scripts/ops/prune_safe.sh --keep "${PREV_SHA:0:7}" --min-releases 1
prod$ scripts/ops/prune_safe.sh --keep "${PREV_SHA:0:7}" --min-releases 1 --apply
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$PREV_SHA"; df -h /
```
The dry run never lists a `PREV_SHA` tag (**STOP** if it does). After `--apply`: `7` and the `PRUNE_RESULT` line;
`Avail` ≥ **12G** (**STOP** below).

## 2. Check out the release (files only, nothing restarts)

```
prod$ git fetch origin pilot/b1-billing
prod$ git checkout -B pilot/b1-billing "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls backend/scripts/deploy5_pilot_end_dates.py backend/scripts/polar_sandbox_check.py docs/legal/PILOT_TERMS_v1.md \
         docs/legal/PILOT_TERMS_v1.pdf docs/ops/DEPLOY_5_RUNBOOK.md docs/ops/DEPLOY_4_RUNBOOK.md
```
Expect `CHECKOUT_OK` and the six paths. **STOP** otherwise (`git checkout -B <previous branch> "$PREV_COMMIT"`).

## 3. Record Celery Beat memory (read-only)
```
prod$ scripts/ops/beat_memory.sh --target production | tee $HOME/deploy5-beat.txt
prod$ BEAT_RSS_KB=$(grep -o 'rss_kb=[0-9]*' $HOME/deploy5-beat.txt | cut -d= -f2); echo $BEAT_RSS_KB
```

## 4. Backup: `BACKUP_RESULT` from R2, or the laptop copy (required)

**If off-host backups are configured** (`/etc/plasma/ops.env` with `BACKUP_REMOTE`):
```
prod$ sudo test -f /etc/plasma/ops.env && sudo grep -q '^BACKUP_REMOTE=.' /etc/plasma/ops.env && echo R2_CONFIGURED
prod$ sudo systemctl start plasma-backup-daily.service; journalctl -u plasma-backup-daily -n 20 -o cat | grep BACKUP_RESULT
```
With `R2_CONFIGURED`: expect a fresh `BACKUP_RESULT set=plasma_prod_… tier=daily … remote=r2:<bucket>/plasma/daily
via rclone …` line from **now**. Write its `set=` value down as `$SET`.

**Otherwise** (no `R2_CONFIGURED`), the laptop copy:
```
prod$ BACKUP_REMOTE=file:///var/backups/plasma scripts/ops/backup.sh --target production --skip-tender-documents
prod$ SET=<the set= value of the last line>; ls -l /var/backups/plasma/$SET.*
laptop$ PROD=<prod>; SET=<same>; scp "$PROD:/var/backups/plasma/$SET.*" /d/plasma-backups/ && cd /d/plasma-backups && sha256sum -c "$SET.sha256"
```
Expect `BACKUP_RESULT set=… tier=none …` and `…dump: OK`, `…private.tar.gz: OK`.

**STOP before step 9 without a `BACKUP_RESULT` line from R2 or a verified laptop copy.**

## 5. Host size
Stay on 4gb. Memory limits are unchanged (step 7 shows them).

## 6. Transfer the image bundle
```
laptop$ scp /d/plasma-release/plasma-release-640e9be.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-640e9be.tar.gz
```
Expect `7984b5363d26db7d0a471f2c381a743717aba93e3795225af88cc3c976d7e995`. **STOP** if it differs (copy again).

## 7. `.env`: keep a copy, one block for P1 and B1 (only if missing), the production Gemini key, the rotated Telegram token

One block for both cases: Deploy 4's P1 keys (SMTP through Resend, `PUBLIC_APP_URL`, `PUBLIC_BOOK_CALL_URL`, team
alerts) and the B1 keys are each **added only if the key is missing**, so Case D4 keeps its values and Case D3 gets
them all; re-running the block is safe. Two keys are **replaced**: `GEMINI_API_KEY` (only if the key in `.env` does not
answer `200`) and `TELEGRAM_BOT_TOKEN` (the rotated token).

```
prod$ cp -p .env .env.pre-deploy5 && chmod 600 .env.pre-deploy5 && cmp .env .env.pre-deploy5 && echo ENV_SAVED
prod$ grep -c '^SECRET_KEY=.' .env; grep -c '^PLASMA_ADMIN_EMAILS=.' .env
prod$ set +o history   # the values below are secrets: keep them out of ~/.bash_history
prod$ addenv() { if grep -q "^$1=" .env; then echo "KEEP $1"; else printf '%s=%s\n' "$1" "$2" >> .env; echo "ADDED $1"; fi; }
prod$ setenv() { if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; echo "REPLACED $1"; else printf '%s=%s\n' "$1" "$2" >> .env; echo "ADDED $1"; fi; }
prod$ grep -q '^# --- Deploy 5' .env || printf '\n# --- Deploy 5 (P1 from Deploy 4 if missing, B1 billing) ---\n' >> .env
# Deploy 5.1: explicit, so every service reads production even where compose does not set it
prod$ setenv ENVIRONMENT 'production'
# P1 (Deploy 4 step 7): sign-in codes, invitations, invoices and the welcome e-mail over Resend SMTP
prod$ addenv SMTP_HOST 'smtp.resend.com'
prod$ addenv SMTP_PORT '587'
prod$ addenv SMTP_TLS 'starttls'
prod$ addenv SMTP_USER 'resend'
prod$ addenv SMTP_PASSWORD '<the app Resend API key re_…, sending access to plasmaos.uz>'
prod$ addenv SMTP_FROM 'Plasma <no-reply@plasmaos.uz>'
prod$ addenv PUBLIC_APP_URL 'https://console.plasmaos.uz'
prod$ addenv PUBLIC_BOOK_CALL_URL 'https://cal.com/plasmahq/30min'
# Team alerts (sign-ups, pilot and call requests, purchases, AI provider failures): Telegram if set, else e-mail to PLASMA_ADMIN_EMAILS
prod$ addenv ADMIN_ALERT_TELEGRAM_CHAT_ID '<team group chat id, -100…>'
# B1: Polar ("Polar live switch" section). production = live payments; sandbox = test mode (https://sandbox-api.polar.sh)
prod$ addenv POLAR_ENV 'production'
prod$ addenv POLAR_ACCESS_TOKEN '<Polar organization access token: checkouts:write, discounts:write, products:read, customer_sessions:write, orders:read, subscriptions:read>'
prod$ addenv POLAR_WEBHOOK_SECRET '<whsec_… of the webhook endpoint>'
prod$ addenv POLAR_PRODUCT_IDS '{"pilot":"<id>","pursuit_desk":"<id>","extra_pursuit":"<id>","per_tender":"<id>"}'
# B1: bank transfer invoices (proforma; the official e-invoice is issued after payment)
prod$ addenv INVOICE_SELLER_NAME 'PLASMA AI SOLUTIONS MChJ (LLC)'
prod$ addenv INVOICE_SELLER_ADDRESS '21 Mustaqillik Street, Qarshi, Qashqadaryo, Uzbekistan'
prod$ addenv INVOICE_SELLER_TIN '313156099'
prod$ addenv INVOICE_SELLER_EMAIL 'hq@plasmaos.uz'
prod$ addenv INVOICE_SELLER_PHONE '+998 94 877 87 83'
prod$ addenv INVOICE_BANK_DETAILS_UZS 'Bank: Aloqa Bank | Account (UZS): <20-digit account> | MFO (bank code): 00401 | Beneficiary: Plasma AI Solutions | TIN: 313156099'
# USD account not opened yet: non-residents pay by card only. Later: INVOICE_BANK_DETAILS_USD=… and INVOICE_USD_ENABLED=true
prod$ addenv INVOICE_USD_ENABLED 'false'
prod$ addenv BILLING_KICKOFF_URL 'https://cal.com/plasmahq/30min'
```
Expect `ENV_SAVED`, `1`, `1` (an existing `SECRET_KEY` and `PLASMA_ADMIN_EMAILS`), then one `KEEP`/`ADDED` line per
key: Case D4 `KEEP` for the P1 keys, `ADDED` for B1; Case D3 `ADDED` throughout. A `KEEP` for a key that holds an
old or empty value: `setenv <KEY> '<value>'`.

**Production Gemini key** (only if the key in `.env` is not the production one). The check sends one tiny call
with the key **from `.env`** (a fraction of a cent; the key is not typed or printed):
```
prod$ gemini_check() { curl -s -o /dev/null -w '%{http_code}\n' -H "x-goog-api-key: $(grep '^GEMINI_API_KEY=' .env | cut -d= -f2-)" -H 'Content-Type: application/json' \
        -d '{"contents":[{"parts":[{"text":"Reply OK"}]}]}' "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"; }
prod$ gemini_check
```
`200` → keep it (Case D4: Deploy 4 put the production key in). Anything else (Case D3 still has the development key,
which returns `402`): `setenv GEMINI_API_KEY '<PRODUCTION_GEMINI_KEY>'` (the key from a separate billing account), then
`gemini_check` again → `200`. **STOP** without `200` (every analysis would fail).

**Rotated `TELEGRAM_BOT_TOKEN`.** Revoke now, not before the window (production alerts fail from the revoke until
step 11; the app is stopped from step 9 anyway): @BotFather → `/mybots` → the production bot → API Token → **Revoke
current token**, copy the new token.
```
prod$ setenv TELEGRAM_BOT_TOKEN '<the new token from BotFather>'
prod$ tg_check() { curl -s "https://api.telegram.org/bot$(grep '^TELEGRAM_BOT_TOKEN=' "$1" | cut -d= -f2-)/getMe" | grep -o '"ok":[a-z]*'; }
prod$ tg_check .env; tg_check .env.pre-deploy5
prod$ set -o history
```
Expect `REPLACED TELEGRAM_BOT_TOKEN`, then `"ok":true` (the new token) and `"ok":false` (the revoked one in the copy).
**STOP** on `"ok":false` for `.env`. The same bot elsewhere needs the new token as well, or its messages stop: the
landing's form alerts (Vercel `TELEGRAM_BOT_TOKEN`, step 15) and the host alerts (`OPS_TELEGRAM_BOT_TOKEN` in
`/etc/plasma/ops.env`, if it is the same bot).

**Every key present once, with a value**, and **no placeholders left**:
```
prod$ KEYS="ENVIRONMENT SECRET_KEY PLASMA_ADMIN_EMAILS TELEGRAM_BOT_TOKEN GEMINI_API_KEY SMTP_HOST SMTP_PORT SMTP_TLS SMTP_USER SMTP_PASSWORD SMTP_FROM PUBLIC_APP_URL PUBLIC_BOOK_CALL_URL ADMIN_ALERT_TELEGRAM_CHAT_ID POLAR_ENV POLAR_ACCESS_TOKEN POLAR_WEBHOOK_SECRET POLAR_PRODUCT_IDS INVOICE_SELLER_NAME INVOICE_SELLER_ADDRESS INVOICE_SELLER_TIN INVOICE_SELLER_EMAIL INVOICE_SELLER_PHONE INVOICE_BANK_DETAILS_UZS INVOICE_USD_ENABLED BILLING_KICKOFF_URL"
prod$ bad=0; for k in $KEYS; do n="$(grep -c "^$k=" .env)/$(grep -c "^$k=." .env)"; [ "$n" = 1/1 ] || { echo "BAD $k lines/with-value=$n"; bad=1; }; done; [ $bad = 0 ] && echo ALL_KEYS_OK
prod$ grep -nE '^[A-Z0-9_]+=.*(<[^>@]*>|…|CHANGE_ME)' .env | cut -d= -f1; echo PLACEHOLDER_SCAN_DONE
prod$ chmod 600 .env
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit' | sort | uniq -c
```
Expect `ALL_KEYS_OK` (a `BAD` line: `0/0` missing → `addenv`; `1/0` empty or `2/…` duplicate → fix that line with
`setenv`, removing the extra one by hand), then **only** `PLACEHOLDER_SCAN_DONE` (every line printed before it is a
`<…>` value still to fill: `setenv <KEY> '<value>'`, line number and key shown, never the value; `SMTP_FROM`'s
`<no-reply@plasmaos.uz>` is not a placeholder), `CONFIG_OK`, and exactly the Deploy 3/4 lines:
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
**STOP** on different numbers, without `ALL_KEYS_OK`, or with a placeholder line (card checkout needs
`PUBLIC_APP_URL`; invoices and the welcome e-mail need SMTP). The backend **refuses to start** with
`POLAR_ENV=production` unless the token, the secret and the product ids are all set (step 11 would show it): fill
them or `setenv POLAR_ENV 'sandbox'` with the sandbox values.

- **`SECRET_KEY` does not change** in this window: the sign-in codes, their limiter keys and the sealed codes in the
  e-mail outbox are derived from it; rotating it invalidates every open code and every session.
- The app's Resend key (`SMTP_PASSWORD`) and the landing's (`RESEND_API_KEY`, step 15) are separate keys, so either
  can be revoked alone. **[D3]**: the domain `plasmaos.uz` must be verified in Resend first (Deploy 4, "Before the
  window").
- Telegram chat id: add the bot to the team group, send one message, then
  `curl -s "https://api.telegram.org/bot$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)/getUpdates" | grep -o '"chat":{"id":-[0-9]*'`.
- `AI_PRICE_TABLE_JSON` is not part of this block (**[D3]**: Deploy 4 step 16 decides it).

## 8. Import the images
```
prod$ scripts/compose-release.sh import --expect "$SHA" < /opt/plasma-console/plasma-release-640e9be.tar.gz
prod$ rm /opt/plasma-console/plasma-release-640e9be.tar.gz && df -h /
```
Expect seven `Loaded image: plasma-<service>:640e9be…`, then `every service has plasma-<service>:640e9be…`; `Use%` ≤ 85 %.
**STOP** on `import incomplete` (repeat step 6).

## 9. Counts, pre-stop gate, then stop the app (db, redis and ClamAV keep running)

Counts before the migrations (kept for the step 10 checks):
```
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -At <<'SQL' | tee $HOME/deploy5-before-counts.txt
select 'users', approval_status, count(*) from users group by 2 order by 2;
select 'company_profiles', approval_status, count(*) from company_profiles group by 2 order by 2;
select 'organizations', '', count(*) from organizations;
select 'pursuits_with_runs', '', count(distinct pursuit_id) from pursuit_analysis_runs;
SQL
prod$ docker exec plasma_db psql -U plasma -d plasma_ai -At -c "select 'organizations', access_state, count(*) from organizations group by 2 order by 2" | tee -a $HOME/deploy5-before-counts.txt
```
(**[D3]**: the last command fails, there is no `access_state` yet; that is expected.)

The pre-stop gate (Deploy 5.1: moved after the counts, right before the stop):
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy5-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect `DNS_OK`, `"ready":true`, `DBREDIS_UNCHANGED`. **STOP, do not stop anything** without `DNS_OK`: `docker restart
plasma_db plasma_redis plasma_clamav`, then `for s in $APPS; do docker restart plasma_$s; done`, `/health/ready`, gate again.
```
prod$ date -u +%T
prod$ scripts/compose-release.sh stop $APPS
prod$ docker ps --format '{{.Names}}' | sort
```
Expect seven `Stopped`, then only `plasma_clamav`, `plasma_db`, `plasma_redis`.
Abort without deploying: `prod$ for s in $APPS; do docker start plasma_$s; done`.

## 10. Switch images, migrate (in order)

```
prod$ scripts/compose-release.sh use "$SHA"
prod$ time scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic current
```
Expect `images switched to 640e9be; nothing was restarted`, then (**[D3]**: first Deploy 4's four lines, as in the
Deploy 4 runbook step 10):
```
INFO  [alembic.runtime.migration] Running upgrade 20261016_0002_p1_organization_access -> 20261023_0001_p2_partner_finder, …
INFO  [alembic.runtime.migration] Running upgrade 20261023_0001_p2_partner_finder -> 20261024_0001_p3_plans_limits, P3: plans and limits. …
INFO  [alembic.runtime.migration] Running upgrade 20261024_0001_p3_plans_limits -> 20261025_0001_b1_billing, B1: billing. …
20261025_0001_b1_billing (head)
```
Rehearsal (a copy of the production-shaped database, each migration timed separately, each including ~2 s of
start-up): from Deploy 4: P2 11.5 s, P3 8.4 s, B1 5.7 s (**26 s**); from Deploy 3: S1 5.3 + 2.7 s, P1 3.3 + 2.8 s,
P2 3.3 s, P3 3.1 s, B1 3.6 s (**24 s**).

What they do:
1. `20261023_0001_p2_partner_finder`: partner requests, their events, prospective JV members (new tables only).
2. `20261024_0001_p3_plans_limits`: `organizations.plan` (+ two override columns), `organization_pursuit_usage`
   (backfilled: one row per pursuit with an analysis), `organization_plan_grants`, alert kind `PLAN_USAGE`.
3. `20261025_0001_b1_billing`: the eleven billing tables (empty), `organizations.billing_status`, the BILLING
   e-mail kinds and team alert.

**STOP → Rollback A2** if an upgrade fails (each migration is one transaction; the ones before it stay applied,
which the previous build tolerates).

After-check:
```
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -At <<'SQL'
select 'organizations', access_state, plan, count(*) from organizations group by 2, 3 order by 2, 3;
select 'usage_rows', count(*) from organization_pursuit_usage;
select 'billing_orders', count(*) from billing_orders;
select 'users', approval_status, count(*) from users group by 2 order by 2;
SQL
```
Expect: every `pilot` organization has plan `pilot`, `paid` → `pursuit_desk`, `explore`/`disabled` → `explore`; the
organization total as before; `usage_rows` = `pursuits_with_runs` from step 9; `billing_orders` 0. **[D3]**: also
Deploy 4's user-approval after-check (pending users 0, approved = before approved + pending). Rehearsal: users
approved 16, pending 0; organizations 7 (all `pilot` / `pilot`); usage rows 10; billing orders 0. **STOP → Rollback A**
on a count that does not add up.

## 10b. Data step: pilot end dates (before the app starts)

From step 11 the hourly billing job moves **every Pilot whose end date has come to Explore**. First list:
```
prod$ time $RUN python scripts/deploy5_pilot_end_dates.py --target production | tee $HOME/deploy5-pilots.txt
```
One JSON line per Pilot organization, then `SUMMARY {"set": …, "keep": …, "no_start_date": …, "listed_only": …,
"ends_at_first_run": …}`:
- `pilot_setup: true` (created by `scripts/pilot_setup.py`): `action` **`set`** (end date becomes start + 3 months),
  `keep` (already so) or `no_start_date` (left alone: set dates in Admin → Organizations later);
- `pilot_setup: false` (approved by hand before P1, or set by an admin): **`listed_only`**, never changed here. Without
  an end date such a pilot never ends; with one, it ends on that date;
- **`ends_at_first_run: true`**: this pilot's end date (after the step) is today or earlier, so it **moves to Explore
  within the hour**. Owner: if that is not intended, extend it now:
  `prod$ docker exec plasma_db psql -U plasma -d plasma_ai -c "update organizations set plan_ends_on = '<YYYY-MM-DD>' where id = '<organization_id>' and plan = 'pilot'"`
  (one row; then re-run the list; record the change in the log).

Then apply and re-check:
```
prod$ time $RUN python scripts/deploy5_pilot_end_dates.py --target production --apply --confirm PILOT_END_DATES | tail -n 1
prod$ $RUN python scripts/deploy5_pilot_end_dates.py --target production | tail -n 1
```
Expect the first `SUMMARY` with `"applied"` = the listed `set` count, the second with `"set": 0`. Each change is an
`ORGANIZATION_ACCESS_CHANGED` audit event (actor `deploy5-pilot-end-dates`). Rehearsal (two `pilot_setup.py`
pilots added to the copy): list 4 s, `set` 1 / `keep` 1 / `listed_only` 7; apply 4 s, `applied` 1; re-run `set` 0.
The production-shaped copy itself has **7 pilots without dates** (`listed_only`): they keep running until an admin
gives them an end date.

## 11. Start the release

```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; date -u +%T; curl -fsS http://127.0.0.1:8000/health; echo
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ docker inspect -f '{{.State.Health.Status}} started={{.State.StartedAt}}' plasma_clamav
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy5-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect `"build_sha":"640e9be"`, `FRONTEND_OK`, ClamAV `healthy` with its old start time, `DBREDIS_UNCHANGED`. **STOP →
Rollback A** if `/health/ready` is not OK after 5 minutes (`docker logs plasma_backend --tail 30`: a
`POLAR_ENV=production requires …` line means step 7's Polar values are incomplete: fix `.env`, `up` again).

## 12. Smoke, Beat memory, plans

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
prod$ docker exec plasma_db psql -U plasma -d plasma_ai -c "select plan, access_state, billing_status, count(*) from organizations group by 1,2,3"
```
Expect `Result: N ok, M warning(s), 0 failure(s)`, `analysis smoke: OK`, Beat `growth=…%` exit 0, the plans as in
step 10, `billing_status` empty everywhere.

**[D3]** now: Deploy 4 steps **12b** (test sign-in code), **13-14** (live analysis and EOI smoke), **15** (award
ledger), **16** (AI prices) and **17** (S1/P1 feature checks).

## 13. The Polar webhook route is reachable (no payment)

```
prod$ curl -s -o /dev/null -w '%{http_code}\n' -X POST https://console.plasmaos.uz/api/v1/billing/webhooks/polar
prod$ curl -s -X POST https://console.plasmaos.uz/api/v1/billing/webhooks/polar; echo
```
Expect `403` and `{"detail":"webhook_headers_missing"}` (the route answers through the app domain and the frontend's
`/api/v1` rewrite; unsigned calls are refused and stored nowhere). **`401 {"detail":"Unauthorized"}`** = a frontend
before Deploy 5.1 (its proxy did not let the webhook through): deploy 5.1. **STOP the live test** on `404`/`502` (Caddy or the route: fix forward). In the Polar
dashboard (Settings → Webhooks → the endpoint) the URL must be exactly this one.

## 14. The owner's live test (production, ~30 min)

Use two **new** test accounts (personal mailboxes, not admins), each with its own test organization. Keep a log of
every result. The night rollback rule applies.

**14.1 Explore limits** (test account A, a fresh self sign-up):
1. Sign in with an e-mail code; complete onboarding (company form). → The **Explore** view: opportunities, "Check one
   tender free each month", "Start a pilot", "Book a call". A **new sign-up** team alert arrives.
2. "Check this tender" on one open tender → its pursuit opens with only **Overview** and **Requirements**; start the
   analysis. → It runs (counted: Admin → Organizations shows 1 of 1).
3. Back on Explore, "Check this tender" on a second tender and start its analysis. → Refused: **"This month's free
   tender check is used. Start a pilot, or check another tender next month"**; the notice "the next one opens on
   1 Nov 2026".
4. Team: invite one colleague → allowed (the owner + 1 = 2 seats; an open invitation takes a seat); a second
   invitation → refused (**Explore: 2 users**). Revoke the open invitation afterwards.

**14.2 Pilot by card with the one-use 100% code** (account A, continuing):
1. "Start a pilot" → company details (non-resident or resident: card either way) → **Terms** (the full Plasma Pilot and
   Subscription Terms v1; tick "I have read and accept…") → **Card** → "Continue to card payment".
   → Polar's checkout (live, not sandbox: no "test mode" banner) for **USD 900**.
2. Enter the one-use 100% discount code (section "Polar live switch", item 4) → total **USD 0** → pay.
   → Back on Plasma: "Confirming your payment…" then **"Pilot is active"** within ~1 minute.
3. Check: Admin → Billing → the organization: order **paid** (amount 0, card), a Polar webhook event `order.paid` →
   `activated`, terms acceptance (version, hash, account A's e-mail, an IP that is **not** 172.x/10.x), an open
   onboarding task; the team alert "bought Pilot (card)"; the welcome e-mail at the billing e-mail with the kickoff
   link and the **terms PDF attached**; the plan **Pilot**, today → +3 months, 6 pursuits (the step 14.1 pursuit
   still counts 1).
   **If "Confirming" stays > 2 minutes**: Polar → Webhooks → the endpoint's deliveries. `403` = the secret in `.env`
   differs from the endpoint's (copy it again, `up` backend); no delivery = wrong URL; `202` with an outcome other
   than `activated` = send the log line `docker logs plasma_backend 2>&1 | grep polar_webhook | tail` to the team.
4. Then put the test organization back: Admin → Billing → "Override plan or status" → plan `explore`, status `none`,
   reason "Deploy 5 live test" (or disable it in Admin → Organizations).

**14.3 Pilot by bank transfer** (test account B, a resident firm, a fresh self sign-up):
1. "Start a pilot" → company details with **"Registered in Uzbekistan"** and a 9-digit TIN → Terms → **Bank
   transfer** ("We e-mail an invoice in UZS…; payment is due within 7 days") → "Get the invoice and start now".
   → "Invoice PL-2026-001 is on its way"; **the workspace opens at once** (Pilot) with the notice "Invoice PL-2026-001
   is waiting for payment".
2. Check the e-mail at the billing address: "Payment invoice (proforma) PL-2026-001 from Plasma" with the PDF: title
   **"Payment invoice (proforma) PL-2026-001"**, PLASMA AI SOLUTIONS MChJ, Qarshi, TIN 313156099, **Aloqa Bank, MFO
   00401**, USD 900 = UZS at **today's CBU rate** (compare with cbu.uz), due in 7 days, the day-10 rule, the
   30-day guarantee, "The official electronic invoice is issued after payment."
3. A non-resident company (untick "Registered in Uzbekistan") sees **no bank transfer** option (card only).
4. Then: Admin → Billing → the organization → the order → **Record refund** with note "Deploy 5 live test, no
   payment" and "Return the organization to Explore" ticked. → Invoice **void**, plan Explore. **PL-2026-001 is used
   by this test** (a voided proforma; the next real invoice is PL-2026-002).

**Pass**: every arrow above. **Fail and not obvious within 20 minutes → Rollback A, landing unchanged.**

## 15. Landing: promote the checkout links (only after step 14 passes)

**Vercel variables** (plasma-landing → Settings → Environment Variables; set each for **Production and Preview**, so
the preview checked before the window and the promoted build read the same values; reference:
`docs/r2/LANDING_R2.md` in the landing repository):

| Variable | Value | Read |
| --- | --- | --- |
| `RESEND_API_KEY` | the landing's own Resend API key (`re_…`, sending access to `plasmaos.uz`; not the app's `SMTP_PASSWORD`). **Required**: without it every form answers 503 | at run time |
| `FORMS_TO_EMAIL` | `hq@plasmaos.uz` (the default; the inbox for all four forms) | at run time |
| `FORMS_FROM_EMAIL` | unset (default `Plasma website <forms@plasmaos.uz>`; the domain is the one verified in Resend) | at run time |
| `NEXT_PUBLIC_BOOKING_URL` | `https://cal.com/plasmahq/30min`, the same link as `PUBLIC_BOOK_CALL_URL` and `BILLING_KICKOFF_URL` (step 7) | at build |
| app URL | **no variable**: `appUrl` in the landing's `src/config/site.ts` is `https://console.plasmaos.uz/`; "Sign in", Explore and the checkout links are built from it. It must equal `PUBLIC_APP_URL` (step 7); **STOP** this step if it does not (a landing code change) | at build |
| `COMPANY_LEGAL_NAME` | only the legal name the owner confirms for the site (the registered name is on the invoices: `INVOICE_SELLER_NAME`); empty shows "Plasma". Never a guess | at build |
| `PILOT_GUARANTEE` | unset (on: "Cancel within the first 30 days and we refund the full fee.", terms §6); `off` hides it | at build |
| `SECURITY_PROGRAM_LINE` | unset (on, owner 24 Oct 2026); `off` hides it | at build |
| `BACKUPS_LIVE` | `1` **only** if off-host backups run (step 4: `R2_CONFIGURED`) and a restore test passed; else unset | at build |
| `HOSTING_REGION_TEXT` | unset unless the owner approved the text of "Where your data is" | at build |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional form alerts; if this is the production bot, the **rotated** token from step 7 | at run time |

A build-time value changed after the preview was built needs a redeploy of the preview before promoting it.

In Vercel (plasma-landing): promote the `landing/r2` preview checked in "Before the window" to production. Check
`https://plasmaos.uz/en/pricing`: "Start a pilot" opens `https://console.plasmaos.uz/billing/start?plan=pilot…` and lands on
the checkout (signed out: the sign-in page, then the checkout again with `plan` kept); "Book a demo" opens the
cal.com link; one "Request the trust pack" form (your own e-mail) arrives in `FORMS_TO_EMAIL`. **On a night rollback
this step is not done**: the landing stays on its old version.

## 16. Feature check (owner, browser; may be next morning)

1. **Admin → Billing**: onboarding queue (the step 14 tasks: mark done), customers, an organization's detail
   (invoices, orders with `ref`/`utm_*` when the visit had them, payments, terms, webhook events, audit).
2. **Per-tender review**: on a test organization in Explore, "Per-tender: checkout link" → a one-use link
   `…/billing/start?plan=per_tender&offer=…` (shown once); opening it shows the checkout for USD 400; a second use is
   refused. "Per-tender: invoice (signed order)" issues a proforma at once.
3. **Partner finder** (P2) on a pilot organization's pursuit with an analysis: Team tab → gaps → suggestions;
   "Request introduction" → Admin → Partner requests.
4. **Plans** (P3): Admin → Organizations shows plan, period, pursuits used/limit, introductions; the 80 % notice.
5. **Billing page** of a card customer shows "Manage subscription" (opens Polar's customer portal); a bank-transfer
   Pursuit Desk shows "Cancel renewal" (the request appears in Admin → Billing with "Confirm cancellation").

## 17. Done, and the 24-hour check

```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy5-dbredis.txt && echo DBREDIS_UNCHANGED
prod$ scripts/ops/disk_report.sh --threshold 85; free -h; tail -n 4 .release-history
```
24 hours later:
```
prod$ docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -c "select kind, state, count(*) from email_deliveries where created_at > now() - interval '1 day' group by 1,2" -c "select kind, state, count(*) from admin_alerts where created_at > now() - interval '1 day' group by 1,2" -c "select event_type, outcome, processing_error, count(*) from billing_events group by 1,2,3"
```
Expect `oom=false restarts=0`, smoke `0 failure(s)`, Beat exit 0, e-mails `SENT`, alerts delivered, every billing event
processed (no `processing_error`). Then delete the backup copy, `.env.pre-deploy5` (it holds the revoked Telegram
token) and `.env.deploy5` if a Rollback A2 made one.

---

## Polar live switch

**1. Products** (Polar → Products, live organization; currency USD; exact prices, as the app's catalogue):

| Product | Type | Price | `POLAR_PRODUCT_IDS` key |
| --- | --- | --- | --- |
| Pilot | one-time | 900.00 | `pilot` |
| Pursuit Desk | recurring, **yearly** | 6,000.00 | `pursuit_desk` |
| Extra pursuit | one-time | 200.00 | `extra_pursuit` |
| Per-tender review | one-time | 400.00 | `per_tender` |

Copy each product id (Product → ⋯ → Copy ID).

**2. Organization access token** (Settings → Developers → New token): scopes **`checkouts:write`,
`discounts:write`, `products:read`, `customer_sessions:write`, `orders:read`, `subscriptions:read`** (the last two for
`scripts/billing/reconcile_polar.py`, Deploy 5.1); no expiry or one year. Shown once. A token's scopes cannot be added
later: create a new one and replace `POLAR_ACCESS_TOKEN`.

**3. Webhook** (Settings → Webhooks → Add endpoint):
- URL: **`https://console.plasmaos.uz/api/v1/billing/webhooks/polar`**; format **Raw**;
- events, exactly these eight (**not** `checkout.*`: the app ignores them, and an endpoint subscribed to `checkout.*`
  only never activates a card payment): **`order.paid`, `order.refunded`, `subscription.created`,
  `subscription.active`, `subscription.updated`, `subscription.canceled`, `subscription.uncanceled`,
  `subscription.revoked`**;
- **secret: generate a new one for production** (never reuse the sandbox secret; the sandbox secret was shared in a
  chat on 25 Oct and is to be regenerated there too). Copy the `whsec_…` value.
- Rotating later: regenerate in Polar, put the new value in `.env`, `scripts/compose-release.sh up "$SHA" --no-deps
  backend` (pre-stop gate first). Deliveries in between fail with 403 and Polar retries them.

**4. The one-use 100% test code** (Discounts → New): type **percentage 100 %**, duration **once**, **maximum
redemptions 1**, products **Pilot** only, a code like `D5LIVE-<random>`. The app's checkout accepts codes unless it
applies the pilot credit itself. Delete or let it expire after step 14.2.

**5. `.env` keys** (step 7): `POLAR_ENV=production`, `POLAR_ACCESS_TOKEN`, `POLAR_WEBHOOK_SECRET`, `POLAR_PRODUCT_IDS`
with the four ids. `POLAR_ENV=production` is refused unless the environment is production and all three values are
set. **Back to the sandbox**: `POLAR_ENV=sandbox` with the sandbox token, secret and product ids, then `up` the APP
services (pre-stop gate first). Check either way from a one-off container:
```
prod$ $RUN python scripts/polar_sandbox_check.py
```
(sandbox only: it refuses `POLAR_ENV=production` by design; for live, the product list in the Polar dashboard is the
check.)

---

## Rollback

ClamAV, db and redis are not part of any rollback. **Default: fix forward**, except the **night rule**: the live test
(step 14) failing without an obvious fix within 20 minutes → **A**, landing unchanged. Every rollback starts with
the pre-stop gate (step 9's three commands).

**A. Previous images on the new schema (first choice).** All migrations only add tables and columns (the previous
build ignores `plan`, `billing_status` and the new tables).
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
```
Expect `build_sha` = `PREV_SHA` and smoke with one expected failure: `database schema is not at the Alembic head:
… Can't locate revision identified by '20261025_0001_b1_billing'`. Remnants while on A: the billing, plan and partner
tables stay, unused; orders taken in step 14 stay recorded (refund a real card payment in Polar if one was taken).
Polar keeps delivering webhooks: they fail (404 on the old build) and Polar retries them; disable the endpoint in
Polar while on A. **[D3]**: Deploy 4's Rollback A remnants apply as well.

**A2. Exact return (old images, checkout, `.env`, previous schema).**
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261016_0002_p1_organization_access
prod$ scripts/compose-release.sh use "$PREV_SHA"
prod$ git checkout -B <previous branch> "$PREV_COMMIT" && test "$(git rev-parse HEAD)" = "$PREV_COMMIT" && echo CHECKOUT_OK
prod$ cp -p .env .env.deploy5 && chmod 600 .env.deploy5 && cp -p .env.pre-deploy5 .env && echo ENV_RESTORED
prod$ for k in TELEGRAM_BOT_TOKEN GEMINI_API_KEY; do sed -i "s|^$k=.*|$(grep "^$k=" .env.deploy5)|" .env; done
prod$ diff <(grep -E '^(TELEGRAM_BOT_TOKEN|GEMINI_API_KEY)=' .env | sort) <(grep -E '^(TELEGRAM_BOT_TOKEN|GEMINI_API_KEY)=' .env.deploy5 | sort) >/dev/null && echo SECRETS_KEPT
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
```
The downgrade (rehearsal: **4 s**) removes B1, P3 and P2 **with their data** (orders, invoices, partner requests, usage
rows); **[D3]**: then continue with Deploy 4's Rollback B to reach the Deploy 3 schema. The restored `.env` keeps
step 7's rotated Telegram token (the old one is revoked) and the production Gemini key (the carry-over lines).
Expect `DNS_OK`, `CHECKOUT_OK`, `ENV_RESTORED`, `SECRETS_KEPT`, `build_sha` = `PREV_SHA`, smoke **0 failures**.

**C. Database restore** (loses everything since step 4): Deploy 1 Rollback C with `$SET` from step 4 (pre-stop gate
first), then A2's image/checkout/`.env` lines. Never `docker compose down -v`.

---

## Gate and rehearsal (evidence)

**Gate** (LF `git archive` exports; backend groups in a 1.5 GB one-off container on `plasma_db`'s loopback with a
disposable database and a Redis sidecar, the local staging stack stopped for memory (owner-approved), a watchdog on
the shared stack; frontend and browser groups on Windows). The backend groups ran on `576b187` (RC-5 code); the
backend code is unchanged since (`dbb6550` changes one test, `c17cc7e` and `640e9be` only the frontend); the
frontend, browser and audit groups ran on the release commit `640e9be`:

| Group | Result |
| --- | --- |
| backend (12 batches, a fresh process each) | **1,238 passed**, 1 skipped, **1 failed**: `test_b1_billing.py::test_polar_env_switch_both_ways`, a test reading the container's Polar keys from the environment; fixed in `dbb6550` (keys passed as `None`) and re-run with and without Polar variables in the environment: **2 passed** |
| security | **118 passed** (incl. the 20 MB upload case) |
| analysis / connectors | **50** / **198** passed (1 skipped) |
| migrations | heads, current, check, schema preflight: **PASS** (head `20261025_0001_b1_billing`) |
| performance | **PASS** |
| config-dependencies | 24 passed, `pip check` clean. **npm audit found Next.js 16.3.8 advisories (critical: unauthenticated RCE in the Image Optimization API with SVG and in `use cache`; DoS with Server Actions) and follow-redirects 1.16.0 (high)** → `c17cc7e`: Next.js **16.4.3**, follow-redirects 1.16.1 (eslint-config-next kept at 16.3.8: its newer React-hooks lint rules flag 40 existing lines, a separate change). On `640e9be`: `npm audit --omit=dev` **0**, full audit **0** |
| frontend | npm ci, typecheck, lint, **420/420** node tests, RTL audit, production build: **PASS** |
| browser (`release-hardening-browser.py`) | **214 passed, 0 failed** (the fixture port 3114 sits in a Windows-reserved range: `PLASMA_RELEASE_BROWSER_PORT=3314`). The first run (`c17cc7e`) failed the three Team-tab cases (w5, w6, w7): P2 had made the Team tab's load all-or-nothing on the partner requests (a refused call, e.g. a plan without partner search, blanked the tab). Fixed in `640e9be` |

**Rehearsal** (2026-10-25, fresh copies of the production-shaped database at the Deploy 3 head (users approved 15,
pending 1; company profiles approved 7; organizations 7; pursuits 28 with 62 analysis runs; tenders 3,729), the release
code on the Windows host against the local Postgres; times include each command's start-up):

| Step | Result |
| --- | --- |
| copy of the database (pg_dump -Fc / pg_restore) | 115 s and 194 s |
| from the Deploy 3 head: seven migrations | **24.2 s** (S1 5.3 / 2.7, P1 3.3 / 2.8, P2 3.3, P3 3.1, B1 3.6) |
| after (Deploy 3 start) | users approved 16, pending 0, `USER_APPROVED`/`P1_MIGRATION` 1; organizations 7 = pilot/pilot 7; usage rows 10; billing orders 0; `alembic check` clean |
| from the Deploy 4 head: three migrations | **25.6 s** (P2 11.5, P3 8.4, B1 5.7); the same after-counts |
| data step on the copy (7 legacy pilots, no dates) | list 3.3 s: `listed_only` 7, `ends_at_first_run` 0 |
| data step with two `pilot_setup.py` pilots added | list ~4 s: `set` 1 (2026-11-15 → 2026-12-01), `keep` 1; apply ~4 s `applied` 1; re-run `set` 0 |
| first billing run on the migrated copy | `{'reminders': 0, 'suspended': 0, 'ended': 0, 'renewed': 0}` (0.4-6 s) |
| Rollback A2 downgrade B1 → P3 → P2 (to the Deploy 4 head) | **4.0 s**; upgrade again 2.9 s |
