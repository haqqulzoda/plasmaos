# Deploy 4 runbook: production a83d575 / images 169d451 → pilot/s1-release, images <SHA4>

For the owner, copy-paste on the production host. Every step has the command, what you must
see, and a **STOP** condition. Same rules as Deploys 1-3: a short clean cut-over (the app is
stopped while the schema moves), every feature proven on production afterwards, problems fixed
forward first, two rollbacks, the **pre-stop gate** before every app stop
(docs/ops/RUNBOOK_TEMPLATE.md). New in this window: the **award ledger is filled on production**
(all procurement categories, four countries, step 15), and an owner section to **create Loom
previews on production** (after step 18).

| | |
| --- | --- |
| Checkout | `pilot/s1-release` @ its newest commit (four squashed S1 commits on `a83d575` plus the S1-8 report; pushed by the owner before the window; local only until then). **Never deploy or push `pilot/s1-int`**: same tree, but its history is not clean |
| Images | **built from the release commit before the window** (not part of S1-7): `plasma-<service>:<SHA4>`, bundle `plasma-release-<short4>.tar.gz`, `<bytes>`, sha256 `<…>`; `/health` reports `build_sha` `<SHA4>`. Fill these four values from `scripts/compose-release.sh export` before the window |
| Running today | Deploy 3: checkout `a83d575` (Deploy 3 runbook commit), images `169d45179bf41786e8f8e305a7379e48f19238f5`, schema `20261011_0001_r3_organization_record_events` (step 1 checks all three) |
| Host | Hetzner 2 vCPU / 3.7 GiB, `/opt/plasma-console/plasmaos`, `HOST_PROFILE=4gb`, `PLASMA_NO_BUILD=1` |
| Migrations | two, both additive (the Deploy 3 build runs on the new schema: Rollback A): `20261012_0001_s1_award_ledger` (award ledger: `award_notice_snapshots`, `award_outcomes`, append-only), `20261012_0002_s1_product_analytics` (`product_events`, `ai_call_costs`, append-only) (step 10) |
| New variables | `AI_PRICE_TABLE_JSON` (optional, default: the table in `backend/app/core/ai_pricing.py`, step 16). Nothing else |
| New in the release | **S1 award ledger**: World Bank contract-award notices for Uzbekistan, Kazakhstan, Kyrgyz Republic and Tajikistan, all procurement groups, every bidder with its verbatim status and reason, append-only; read-time firm-name normalization (legal forms in abbreviations and in words, Latin and Cyrillic); notice-country validation against the World Bank Projects API; `/admin/award-ledger` (operators; CSV, market sizing and firm exports for admins). **S1 product analytics**: server-side product events, the AI cost ledger (one row per provider call, estimated USD), `/admin/metrics` (admins). **S1 outreach**: prospect previews (`seed_demo.py --prospect-file` / `--from-ledger`, "<Firm> — Plasma preview", exclusive, archivable), coverage strip on Opportunities, legacy URL redirects, EOI versions marked "Draft — not reviewed by your team" when seeded. `analysis_smoke.py --live` auto-picks an open REOI with a notice of at least 5,000 characters |
| Gate | `<SHA4>`, from an LF export (end of this file) |
| **Not touched** | **`db`, `redis` and `clamav` keep their containers** (never `up`, `down`, `restart` or `rollback` them here) |
| Downtime | step 9 → step 11: **~75 s** expected (rehearsal: two migrations 5 s on a copy of the production-shaped database; Deploy 3 measured image switch 8 s, start to `/health/ready` 48 s, stop ~12 s) |
| Window | ~30 min to step 11 plus the transfer (step 6); ingestion and validation ~5 min (step 15); then ~45 min of checks |

**Rule for this whole window: every `up` names its services and has `--no-deps`.** Never run
`up` without a service list, `compose-release.sh rollback`, `docker compose up`, `down` or
`restart`: with this compose file those would recreate `db`/`redis`.

Conventions as before: `prod$` on the production host in `/opt/plasma-console/plasmaos`; `laptop$`
on the owner's PC (Git Bash). `<prod>`, `<APP_DOMAIN>`, `<API_DOMAIN>` as before.

APP services (the only ones this runbook recreates):
`celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend`

