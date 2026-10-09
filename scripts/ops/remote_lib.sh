#!/usr/bin/env bash
# Off-host backup targets for scripts/ops/backup.sh and restore_drill.sh. Source it after lib.sh.
# shellcheck shell=bash
#
# remote_setup REMOTE   sets REMOTE_KIND (ssh|file|s3|rclone), RPATH and REMOTE_DESC; REMOTE is one of
#   ssh://user@host[:port]/path   e.g. Hetzner Storage Box: ssh://u123456@u123456.your-storagebox.de:23/./plasma
#   user@host:/path               ssh on BACKUP_SSH_PORT (default 22)
#   s3://bucket/prefix            aws CLI (AWS_* credentials; AWS_ENDPOINT_URL for S3-compatible storage)
#   rclone:remote:path            rclone (configured remote)
#   r2://bucket/prefix            Cloudflare R2 (any S3-compatible store) configured only from the environment:
#                                   BACKUP_S3_ENDPOINT          https://<account id>.r2.cloudflarestorage.com
#                                   BACKUP_S3_ACCESS_KEY_ID / BACKUP_S3_SECRET_ACCESS_KEY  (an R2 API token)
#                                   BACKUP_S3_REGION            default auto
#                                   BACKUP_S3_TOOL              rclone | aws (default: rclone if installed, else aws)
#                                 The bucket may also come from BACKUP_S3_BUCKET (then r2:///prefix).
#                                 Nothing secret is put on a command line; the endpoint, bucket and keys
#                                 are replaced by <endpoint>, <bucket>, <secret> in everything printed.
#   file:///path                  a mounted remote file system (or a local test target)
# remote_put NAME < data, remote_commit NAME, remote_get NAME > data, remote_hash NAME,
# remote_size NAME, remote_list, remote_rm NAME...  act on "$RPATH/NAME".

remote_setup() {
  local remote="$1" rest hostpart bucket prefix tool
  case "$remote" in
    ssh://*)
      rest="${remote#ssh://}"
      hostpart="${rest%%/*}"; RPATH="/${rest#*/}"
      [ "$rest" != "$hostpart" ] || die "BACKUP_REMOTE=ssh://user@host[:port]/path needs a path"
      SSH_DEST="${hostpart%%:*}"; SSH_PORT=22
      [ "$hostpart" = "$SSH_DEST" ] || SSH_PORT="${hostpart##*:}"
      # ssh://host/./dir means "dir relative to the login directory" (Storage Box style).
      case "$RPATH" in /./*) RPATH="${RPATH#/./}" ;; esac
      REMOTE_KIND=ssh; REMOTE_DESC="$remote" ;;
    s3://*) REMOTE_KIND=s3; RPATH="${remote%/}"; REMOTE_DESC="$RPATH" ;;
    rclone:*) REMOTE_KIND=rclone; RPATH="${remote#rclone:}"; RPATH="${RPATH%/}"; REMOTE_DESC="$remote" ;;
    r2://*)
      rest="${remote#r2://}"; rest="${rest%/}"
      bucket="${rest%%/*}"; prefix=""
      [ "$rest" = "$bucket" ] || prefix="${rest#*/}"
      bucket="${bucket:-${BACKUP_S3_BUCKET:-}}"
      [ -n "$bucket" ] || die "BACKUP_REMOTE=r2://bucket/prefix (or r2:///prefix with BACKUP_S3_BUCKET) needs a bucket"
      [ -n "${BACKUP_S3_ENDPOINT:-}" ] || die "BACKUP_S3_ENDPOINT is not set (https://<account id>.r2.cloudflarestorage.com)"
      [ -n "${BACKUP_S3_ACCESS_KEY_ID:-}" ] && [ -n "${BACKUP_S3_SECRET_ACCESS_KEY:-}" ] \
        || die "BACKUP_S3_ACCESS_KEY_ID and BACKUP_S3_SECRET_ACCESS_KEY must be set"
      BACKUP_S3_BUCKET="$bucket"
      tool="${BACKUP_S3_TOOL:-}"
      if [ -z "$tool" ]; then
        if command -v rclone >/dev/null 2>&1; then tool=rclone; else tool=aws; fi
      fi
      case "$tool" in
        rclone)
          # An on-the-fly rclone remote named "plasmar2", defined only in this process's environment.
          export RCLONE_CONFIG_PLASMAR2_TYPE=s3 RCLONE_CONFIG_PLASMAR2_PROVIDER="${BACKUP_S3_PROVIDER:-Cloudflare}"
          export RCLONE_CONFIG_PLASMAR2_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID"
          export RCLONE_CONFIG_PLASMAR2_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY"
          export RCLONE_CONFIG_PLASMAR2_ENDPOINT="$BACKUP_S3_ENDPOINT"
          export RCLONE_CONFIG_PLASMAR2_REGION="${BACKUP_S3_REGION:-auto}"
          export RCLONE_CONFIG_PLASMAR2_NO_CHECK_BUCKET=true
          REMOTE_KIND=rclone; RPATH="plasmar2:$bucket${prefix:+/$prefix}" ;;
        aws)
          export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY"
          export AWS_ENDPOINT_URL="$BACKUP_S3_ENDPOINT" AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-auto}"
          # R2 does not implement the newer default checksums of recent aws CLI versions.
          export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
          unset AWS_PROFILE
          REMOTE_KIND=s3; RPATH="s3://$bucket${prefix:+/$prefix}" ;;
        *) die "BACKUP_S3_TOOL must be rclone or aws" ;;
      esac
      REMOTE_DESC="r2:<bucket>${prefix:+/$prefix} via $tool (endpoint, bucket and keys from the environment)"
      redact_output ;;
    file://*) REMOTE_KIND=file; RPATH="${remote#file://}"; RPATH="${RPATH%/}"; REMOTE_DESC="$remote" ;;
    *:*)
      REMOTE_KIND=ssh; SSH_DEST="${remote%%:*}"; RPATH="${remote#*:}"; RPATH="${RPATH%/}"
      SSH_PORT="${BACKUP_SSH_PORT:-22}"; REMOTE_DESC="$remote" ;;
    *) die "unsupported BACKUP_REMOTE=$remote (see scripts/ops/remote_lib.sh)" ;;
  esac
  SSH_WRITE="${BACKUP_SSH_WRITE:-dd of=%s bs=1M}"
}

