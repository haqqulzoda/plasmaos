#!/usr/bin/env bash
# Read-only Celery Beat memory reading for the deploy runbook. Changes nothing.
#
#   scripts/ops/beat_memory.sh [--target production|staging|local] [--baseline RSS_KB]
#                              [--max-growth PERCENT] [--max-of-limit PERCENT]
#
# Prints one line: celery_beat rss_kb=... limit_kb=... of_limit=...% [baseline_kb=... growth=...%]
# RSS is the Beat process's VmRSS (PID 1 in the container); the limit is the container's
# memory limit (0 = none). Record the line at deploy (no --baseline); at the final step and
# the day after, pass the recorded rss_kb as --baseline.
# Exit status: 0 = within bounds, 1 = growth above --max-growth (default 50) or RSS above
# --max-of-limit of the limit (default 80), 2 = usage error or no running celery_beat.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${OPS_TARGET:-production}"
BASELINE=""
MAX_GROWTH=50
MAX_OF_LIMIT=80

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --baseline) BASELINE="$2"; shift 2 ;;
    --max-growth) MAX_GROWTH="$2"; shift 2 ;;
    --max-of-limit) MAX_OF_LIMIT="$2"; shift 2 ;;
    *) echo "usage: $0 [--target T] [--baseline RSS_KB] [--max-growth P] [--max-of-limit P]" >&2; exit 2 ;;
  esac
done
case "$BASELINE" in ''|*[!0-9]*) [ -z "$BASELINE" ] || { echo "--baseline takes kB (digits)" >&2; exit 2; } ;; esac

PROJECT="$(ops_project "$TARGET")"
cid="$(ops_cid "$PROJECT" celery_beat)"
[ -n "$cid" ] || { echo "no running celery_beat in project $PROJECT" >&2; exit 2; }
rss_kb="$("${_DOCKER[@]}" exec "$cid" sh -c 'grep VmRSS /proc/1/status' 2>/dev/null | tr -dc '0-9')"
limit_bytes="$("${_DOCKER[@]}" inspect -f '{{.HostConfig.Memory}}' "$cid" 2>/dev/null | tr -dc '0-9')"
[ -n "$rss_kb" ] || { echo "cannot read VmRSS of celery_beat" >&2; exit 2; }
limit_kb=$(( ${limit_bytes:-0} / 1024 ))

status=0
line="celery_beat rss_kb=$rss_kb limit_kb=$limit_kb"
if [ "$limit_kb" -gt 0 ]; then
  of_limit=$(( rss_kb * 100 / limit_kb ))
  line="$line of_limit=${of_limit}%"
  [ "$of_limit" -le "$MAX_OF_LIMIT" ] || status=1
fi
if [ -n "$BASELINE" ] && [ "$BASELINE" -gt 0 ]; then
  growth=$(( (rss_kb - BASELINE) * 100 / BASELINE ))
  line="$line baseline_kb=$BASELINE growth=${growth}%"
  [ "$growth" -le "$MAX_GROWTH" ] || status=1
fi
echo "$line"
exit "$status"