**One-off containers.** Ingestion, validation and the Loom previews run in **one-off backend
containers** (`scripts/compose-release.sh run --rm --no-deps -T backend …`), never via `exec` into
`plasma_backend`, as the demo seed in Deploy 2: their peak counts against their own container, and
the container is removed when it ends. Check `free -h` shows `available` ≥ ~600Mi before each.

---

## 0. Variables (every new production shell)

```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<the newest commit of pilot/s1-release>
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
prod$ git fetch origin pilot/s1-release
prod$ git checkout -B pilot/s1-release "$COMMIT"
prod$ test "$(git rev-parse HEAD)" = "$COMMIT" && echo CHECKOUT_OK
prod$ ls backend/scripts/ingest_award_ledger.py backend/scripts/validate_award_ledger.py backend/scripts/demo/seed_demo.py docs/ops/DEPLOY_4_RUNBOOK.md
```
Expect `CHECKOUT_OK` and the four paths. **STOP** otherwise (`git checkout -B pilot/week1 "$PREV_COMMIT"`).

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

## 7. `.env`: keep a copy (no new required variable)
```
prod$ cp -p .env .env.pre-deploy4 && chmod 600 .env.pre-deploy4 && cmp .env .env.pre-deploy4 && echo ENV_SAVED
prod$ scripts/compose-release.sh config --quiet && echo CONFIG_OK
prod$ scripts/compose-release.sh config | grep -E -- '--concurrency=|mem_limit' | sort | uniq -c
```
Expect `ENV_SAVED`, `CONFIG_OK`, and exactly the Deploy 3 lines:
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
**STOP** on different numbers. `AI_PRICE_TABLE_JSON` is **not** set in this window (step 16 decides).

## 8. Import the images
```
prod$ scripts/compose-release.sh import --expect "$SHA" < /opt/plasma-console/plasma-release-<short4>.tar.gz
prod$ rm /opt/plasma-console/plasma-release-<short4>.tar.gz && df -h /
```
Expect seven `Loaded image: plasma-<service>:<SHA4>…`, then `every service has plasma-<service>:<SHA4>…`;
`Use%` ≤ 85 %. **STOP** on `import incomplete` (repeat step 6).

## 8b. Pre-check: proposals not linked to any pursuit (read-only SQL)

This release redirects the old Bid Preparation list (`/bid-preparation`, `/dashboard/bid-preparation`) to My
Tenders, which lists pursuits. A legacy proposal whose tender has no pursuit in any organization of the proposal's
user would then only open by its direct link. Count them before stopping anything:
```
prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -v ON_ERROR_STOP=1 <<'SQL'
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
Expect `TOTAL | 0 | 0`. **STOP if `unlinked_proposals` > 0**: the redirect would hide those proposals from the
list. Send the per-organization rows; the owner decides (create pursuits for them first, accept that they open
only by link, or postpone). Nothing has changed yet; resume at step 9 after the decision. (Local rehearsal data:
116 of 122 proposals unlinked across 4 organizations, so expect this STOP unless production differs.)

## 9. Pre-stop gate, then stop the app (db, redis and ClamAV keep running)

```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy4-dbredis.txt && echo DBREDIS_UNCHANGED
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
Expect (rehearsal on a copy of the production-shaped database: 5 s for the two migrations):
```
images switched to <SHA4>; nothing was restarted
INFO  [alembic.runtime.migration] Running upgrade 20261011_0001_r3_organization_record_events -> 20261012_0001_s1_award_ledger, Sprint 1: award ledger v0 (public award notices and one row per bidder).
INFO  [alembic.runtime.migration] Running upgrade 20261012_0001_s1_award_ledger -> 20261012_0002_s1_product_analytics, Sprint 1: server-side product events and the AI cost ledger.
20261012_0002_s1_product_analytics (head)
```
What they do: `award_notice_snapshots` (one row per notice version, raw text kept) and
`award_outcomes` (one row per bidder per notice version); `product_events` and `ai_call_costs`.
All four tables are append-only (a trigger rejects UPDATE/DELETE). No existing table changes.
**STOP → Rollback A2** if the upgrade fails (each migration is one transaction).

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

## 12. Smoke and Beat memory

```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ scripts/compose-release.sh exec -T worker_pursuit_analysis python scripts/analysis_smoke.py
prod$ scripts/ops/beat_memory.sh --target production --baseline "$BEAT_RSS_KB"
```
Expect `Result: N ok, M warning(s), 0 failure(s)`, `analysis smoke: OK`, Beat `growth=…%` exit 0.

