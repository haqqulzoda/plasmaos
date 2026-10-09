#!/usr/bin/env bash
# Host monitor: run every 5 minutes by deploy/systemd/plasma-monitor.timer on the production host.
#
#   scripts/ops/monitor.sh [--target production|staging|local] [--state-dir DIR] [--dry-run]
#
# Checks (read-only towards the stack; the DNS check starts one short-lived container):
#   ready     backend /health/ready (database + redis)
#   dns       a fresh one-off container resolves db, redis, clamav (lib.sh ops_dns_check)
#   containers  every container of the project is running; restarts and OOM kills since the last run
#             (a recreated container, i.e. a new id after a deploy, is not a restart)
#   disk      MONITOR_DISK_PATH (/) used above MONITOR_DISK_PERCENT (85)
#   beat      Beat heartbeat age in Redis (BEAT_HEARTBEAT_MAX_AGE, 60 s, as smoke.sh)
#   refresh   every customer-visible scheduled source refreshed successfully within 2x its cadence
#             (backend/scripts/source_freshness.py inside the backend container)
#   clamav    ClamAV container running and healthy ("starting" counts as fine)
#
# Telegram (scripts/ops/notify.sh) only on a state change: an alert when a check starts failing,
# a recovery when it passes again; at most one message per check per MONITOR_THROTTLE_SECONDS
# (1800). A change inside that window is sent when the window ends, if it still holds. All
# changes of one run go out as one message. A restart keeps "containers" failing for one window,
# so a restart produces one alert and, 30 quiet minutes later, one recovery.
# --dry-run prints the checks and the message it would send; it sends and records nothing.
#
# State: MONITOR_STATE_DIR (default /var/lib/plasma-monitor). Other settings: MONITOR_BACKEND_URL
# (http://127.0.0.1:8000), MONITOR_NOW (seconds since the epoch; tests). Always exits 0 unless the
# alert could not be delivered (then 1, so the systemd unit shows the failure).
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="production"
STATE_DIR="${MONITOR_STATE_DIR:-/var/lib/plasma-monitor}"
DRY_RUN=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
BACKEND_URL="${MONITOR_BACKEND_URL:-http://127.0.0.1:8000}"
DISK_PATH="${MONITOR_DISK_PATH:-/}"
DISK_LIMIT="${MONITOR_DISK_PERCENT:-85}"
THROTTLE="${MONITOR_THROTTLE_SECONDS:-1800}"
NOW="${MONITOR_NOW:-$(date +%s)}"
case "$DISK_LIMIT$THROTTLE$NOW" in *[!0-9]*) die "MONITOR_DISK_PERCENT, MONITOR_THROTTLE_SECONDS and MONITOR_NOW must be whole numbers" ;; esac
PROJECT="$(ops_project "$TARGET")"
D=("${_DOCKER[@]}")

mkdir -p "$STATE_DIR" || die "cannot create $STATE_DIR"
if command -v flock >/dev/null 2>&1; then
  exec 8>"$STATE_DIR/.lock"
  flock -n 8 || { log "another monitor run is active"; exit 0; }
fi

CHECKS=(); STATUS=(); DETAIL=()
record() {  # record CHECK ok|fail DETAIL
  CHECKS+=("$1"); STATUS+=("$2"); DETAIL+=("$3")
  printf '%-10s %-4s %s\n' "$1" "$2" "$3"
}
short() { tr '\n' ' ' | sed 's/  */ /g; s/ $//' | cut -c1-240; }

# ---- ready -------------------------------------------------------------------------------------------
ready="$(curl -sS --max-time 10 "$BACKEND_URL/health/ready" 2>&1)"
if printf '%s' "$ready" | grep -Eq '"ready" *: *true'; then
  record ready ok "/health/ready"
else
  record ready fail "/health/ready: $(printf '%s' "$ready" | short)"
fi

