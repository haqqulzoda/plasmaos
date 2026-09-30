#!/usr/bin/env bash
# Off-host backup of PostgreSQL, private documents and (optionally) tender documents.
#
#   scripts/ops/backup.sh [--target production|staging|local] [--skip-tender-documents]
#                         [--dir DIR] [--keep-days N] [--local]
#
# Every run sends off-host (BACKUP_REMOTE), as one set named plasma_<label>_<UTC>_<hash12>:
#   .dump             pg_dump -Fc, verified with pg_restore --list        (always)
#   .private.tar.gz   /app/private-data of the backend container          (always)
#   .tender.tar.gz    /app/data (tender documents; public, re-acquirable) (unless --skip-tender-documents)
#   .sha256           sha256sum-compatible checksums of the components
#   .manifest         sizes, checksums, source commit; uploaded last, it marks the set complete
#
# Local disk: only the database dump is written locally (BACKUP_DIR, default ./backups;
# about the size of the dump, and kept for BACKUP_LOCAL_KEEP_DAYS as a fast restore point).
# The document archives are streamed from the container straight to the remote: while
# streaming, the bytes are hashed, counted and gzip/tar-verified through local FIFOs,
# never stored. After each upload the remote copy is checked (SHA-256 on ssh/file
# remotes; size on s3/rclone, or SHA-256 by re-download with BACKUP_VERIFY_DOWNLOAD=1).
#
# BACKUP_REMOTE (required; the script refuses to run without it unless --local):
#   ssh://user@host[:port]/path   e.g. Hetzner Storage Box: ssh://u123456@u123456.your-storagebox.de:23/./plasma
#   user@host:/path               ssh on BACKUP_SSH_PORT (default 22)
#   s3://bucket/prefix            aws CLI (AWS_* credentials; AWS_ENDPOINT_URL for S3-compatible storage)
#   rclone:remote:path            rclone (configured remote)
#   file:///path                  a mounted remote file system (or a local test target)
# BACKUP_SSH_OPTS adds ssh options (e.g. "-i /root/.ssh/backup_ed25519"). The ssh remote
# only runs mkdir, ls, rm, mv, sha256sum and dd, which Hetzner Storage Box's restricted
# shell allows; override the writer with BACKUP_SSH_WRITE (default: dd of=%s bs=1M).
#
# --local (development only): no BACKUP_REMOTE; the whole set is written to BACKUP_DIR.
#
# Retention on the remote: complete sets older than BACKUP_KEEP_DAYS (default 14) are
# deleted, but the newest BACKUP_MIN_KEEP (default 3) complete sets are always kept;
# tender archives beyond the newest BACKUP_TENDER_KEEP (default 2) are deleted (their
# sets keep the database and private documents); incomplete sets older than a day are
# removed. Local dumps older than BACKUP_LOCAL_KEEP_DAYS (default 7) are deleted, keeping 3.
#
# The last line is machine-readable: BACKUP_RESULT set=... seconds=... bytes=... remote=...
# The stack is addressed by its Compose labels (production = PROD_COMPOSE_PROJECT or the
# checkout directory name, staging = plasma_staging, local = OPS_LOCAL_PROJECT or the
# directory name). Redis is not backed up (see docs/ops/PRODUCTION_READINESS.md).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${OPS_TARGET:-production}"
BACKUP_DIR="${BACKUP_DIR:-$OPS_ROOT/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
MIN_KEEP="${BACKUP_MIN_KEEP:-3}"
TENDER_KEEP="${BACKUP_TENDER_KEEP:-2}"
LOCAL_KEEP_DAYS="${BACKUP_LOCAL_KEEP_DAYS:-7}"
WITH_TENDER=1
LOCAL_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --dir) BACKUP_DIR="$2"; shift 2 ;;
    --keep-days) KEEP_DAYS="$2"; shift 2 ;;
    --skip-tender-documents) WITH_TENDER=0; shift ;;
    --local) LOCAL_ONLY=1; shift ;;
    --no-files|--no-upload) die "$1 was removed: every backup sends the database and private documents off-host (use --skip-tender-documents, or --local for development)" ;;
    -h|--help) sed -n '2,44p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
case "$KEEP_DAYS$MIN_KEEP$TENDER_KEEP$LOCAL_KEEP_DAYS" in *[!0-9]*) die "retention settings must be whole numbers" ;; esac

umask 077
STARTED=$SECONDS
PROJECT="$(ops_project "$TARGET")"
LABEL="$(ops_label "$TARGET")"
mkdir -p "$BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

