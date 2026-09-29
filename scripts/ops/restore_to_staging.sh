#!/usr/bin/env bash
# Restore the latest production backup set into the isolated STAGING stack.
#
#   scripts/ops/restore_to_staging.sh [--src DIR] [--label prod] [--migrate]
#                                     [--no-files] [--no-start] [--yes]
#
# It can only ever act on the plasma_staging project: it uses the staging compose
# files and .env.staging, and refuses to continue unless the database container
# it is about to wipe carries the label com.docker.compose.project=plasma_staging.
# It REPLACES staging's database and files; production is never contacted.
#
# Steps: (optional) fetch -> pick latest plasma_<label>_*.dump -> verify checksums ->
# stop staging app services -> drop/recreate the staging database -> pg_restore ->
# replace staging's private-data/data volumes from the files archive -> (optional)
# alembic upgrade head (--migrate: rehearse the release's migrations on real data) ->
# (optional) STAGING_POST_RESTORE_SQL -> start the stack.
#
# Environment:
#   BACKUP_SRC_DIR         where backup sets are (default ./backups); --src overrides
#   BACKUP_FETCH_CMD       optional command that pulls production backups into BACKUP_SRC_DIR
#                          first (placeholder, e.g. "rsync -a backup-host:/srv/plasma-backups/ ./backups/")
#   STAGING_POST_RESTORE_SQL  optional SQL file run after the restore (e.g. to neutralize
#                          outbound notification targets or scrub personal data)
#
# Restoring production data into staging copies customer data into staging: keep staging
# access as restricted as production and decide whether to scrub (see PRODUCTION_READINESS.md).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SRC="${BACKUP_SRC_DIR:-$OPS_ROOT/backups}"
LABEL="prod"
MIGRATE=0
WITH_FILES=1
START=1
ASSUME_YES=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --migrate) MIGRATE=1; shift ;;
    --no-files) WITH_FILES=0; shift ;;
    --no-start) START=0; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# A custom compose command could point anywhere; this script only ever uses the staging files.
unset OPS_COMPOSE_CMD
ops_compose_setup staging
targets_staging=0
for ((i = 0; i < ${#COMPOSE[@]} - 1; i++)); do
  if [ "${COMPOSE[$i]}" = "-p" ] && [ "${COMPOSE[$((i + 1))]}" = "$STAGING_PROJECT" ]; then targets_staging=1; fi
done
[ "$targets_staging" = "1" ] || die "refusing to run: the compose command does not target the $STAGING_PROJECT project"

if [ -n "${BACKUP_FETCH_CMD:-}" ]; then
  log "fetching backups: $BACKUP_FETCH_CMD"
  bash -c "$BACKUP_FETCH_CMD"
fi

# ---- pick and verify the latest set --------------------------------------------------------
[ -d "$SRC" ] || die "backup directory not found: $SRC"
DUMP="$(ls -1 "$SRC"/plasma_"${LABEL}"_*.dump 2>/dev/null | sort | tail -n 1 || true)"
[ -n "$DUMP" ] || die "no plasma_${LABEL}_*.dump found in $SRC"
BASE="${DUMP%.dump}"
FILES="$BASE.files.tar.gz"
[ -f "$BASE.sha256" ] || die "missing checksum manifest $(basename "$BASE").sha256"
(cd "$SRC" && sha256sum -c "$(basename "$BASE").sha256" >/dev/null) || die "checksum verification failed for $(basename "$BASE")"
if [ "$WITH_FILES" = "1" ] && [ ! -f "$FILES" ]; then
  die "no files archive for $(basename "$BASE"); use --no-files to restore the database only"
fi
log "latest $LABEL backup: $(basename "$BASE") (checksums OK)"

# ---- make sure we are about to wipe STAGING and nothing else -------------------------------
"${COMPOSE[@]}" up -d db redis >/dev/null
DB_CID="$("${COMPOSE[@]}" ps -q db)"
[ -n "$DB_CID" ] || die "the staging db container is not running"
DB_PROJECT="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$DB_CID")"
DB_NAME="$(docker inspect -f '{{.Name}}' "$DB_CID")"
[ "$DB_PROJECT" = "$STAGING_PROJECT" ] || die "db container $DB_NAME belongs to project '$DB_PROJECT', not $STAGING_PROJECT"
case "$DB_NAME" in */plasma_staging_*) ;; *) die "db container name $DB_NAME is not a staging container" ;; esac

for _ in $(seq 1 30); do
  "${COMPOSE[@]}" exec -T db sh -c 'pg_isready -q -U "$POSTGRES_USER" -d postgres' >/dev/null 2>&1 && break
  sleep 2
done
"${COMPOSE[@]}" exec -T db sh -c 'pg_isready -q -U "$POSTGRES_USER" -d postgres' >/dev/null 2>&1 || die "the staging database did not become ready"

if [ "$ASSUME_YES" != "1" ] && [ "${STAGING_RESTORE_CONFIRM:-}" != "yes" ]; then
  [ -t 0 ] || die "not a terminal: pass --yes (or STAGING_RESTORE_CONFIRM=yes) to confirm"
  printf 'This REPLACES the database and files of %s with %s. Type "staging" to continue: ' "$DB_NAME" "$(basename "$BASE")" >&2
  read -r answer
  [ "$answer" = "staging" ] || die "aborted"
fi

# ---- stop app services that use the database -------------------------------------------------
mapfile -t DEFINED < <("${COMPOSE[@]}" config --services)
APP_SERVICES=()
for service in caddy frontend backend celery_worker worker_heavy worker_private_documents worker_pursuit_analysis celery_beat; do
  for defined in "${DEFINED[@]}"; do
    if [ "$defined" = "$service" ]; then APP_SERVICES+=("$service"); fi
  done
done
log "stopping staging app services: ${APP_SERVICES[*]}"
"${COMPOSE[@]}" stop "${APP_SERVICES[@]}" >/dev/null 2>&1 || true

# ---- database -------------------------------------------------------------------------------------
log "recreating the staging database"
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v db="$POSTGRES_DB"' <<'SQL'
DROP DATABASE IF EXISTS :"db" WITH (FORCE);
CREATE DATABASE :"db";
SQL
log "restoring $(basename "$DUMP") (pg_restore)"
"${COMPOSE[@]}" exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' <"$DUMP"

# ---- files -----------------------------------------------------------------------------------------
if [ "$WITH_FILES" = "1" ]; then
  log "replacing staging private-data and data volumes from $(basename "$FILES")"
  "${COMPOSE[@]}" run --rm --no-deps -T backend sh -c \
    'find /app/private-data /app/data -mindepth 1 -delete 2>/dev/null; tar -xzf - -C /app' <"$FILES"
fi

# ---- migrations and post-restore hook ------------------------------------------------------------------
if [ "$MIGRATE" = "1" ]; then
  log "alembic upgrade head on the restored staging database"
  "${COMPOSE[@]}" run --rm --no-deps -T backend alembic upgrade head
fi
if [ -n "${STAGING_POST_RESTORE_SQL:-}" ]; then
  [ -f "$STAGING_POST_RESTORE_SQL" ] || die "STAGING_POST_RESTORE_SQL not found: $STAGING_POST_RESTORE_SQL"
  log "running post-restore SQL $STAGING_POST_RESTORE_SQL"
  "${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <"$STAGING_POST_RESTORE_SQL"
fi

if [ "$START" = "1" ]; then
  log "starting the staging stack"
  "${COMPOSE[@]}" up -d
fi
log "staging restored from $(basename "$BASE"); next: scripts/ops/smoke.sh --target staging"
