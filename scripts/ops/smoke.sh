#!/usr/bin/env bash
# Smoke test for a running Plasma stack. Read-only: GET requests, `pg_isready`,
# `redis-cli ping`, `celery inspect`, `alembic current`, `clamdscan --version`.
# It never dispatches work, writes data or logs in.
#
#   scripts/ops/smoke.sh [--target local|staging|production]
#                        [--frontend-url URL] [--backend-url URL]
#                        [--expect-sha GIT_SHA] [--http-only]
#
# Checks: backend /health and release identity, /health/ready (database + redis),
# frontend 200 and its /api/v1 rewrite to the backend, containers running, Postgres and
# Redis answering, Alembic at head, every Celery queue consumed by a live worker, Beat
# ticking, ClamAV signature freshness, host disk space.
#
# The stack is addressed by its Compose labels (no compose files or .env needed).
# Targets pick the Compose project and default URLs:
#   local       docker compose in this checkout        http://127.0.0.1:3000 and :8000
#   staging     plasma_staging stack                   STAGING_FRONTEND_PORT / STAGING_BACKEND_PORT from .env.staging
#   production  run on the production host             pass --frontend-url/--backend-url (public URLs work)
# --http-only skips every check that needs Docker (use it from a laptop against public URLs).
#
# Exit status: 0 when nothing FAILED (WARN is allowed), 1 otherwise.
# Tunables: SMOKE_CLAMAV_MAX_AGE_DAYS (3), SMOKE_DISK_PATH (/), SMOKE_DISK_WARN_PERCENT (80),
# SMOKE_DISK_FAIL_PERCENT (90), SMOKE_CELERY_TIMEOUT (8), SMOKE_CURL_TIMEOUT (15).
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="local"
FRONTEND_URL=""
BACKEND_URL=""
EXPECT_SHA=""
HTTP_ONLY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --frontend-url) FRONTEND_URL="$2"; shift 2 ;;
    --backend-url) BACKEND_URL="$2"; shift 2 ;;
    --expect-sha) EXPECT_SHA="$2"; shift 2 ;;
    --http-only) HTTP_ONLY=1; shift ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

CURL_TIMEOUT="${SMOKE_CURL_TIMEOUT:-15}"
CELERY_TIMEOUT="${SMOKE_CELERY_TIMEOUT:-8}"
PASS=0; WARN=0; FAIL=0
ok()   { PASS=$((PASS + 1)); printf '[ OK ] %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf '[WARN] %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf '[FAIL] %s\n' "$*"; }

cd "$OPS_ROOT" || exit 1
case "$TARGET" in
  local)
    : "${FRONTEND_URL:=http://127.0.0.1:3000}"; : "${BACKEND_URL:=http://127.0.0.1:8000}" ;;
  staging)
    [ -f .env.staging ] || die ".env.staging not found"
    fp="$(env_file_value .env.staging STAGING_FRONTEND_PORT || true)"
    bp="$(env_file_value .env.staging STAGING_BACKEND_PORT || true)"
    : "${FRONTEND_URL:=http://127.0.0.1:${fp:-13000}}"
    : "${BACKEND_URL:=http://127.0.0.1:${bp:-18000}}" ;;
  production)
    [ -n "$FRONTEND_URL" ] && [ -n "$BACKEND_URL" ] || die "production needs --frontend-url and --backend-url" ;;
  *) die "unknown target '$TARGET'" ;;
esac
FRONTEND_URL="${FRONTEND_URL%/}"; BACKEND_URL="${BACKEND_URL%/}"
echo "Smoke test: target=$TARGET frontend=$FRONTEND_URL backend=$BACKEND_URL"

http_get() { curl -sS --max-time "$CURL_TIMEOUT" "$@"; }