# remote_subdir DIR: every following operation acts on "$RPATH/DIR" (backup tiers).
remote_subdir() {
  RPATH="$RPATH/$1"
  case "$REMOTE_DESC" in
    *" via "*) REMOTE_DESC="${REMOTE_DESC%% via *}/$1 via ${REMOTE_DESC#* via }" ;;
    *) REMOTE_DESC="$REMOTE_DESC/$1" ;;
  esac
}

# Everything this process prints to stderr from now on has the R2 endpoint, bucket and keys masked
# (tools print URLs and bucket names in their errors).
redact_line() {
  local line="$1" secret
  for secret in "${BACKUP_S3_SECRET_ACCESS_KEY:-}" "${BACKUP_S3_ACCESS_KEY_ID:-}"; do
    [ -n "$secret" ] && line="${line//"$secret"/<secret>}"
  done
  [ -n "${BACKUP_S3_ENDPOINT:-}" ] && line="${line//"${BACKUP_S3_ENDPOINT#*://}"/<endpoint>}"
  [ -n "${BACKUP_S3_BUCKET:-}" ] && line="${line//"$BACKUP_S3_BUCKET"/<bucket>}"
  printf '%s\n' "$line"
}
redact_output() {
  [ "${_REDACTING:-0}" = "1" ] && return 0
  _REDACTING=1
  exec 2> >(while IFS= read -r line || [ -n "$line" ]; do redact_line "$line"; done >&2)
}

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
    s3) command -v aws >/dev/null 2>&1 || die "the backup target needs the aws CLI, which is not installed" ;;
    rclone) command -v rclone >/dev/null 2>&1 || die "the backup target needs rclone, which is not installed" ;;
  esac
}

# remote_put NAME < data  -> writes NAME (via NAME.partial where the remote can rename)
remote_put() {
  local name="$1"
  case "$REMOTE_KIND" in
    # shellcheck disable=SC2059
    ssh) rssh_stdin "$(printf "$SSH_WRITE" "$(rq "$RPATH/$name.partial")")" 2>>"${REMOTE_ERR:-/dev/stderr}" ;;
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
remote_get() {  # remote_get NAME > data
  local name="$1"
  case "$REMOTE_KIND" in
    ssh) rssh "cat $(rq "$RPATH/$name")" ;;
    file) cat "$RPATH/$name" ;;
    s3) aws s3 cp "$RPATH/$name" - --only-show-errors ;;
    rclone) rclone cat "$RPATH/$name" ;;
  esac
}
remote_hash() {  # remote_hash NAME -> sha256 of the remote object, empty if the remote cannot tell
  local name="$1"
  case "$REMOTE_KIND" in
    ssh) rssh "sha256sum $(rq "$RPATH/$name")" | cut -c1-64 ;;
    file) sha256sum <"$RPATH/$name" | cut -c1-64 ;;
    s3|rclone) if [ "${BACKUP_VERIFY_DOWNLOAD:-0}" = "1" ]; then remote_get "$name" | sha256sum | cut -c1-64; fi ;;
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
    file) wc -c <"$RPATH/$name" | tr -d ' ' ;;
    ssh) rssh "wc -c < $(rq "$RPATH/$name")" | tr -d ' ' ;;
  esac
}
remote_list() {  # names in the remote directory
  case "$REMOTE_KIND" in
    ssh) rssh "ls -1 $(rq "$RPATH")" ;;
    file) ls -1 "$RPATH" ;;
    s3) aws s3 ls "$RPATH/" | awk '$1 != "PRE" {print $4}' ;;
    rclone) rclone lsf --files-only "$RPATH" ;;
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

# remote_latest_set LABEL -> name of the newest complete set (one with a .manifest), or nothing
remote_latest_set() {
  remote_list | grep "^plasma_$1_[0-9]\{8\}T[0-9]\{6\}Z_[0-9a-f]*\.manifest$" | sort | tail -n 1 | sed 's/\.manifest$//'
}
