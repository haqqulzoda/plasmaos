#!/usr/bin/env bash
# Shared helpers for scripts/ops/*. Source it; do not execute it.
# shellcheck shell=bash

OPS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGING_PROJECT="plasma_staging"
# Every docker call goes through this array so Git Bash on Windows does not rewrite
# container paths such as /app (the setting is scoped to docker, not exported globally,
# because native tools like curl need normal path conversion).
_DOCKER=(env MSYS_NO_PATHCONV=1 "MSYS2_ARG_CONV_EXCL=*" docker)

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# python3 that actually runs (on Windows `python3` can be a Store stub).
ops_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0)' >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

# Value of KEY in an env file (last assignment wins; surrounding quotes stripped).
env_file_value() {
  local file="$1" key="$2" value
  [ -f "$file" ] || return 1
  value="$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n 1 | cut -d= -f2- || true)"
  value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
  printf '%s' "$value"
}

# ---- addressing a running stack by its Compose labels -------------------------------------------
# These need no compose files and no environment variables, so they work on any host
# regardless of how the stack was started.

# ops_project TARGET -> Compose project name of that stack.
#   staging     plasma_staging
#   production  PROD_COMPOSE_PROJECT, default: the checkout directory name (Compose's default)
#   local       OPS_LOCAL_PROJECT, default: the checkout directory name
ops_project() {
  local default
  default="$(basename "$OPS_ROOT" | tr '[:upper:]' '[:lower:]')"
  case "$1" in
    staging) echo "$STAGING_PROJECT" ;;
    production) echo "${PROD_COMPOSE_PROJECT:-$default}" ;;
    local) echo "${OPS_LOCAL_PROJECT:-$default}" ;;
    *) die "unknown target '$1' (use local, staging or production)" ;;
  esac
}

# ops_cid PROJECT SERVICE [all]  -> container id (running only, or any state with "all").
# Images built by Compose carry the project/service labels themselves, so a plain
# `docker run <image>` (or a `compose run` one-off) would match the two labels alone.
# Real service containers are the only ones labelled oneoff=False.
ops_cid() {
  local flag=()
  if [ "${3:-}" = "all" ]; then flag=(-a); fi
  "${_DOCKER[@]}" ps ${flag[@]+"${flag[@]}"} -q \
    --filter "label=com.docker.compose.project=$1" \
    --filter "label=com.docker.compose.service=$2" \
    --filter "label=com.docker.compose.oneoff=False" | head -n 1
}

# ops_state PROJECT SERVICE -> running, exited, ... (empty when the container does not exist).
ops_state() {
  local cid
  cid="$(ops_cid "$1" "$2" all)"
  if [ -n "$cid" ]; then "${_DOCKER[@]}" inspect -f '{{.State.Status}}' "$cid"; fi
}

# ops_exec PROJECT SERVICE COMMAND...  -> docker exec -i (stdin/stdout pass through).
ops_exec() {
  local project="$1" service="$2" cid
  shift 2
  cid="$(ops_cid "$project" "$service")"
  [ -n "$cid" ] || { log "no running container for $project/$service"; return 125; }
  "${_DOCKER[@]}" exec -i "$cid" "$@"
}

# ---- driving a stack with Compose (restore and staging management) -----------------------------
# ops_compose_setup TARGET  ->  fills the COMPOSE array; cds to the repo root.
#   local       plain `docker compose` (the developer stack, project from the directory name)
#   staging     isolated project plasma_staging, docker-compose.staging.yml, .env.staging ONLY
#   production  docker-compose.yml with .env (run on the production host)
# OPS_PROXY=1 adds docker-compose.proxy.yml; OPS_COMPOSE_CMD replaces the whole command
# (for example scripts/compose-release.sh on the production host).
ops_compose_setup() {
  local target="$1"
  cd "$OPS_ROOT" || die "cannot enter $OPS_ROOT"
  if [ -n "${OPS_COMPOSE_CMD:-}" ]; then
    read -r -a COMPOSE <<<"$OPS_COMPOSE_CMD"
    return 0
  fi
  case "$target" in
    local) COMPOSE=("${_DOCKER[@]}" compose) ;;
    staging)
      [ -f .env.staging ] || die ".env.staging not found: copy .env.staging.example and fill it in"
      COMPOSE=("${_DOCKER[@]}" compose --env-file .env.staging -p "$STAGING_PROJECT" -f docker-compose.yml -f docker-compose.staging.yml)
      ;;
    production)
      [ -f .env ] || die ".env not found: run this on the production host from the deployed checkout"
      COMPOSE=("${_DOCKER[@]}" compose --env-file .env -f docker-compose.yml)
      ;;
    *) die "unknown target '$target' (use local, staging or production)" ;;
  esac
  # The host memory profile is loaded after the stack's env file, so its values win.
  local profile_file=""
  case "$target" in
    staging) profile_file="$(ops_host_profile_file .env.staging)" || exit 1 ;;
    production) profile_file="$(ops_host_profile_file .env)" || exit 1 ;;
  esac
  if [ -n "$profile_file" ]; then
    COMPOSE+=(--env-file "$profile_file")
  fi
  if [ "${OPS_PROXY:-0}" = "1" ]; then
    COMPOSE+=(-f docker-compose.proxy.yml)
  fi
}

# ---- host memory profile ----------------------------------------------------------------------------
# ops_host_profile_file ENV_FILE -> path of deploy/host-profiles/<HOST_PROFILE>.env, or nothing
# when no profile is selected. HOST_PROFILE comes from the environment, else from ENV_FILE.
ops_host_profile_file() {
  local profile="${HOST_PROFILE:-}"
  if [ -z "$profile" ]; then profile="$(env_file_value "$1" HOST_PROFILE || true)"; fi
  [ -n "$profile" ] || return 0
  local file="$OPS_ROOT/deploy/host-profiles/$profile.env"
  [ -f "$file" ] || die "HOST_PROFILE=$profile has no deploy/host-profiles/$profile.env (use 4gb or 8gb)"
  echo "$file"
}

# Short label used in backup file names.
ops_label() {
  case "$1" in
    production) echo prod ;;
    staging) echo staging ;;
    *) echo local ;;
  esac
}
