# Deploy 1b runbook: PostgreSQL tuning and OOM protection for db/redis (4gb profile)

> **Status: rehearsed 2026-10-09, clean** (forward twice, rollback once; table at the end).
> Recommended as its own window 24 hours after Deploy 3.

For the owner, copy-paste on the production host. Production's `db` and `redis` containers were
created from the `a275357` compose file and were deliberately never recreated since (Deploy 1 and
Deploy 2 left them alone). They run PostgreSQL with its defaults and no OOM protection:

| | today (`a275357` definition) | after Deploy 1b (`docker-compose.yml` + `HOST_PROFILE=4gb`) |
| --- | --- | --- |
| db command | `postgres` (shared_buffers 128MB, effective_cache_size 4GB, work_mem 4MB, maintenance_work_mem 64MB, max_connections 100) | `postgres -c shared_buffers=256MB -c effective_cache_size=1GB -c work_mem=4MB -c maintenance_work_mem=64MB -c max_connections=100` |
| db oom_score_adj | 0 | **-800** |
| redis oom_score_adj | 0 | **-500** (command unchanged) |

Why: under memory pressure the kernel must kill a worker (positive `oom_score_adj`), never the
database or the broker; and PostgreSQL gets a cache sized for the 4 GB host. Recreating the two
containers keeps their volumes (data untouched) but restarts PostgreSQL and Redis: a short window
in which the app is stopped.

| | |
| --- | --- |
| Checkout | `pilot/week1` at a commit that contains `deploy/compose/dbredis-before-1b.yml` (Deploy 3 or later) |
| Images | unchanged: the running release `$SHA` (no import, no migration) |
| Touched | `db`, `redis` (recreated); app services stopped and started; **ClamAV untouched** |
| Downtime | step 5 → step 9: **37-70 s** in the rehearsal (db/redis recreate → ready: 6 s); rollback 46 s |
| Rollback | recreate `db`/`redis` from `deploy/compose/dbredis-before-1b.yml` (the exact current definition) |
| Combine with Deploy 3? | **No, not until this rehearsal is clean** (see the recommendation at the end) |

Rule for this window: every `up` names its services and has `--no-deps`.

## 0. Variables
```
prod$ cd /opt/plasma-console/plasmaos
prod$ SHA=$(curl -fsS http://127.0.0.1:8000/health | sed -n 's/.*"build_sha":"\([^"]*\)".*/\1/p'); echo $SHA
prod$ APPS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ SMOKE_ORG_ID=<"Plasma Smoke Test" organization_id, as in Deploy 2 step 13>
```
Expect the running release SHA (40 hex characters). **STOP** if empty.

## 1. Pre-checks (nothing changes)
```
prod$ git status --porcelain; ls deploy/compose/dbredis-before-1b.yml
prod$ free -h; df -h /
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/deploy1b-dbredis-before.txt
prod$ docker exec plasma_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "show shared_buffers"'
prod$ scripts/compose-release.sh config | sed -n '/^  db:/,/^  [a-z_]*:$/p' | grep -E 'shared_buffers|oom_score_adj'
prod$ scripts/compose-release.sh config | sed -n '/^  redis:/,/^  [a-z_]*:$/p' | grep oom_score_adj
```
Expect: no file lines and the overlay path; `available` ≥ ~700Mi; db `cmd=[postgres] oom_adj=0`,
redis `cmd=[redis-server --save  --appendonly yes --appendfsync always --dir /data] oom_adj=0`;
`128MB`; then `shared_buffers=256MB` and `oom_score_adj: -800`, and `oom_score_adj: -500`.
**STOP** if the config does not show the new values (`HOST_PROFILE` is not `4gb`).

## 2. Off-host backup
```
prod$ sudo systemctl start plasma-backup-daily.service; journalctl -u plasma-backup-daily -n 3 -o cat
```
Expect `BACKUP_RESULT set=…`. **STOP** without it (no timers yet: run the Deploy 2 step 4 manual backup).

## 3. Smoke before
```
prod$ scripts/ops/smoke.sh --target production --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect `0 failure(s)`.

## 4. Pre-stop gate
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/deploy1b-dbredis-before.txt && echo DBREDIS_UNCHANGED
```
Expect `DNS_OK`, `"ready":true`, `DBREDIS_UNCHANGED`. **STOP** without `DNS_OK`:
`docker restart plasma_db plasma_redis plasma_clamav; then restart app services`, gate again.

## 5. Stop the app (ClamAV keeps running)
```
prod$ date -u +%T
prod$ scripts/compose-release.sh stop $APPS
prod$ docker ps --format '{{.Names}}' | sort
```
Expect seven `Stopped`, then `plasma_clamav`, `plasma_db`, `plasma_redis`.

## 6. Recreate db and redis with the new definition
```
prod$ scripts/compose-release.sh up "$SHA" --no-deps db redis
prod$ until docker exec plasma_db sh -c 'pg_isready -q -U "$POSTGRES_USER"'; do sleep 2; done; echo DB_READY
prod$ docker exec plasma_redis redis-cli ping
```
Expect two `Recreated`/`Started` lines (db, redis only), `DB_READY`, `PONG`.
**STOP → Rollback** if the database does not become ready within 2 minutes (`docker logs --tail 50 plasma_db`).

## 7. Verify the new settings and that the data is there
```
prod$ docker inspect -f '{{.Name}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis
prod$ docker exec plasma_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "show shared_buffers" -c "show effective_cache_size" -c "select count(*) from tenders"'
prod$ docker exec plasma_redis redis-cli dbsize
```
Expect db `oom_adj=-800` with the five `-c` settings, redis `oom_adj=-500`; `256MB`, `1GB`, the
tender count from before; a non-zero Redis key count (AOF reloaded).

