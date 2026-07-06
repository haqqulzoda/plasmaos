#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PLASMA_BUILD_SHA="${PLASMA_BUILD_SHA:-$(git rev-parse HEAD)}"
export PLASMA_BUILD_TIME="${PLASMA_BUILD_TIME:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
export FRONTEND_NEXT_PUBLIC_API_URL="${FRONTEND_NEXT_PUBLIC_API_URL:-/api/v1}"
export BACKEND_INTERNAL_URL="${BACKEND_INTERNAL_URL:-http://backend:8000/api/v1}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  if command -v docker.exe >/dev/null 2>&1; then
    DOCKER_BIN="docker.exe"
  fi
fi
release_env_file="$(mktemp .compose-release.XXXXXX.env)"
trap 'rm -f "$release_env_file"' EXIT
cat >"$release_env_file" <<EOF
PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA
PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME
FRONTEND_NEXT_PUBLIC_API_URL=$FRONTEND_NEXT_PUBLIC_API_URL
BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL
EOF

echo "PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA"
echo "PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME"
echo "FRONTEND_NEXT_PUBLIC_API_URL=$FRONTEND_NEXT_PUBLIC_API_URL"
echo "BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL"

compose_args=(compose)
if [ -f .env ]; then
  compose_args+=(--env-file .env)
fi
if [ -f frontend/.env ]; then
  compose_args+=(--env-file frontend/.env)
fi
compose_args+=(--env-file "$release_env_file")

"$DOCKER_BIN" "${compose_args[@]}" "$@"
