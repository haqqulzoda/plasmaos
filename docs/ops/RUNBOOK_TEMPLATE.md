# Runbook template (production deploys and maintenance windows)

Copy this file to `docs/ops/<NAME>_RUNBOOK.md` and fill every `<…>`. The shape is the one Deploy 1
and Deploy 2 proved: the owner copy-pastes on the production host; every step has the command,
what must be seen, and a **STOP** condition; the window is rehearsed locally first and the
rehearsal numbers are quoted at each step.

Rules that hold for every runbook:

- **The pre-stop gate (below) runs immediately before every step that stops or recreates an app
  service**: the cut-over stop, a single-service recreate, every rollback, a database restore.
- Every `up` names its services and has `--no-deps`. Never `up` without a service list,
  `compose-release.sh rollback`, `docker compose up`, `down` or `restart`: with this compose file
  they would recreate `db`/`redis`. Only a runbook whose purpose is db/redis (Deploy 1b) touches them.
- No `docker system prune`, no `volume prune`, no `docker compose down -v`.
- Fix forward first; two proven rollbacks; an off-host backup verified before the window.

---

## The pre-stop gate (standard snippet)

Why: in Deploy 2, Docker's embedded DNS lost the `db`/`redis` records. The running app kept its
pooled connections, so nothing looked wrong until new containers started and could not find the
database. Only a **new** container proves that a stopped app can come back.

```
prod$ scripts/compose-release.sh run --rm --no-deps -T backend python -c "import socket; [socket.getaddrinfo(h, None) for h in ('db', 'redis', 'clamav')]; print('DNS_OK')" | tail -n 1
prod$ curl -fsS http://127.0.0.1:8000/health/ready; echo
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/<window>-prestop-dbredis.txt
```
Expect: `DNS_OK` (a fresh one-off backend container resolves `db`, `redis` and `clamav`);
`{"ready":true,"dependencies":{"database":true,"redis":true}}`; two fingerprint lines, identical to
the ones recorded in the pre-checks (`diff` them; afterwards the window compares against this file).
**STOP, do not stop anything** if `DNS_OK` is missing (the last line is then a `socket.gaierror`):
`docker restart plasma_db plasma_redis plasma_clamav; then restart app services`
(`for s in $APPS; do docker restart plasma_$s; done`), wait for `/health/ready`, and run the gate again.
**STOP** if `/health/ready` is not `ready: true`. `scripts/ops/smoke.sh` runs the same DNS check
(line `a fresh one-off container resolves db, redis, clamav`), and the host monitor runs it every 5 minutes.

---

## Template

# <Name> runbook: production <current checkout> / images <current SHA> → <branch>, images <new SHA>

For the owner, copy-paste on the production host. <One paragraph: what changes, why, the window.>

| | |
| --- | --- |
| Checkout | `<branch>` @ `<commit>` |
| Images | `plasma-<service>:<SHA>`, bundle `plasma-release-<short>.tar.gz`, **<bytes>**, sha256 `<…>`; `/health` reports `build_sha` `<SHA>` |
| Running today | checkout `<…>`, images `<…>`, schema `<alembic head>` |
| Host | Hetzner 2 vCPU / 3.7 GiB, `/opt/plasma-console/plasmaos`, `HOST_PROFILE=4gb`, `PLASMA_NO_BUILD=1` |
| Migrations | `<revision>` (<additive or not; does the old build run on the new schema?>) — or "none" |
| New variables | `<NAME>` (default `<value>`), … — or "none" |
| **Not touched** | `db`, `redis`, `clamav` keep their containers (unless this runbook is about them) |
| Downtime | step <a> → step <b>: **<n> s** in the rehearsal |
| Rehearsal | <where, which data, which images; peak memory> |

Conventions: `prod$` on the production host in `/opt/plasma-console/plasmaos`; `laptop$` on the
owner's PC (Git Bash). `<prod>`, `<APP_DOMAIN>`, `<API_DOMAIN>` as before.

## 0. Variables (every new production shell)
```
prod$ cd /opt/plasma-console/plasmaos
prod$ COMMIT=<…>; SHA=<…>; PREV_COMMIT=<…>; PREV_SHA=<…>
prod$ APPS="celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat backend frontend"
prod$ curl -fsS http://127.0.0.1:8000/health; echo
```

## 1. Pre-checks (nothing changes)
`git status`, `free -h`, `df -h /`, `alembic current`, image count of `$PREV_SHA`, and the db/redis
fingerprint record:
```
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | tee $HOME/<window>-dbredis.txt
prod$ scripts/ops/smoke.sh --target production --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
```

## 2. Off-host backup (verified copy before anything changes)
With the timers installed (docs/ops/BACKUPS.md) check last night's set, or run one now:
```
prod$ sudo systemctl start plasma-backup-daily.service && journalctl -u plasma-backup-daily -n 3 -o cat
```
Expect a `BACKUP_RESULT set=…` line. **STOP** without it.

## 3. Check out, transfer, import (nothing restarts)
<git checkout; bundle transfer + sha256; `compose-release.sh import --expect "$SHA"`; `.env` copy + new lines;
`compose-release.sh config` with the expected `mem_limit`/`--concurrency` lines>

## 4. Pre-stop gate
<the standard snippet above>

## 5. Stop the app
```
prod$ scripts/compose-release.sh stop $APPS
```

## 6. Switch images, migrate
```
prod$ scripts/compose-release.sh use "$SHA"
prod$ scripts/compose-release.sh run --rm --no-deps backend alembic upgrade head
```

## 7. Start, smoke, feature checks
```
prod$ scripts/compose-release.sh up "$SHA" --no-deps $APPS
prod$ until curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; do sleep 3; done
prod$ scripts/ops/smoke.sh --target production --expect-sha "$SHA" --frontend-url https://<APP_DOMAIN> --backend-url https://<API_DOMAIN>
prod$ docker inspect -f '{{.Name}} {{.Id}} cmd={{.Config.Cmd}} oom_adj={{.HostConfig.OomScoreAdj}}' plasma_db plasma_redis | diff - $HOME/<window>-dbredis.txt && echo DBREDIS_UNCHANGED
```
<live analysis smoke, EOI smoke, feature check, 24-hour check>

## Rollback
Default: fix forward. Every rollback starts with the pre-stop gate.
**A.** previous images on the new schema: gate, then `scripts/compose-release.sh up "$PREV_SHA" --no-deps $APPS`, smoke.
**A2.** exact return (previous checkout and `.env`). **B.** schema rollback (if any). **C.** database restore
from the verified set (docs/ops/BACKUPS.md "Restore").