# ---- dns ----------------------------------------------------------------------------------------------
dns="$(ops_dns_check "$PROJECT")"; dns_status=$?
case "$dns_status" in
  0) record dns ok "a fresh container resolves ${OPS_DNS_NAMES// /, }" ;;
  1) record dns fail "a fresh container cannot resolve $(printf '%s\n' "$dns" | sed -n 's/^DNS_FAIL //p'). Remedy: $DNS_REMEDY" ;;
  *) record dns fail "DNS check could not run: $(printf '%s\n' "$dns" | tail -n 1 | short)" ;;
esac

# ---- containers: down, restarted, OOM-killed -------------------------------------------------------
mapfile -t ids < <("${D[@]}" ps -a -q --filter "label=com.docker.compose.project=$PROJECT" \
  --filter "label=com.docker.compose.oneoff=False")
current_file="$STATE_DIR/containers.current"
: >"$current_file"
if [ "${#ids[@]}" -gt 0 ]; then
  "${D[@]}" inspect -f '{{.Name}} {{.Id}} {{.RestartCount}} {{.State.OOMKilled}} {{.State.StartedAt}} {{.State.Status}}' "${ids[@]}" \
    | sed 's#^/##' | sort >"$current_file"
fi
events=(); down=()
while read -r name id restarts oom started state; do
  [ -n "$name" ] || continue
  case "$name" in *pgadmin*) continue ;; esac            # tools profile, not part of the service
  [ "$state" = "running" ] || down+=("$name is $state")
  previous="$(grep "^$name " "$STATE_DIR/containers.previous" 2>/dev/null | head -n 1 || true)"
  [ -n "$previous" ] || continue
  read -r _ prev_id prev_restarts _ prev_started _ <<<"$previous"
  [ "$prev_id" = "$id" ] || continue                     # recreated (deploy): not a restart
  if [ "$restarts" != "$prev_restarts" ] || [ "$started" != "$prev_started" ]; then
    event="$name restarted (restart count $prev_restarts -> $restarts)"
    [ "$oom" = "true" ] && event="$event, OOM-killed"
    events+=("$event")
  elif [ "$oom" = "true" ] && ! grep -q "^$name .* true " "$STATE_DIR/containers.previous" 2>/dev/null; then
    events+=("$name was OOM-killed")
  fi
done <"$current_file"
if [ "$DRY_RUN" = "0" ]; then mv "$current_file" "$STATE_DIR/containers.previous"; else rm -f "$current_file"; fi
if [ "${#events[@]}" -gt 0 ] && [ "$DRY_RUN" = "0" ]; then
  printf '%s %s\n' "$NOW" "$(IFS=';'; echo "${events[*]}")" >"$STATE_DIR/containers.last_event"
fi
last_event_at=0; last_event=""
if [ -f "$STATE_DIR/containers.last_event" ]; then
  read -r last_event_at last_event <"$STATE_DIR/containers.last_event"
fi
if [ "${#ids[@]}" -eq 0 ]; then
  record containers fail "no containers found for project $PROJECT"
elif [ "${#down[@]}" -gt 0 ]; then
  record containers fail "$(IFS=';'; echo "${down[*]}")"
elif [ "${#events[@]}" -gt 0 ]; then
  record containers fail "$(IFS=';'; echo "${events[*]}")"
elif [ $((NOW - ${last_event_at:-0})) -lt "$THROTTLE" ]; then
  record containers fail "${last_event:-restart} (no new restart since)"
else
  record containers ok "${#ids[@]} containers running, no restart or OOM kill in the last $((THROTTLE / 60)) min"
fi

# ---- disk ---------------------------------------------------------------------------------------------
used="$(df -Pk "$DISK_PATH" 2>/dev/null | tail -n 1 | grep -o '[0-9]\{1,3\}%' | head -n 1 | tr -d '%')"
if [ -z "$used" ]; then
  record disk fail "cannot read usage of $DISK_PATH"
elif [ "$used" -gt "$DISK_LIMIT" ]; then
  record disk fail "$DISK_PATH is ${used}% full (limit ${DISK_LIMIT}%)"
else
  record disk ok "$DISK_PATH is ${used}% full"
fi