## 13. Live analysis smoke

```
prod$ export ANALYSIS_SMOKE_TOKEN="$($RUN python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 -I -S backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
```
New: the auto-pick takes the first open World Bank REOI whose official notice has at least 5,000
characters; if none, it fails asking for `--tender-id`. Expect `"status": "COMPLETED"`,
`"quality_state": "READY_FOR_REVIEW"`, `live analysis smoke: OK`. The run now also writes one
`ai_call_costs` row per provider call (step 16 reads them).

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
Expect (rehearsal 2026-10-12: 94 s, 53 pages, peak ~80 MiB) a JSON summary with `notices_seen` ≈
3,329, `snapshots_created` = `notices_seen` (first run), `rows_inserted` ≈ 11,283, `notices_undated` 0,
`truncated_passes` `[]`, and `rows_by_country_group` matching the table below. Then the counts per country × group:
```
prod$ docker exec plasma_db psql -U plasma -d plasma_ai -c "select country, procurement_group, count(distinct notice_id) as notices, count(*) as bidder_rows from award_outcomes group by 1,2 order by 1,2"
```
Expected (rehearsal 2026-10-12, window from 2024-10-12; production differs by the notices published
or dropped out of the window since):

| Country | Consultant Services | Goods | Works | Non-consulting Services | Total |
| --- | --- | --- | --- | --- | --- |
| Uzbekistan | 245 / 475 | 292 / 821 | 571 / 2,989 | 412 / 1,602 | **1,520 / 5,887** |
| Kazakhstan | 40 / 40 | 25 / 29 | 20 / 57 | 6 / 8 | **91 / 134** |
| Kyrgyz Republic | 283 / 1,019 | 571 / 1,654 | 128 / 656 | 15 / 40 | **997 / 3,369** |
| Tajikistan | 233 / 478 | 274 / 789 | 185 / 572 | 26 / 54 | **718 / 1,893** |
| **All** | 801 / 2,012 | 1,162 / 3,293 | 904 / 4,274 | 459 / 1,704 | **3,326 / 11,283** |

Each cell: notices / bidder rows. (A notice can be counted in two cells only if the World Bank re-publishes it under another group; none did in the rehearsal.)

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
Expect the second ingest to report `snapshots_created` 0 and `snapshots_unchanged` = `notices_seen`,
`rows_inserted` 0 (rehearsal: 82 s), and the validation (rehearsal: 68 s, ~80 MiB) to report
`"projects": {"projects": 82, "fetched": …, "cached": …, "failed": 6, "invalid": 0}` (failed = the
Projects API has no record yet; a second run counts the cached ones) and
`"by_flag": {"FOREIGN_BIDDER_SECTION": 9, "DUPLICATE_AWARD_NOTICE": 20, "PROJECT_NOT_RESOLVABLE": 15}`. Flagged notices stay in the ledger;
`PROJECT_COUNTRY_MISMATCH`, `FOREIGN_BIDDER_SECTION` and `DUPLICATE_AWARD_NOTICE` notices are left
out of market sizing, the target lists and the Loom previews' references; `PROJECT_NOT_RESOLVABLE`
ones are kept (the Projects API does not return a few new projects). Rehearsal: 9
`FOREIGN_BIDDER_SECTION` (award sections of other countries published on Uzbek, Tajik and Kyrgyz
packages), 20 `DUPLICATE_AWARD_NOTICE` (every award of the notice published again in another notice), 0 mismatches, 15
unresolvable notices on 4 new projects. **STOP** (and send the JSON) if `PROJECT_COUNTRY_MISMATCH`
appears or a count is more than double the rehearsal's.

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

## 17. S1 feature check (owner, browser, `https://<APP_DOMAIN>`)

1. **Admin → Metrics** (admin): weekly active organizations, funnel, median/p90 analysis time and
   cost per analysis (the step 13 run is there; demo organizations are excluded unless asked for).
