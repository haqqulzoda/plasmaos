#!/usr/bin/env bash
# Run Docker Compose against the isolated staging stack.
#
#   scripts/ops/compose-staging.sh [--proxy] up -d --build
#   scripts/ops/compose-staging.sh ps
#   scripts/ops/compose-staging.sh --profile tools up -d pgadmin
#
# Always uses project plasma_staging, docker-compose.staging.yml and .env.staging
# (never .env). Before anything that creates or starts containers it runs
# verify_staging_isolation.py; set OPS_SKIP_ISOLATION_CHECK=1 to skip (not advised).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "${1:-}" = "--proxy" ]; then
  export OPS_PROXY=1
  shift
fi
[ "$#" -gt 0 ] || die "usage: compose-staging.sh [--proxy] <docker compose arguments>"
ops_compose_setup staging

export PLASMA_BUILD_SHA="${PLASMA_BUILD_SHA:-$(git -C "$OPS_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)}"
export PLASMA_BUILD_TIME="${PLASMA_BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

case " $* " in
  *" up "*|*" create "*|*" start "*|*" restart "*|*" run "*|*" build "*)
    if [ "${OPS_SKIP_ISOLATION_CHECK:-0}" != "1" ]; then
      py="$(ops_python)" || die "python3 is required for the isolation check (or set OPS_SKIP_ISOLATION_CHECK=1)"
      proxy_flag=()
      if [ "${OPS_PROXY:-0}" = "1" ]; then proxy_flag=(--with-proxy); fi
      "$py" "$OPS_ROOT/scripts/ops/verify_staging_isolation.py" ${proxy_flag[@]+"${proxy_flag[@]}"} >&2
    fi
    ;;
esac

log "staging: ${COMPOSE[*]} $*"
exec "${COMPOSE[@]}" "$@"