# ---- beat ---------------------------------------------------------------------------------------------
beat="$(ops_exec "$PROJECT" redis redis-cli GET "$BEAT_HEARTBEAT_KEY" 2>/dev/null </dev/null | tr -d '\r' | tail -n 1)"
beat_age=-1
case "$beat" in ''|*[!0-9]*) ;; *) beat_age=$((NOW - beat)) ;; esac
case "$(beat_heartbeat_verdict "$beat_age")" in
  ok) record beat ok "heartbeat ${beat_age}s old" ;;
  stale) record beat fail "heartbeat ${beat_age}s old (limit ${BEAT_HEARTBEAT_MAX_AGE}s): Beat or the celery worker is stuck" ;;
  *) record beat fail "no Beat heartbeat in Redis" ;;
esac

# ---- refresh ------------------------------------------------------------------------------------------
freshness="$(ops_exec "$PROJECT" backend python scripts/source_freshness.py 2>/dev/null </dev/null | tr -d '\r' | grep '^source=' || true)"
if [ -z "$freshness" ]; then
  record refresh fail "source freshness could not be read (backend/scripts/source_freshness.py)"
else
  stale="$(printf '%s\n' "$freshness" | awk '/verdict=stale/ {
      split($1, s, "="); split($2, c, "="); split($3, a, "=");
      age = (a[2] < 0) ? "never" : sprintf("%.1fh ago", a[2] / 3600);
      printf "%s last success %s (cadence %gh); ", s[2], age, c[2] / 3600 }')"
  if [ -n "$stale" ]; then
    record refresh fail "${stale%; }"
  else
    record refresh ok "$(printf '%s\n' "$freshness" | grep -c 'verdict=ok') scheduled source(s) fresh"
  fi
fi

# ---- clamav -------------------------------------------------------------------------------------------
clam_cid="$(ops_cid "$PROJECT" clamav all)"
if [ -z "$clam_cid" ]; then
  record clamav fail "no ClamAV container"
else
  clam="$("${D[@]}" inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$clam_cid")"
  case "$clam" in
    "running healthy"|"running starting") record clamav ok "ClamAV $clam" ;;
    *) record clamav fail "ClamAV $clam: uploads cannot be scanned" ;;
  esac
fi

# ---- state changes and the message ------------------------------------------------------------------
messages=(); updates=()
fails=0
for i in "${!CHECKS[@]}"; do
  check="${CHECKS[$i]}"; status="${STATUS[$i]}"
  [ "$status" = "ok" ] || fails=$((fails + 1))
  notified=ok; last_sent=0
  if [ -f "$STATE_DIR/check.$check" ]; then read -r notified last_sent <"$STATE_DIR/check.$check"; fi
  [ "$status" != "$notified" ] || continue
  if [ $((NOW - ${last_sent:-0})) -lt "$THROTTLE" ]; then
    log "$check changed to $status; message held (one per $((THROTTLE / 60)) min per check)"
    continue
  fi
  if [ "$status" = "fail" ]; then messages+=("ALERT $check: ${DETAIL[$i]}"); else messages+=("RECOVERED $check: ${DETAIL[$i]}"); fi
  updates+=("$check $status")
done
echo "MONITOR_RESULT project=$PROJECT checks=${#CHECKS[@]} failing=$fails messages=${#messages[@]}"
[ "${#messages[@]}" -gt 0 ] || exit 0

text="$(printf '%s\n' "${messages[@]}")"
if [ "$DRY_RUN" = "1" ]; then
  printf 'would send:\n%s\n' "$text"
  exit 0
fi
"$(dirname "${BASH_SOURCE[0]}")/notify.sh" "$text"; sent=$?
if [ "$sent" = "1" ]; then
  log "the alert was not delivered; it is retried on the next run"
  exit 1
fi
# Delivered (0), or Telegram not configured (3: the text is in the journal): remember the change.
for update in "${updates[@]}"; do
  printf '%s %s\n' "${update#* }" "$NOW" >"$STATE_DIR/check.${update%% *}"
done
exit 0
