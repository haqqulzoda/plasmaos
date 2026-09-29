#!/usr/bin/env bash
# Timestamped backup of Postgres and the private-document / tender-document volumes.
#
#   scripts/ops/backup.sh [--target production|staging|local] [--dir DIR]
#                         [--keep-days N] [--no-files] [--no-upload]
#
# Produces, in BACKUP_DIR (default ./backups, git-ignored):
#   plasma_<label>_<UTCstamp>_<hash12>.dump            pg_dump custom format (verified readable)
#   plasma_<label>_<UTCstamp>_<hash12>.files.tar.gz    /app/private-data + /app/data of the backend container
#   plasma_<label>_<UTCstamp>_<hash12>.sha256          checksums of both files
# The name matches the existing plasma_prod_<stamp>_<hash>.dump convention; <label> is
# prod, staging or local.
#
# Retention: sets older than BACKUP_KEEP_DAYS (default 14) are deleted, but the newest
# BACKUP_MIN_KEEP (default 3) sets are always kept.
#
# Off-host copy (REQUIRED for a real backup; placeholder until you choose a target):
#   BACKUP_REMOTE=user@backup-host:/srv/plasma-backups/      copied with rsync
#   BACKUP_REMOTE=s3://your-bucket/plasma/                    copied with the aws CLI
# The stack is addressed by its Compose labels (project from --target: production =
# PROD_COMPOSE_PROJECT or the checkout directory name, staging = plasma_staging, local =
# OPS_LOCAL_PROJECT or the directory name), so no compose files or .env are needed.
# Redis is not backed up: it only holds auth-replay keys and queue state that is
# rebuilt (see docs/ops/PRODUCTION_READINESS.md).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${OPS_TARGET:-production}"
BACKUP_DIR="${BACKUP_DIR:-$OPS_ROOT/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
MIN_KEEP="${BACKUP_MIN_KEEP:-3}"
WITH_FILES=1
UPLOAD=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --dir) BACKUP_DIR="$2"; shift 2 ;;
    --keep-days) KEEP_DAYS="$2"; shift 2 ;;
    --no-files) WITH_FILES=0; shift ;;
    --no-upload) UPLOAD=0; shift ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
case "$KEEP_DAYS$MIN_KEEP" in *[!0-9]*) die "--keep-days and BACKUP_MIN_KEEP must be whole numbers" ;; esac

umask 077
PROJECT="$(ops_project "$TARGET")"
LABEL="$(ops_label "$TARGET")"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PARTIAL="$BACKUP_DIR/.partial_${LABEL}_${STAMP}_$$"
trap 'rm -f "$PARTIAL".dump "$PARTIAL".files' EXIT

# ---- 1. database ------------------------------------------------------------------
log "dumping the $TARGET database (pg_dump -Fc)"
ops_exec "$PROJECT" db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' >"$PARTIAL.dump"   || die "pg_dump failed (is the $PROJECT db container running?)"
[ -s "$PARTIAL.dump" ] || die "pg_dump produced an empty file"
log "verifying the dump is readable (pg_restore --list)"
ops_exec "$PROJECT" db pg_restore --list <"$PARTIAL.dump" >/dev/null || die "the dump failed verification"
HASH="$(sha256sum <"$PARTIAL.dump" | cut -c1-12)"
NAME="plasma_${LABEL}_${STAMP}_${HASH}"

# ---- 2. files -----------------------------------------------------------------------
if [ "$WITH_FILES" = "1" ]; then
  log "archiving private-data and data volumes from the backend container"
  status=0
  ops_exec "$PROJECT" backend tar -C /app -czf - private-data data >"$PARTIAL.files" || status=$?
  # tar exits 1 when a file changed while being read; that is a warning, anything else is fatal.
  if [ "$status" -gt 1 ]; then die "tar failed with status $status"; fi
  [ "$status" -eq 0 ] || log "WARN: some files changed while archiving (tar status 1)"
  # Read via stdin: a path such as C:/... would be taken for a remote host by tar on Windows.
  tar -tzf - <"$PARTIAL.files" >/dev/null || die "the files archive failed verification"
fi

# ---- 3. commit the set ----------------------------------------------------------------
mv "$PARTIAL.dump" "$BACKUP_DIR/$NAME.dump"
[ "$WITH_FILES" = "1" ] && mv "$PARTIAL.files" "$BACKUP_DIR/$NAME.files.tar.gz"
(
  cd "$BACKUP_DIR"
  sha256sum "$NAME.dump" >"$NAME.sha256"
  if [ "$WITH_FILES" = "1" ]; then sha256sum "$NAME.files.tar.gz" >>"$NAME.sha256"; fi
  sha256sum -c "$NAME.sha256" >/dev/null
)
log "backup set written: $BACKUP_DIR/$NAME.*"
ls -l "$BACKUP_DIR/$NAME".* | awk '{printf "  %10s bytes  %s\n", $5, $NF}' >&2

# ---- 4. off-host copy -------------------------------------------------------------------
if [ "$UPLOAD" = "1" ]; then
  if [ -n "${BACKUP_REMOTE:-}" ]; then
    case "$BACKUP_REMOTE" in
      s3://*)
        command -v aws >/dev/null 2>&1 || die "BACKUP_REMOTE is an s3:// target but the aws CLI is not installed"
        for f in "$BACKUP_DIR/$NAME".*; do aws s3 cp "$f" "${BACKUP_REMOTE%/}/" --only-show-errors; done ;;
      *)
        command -v rsync >/dev/null 2>&1 || die "rsync is required for BACKUP_REMOTE=$BACKUP_REMOTE"
        rsync -a --partial "$BACKUP_DIR/$NAME".* "$BACKUP_REMOTE" ;;
    esac
    log "copied off-host to $BACKUP_REMOTE"
  else
    log "WARN: BACKUP_REMOTE is not set; this backup exists only on this host (no off-host copy)"
  fi
fi

# ---- 5. retention --------------------------------------------------------------------------
mapfile -t SETS < <(ls -1 "$BACKUP_DIR"/plasma_"${LABEL}"_*.dump 2>/dev/null | sort)
total="${#SETS[@]}"
removed=0
for dump in "${SETS[@]}"; do
  [ $((total - removed)) -gt "$MIN_KEEP" ] || break
  if [ -n "$(find "$dump" -mtime +"$KEEP_DAYS" -print 2>/dev/null)" ]; then
    base="${dump%.dump}"
    rm -f "$dump" "$base.files.tar.gz" "$base.sha256"
    removed=$((removed + 1))
    log "retention: removed $(basename "$base") (older than $KEEP_DAYS days)"
  fi
done
log "done: $((total - removed)) $LABEL backup set(s) kept in $BACKUP_DIR"
