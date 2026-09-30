#!/usr/bin/env bash
# Read-only disk report for a Plasma host. Changes nothing.
#
#   scripts/ops/disk_report.sh [--target production|staging|local] [--threshold PERCENT]
#                              [--path PATH] [--top N]
#
# Prints: filesystem use of PATH (default /) and of Docker's data root, `docker system df`,
# per-volume sizes, SHA-tagged release images (and which are in use), and the largest
# tender-document directories inside the backend container.
# Exit status: 0 = at or below the threshold, 1 = PATH or Docker's data root is above
# --threshold (default DISK_REPORT_THRESHOLD or 85), 2 = usage error.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${OPS_TARGET:-production}"
THRESHOLD="${DISK_REPORT_THRESHOLD:-85}"
DISK_PATH="${DISK_REPORT_PATH:-/}"
TOP=10
RELEASE_IMAGE_PREFIX="${RELEASE_IMAGE_PREFIX:-plasma-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --threshold) THRESHOLD="$2"; shift 2 ;;
    --path) DISK_PATH="$2"; shift 2 ;;
    --top) TOP="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$THRESHOLD$TOP" in *[!0-9]*) echo "--threshold and --top must be whole numbers" >&2; exit 2 ;; esac
PROJECT="$(ops_project "$TARGET")"
D=("${_DOCKER[@]}")

section() { printf '\n== %s\n' "$1"; }
percent_used() { df -P "$1" 2>/dev/null | tail -n 1 | awk '{gsub("%", "", $5); print $5}'; }

over=0
section "filesystem"
df -h "$DISK_PATH"
used="$(percent_used "$DISK_PATH")"
if [ -n "$used" ] && [ "$used" -gt "$THRESHOLD" ]; then over=1; fi
root_dir="$("${D[@]}" info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
if [ -n "$root_dir" ] && [ -d "$root_dir" ]; then
  root_used="$(percent_used "$root_dir")"
  echo "docker data root $root_dir: ${root_used:-?}% used"
  if [ -n "$root_used" ] && [ "$root_used" -gt "$THRESHOLD" ]; then over=1; fi
else
  echo "docker data root ${root_dir:-?} is not visible from this shell (Docker Desktop VM); only $DISK_PATH is checked"
fi

section "docker system df"
"${D[@]}" system df

section "volumes (size)"
"${D[@]}" system df -v 2>/dev/null \
  | awk '/^Local Volumes space usage:/ {on=1; next} /^Build cache usage:/ {on=0} on && NF' \
  | sed -n '1,200p'

section "release images ($RELEASE_IMAGE_PREFIX<service>:<SHA>)"
in_use="$("${D[@]}" ps -aq | xargs -r "${D[@]}" inspect -f '{{.Image}}' 2>/dev/null | sort -u)"
"${D[@]}" images --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}} {{.Size}}' \
  | awk -v p="$RELEASE_IMAGE_PREFIX" 'index($1, p) == 1' \
  | while read -r ref id created_date created_time _zone _abbr size; do
      tag="${ref##*:}"
      [[ "$tag" =~ ^[0-9a-f]{7,40}$ ]] || continue
      mark=""
      if printf '%s\n' "$in_use" | grep -qxF "$id"; then mark="  [in use]"; fi
      printf '%-70s %s %s %8s%s\n' "$ref" "$created_date" "$created_time" "$size" "$mark"
    done | sort -k2,3 -r
echo "SHAs present: $("${D[@]}" images --format '{{.Repository}}:{{.Tag}}' | awk -v p="$RELEASE_IMAGE_PREFIX" 'index($1, p) == 1' | sed 's/.*://' | grep -E '^[0-9a-f]{7,40}$' | sort -u | tr '\n' ' ')"

section "largest tender-document directories (top $TOP, backend container /app/data/documents)"
if ! ops_exec "$PROJECT" backend sh -c "du -sk /app/data/documents/* 2>/dev/null | sort -rn | head -n $TOP; du -sk /app/data /app/private-data 2>/dev/null" </dev/null \
  | awk '{printf "%10.1f MB  %s\n", $1 / 1024, $2}'; then
  echo "(no running backend container for project $PROJECT)"
fi

section "summary"
echo "$DISK_PATH: ${used:-?}% used; threshold ${THRESHOLD}%"
if [ "$over" = "1" ]; then
  echo "ABOVE THRESHOLD: run scripts/ops/prune_safe.sh (dry run) and review before deploying" >&2
  exit 1
fi
echo "OK"