# ---- remote addressing ------------------------------------------------------------------------
if [ "$LOCAL_ONLY" = "1" ]; then
  [ "$TARGET" != "production" ] || die "--local is for development only; production backups must go off-host"
  REMOTE_KIND=file; RPATH="$BACKUP_DIR"; REMOTE_DESC="local:$BACKUP_DIR (NOT off-host)"
else
  [ -n "${BACKUP_REMOTE:-}" ] || die "BACKUP_REMOTE is not set: backups must go off-host (see the header; --local for development only)"
  case "$BACKUP_REMOTE" in
    ssh://*)
      rest="${BACKUP_REMOTE#ssh://}"
      hostpart="${rest%%/*}"; RPATH="/${rest#*/}"
      [ "$rest" != "$hostpart" ] || die "BACKUP_REMOTE=ssh://user@host[:port]/path needs a path"
      SSH_DEST="${hostpart%%:*}"; SSH_PORT=22
      [ "$hostpart" = "$SSH_DEST" ] || SSH_PORT="${hostpart##*:}"
      # ssh://host/./dir means "dir relative to the login directory" (Storage Box style).
      case "$RPATH" in /./*) RPATH="${RPATH#/./}" ;; esac
      REMOTE_KIND=ssh ;;
    s3://*) REMOTE_KIND=s3; RPATH="${BACKUP_REMOTE%/}" ;;
    rclone:*) REMOTE_KIND=rclone; RPATH="${BACKUP_REMOTE#rclone:}"; RPATH="${RPATH%/}" ;;
    file://*) REMOTE_KIND=file; RPATH="${BACKUP_REMOTE#file://}"; RPATH="${RPATH%/}" ;;
    *:*)
      REMOTE_KIND=ssh; SSH_DEST="${BACKUP_REMOTE%%:*}"; RPATH="${BACKUP_REMOTE#*:}"; RPATH="${RPATH%/}"
      SSH_PORT="${BACKUP_SSH_PORT:-22}" ;;
    *) die "unsupported BACKUP_REMOTE=$BACKUP_REMOTE (see the header)" ;;
  esac
  REMOTE_DESC="$BACKUP_REMOTE"
fi
SSH_WRITE="${BACKUP_SSH_WRITE:-dd of=%s bs=1M}"

rssh_stdin() {  # rssh_stdin COMMAND < data  -> run one command on the ssh remote, feeding it stdin
  # shellcheck disable=SC2086
  ssh -p "$SSH_PORT" -o BatchMode=yes ${BACKUP_SSH_OPTS:-} "$SSH_DEST" "$1"
}
rssh() { rssh_stdin "$1" </dev/null; }
rq() { printf "'%s'" "$1"; }   # quote a path for the remote shell (paths never contain ')

remote_prepare() {
  case "$REMOTE_KIND" in
    ssh) rssh "mkdir -p $(rq "$RPATH")" ;;
    file) mkdir -p "$RPATH" ;;
    s3) command -v aws >/dev/null 2>&1 || die "BACKUP_REMOTE is s3:// but the aws CLI is not installed" ;;
    rclone) command -v rclone >/dev/null 2>&1 || die "BACKUP_REMOTE is rclone: but rclone is not installed" ;;
  esac
}

# remote_put NAME < data  -> writes NAME (via NAME.partial where the remote can rename)
remote_put() {
  local name="$1"
  case "$REMOTE_KIND" in
    # shellcheck disable=SC2059
    ssh) rssh_stdin "$(printf "$SSH_WRITE" "$(rq "$RPATH/$name.partial")")" 2>>"$WORK/remote.err" ;;
    file) cat >"$RPATH/$name.partial" ;;
    s3) aws s3 cp - "$RPATH/$name" --only-show-errors ;;
    rclone) rclone rcat "$RPATH/$name" ;;
  esac
}
remote_commit() {  # NAME.partial -> NAME
  local name="$1"
  case "$REMOTE_KIND" in
    ssh) rssh "mv $(rq "$RPATH/$name.partial") $(rq "$RPATH/$name")" ;;
    file) mv "$RPATH/$name.partial" "$RPATH/$name" ;;
    *) : ;;
  esac
}
remote_hash() {  # remote_hash NAME -> sha256 of the remote object, empty if the remote cannot tell
  local name="$1"
  case "$REMOTE_KIND" in
    ssh) rssh "sha256sum $(rq "$RPATH/$name")" | cut -c1-64 ;;
    file) sha256sum <"$RPATH/$name" | cut -c1-64 ;;
    s3) if [ "${BACKUP_VERIFY_DOWNLOAD:-0}" = "1" ]; then aws s3 cp "$RPATH/$name" - --only-show-errors | sha256sum | cut -c1-64; fi ;;
    rclone) if [ "${BACKUP_VERIFY_DOWNLOAD:-0}" = "1" ]; then rclone cat "$RPATH/$name" | sha256sum | cut -c1-64; fi ;;
  esac
}
remote_size() {  # remote_size NAME -> byte size of the remote object
  local name="$1" path bucket prefix=""
  case "$REMOTE_KIND" in
    s3)
      path="${RPATH#s3://}"; bucket="${path%%/*}"
      if [ "$path" != "$bucket" ]; then prefix="${path#*/}/"; fi
      aws s3api head-object --bucket "$bucket" --key "$prefix$name" --query ContentLength --output text ;;
    rclone) rclone lsjson "$RPATH/$name" | sed -n 's/.*"Size":\([0-9]*\).*/\1/p' | head -n 1 ;;
  esac
}
remote_list() {  # names in the remote directory
  case "$REMOTE_KIND" in
    ssh) rssh "ls -1 $(rq "$RPATH")" ;;
    file) ls -1 "$RPATH" ;;
    s3) aws s3 ls "$RPATH/" | awk '{print $4}' ;;
    rclone) rclone lsf "$RPATH" ;;
  esac
}
remote_rm() {  # remote_rm NAME...
  [ "$#" -gt 0 ] || return 0
  local name quoted=""
  case "$REMOTE_KIND" in
    ssh) for name in "$@"; do quoted="$quoted $(rq "$RPATH/$name")"; done; rssh "rm -f$quoted" ;;
    file) for name in "$@"; do rm -f "$RPATH/$name"; done ;;
    s3) for name in "$@"; do aws s3 rm "$RPATH/$name" --only-show-errors; done ;;
    rclone) for name in "$@"; do rclone deletefile "$RPATH/$name"; done ;;
  esac
}

