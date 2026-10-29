# Deploy 5.1 runbook: production hotfix on Deploy 5 (backend and frontend images cc8023a, no migrations)

For the owner, copy-paste on the production host. Same rules as Deploy 5 (`docs/ops/DEPLOY_5_RUNBOOK.md`): every step
has the command, what you must see and a **STOP** condition; the pre-stop gate before every recreate; fix forward
first. No night window needed: the backend and frontend restart in seconds, and one crash-looping worker is
recreated.

**What 5.1 fixes** (production incidents after Deploy 5):

| # | Incident | Fix |
| --- | --- | --- |
| 1 | The live Polar webhook was subscribed to `checkout.*` only: `order.paid`/`subscription.*` never arrived, and one Pursuit Desk card payment is paid in Polar but **pending** in Plasma (possibly activated by hand with an override) | the endpoint's events (step 9); **`scripts/billing/reconcile_polar.py`** (step 10) applies the order.paid path to paid orders, or only links the Polar ids when the plan was activated by hand |
| 2 | Admin → Billing: override, per-tender link and per-tender invoice posted to `/organizations/undefined/…` (**422 "Invalid request"**) | the page keeps the organization id (the detail dialog's close event dropped it); `organization_id` explicit in the detail; override dates default (Pilot +3 months, annual +12) and can be given; the backend's message in the dialog |
| 3 | No API domain in production: the runbook's smoke and webhook URL used `<API_DOMAIN>` | app `https://console.plasmaos.uz` (it serves `/api/v1/*` from the backend), host backend `http://127.0.0.1:8000`, webhook `https://console.plasmaos.uz/api/v1/billing/webhooks/polar`. **Also found**: the Deploy 5 frontend answered that webhook URL with **401** (the route was not public in its proxy), so deliveries through the app domain never reached the backend. Fixed in the 5.1 frontend |
| 4 | `worker_pursuit_analysis` crash-looped (**378 restarts**): its compose service had no `ENVIRONMENT` line, so it read the default `development` and refused `POLAR_ENV=production` | `ENVIRONMENT: ${ENVIRONMENT:-production}` like every Python service (a test checks all of them); `.env` now also sets **`ENVIRONMENT=production`** explicitly (step 4) |
| 5 | Nobody noticed that no `order.paid` arrived | Admin → Billing warns when no `order.paid` delivery has arrived 24 hours after the first card checkout |

| | |
| --- | --- |
| Checkout | `pilot/deploy-5-1-hotfix` @ its newest commit (this runbook's commit; the owner pushes it) = Deploy 5 (`a972d91`) + `cc8023a` (code) + docs |
| Images | **backend and frontend only**, built from **`cc8023a3444a3dabbc573a827163a364e49a4b40`**: `plasma-backend:cc8023a3444a3dabbc573a827163a364e49a4b40`, `plasma-frontend:cc8023a3444a3dabbc573a827163a364e49a4b40`; bundle `plasma-release-cc8023a.tar.gz`, **`1,571,820,723`** bytes, sha256 **`562f24e99dc432fbb2daefd786524c54c1ab475016ad9d08f3978c56bcb8335d`**. The five workers keep their Deploy 5 images (`640e9be`: nothing a worker runs changed), tagged under the new SHA in step 5 so `compose-release.sh` can switch. `/health` reports `build_sha` `cc8023a` |
| Running today | Deploy 5: images `640e9be4a6af42f32ff55e65579c486dfee40bae`, schema `20261025_0001_b1_billing` |
| Migrations | **none**. The schema stays at `20261025_0001_b1_billing (head)`; Rollback is an image switch |
| Recreated | `backend`, `frontend`, `worker_pursuit_analysis` (the last for its `ENVIRONMENT`). **Not touched**: `db`, `redis`, `clamav`, `celery_worker`, `worker_heavy`, `worker_private_documents`, `celery_beat` |
| Data changes | only by step 10 (reconcile), audited (actor `reconcile`), after a dry run |
| Downtime | seconds (backend and frontend recreated); analyses were not running anyway (the worker was crash-looping) |

Conventions as in Deploy 5: `prod$` on the production host in `/opt/plasma-console/plasmaos`; `laptop$` on the owner's
PC (Git Bash). **Domains: the app is `https://console.plasmaos.uz`; there is no API domain**; on the host the backend
is `http://127.0.0.1:8000`. **Every `up` names its services and has `--no-deps`** (never a bare `up`, `down`,
`restart` or `rollback`: they would recreate `db`/`redis`).

---

## Before (Polar dashboard, live organization; no app change)

1. **A new organization access token** (Settings → Developers → New token). Scopes: **`checkouts:write`,
   `discounts:write`, `products:read`, `customer_sessions:write`, `orders:read`, `subscriptions:read`**. The two read
   scopes are new (step 10 reads the order and the subscription); a token's scopes cannot be added later. Shown once:
   keep it for step 4. Do **not** revoke the current token yet (the running backend uses it until step 6).
2. **The webhook endpoint's URL and events** are set in step 9, after the 5.1 frontend runs (the old frontend refuses
   the delivery at the app domain with 401).

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<the newest commit of pilot/deploy-5-1-hotfix (this runbook's commit)>
prod$ SHA=cc8023a3444a3dabbc573a827163a364e49a4b40
prod$ PREV_SHA=640e9be4a6af42f32ff55e65579c486dfee40bae
prod$ WORKERS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat"
prod$ RUN="scripts/compose-release.sh run --rm --no-deps -T backend"
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```
Expect `"build_sha":"640e9be"`. **STOP** otherwise (this runbook is for Deploy 5 only).

## 1. Pre-checks (read-only)

```
prod$ git status --porcelain; git rev-parse HEAD; free -h; df -h /
prod$ docker exec plasma_backend alembic current
prod$ docker inspect -f '{{.Name}} status={{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} mem={{.HostConfig.Memory}}' $(docker ps -aq --filter name=plasma_) | sort | tee $HOME/deploy51-before.txt
prod$ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' plasma_worker_pursuit_analysis | grep -E '^(ENVIRONMENT|POLAR_ENV)='
prod$ docker logs --tail 5 plasma_worker_pursuit_analysis 2>&1 | cut -c1-200
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -At <<'SQL' | tee $HOME/deploy51-billing-before.txt
select 'order', id, organization_id, product, status, provider_checkout_id is not null, activated_at is not null, created_at from billing_orders where method = 'card' order by created_at;
select 'event', event_type, outcome, count(*) from billing_events group by 2, 3 order by 2, 3;
select 'org', o.id, o.plan, o.billing_status, o.plan_started_on, o.plan_ends_on from organizations o where o.id in (select organization_id from billing_orders where method = 'card');
SQL
```
Expect: no file lines (untracked `.env.pre-deploy*` are fine); `available` ≥ ~700Mi; `20261025_0001_b1_billing (head)`;
`worker_pursuit_analysis` with many restarts and **`POLAR_ENV=production` but no `ENVIRONMENT=` line** (the incident;
its log ends in `POLAR_ENV=production requires…`); every other container `restarts=0`. The billing lines show the card
orders (the incident's Pursuit Desk order `pending`), only `checkout.*` events, and the organizations. Keep the files.

**Memory of `worker_pursuit_analysis`**: `mem=402653184` (384 MiB, the 4gb profile) is expected. `mem=301989888`
(288 MiB) means the container was created **without** the host profile (a plain `docker compose`, not
`scripts/compose-release.sh`): step 6 recreates it through the wrapper with the profile. Note which you saw.

## 2. Check out the release (files only, nothing restarts)

```
prod$ git fetch origin pilot/deploy-5-1-hotfix
prod$ git checkout -B pilot/deploy-5-1-hotfix "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls backend/scripts/billing/reconcile_polar.py docs/ops/DEPLOY_5_1_RUNBOOK.md
prod$ grep -c 'ENVIRONMENT: ${ENVIRONMENT:-production}' docker-compose.yml
```
Expect `CHECKOUT_OK`, both paths and **`7`** (backend, frontend, celery_worker, worker_heavy, worker_private_documents,
celery_beat and now worker_pursuit_analysis; Deploy 5's file had 6). **STOP** on anything but `7`.

## 3. Backup (required: step 10 writes billing data)

Deploy 5 step 4 exactly (R2 `BACKUP_RESULT`, or the laptop copy verified with `sha256sum -c`). **STOP before step 10
without one.**

## 4. `.env`: `ENVIRONMENT=production` explicitly, the new Polar token

```
prod$ cp -p .env .env.pre-deploy51 && chmod 600 .env.pre-deploy51 && cmp .env .env.pre-deploy51 && echo ENV_SAVED
prod$ set +o history
prod$ setenv() { if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; echo "REPLACED $1"; else printf '%s=%s\n' "$1" "$2" >> .env; echo "ADDED $1"; fi; }
prod$ setenv ENVIRONMENT 'production'
prod$ setenv POLAR_ACCESS_TOKEN '<the new token from "Before" item 1>'
prod$ set -o history
prod$ for k in ENVIRONMENT POLAR_ENV POLAR_ACCESS_TOKEN POLAR_WEBHOOK_SECRET POLAR_PRODUCT_IDS; do echo "$k $(grep -c "^$k=" .env)/$(grep -c "^$k=." .env)"; done
prod$ grep '^ENVIRONMENT=' .env; grep '^POLAR_ENV=' .env
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -c 'ENVIRONMENT: production'
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit' | sort | uniq -c
```
Expect `ENV_SAVED`, `ADDED`/`REPLACED ENVIRONMENT`, `REPLACED POLAR_ACCESS_TOKEN`, five `1/1` lines,
`ENVIRONMENT=production`, `POLAR_ENV=production`, `CONFIG_OK`, **`7`**, and exactly Deploy 5's limits:
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
**STOP** on different numbers (a `288m`/`301989888` line means `HOST_PROFILE=4gb` is missing from `.env`).

The token check needs the release images (step 5), so it is in step 7.

## 5. Transfer and import the two images; the workers keep theirs under the new SHA

```
laptop$ scp /d/plasma-release/plasma-release-cc8023a.tar.gz "$PROD:/opt/plasma-console/"
prod$ sha256sum /opt/plasma-console/plasma-release-cc8023a.tar.gz
prod$ scripts/compose-release.sh import < /opt/plasma-console/plasma-release-cc8023a.tar.gz
prod$ for s in $WORKERS; do docker tag "plasma-$s:$PREV_SHA" "plasma-$s:$SHA" && echo "TAGGED $s"; done
prod$ docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ":$SHA"
prod$ rm /opt/plasma-console/plasma-release-cc8023a.tar.gz && df -h /
```
Expect sha256 `562f24e99dc432fbb2daefd786524c54c1ab475016ad9d08f3978c56bcb8335d` (**STOP** if it differs: copy again), `Loaded image: plasma-backend:cc8023a3444a3dabbc573a827163a364e49a4b40` and
`Loaded image: plasma-frontend:cc8023a3444a3dabbc573a827163a364e49a4b40`, five `TAGGED`, then **`7`**. (No `--expect` on the import: the bundle holds
two services by design; step 6's `up` refuses to switch unless all seven exist.)

## 6. Pre-stop gate, then recreate backend, frontend and the pursuit worker

```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy51-dbredis.txt
```
Expect `DNS_OK` and `"ready":true`. **STOP, recreate nothing** without them (Deploy 5 step 9's recovery, then gate again).
```
prod$ date -u +%T
prod$ scripts/compose-release.sh up "$SHA" --no-deps backend frontend worker_pursuit_analysis
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; date -u +%T; curl -fsS http://127.0.0.1:8000/health; echo
prod$ until curl -fsS -o /dev/null http://127.0.0.1:3000/; do sleep 3; done; echo FRONTEND_OK
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy51-dbredis.txt && echo DBREDIS_UNCHANGED
```
Expect the image switch (`… -> plasma-<service>:cc8023a3444a3dabbc573a827163a364e49a4b40` for all seven), **three** containers recreated,
`"build_sha":"cc8023a"`, `FRONTEND_OK`, `DBREDIS_UNCHANGED`. **STOP → Rollback** if `/health/ready` is not OK after
5 minutes (`docker logs plasma_backend --tail 30`).

## 7. The pursuit worker stays up; smoke; the token's scopes

Wait two minutes, then:
```
prod$ docker inspect -f '{{.Name}} status={{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} mem={{.HostConfig.Memory}} cmd={{.Config.Cmd}}' plasma_worker_pursuit_analysis
prod$ docker exec plasma_worker_pursuit_analysis printenv ENVIRONMENT POLAR_ENV
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$ $RUN python -c "import asyncio; from app.services.billing_polar import polar_client; c = polar_client(); print('POLAR_READ', asyncio.run(c._get('/v1/orders/', {'limit': 1})).get('pagination'))"
```
Expect `status=running restarts=0 oom=false mem=402653184 … --concurrency=1 …`, `production` twice, smoke
`Result: N ok, M warning(s), 0 failure(s)` (it now passes the real app URL and the host backend), `analysis smoke:
OK`, and a `POLAR_READ {…total_count…}` line. **`PolarError: polar_http_403`/`401`** = the token in `.env` lacks
`orders:read` (create it again with "Before" item 1; `setenv`; `up "$SHA" --no-deps backend`). **STOP step 10**
until `POLAR_READ` works.

## 8. The webhook route answers through the app domain (no payment)

```
prod$ curl -s -o /dev/null -w '%{http_code}\n' -X POST https://console.plasmaos.uz/api/v1/billing/webhooks/polar
prod$ curl -s -X POST https://console.plasmaos.uz/api/v1/billing/webhooks/polar; echo
```
Expect `403` and `{"detail":"webhook_headers_missing"}`: the request reached the backend's signature check. `401
{"detail":"Unauthorized"}` = the old frontend still runs (step 6). `404`/`502` = the host proxy (fix forward).

## 9. Polar: the webhook endpoint's URL and events

Polar → Settings → Webhooks → the production endpoint (keep its secret; it is `POLAR_WEBHOOK_SECRET`):
- URL: **`https://console.plasmaos.uz/api/v1/billing/webhooks/polar`**, format **Raw**;
- events, exactly: **`order.paid`, `order.refunded`, `subscription.created`, `subscription.active`,
  `subscription.updated`, `subscription.canceled`, `subscription.uncanceled`, `subscription.revoked`**. Untick
  `checkout.*` (the app ignores them).

Then revoke the **old** access token (Settings → Developers). Polar does not resend events that were never subscribed:
the missed `order.paid` comes from step 10, not from a redelivery.

## 10. Reconcile the pending card payment (dry run first)

```
prod$ $RUN python scripts/billing/reconcile_polar.py --target production --all-pending --dry-run | tee $HOME/deploy51-reconcile-dry.txt
```
One JSON line per pending card order, then `SUMMARY {…, "applied": 0, "dry_run": true}`. For the incident's Pursuit
Desk order expect `"polar_checkout_status": "succeeded"`, one Polar order `"status": "paid", "paid": true`, a
`"subscription_status": "active"` and **`"action"`**:
- **`link_only`**: the organization is already on Pursuit Desk (activated by hand with an override). Applying links
  the Polar order and subscription ids and marks the order paid; the plan, its dates and the billing status stay as the
  admin set them, no e-mail, no onboarding task. **`"check_dates": true`** = the organization's dates are not one full
  year: fix them afterwards in Admin → Billing → Override (start and end dates, same plan);
- **`activate`**: the organization is not on the plan yet. Applying runs the order.paid path: payment recorded, Pursuit
  Desk today → +12 months, onboarding task, welcome e-mail, team alert;
- `not_paid` (abandoned checkouts: `open`/`expired`), `needs_review`, `mismatch`: nothing happens; report them.

**STOP** on `polar_error` (step 7's token check) or if the incident's order is not `link_only`/`activate`. Then the
one order, by its id:
```
prod$ ORDER=<the incident order's "order_id" from the dry run>
prod$ $RUN python scripts/billing/reconcile_polar.py --target production --order "$ORDER" --dry-run | tail -n 2
prod$ $RUN python scripts/billing/reconcile_polar.py --target production --order "$ORDER" | tee $HOME/deploy51-reconcile.txt
prod$ $RUN python scripts/billing/reconcile_polar.py --target production --order "$ORDER" | tail -n 1
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -At <<SQL
select status, provider_subscription_id is not null, activated_at is not null, plan_started_on, plan_ends_on from billing_orders where id = '$ORDER';
select method, provider_payment_id is not null, amount_cents, currency, note from billing_payments where order_id = '$ORDER';
select action, actor_label, created_at from admin_activity_events where actor_label = 'reconcile' order by created_at;
SQL
```
Expect the same action as the dry run with `"applied": true` (`"outcome": "linked"` or `"activated"`), then
`"already_paid": 1` on the second run (idempotent). The order `paid|t|t|<dates>`; one card payment with the Polar order
id and the note `Polar order.paid (reconciled: …)`; audit lines with actor `reconcile`. Other pending card orders:
`--all-pending` without `--dry-run` applies only those Polar shows as paid; abandoned ones stay `pending`.

## 11. Admin → Billing (browser)

1. The page shows the warning **"Polar has not delivered order.paid"** (first card checkout more than 24 hours ago,
   no `order.paid` delivery yet), listing what Polar delivered (`checkout.*`). It **clears with the next real
   `order.paid` delivery**; reconciliation does not count as a delivery. To prove the pipeline now (recommended),
   repeat Deploy 5 step 14.2 on a test organization with a new one-use 100 % code: the order is paid within a minute,
   the event list shows `order.paid` → `activated`, and the warning is gone. Then put the test organization back
   (Override: plan `explore`, status `none`).
2. Open the reconciled organization: the order **paid**, the payment with its Polar id, the audit line by
   `reconcile`.
3. **Override plan or status** → Cancel: the detail comes back. Override with an empty reason: the dialog says **"Give
   a reason"** (not "Invalid request"). Override on a test organization with plan `pilot` and no dates: today → +3
   months (the dates fields are optional). "Per-tender: checkout link" on a test organization: a one-use link (not a
   422).

## 12. Done, and the 24-hour check

```
prod$ docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q) | sort
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
prod$ docker exec plasma_db psql -U plasma -d plasma_ai -c "select event_type, outcome, processing_error, count(*) from billing_events where received_at > now() - interval '1 day' group by 1,2,3"
```
Expect `oom=false restarts=0` everywhere (the pursuit worker included), smoke `0 failure(s)`, and (after any card
payment or subscription change) `order.paid`/`subscription.*` events processed without `processing_error`. Then delete
`.env.pre-deploy51` (it holds the old token) and the backup copy.

---

## Rollback (images only; keep the checkout and `.env`)

The previous build runs on the same schema, and the compose fix and `ENVIRONMENT=production` are harmless for it (they
keep the pursuit worker up). The pre-stop gate first:
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
```
Expect `DNS_OK` (and `"ready":true` unless the new backend is what failed). Then:
```
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps backend frontend worker_pursuit_analysis
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://console.plasmaos.uz --backend-url http://127.0.0.1:8000
```
Expect `build_sha` `640e9be`, smoke 0 failures. On the old frontend the webhook URL answers 401 again: Polar retries
deliveries for a while; reconcile later with the 5.1 images. Reconciled orders stay paid (correct data; the old build
reads them).

---

## If `worker_pursuit_analysis` is OOM-killed

Step 1/7 show its limit. The 4gb profile gives it **384 MiB** (`deploy/host-profiles/4gb.env`); an OOM kill **at
288 MiB** means the container ran without the profile (compose default), which step 6 fixes. Report an OOM at 384 MiB
with `docker inspect -f '{{.State.OOMKilled}}'` and the task that ran (`docker logs plasma_worker_pursuit_analysis
--since 1h | grep -E 'Task|Killed'`): raising it within the 4gb budget is a profile change, not part of 5.1.

---

## Gate and evidence

Changed areas: billing service and endpoints, the Polar client, the admin billing page, the frontend proxy, the
compose file, the two runbooks. **No migration** (no model or Alembic change; head stays
`20261025_0001_b1_billing`).

| Check | Result |
| --- | --- |
| backend, whole suite (LF `git archive` of `1e15623`, WSL Ubuntu, loopback Postgres with disposable `plasma_s05b4b_*` databases, 10 batches) | **1,239 passed**, 1 skipped, **3 failed**, all resolved: `test_p0_2a…same_origin_api` (the contract names the public proxy paths: updated for the webhook path in `cc8023a`), `test_r3_ops…pre_stop_gate` (`DEPLOY_5_RUNBOOK.md` step 9 had the counts between the gate and the stop: reordered here), `test_r3_01_invitations` (the test runner exported a local `SMTP_HOST`: passes without it). Re-run: **5 passed** |
| B1 billing + release config (`test_b1_billing.py`, `test_release_config.py`) | **38 passed**: reconcile (dry run, `activate`, `link_only` after a manual override with no onboarding task or welcome e-mail, `not_paid`, Polar `403`, not found, idempotent second run, a late `order.paid` → `duplicate_payment`, the subscription's events apply after linking), Polar matching (paid, pending, void, refunded, two paid, other order), override default and kept dates and its messages, `organization_id` in every detail, the 24-hour `order.paid` warning, every Python compose service sets `ENVIRONMENT` (fails on Deploy 5's file: `worker_pursuit_analysis` had none) |
| frontend group | typecheck, lint, **421/421** node tests (later **14/14** for the changed B1/R3 files after the proxy reformat), RTL audit, production build: **PASS** |
| browser (`release-hardening-browser.py`, production build, port 3314) | **151 passed, 1 failed**: the new case `d5-1/admin-billing/detail-actions-post-real-id` (a race in the case itself: it reopened the detail before the save's response; fixed in `474fb2d`), re-run **PASS**: override, per-tender link and per-tender invoice post to `/organizations/<real id>/…`, a refused save shows "Give a reason", Cancel returns to the detail, the warning lists `checkout.created ×2`. No external requests |
| webhook through the app domain (stub backend behind `next start` of the production build, an unsigned-session POST with Standard Webhooks headers) | Deploy 5 frontend: **`401 {"detail":"Unauthorized"}`, never reached the backend**. 5.1 frontend: reached `/api/v1/billing/webhooks/polar`, **body byte-identical (sha256), `webhook-*` headers intact** |
| compose | rendered with a production-like `.env` and the 4gb profile: **7** services with `ENVIRONMENT: production` |
| Polar API shapes | public OpenAPI: `GET /v1/orders/?checkout_id=` exists; order statuses `draft/pending/paid/refunded/partially_refunded/void`; scopes `orders:read`, `subscriptions:read`, `checkouts:read|write`; the eight events exist. Sandbox reads (`/v1/orders/`, `/v1/checkouts/`, `/v1/subscriptions/`): 200 |

**Images** (`scripts/compose-release.sh build-only backend`, then `frontend`, from the LF worktree at `cc8023a3444a3dabbc573a827163a364e49a4b40`; the
local ClamAV and the four shared workers were stopped for the builds, owner-approved, and started again):
| Image | Id | Size | `PLASMA_BUILD_TIME` |
| --- | --- | --- | --- |
| `plasma-backend:cc8023a3444a3dabbc573a827163a364e49a4b40` | `ea02df54f93f` | 4.32 GB | 2026-10-29T22:53:41Z |
| `plasma-frontend:cc8023a3444a3dabbc573a827163a364e49a4b40` | `b4963a905996` | 1.48 GB | 2026-10-29T22:57:50Z |

Both bake `PLASMA_BUILD_SHA=cc8023a…`; the frontend bakes `NEXT_PUBLIC_API_URL=/api/v1` and
`BACKEND_INTERNAL_URL=http://backend:8000/api/v1`, and its compiled proxy contains `/api/v1/billing/webhooks/polar`.
Bundle `compose-release.sh export cc8023a… backend frontend` (222 s): `D:\plasma-release\plasma-release-cc8023a.tar.gz`,
**1,571,820,723 bytes**, sha256 **`562f24e99dc432fbb2daefd786524c54c1ab475016ad9d08f3978c56bcb8335d`** (also in
`plasma-release-cc8023a.tar.gz.sha256`), `gzip -t` OK, manifest = the two images above. The size is close to Deploy
5's seven-image bundle: a new SHA rebuilds the backend's dependency layers (the Dockerfiles set `PLASMA_BUILD_SHA`
before `pip install`/`npm ci`), and those layers are most of it.

Not rehearsed: the production switch itself (no production copy was needed: no migration, three containers
recreated). The reconcile script ran against a disposable Postgres with a fake Polar (the test above) and read-only
calls against the Polar sandbox (no paid orders there); the first real run is step 10's dry run.