# ---- backend health and release identity --------------------------------------------------------
health="$(http_get "$BACKEND_URL/health" 2>&1)" && health_ok=1 || health_ok=0
if [ "$health_ok" = "1" ] && printf '%s' "$health" | grep -Eq '"status" *: *"ok"'; then
  sha="$(printf '%s' "$health" | sed -n 's/.*"build_sha" *: *"\([^"]*\)".*/\1/p')"
  built="$(printf '%s' "$health" | sed -n 's/.*"build_time" *: *"\([^"]*\)".*/\1/p')"
  ok "backend /health ok (build_sha=${sha:-none} build_time=${built:-none})"
  if [ -z "$sha" ] || [ "$sha" = "unknown" ]; then
    warn "release metadata has no build identity (image built without PLASMA_BUILD_SHA)"
  elif [ -n "$EXPECT_SHA" ]; then
    case "$sha" in "$EXPECT_SHA"*) ok "build_sha matches expected $EXPECT_SHA" ;; *) fail "build_sha $sha does not match expected $EXPECT_SHA" ;; esac
  fi
else
  fail "backend /health did not return status ok at $BACKEND_URL/health"
fi

version="$(http_get "$BACKEND_URL/api/v1/health/version" 2>&1 || true)"
printf '%s' "$version" | grep -Eq '"version" *: *"[^"]+"' \
  && ok "release metadata /api/v1/health/version: $(printf '%s' "$version" | sed -n 's/.*"version" *: *"\([^"]*\)".*/\1/p')" \
  || fail "release metadata /api/v1/health/version missing"

ready_file="$(mktemp)"
ready_code="$(http_get -o "$ready_file" -w '%{http_code}' "$BACKEND_URL/health/ready" 2>/dev/null || true)"
ready_body="$(cat "$ready_file" 2>/dev/null || true)"; rm -f "$ready_file"
if [ "$ready_code" = "200" ] && printf '%s' "$ready_body" | grep -Eq '"ready" *: *true'; then
  ok "backend /health/ready: database and redis reachable"
else
  fail "backend /health/ready returned $ready_code: $ready_body"
fi

# ---- frontend -------------------------------------------------------------------------------------------
code="$(http_get -L -o /dev/null -w '%{http_code}' "$FRONTEND_URL/" 2>/dev/null || true)"
[ "$code" = "200" ] && ok "frontend GET / -> 200" || fail "frontend GET / -> $code"
via="$(http_get "$FRONTEND_URL/api/v1/health/version" 2>&1 || true)"
printf '%s' "$via" | grep -Eq '"version" *: *"[^"]+"' \
  && ok "frontend rewrites /api/v1/* to the backend" \
  || fail "frontend /api/v1/health/version did not reach the backend"

# ---- host disk ------------------------------------------------------------------------------------------------
used="$(df -Pk "${SMOKE_DISK_PATH:-/}" 2>/dev/null | tail -n 1 | grep -o '[0-9]\{1,3\}%' | head -n 1 | tr -d '%')"
if [ -n "$used" ]; then
  if [ "$used" -ge "${SMOKE_DISK_FAIL_PERCENT:-90}" ]; then fail "disk ${SMOKE_DISK_PATH:-/} is ${used}% full"
  elif [ "$used" -ge "${SMOKE_DISK_WARN_PERCENT:-80}" ]; then warn "disk ${SMOKE_DISK_PATH:-/} is ${used}% full"
  else ok "disk ${SMOKE_DISK_PATH:-/} is ${used}% full"; fi
fi

# ---- Docker-level checks ----------------------------------------------------------------------------------------
if [ "$HTTP_ONLY" = "1" ]; then
  echo "(--http-only: skipping container, queue, beat and ClamAV checks)"
else
  command -v docker >/dev/null 2>&1 || die "docker not found (use --http-only for HTTP checks only)"
  PROJECT="$(ops_project "$TARGET")"
  echo "Compose project: $PROJECT"
  for service in db redis backend frontend celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat clamav; do
    state="$(ops_state "$PROJECT" "$service" || true)"
    [ "$state" = "running" ] && ok "container $service is running" || fail "container $service is ${state:-not present}"
  done
  [ "$(ops_state "$PROJECT" pgadmin || true)" = "running" ] \
    && warn "pgadmin is running (tools profile); it should not run on production or staging"

  ops_exec "$PROJECT" db sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 \
    && ok "postgres accepts connections (pg_isready)" || fail "postgres is not ready"
  [ "$(ops_exec "$PROJECT" redis redis-cli ping 2>/dev/null | tr -d '\r')" = "PONG" ] \
    && ok "redis answers PING" || fail "redis did not answer PING"

  head_out="$(ops_exec "$PROJECT" backend alembic current 2>/dev/null || true)"
  printf '%s' "$head_out" | grep -q '(head)' \
    && ok "database schema is at the Alembic head ($(printf '%s' "$head_out" | grep -o '[0-9]\{8\}_[0-9a-z_]*' | head -n 1))" \
    || fail "database schema is not at the Alembic head: $(printf '%s' "$head_out" | tail -n 1)"

  queues="$(ops_exec "$PROJECT" celery_worker celery -A app.core.celery_app inspect active_queues --timeout "$CELERY_TIMEOUT" --json 2>/dev/null || true)"
  if [ -z "$queues" ]; then
    fail "no celery worker answered (inspect active_queues)"
  else
    for queue in celery ai_fast_queue heavy_dl_queue private_documents pursuit_analysis; do
      printf '%s' "$queues" | grep -Eq "\"name\": *\"$queue\"" && ok "queue $queue has a live worker" || fail "queue $queue has no live worker"
    done
  fi

  # Beat liveness from direct evidence, not container logs (Docker Desktop can stop capturing them):
  # a worker writes the receipt time of Beat's 10-second publish_notifications task to Redis
  # (app.core.celery_app.BEAT_HEARTBEAT_KEY); its age is read with the same broker URL.
  beat_age="$(ops_exec "$PROJECT" backend python -c "
import os, time
from redis import Redis
value = Redis.from_url(os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'), socket_timeout=3).get('$BEAT_HEARTBEAT_KEY')
print(int(time.time()) - int(value) if value else -1)" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
  case "$(beat_heartbeat_verdict "$beat_age")" in
    ok) ok "beat is dispatching (a worker received its 10-second task ${beat_age}s ago)" ;;
    stale) fail "beat heartbeat is ${beat_age}s old (limit ${BEAT_HEARTBEAT_MAX_AGE}s): Beat or the celery queue's worker is stuck" ;;
    *) fail "no beat heartbeat in Redis ($BEAT_HEARTBEAT_KEY): Beat has not dispatched to a worker" ;;
  esac

  # The backend reaches clamd over TCP; test that exact path (PING -> PONG) from the backend container.
  clam_ping="$(ops_exec "$PROJECT" backend python -c "
import os, socket
s = socket.create_connection((os.environ.get('PRIVATE_DOCUMENT_SCAN_HOST', 'clamav'), int(os.environ.get('PRIVATE_DOCUMENT_SCAN_PORT', '3310'))), 5)
s.sendall(b'zPING\0'); print(s.recv(16).decode().replace(chr(0), '').strip())" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
  if [ "$clam_ping" = "PONG" ]; then
    ok "clamd answers PING from the backend container (private uploads can be scanned)"
  else
    fail "clamd does not answer PING from the backend container (uploads cannot be scanned)"
  fi
  clam="$(ops_exec "$PROJECT" clamav freshclam --version 2>/dev/null | tr -d '\r' | head -n 1 || true)"
  sig_epoch=""
  if printf '%s' "$clam" | grep -Eq '^ClamAV [^/]+/[0-9]+/'; then
    sig_epoch="$(date -u -d "${clam##*/}" +%s 2>/dev/null || true)"
  fi
  if [ -n "$sig_epoch" ]; then
    age_days=$(( ($(date -u +%s) - sig_epoch) / 86400 ))
    if [ "$age_days" -gt "${SMOKE_CLAMAV_MAX_AGE_DAYS:-3}" ]; then warn "ClamAV signatures are $age_days days old ($clam)"
    else ok "ClamAV signatures are $age_days day(s) old ($clam)"; fi
  else
    warn "ClamAV signature date could not be read (${clam:-no output})"
  fi
  clam_cid="$(ops_cid "$PROJECT" clamav)"
  if [ -n "$clam_cid" ] && [ "$("${_DOCKER[@]}" inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$clam_cid")" = "unhealthy" ]; then
    warn "ClamAV container healthcheck reports unhealthy"
  fi
fi

echo "----"
echo "Result: $PASS ok, $WARN warning(s), $FAIL failure(s)"
[ "$FAIL" -eq 0 ]
