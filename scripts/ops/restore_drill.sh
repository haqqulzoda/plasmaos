#!/usr/bin/env bash
# Restore drill: prove the newest off-host backup can be restored and run.
#
#   scripts/ops/restore_drill.sh [--tier daily|weekly|none] [--label prod] [--images SHA]
#                                [--migrate] [--stop-after] [--yes]
#
# 1. finds the newest COMPLETE set (one with a .manifest) on BACKUP_REMOTE[/<tier>] (same
#    remotes as backup.sh, e.g. r2:// with BACKUP_S3_* read-only credentials),
# 2. downloads it to BACKUP_DIR/drill/<set> and verifies every component against the .sha256
#    file and the manifest,
# 3. restores it into the isolated plasma_staging stack with restore_to_staging.sh (which refuses
#    to touch anything but plasma_staging and reads only .env.staging),
# 4. waits for staging's /health/ready and runs smoke.sh --target staging.
# Production is never contacted. Run it on the laptop or a spare host, not on the 4 GB production
# host (a second stack does not fit there). --images SHA starts staging from already loaded
# plasma-<service>:SHA release images (no build). --migrate also runs the checkout's migrations
# (rehearsing a release on the restored data). --stop-after stops the staging stack at the end.
#
# The last line is machine-readable:
#   DRILL_RESULT set=... age_hours=... bytes=... download_seconds=... restore_seconds=... smoke=pass|fail
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=remote_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/remote_lib.sh"

TIER="daily"
LABEL="prod"
IMAGES=""
MIGRATE=()
STOP_AFTER=0
ASSUME_YES=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --images) [[ "${2:-}" =~ ^[0-9a-f]{7,40}$ ]] || die "--images needs a release SHA"; IMAGES="$2"; shift 2 ;;
    --migrate) MIGRATE=(--migrate); shift ;;
    --stop-after) STOP_AFTER=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ "$ASSUME_YES" = "1" ] || die "the drill replaces the staging database and files: pass --yes"
[ -n "${BACKUP_REMOTE:-}" ] || die "BACKUP_REMOTE is not set (the remote the backups go to)"
cd "$OPS_ROOT"
[ -f .env.staging ] || die ".env.staging not found: the drill restores into the staging stack"

remote_setup "$BACKUP_REMOTE"
case "$TIER" in daily|weekly) remote_subdir "$TIER" ;; none) ;; *) die "--tier must be daily, weekly or none" ;; esac

# ---- 1. newest complete set ---------------------------------------------------------------------------
SET="$(remote_latest_set "$LABEL")"
[ -n "$SET" ] || die "no complete plasma_${LABEL}_* set on $REMOTE_DESC"
stamp="$(echo "$SET" | sed 's/^plasma_[a-z]*_\([0-9]\{8\}\)T\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)Z_.*/\1 \2:\3:\4/')"
age_hours=$(( ($(date -u +%s) - $(date -u -d "$stamp" +%s)) / 3600 ))
log "newest complete set on $REMOTE_DESC: $SET (${age_hours} h old)"

# ---- 2. download and verify ---------------------------------------------------------------------------
BACKUP_DIR="${BACKUP_DIR:-$OPS_ROOT/backups}"
DEST="$BACKUP_DIR/drill/$SET"
rm -rf "$DEST"; mkdir -p "$DEST"
started=$SECONDS
remote_get "$SET.manifest" >"$DEST/$SET.manifest"
remote_get "$SET.sha256" >"$DEST/$SET.sha256"
mapfile -t COMPONENTS < <(awk -v set="$SET" 'index($1, set ".") == 1 && NF == 3 {print $1 " " $2 " " $3}' "$DEST/$SET.manifest")
[ "${#COMPONENTS[@]}" -gt 0 ] || die "the manifest of $SET lists no components"
bytes=0
for line in "${COMPONENTS[@]}"; do
  read -r name size sha <<<"$line"
  remote_get "$name" >"$DEST/$name"
  actual_size="$(wc -c <"$DEST/$name" | tr -d ' ')"
  actual_sha="$(sha256sum <"$DEST/$name" | cut -c1-64)"
  [ "$actual_size" = "$size" ] && [ "$actual_sha" = "$sha" ] \
    || die "$name does not match its manifest (size $actual_size/$size, sha256 $actual_sha/$sha)"
  bytes=$((bytes + size))
  log "  $name: $size bytes, matches the manifest"
done
(cd "$DEST" && sha256sum -c --quiet "$SET.sha256") || die "checksum verification failed for $SET"
download_seconds=$((SECONDS - started))
log "downloaded and verified $SET ($bytes bytes) in ${download_seconds}s"

# ---- 3. restore into staging --------------------------------------------------------------------------
if [ -n "$IMAGES" ]; then
  for service in backend frontend celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat; do
    "${_DOCKER[@]}" image inspect "plasma-$service:$IMAGES" >/dev/null 2>&1 || die "missing release image plasma-$service:$IMAGES"
    "${_DOCKER[@]}" tag "plasma-$service:$IMAGES" "$STAGING_PROJECT-$service:latest"
  done
  log "staging uses the release images $IMAGES (no build)"
fi
started=$SECONDS
"$OPS_ROOT/scripts/ops/restore_to_staging.sh" --src "$DEST" --label "$LABEL" --yes ${MIGRATE[@]+"${MIGRATE[@]}"}
backend_port="$(env_file_value .env.staging STAGING_BACKEND_PORT || true)"
ready_url="http://127.0.0.1:${backend_port:-18000}/health/ready"
for _ in $(seq 1 100); do
  curl -fsS --max-time 5 "$ready_url" >/dev/null 2>&1 && break
  sleep 3
done
curl -fsS --max-time 5 "$ready_url" >/dev/null 2>&1 || log "WARN: $ready_url is not ready after 5 minutes"
# A fresh ClamAV loads its signatures for 1-4 minutes before it answers (smoke checks it).
clam_cid="$(ops_cid "$STAGING_PROJECT" clamav)"
for _ in $(seq 1 60); do
  [ -z "$clam_cid" ] && break
  [ "$("${_DOCKER[@]}" inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$clam_cid")" = healthy ] && break
  sleep 10
done
restore_seconds=$((SECONDS - started))

# ---- 4. smoke -----------------------------------------------------------------------------------------------
smoke=pass
"$OPS_ROOT/scripts/ops/smoke.sh" --target staging || smoke=fail
if [ "$STOP_AFTER" = "1" ]; then
  "$OPS_ROOT/scripts/ops/compose-staging.sh" stop >/dev/null 2>&1 || true
  log "staging stopped"
fi
echo "DRILL_RESULT set=$SET age_hours=$age_hours bytes=$bytes download_seconds=$download_seconds restore_seconds=$restore_seconds smoke=$smoke"
[ "$smoke" = "pass" ]