# send NAME KIND < data : stream to the remote while hashing, counting and (KIND=tgz)
# verifying the gzip/tar stream; then verify the remote copy. KIND=meta files (checksums,
# manifest) are not listed as components. May run in a pipeline subshell, so results go
# to files in $WORK, not shell variables.
send() {
  local name="$1" kind="$2" p_hash p_size p_test="" status
  rm -f "$WORK"/*.fifo
  mkfifo "$WORK/hash.fifo" "$WORK/size.fifo" "$WORK/test.fifo"
  sha256sum <"$WORK/hash.fifo" | cut -c1-64 >"$WORK/$name.sha" & p_hash=$!
  wc -c <"$WORK/size.fifo" | tr -d ' ' >"$WORK/$name.bytes" & p_size=$!
  if [ "$kind" = "tgz" ]; then
    # gzip -dc checks the CRC; tar -t checks the archive structure; cat drains what tar leaves.
    ( set -o pipefail; gzip -dc <"$WORK/test.fifo" | { tar -tf - >/dev/null && cat >/dev/null; } ) 2>"$WORK/$name.test" & p_test=$!
  else
    cat <"$WORK/test.fifo" >/dev/null & p_test=$!
  fi
  status=0
  tee "$WORK/hash.fifo" "$WORK/size.fifo" "$WORK/test.fifo" | remote_put "$name" || status=$?
  wait "$p_hash" || status=1
  wait "$p_size" || status=1
  local tested=0
  wait "$p_test" || tested=1
  if [ "$tested" != "0" ] || [ "$status" != "0" ]; then
    # Never leave a partial or unverified object behind (s3/rclone write the final name).
    remote_rm "$name.partial" "$name" >/dev/null 2>&1 || true
    [ "$tested" = "0" ] || die "$name: the stream failed gzip/tar verification ($(tr '\n' ' ' <"$WORK/$name.test"))"
    die "$name: upload to $REMOTE_DESC failed ($(tail -n 3 "$WORK/remote.err" 2>/dev/null | tr '\n' ' '))"
  fi
  SENT_SHA="$(cat "$WORK/$name.sha")"; SENT_BYTES="$(cat "$WORK/$name.bytes")"
  remote_commit "$name"
  local remote_sha
  remote_sha="$(remote_hash "$name" || true)"
  if [ -n "$remote_sha" ]; then
    if [ "$remote_sha" != "$SENT_SHA" ]; then
      remote_rm "$name" || true
      die "$name: remote checksum $remote_sha does not match the sent $SENT_SHA (remote copy deleted)"
    fi
    log "  $name: $SENT_BYTES bytes, remote sha256 verified"
  else
    [ "$(remote_size "$name")" = "$SENT_BYTES" ] || die "$name: remote size does not match the $SENT_BYTES bytes sent"
    log "  $name: $SENT_BYTES bytes, remote size verified (BACKUP_VERIFY_DOWNLOAD=1 re-hashes it)"
  fi
  if [ "$kind" != "meta" ]; then
    printf '%s  %s\n' "$SENT_SHA" "$name" >>"$WORK/set.sha256"
    printf '%s %s %s\n' "$name" "$SENT_BYTES" "$SENT_SHA" >>"$WORK/set.components"
  fi
}

# archive NAME DIR : tar DIR (relative to /app) in the backend container and send it.
archive() {
  local name="$1" dir="$2" status
  set +e
  ops_exec "$PROJECT" backend tar -C /app -czf - "$dir" </dev/null 2>"$WORK/tar.err" | send "$name" tgz
  status=("${PIPESTATUS[@]}")
  set -e
  [ "${status[1]}" = "0" ] || exit "${status[1]}"   # send already logged why
  # tar exits 1 when a file changed while being read (a warning); anything else is fatal.
  if [ "${status[0]}" -gt 1 ]; then die "tar of /app/$dir failed with status ${status[0]}: $(tail -n 3 "$WORK/tar.err" | tr '\n' ' ')"; fi
  [ "${status[0]}" -eq 0 ] || log "WARN: some files in /app/$dir changed while archiving (tar status 1)"
}

# ---- one run at a time -------------------------------------------------------------------------
if command -v flock >/dev/null 2>&1; then
  exec 9>"$BACKUP_DIR/.backup.lock"
  flock -n 9 || die "another backup is running (lock $BACKUP_DIR/.backup.lock)"
fi
WORK="$(mktemp -d "$BACKUP_DIR/.work.XXXXXX")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PARTIAL="$BACKUP_DIR/.partial_${LABEL}_${STAMP}_$$.dump"
trap 'rm -rf "$WORK" "$PARTIAL"' EXIT
remote_prepare

# ---- 1. database (the only component written to local disk) -------------------------------------
log "dumping the $TARGET database (pg_dump -Fc)"
ops_exec "$PROJECT" db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' </dev/null >"$PARTIAL" \
  || die "pg_dump failed (is the $PROJECT db container running?)"
[ -s "$PARTIAL" ] || die "pg_dump produced an empty file"
# pg_restore --list stops after the table of contents; drain the rest so `docker exec -i`
# does not fail writing stdin to a process that has already exited.
ops_exec "$PROJECT" db sh -c 'pg_restore --list >/dev/null && cat >/dev/null' <"$PARTIAL" \
  || die "the dump failed verification (pg_restore --list)"
NAME="plasma_${LABEL}_${STAMP}_$(sha256sum <"$PARTIAL" | cut -c1-12)"
log "sending set $NAME to $REMOTE_DESC"
send "$NAME.dump" raw <"$PARTIAL"
if [ "$REMOTE_KIND" = "file" ] && [ "$RPATH" = "$BACKUP_DIR" ]; then
  rm -f "$PARTIAL"                                  # --local: the remote copy is the local copy
else
  mv "$PARTIAL" "$BACKUP_DIR/$NAME.dump"           # fast local restore point
fi

# ---- 2. documents (streamed, never stored locally) ---------------------------------------------------
archive "$NAME.private.tar.gz" private-data
if [ "$WITH_TENDER" = "1" ]; then
  archive "$NAME.tender.tar.gz" data
else
  log "  tender documents skipped (--skip-tender-documents)"
fi

# ---- 3. checksums and manifest (the manifest marks the set complete) ----------------------------------
send "$NAME.sha256" meta <"$WORK/set.sha256"
{
  echo "set=$NAME"
  echo "created_utc=$STAMP"
  echo "target=$TARGET"
  echo "source_commit=$(git -C "$OPS_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "tender_documents=$([ "$WITH_TENDER" = "1" ] && echo included || echo skipped)"
  echo "# component bytes sha256"
  cat "$WORK/set.components"
} >"$WORK/set.manifest"
send "$NAME.manifest" meta <"$WORK/set.manifest"
if [ "$REMOTE_KIND" = "file" ] && [ "$RPATH" = "$BACKUP_DIR" ]; then :; else
  cp "$WORK/set.sha256" "$BACKUP_DIR/$NAME.sha256"
fi

# ---- 4. retention ----------------------------------------------------------------------------------------
CUTOFF="$(date -u -d "-$KEEP_DAYS days" +%Y%m%dT%H%M%SZ 2>/dev/null || date -u -v-"$KEEP_DAYS"d +%Y%m%dT%H%M%SZ)"
DAY_AGO="$(date -u -d "-1 day" +%Y%m%dT%H%M%SZ 2>/dev/null || date -u -v-1d +%Y%m%dT%H%M%SZ)"
mapfile -t REMOTE_NAMES < <(remote_list | grep "^plasma_${LABEL}_[0-9]\{8\}T[0-9]\{6\}Z_" | sort || true)
mapfile -t SETS < <(printf '%s\n' "${REMOTE_NAMES[@]}" | sed -n 's/^\(plasma_[a-z]*_[0-9T]*Z_[0-9a-f]*\)\..*/\1/p' | sort -u)
has() { printf '%s\n' "${REMOTE_NAMES[@]}" | grep -qxF "$1"; }
COMPLETE=(); for set in "${SETS[@]}"; do if has "$set.manifest"; then COMPLETE+=("$set"); fi; done
stamp_of() { echo "$1" | sed 's/^plasma_[a-z]*_\([0-9T]*Z\)_.*/\1/'; }
doomed=()
for set in "${SETS[@]}"; do
  if ! has "$set.manifest" && [ "$(stamp_of "$set")" \< "$DAY_AGO" ]; then
    for n in "${REMOTE_NAMES[@]}"; do case "$n" in "$set".*) doomed+=("$n") ;; esac; done
    log "retention: removing incomplete set $set"
  fi