## 8. DNS from a fresh container (the new db/redis have new addresses)
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
```
Expect `DNS_OK`. **STOP** otherwise: `docker restart plasma_db plasma_redis plasma_clamav`, repeat.

## 9. Start the app
```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done; date -u +%T; curl -fsS http://127.0.0.1:8000/health; echo
```
Expect `build_sha` = `$SHA`. Downtime = this time minus step 5's.

## 10. Smoke, live analysis, Beat
```
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ export ANALYSIS_SMOKE_TOKEN="$(scripts/compose-release.sh run --rm --no-deps -T backend python scripts/smoke_account.py token | tail -n 1)"
prod$ python3 -I -S backend/scripts/analysis_smoke.py --live --api-base http://127.0.0.1:8000/api/v1 --org-id "$SMOKE_ORG_ID" --org-name "Plasma Smoke Test" --max-latency 300
prod$ unset ANALYSIS_SMOKE_TOKEN
prod$ docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | sort; free -h
```
Expect `0 failure(s)` (the DNS line included), `live analysis smoke: OK`, PostgreSQL memory a little
higher than before (larger shared buffers), `available` ≥ ~600Mi. 24 hours later:
`docker inspect -f '{{.Name}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -q)`.

## Rollback (back to today's definition; data untouched)
Pre-stop gate first (expect `DNS_OK` and `"ready":true`; STOP without `DNS_OK`:
`docker restart plasma_db plasma_redis plasma_clamav; then restart app services`), then the rollback:
```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ scripts/compose-release.sh stop $APPS
prod$ scripts/compose-release.sh -f docker-compose.yml -f deploy/compose/dbredis-before-1b.yml up -d --no-deps db redis
prod$ until docker exec plasma_db sh -c 'pg_isready -q -U "$POSTGRES_USER"'; do sleep 2; done
prod$ docker inspect -f '{{.Name}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```
Expect db `cmd=[postgres] oom_adj=0`, redis `oom_adj=0` (as in `$HOME/deploy1b-dbredis-before.txt`
apart from the container ids), then smoke `0 failure(s)`.

## Rehearsal (2026-10-09, laptop, clean)

Setup: the isolated `plasma_staging` stack on the laptop (Docker VM 3.7 GiB like production,
`HOST_PROFILE=4gb`), the shared local stack stopped. Data: a daily backup set of the local
production-shaped database (119.7 MB, 3,118 tenders) sent to an R2-style endpoint and restored
with `scripts/ops/restore_drill.sh`; production's app images `4f09b8e`; `db`/`redis` created from
`deploy/compose/dbredis-before-1b.yml` (today's production definition). Commands: this runbook's,
with `scripts/ops/compose-staging.sh` in place of `compose-release.sh`.

| Step | Result |
| --- | --- |
| restore drill (download + verify, restore, smoke) | set verified against manifest and `.sha256` in 3 s; restore + start 98 s; smoke 27 ok, 0 failures once ClamAV was healthy (first ClamAV boot loads signatures for 1-4 min; the drill now waits for it) |
| before: db/redis definition | db `cmd=[postgres] oom_adj=0`, redis `oom_adj=0`; `shared_buffers=128MB` |
| pre-stop gate | `DNS_OK`, `"ready":true` (both passes and the rollback) |
| stop app → db/redis recreated → `pg_isready`/`PONG` | 12 s stop; recreate to ready **6 s** |
| new settings verified | db `cmd=[postgres -c shared_buffers=256MB -c effective_cache_size=1GB -c work_mem=4MB -c maintenance_work_mem=64MB -c max_connections=100] oom_adj=-800`, redis `oom_adj=-500`; `show shared_buffers` 256MB; 3,118 tenders before and after; Redis keys kept (AOF reloaded) |
| DNS from a fresh container after the recreate | `DNS_OK` (new addresses resolved) |
| start → `/health/ready` (**downtime**) | **70 s** first pass, **37 s** second pass |
| smoke (new definition) | 27 ok, 0 failures (the one warning was the laptop's own disk) |
| live analysis (new definition) | auto-picked REOI: 11 requirements, READY_FOR_REVIEW, 80 s; OP00472554: 7 requirements, READY_FOR_REVIEW, 94 s. A first attempt on the auto-picked tender returned 0 requirements: its pass 1 hit a Gemini `ReadTimeout` and pass 2 found nothing; the same tender gave 11 on both definitions afterwards (provider variance, not the database) |
| rollback → old definition | db `cmd=[postgres] oom_adj=0`, redis `oom_adj=0`, `shared_buffers=128MB`, 3,118 tenders; downtime **46 s**; smoke 27 ok, 0 failures; live analysis on the old definition: 11 and 6 requirements, READY_FOR_REVIEW |
| peak memory (all containers, rehearsal steps) | 2,379 MiB: ClamAV 964, celery_worker 332, backend 234, PostgreSQL **171** (256MB shared buffers), worker_pursuit_analysis 183, worker_private_documents 172, worker_heavy 158, Beat 142, frontend 91, Redis 18 |

## Recommendation

Run Deploy 1b as **its own short window 24 hours after Deploy 3**: the rehearsal was clean (forward
twice, rollback once, smoke and live analysis on both definitions), it touches the two stateful
containers every earlier window left alone, and it is independent of the Deploy 3 code; keeping it
separate means a problem in either window has one cause. Expected downtime about one minute.