2. **Admin → Award ledger** (step 15) and its CSV download; market sizing `.md`/`.csv` downloads (admin).
3. **Opportunities**: the coverage strip above the list (sources and countries covered).
4. Legacy URLs redirect (e.g. the old bid-preparation list → Pursuits; the vault → Company & Experience).
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
   Rehearsal (local, non-admin pilot user): seven `403`; the pages redirected to `/dashboard`.

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
```
Expect `oom=false restarts=0`, smoke `0 failure(s)`, Beat exit 0. Then delete
`/var/backups/plasma/$SET.*` and `.env.pre-deploy4`.

The ledger is **not** refreshed by Beat in this release. To add newer notices later, re-run the
step 15 ingest and validation (idempotent; ~94 min).

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
message. Local data 2026-10-13: one open Central Asian REOI (3,766 characters, a regional CQS on infection
prevention), 21 closed within 120 days.

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
`archived_other_previews`, and `replay` / `kept.status` (`open` or `closed <date>`). Rehearsal: 69 s for
one pinned preview; 120-199 s for best of 3
with inline analysis (on production the worker analyses; allow ~1-3 min per candidate). If a run
stops on the analysis wait, finish that candidate with `--resume <label> --tender-external
world_bank:<its OP id> --candidates 1` (the label is printed per candidate), then archive the
candidates you do not keep (step 4).

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
wrong. A failed or partial ingest (step 15) is **not** a reason to roll back: the app does not read
the ledger outside the admin pages and the previews; re-run it. Every rollback starts with the
pre-stop gate (step 9's three commands).

**A. Deploy 3 images on the new schema (first choice).** The two migrations only add tables.
```
prod$ $RUN python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; curl -fsS http://127.0.0.1:8000/health; echo
prod$ scripts/ops/smoke.sh --target production --expect-sha "$PREV_SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect `build_sha` `169d4517…` and smoke with one expected failure: `database schema is not at the
Alembic head: … Can't locate revision identified by '20261012_0002_s1_product_analytics'`. Remnants
while on A: the ledger, product events and AI cost rows stay, unused; preview organizations stay
(archive them first if you can).

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
Expect `DNS_OK` (STOP without it), `CHECKOUT_OK`, `ENV_RESTORED`, `build_sha` `169d4517…`, the same
single expected smoke failure.

**B. Schema rollback (not needed; only while `:latest` is still the new image).** Drops the four
S1 tables, **including the ingested ledger and the AI cost rows**:
`prod$ scripts/compose-release.sh run --rm --no-deps backend alembic downgrade 20261011_0001_r3_organization_record_events`

**C. Database restore** (loses everything since step 4): Deploy 1 Rollback C with `$SET` from
step 4 (pre-stop gate first), then A2. Never `docker compose down -v`.

---

## Gate and rehearsal (evidence)

**Gate** (`pilot/s1-release` 4f8c019, the final S1 tree; LF `git archive` export; details in docs/audits/s1/S1_8_REPORT.md):

| Group | Result |
| --- | --- |
| backend | **1,193 passed**, 1 skipped, 0 failed (12 batches, fresh process each) |
| security | **118 passed**, including the 20 MB upload case (413) |
| analysis / connectors | 50 / 198 passed |
| migrations / performance | pass |
| config-dependencies | 24 passed, `pip check` clean, `npm audit --omit=dev` 0 |
| frontend / browser | npm ci, typecheck, lint, **406/406** node tests, RTL audit, build; **214** browser cases passed (Windows) |

**Rehearsal** (2026-10-12, a fresh copy of the production-shaped database at the Deploy 3 head, the release code in
one-off capped containers; times include each container's start; the app cut-over itself (steps 6-11) was not
rehearsed: it needs the release images and would stop the shared local stack, and Deploy 3 proved it):

| Step | Result |
| --- | --- |
| copy of the database (265 MB) | 42 s |
| two migrations | **5 s**; output exactly as in step 10; `20261012_0002_s1_product_analytics (head)` |
| first ingest (step 15) | **94 s**, 53 pages, 3,329 notices, 11,283 bidder rows, peak ~80 MiB |
| second ingest | 82 s, 0 created, 3,329 unchanged |
| validation | 68 s; 82 projects; `FOREIGN_BIDDER_SECTION` 9, `DUPLICATE_AWARD_NOTICE` 20, `PROJECT_NOT_RESOLVABLE` 15 |
| Loom plan, Central Asia | 8 s, `REFUSED` (no Central Asian REOI qualified that day) |
| Loom plan, `--allow-global` | 8 s |
| Loom pinned preview (`--candidates 1`) | 69 s (inline analysis), peak ~150 MiB |
| list / archive / list | 5 / 5 / 6 s; `archived: true`, demo user revoked, records kept |
| Loom best of 3 (five firms, `--allow-global`) | 120-199 s each, USD 0.10-0.21 each at the default prices |