done
count="${#COMPLETE[@]}"
for ((i = 0; i < count; i++)); do
  set="${COMPLETE[$i]}"
  [ $((count - i)) -gt "$MIN_KEEP" ] || break
  if [ "$(stamp_of "$set")" \< "$CUTOFF" ]; then
    for n in "${REMOTE_NAMES[@]}"; do case "$n" in "$set".*) doomed+=("$n") ;; esac; done
    log "retention: removing $set (older than $KEEP_DAYS days)"
  fi
done
mapfile -t TENDERS < <(printf '%s\n' "${REMOTE_NAMES[@]}" | grep '\.tender\.tar\.gz$' | sort -r || true)
for ((i = TENDER_KEEP; i < ${#TENDERS[@]}; i++)); do
  doomed+=("${TENDERS[$i]}")
  log "retention: removing tender archive ${TENDERS[$i]} (keeping the newest $TENDER_KEEP)"
done
if [ "${#doomed[@]}" -gt 0 ]; then
  mapfile -t doomed < <(printf '%s\n' "${doomed[@]}" | sort -u)
  remote_rm "${doomed[@]}"
fi
if [ "$REMOTE_KIND" != "file" ] || [ "$RPATH" != "$BACKUP_DIR" ]; then
  mapfile -t LOCAL < <(ls -1 "$BACKUP_DIR"/plasma_"${LABEL}"_*.dump 2>/dev/null | sort || true)
  for ((i = 0; i < ${#LOCAL[@]}; i++)); do
    [ $((${#LOCAL[@]} - i)) -gt 3 ] || break
    if [ -n "$(find "${LOCAL[$i]}" -mtime +"$LOCAL_KEEP_DAYS" -print 2>/dev/null)" ]; then
      base="${LOCAL[$i]%.dump}"
      rm -f "$base".*
      log "retention: removed local copy $(basename "$base") (older than $LOCAL_KEEP_DAYS days)"
    fi
  done
fi

SECONDS_TAKEN=$((SECONDS - STARTED))
TOTAL_BYTES="$(awk '{sum += $2} END {print sum + 0}' "$WORK/set.components")"
log "done: set $NAME, $TOTAL_BYTES bytes to $REMOTE_DESC in ${SECONDS_TAKEN} s; $((count)) complete set(s) on the remote before retention"
echo "BACKUP_RESULT set=$NAME seconds=$SECONDS_TAKEN bytes=$TOTAL_BYTES tender_documents=$([ "$WITH_TENDER" = "1" ] && echo included || echo skipped) remote=$REMOTE_DESC"
