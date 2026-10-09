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
  value="${value%$'\r'}"   # a file edited on Windows
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
# Beat liveness (smoke.sh): the Redis key a worker refreshes whenever it starts Beat's
# 10-second publish_notifications task, and the largest acceptable age.
BEAT_HEARTBEAT_KEY="plasma:beat:heartbeat"
BEAT_HEARTBEAT_MAX_AGE="${BEAT_HEARTBEAT_MAX_AGE:-60}"

# beat_heartbeat_verdict AGE_SECONDS -> ok | stale | missing  (AGE -1 or empty: no heartbeat)
beat_heartbeat_verdict() {
  local age="${1:-}"
  case "$age" in ''|-*|*[!0-9-]*) echo missing; return ;; esac
  if [ "$age" -lt "$BEAT_HEARTBEAT_MAX_AGE" ]; then echo ok; else echo stale; fi
}

ops_exec() {
  local project="$1" service="$2" cid
  shift 2
  cid="$(ops_cid "$project" "$service")"
  [ -n "$cid" ] || { log "no running container for $project/$service"; return 125; }
  "${_DOCKER[@]}" exec -i "$cid" "$@"
}

# ---- DNS guard (R3) -----------------------------------------------------------------------------
# Docker's embedded DNS can lose a service's records (Deploy 2: db and redis vanished; the running
# app kept its pooled connections, so nothing failed until new containers started). Only a NEW
# container proves resolution, so ops_dns_check starts a one-off container from the image the
# backend runs, on the backend's network (what `compose run --rm --no-deps backend` does, without
# needing the compose files), and resolves db, redis and clamav there.
DNS_REMEDY="docker restart plasma_db plasma_redis plasma_clamav; then restart app services"
OPS_DNS_NAMES="${OPS_DNS_NAMES:-db redis clamav}"

# ops_dns_check PROJECT -> one "name=address" or "name=UNRESOLVED" line per name, then DNS_OK or
# "DNS_FAIL name..."; returns 0 (all resolve), 1 (a name does not resolve) or 2 (cannot check).
ops_dns_check() {
  local project="$1" cid image network out status
  cid="$(ops_cid "$project" backend all)"
  if [ -z "$cid" ]; then echo "DNS_CHECK_UNAVAILABLE no backend container in project $project"; return 2; fi
  image="$("${_DOCKER[@]}" inspect -f '{{.Image}}' "$cid")"
  network="$("${_DOCKER[@]}" inspect -f '{{.HostConfig.NetworkMode}}' "$cid")"
  # shellcheck disable=SC2086
  out="$("${_DOCKER[@]}" run --rm --pull never --network "$network" --memory 128m --oom-score-adj 1000 \
    --label plasma.ops=dns-check --entrypoint python "$image" -c '
import socket, sys
bad = []
for name in sys.argv[1:]:
    try:
        found = sorted({info[4][0] for info in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)})
        print(name + "=" + ",".join(found))
    except OSError as exc:
        bad.append(name)
        print(name + "=UNRESOLVED (" + type(exc).__name__ + ")")
print("DNS_FAIL " + " ".join(bad) if bad else "DNS_OK")
sys.exit(1 if bad else 0)' $OPS_DNS_NAMES 2>&1)"
  status=$?
  printf '%s\n' "$out"
  case "$status" in
    0) return 0 ;;
    1) if printf '%s\n' "$out" | grep -q '^DNS_FAIL'; then return 1; fi ;;
  esac
  echo "DNS_CHECK_UNAVAILABLE the one-off container did not run (status $status)"
  return 2
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
  # Extra staging overlays (rehearsals), e.g. OPS_STAGING_OVERLAYS=deploy/compose/dbredis-before-1b.yml
  if [ "$target" = "staging" ] && [ -n "${OPS_STAGING_OVERLAYS:-}" ]; then
    local overlay
    for overlay in $OPS_STAGING_OVERLAYS; do
      [ -f "$overlay" ] || die "OPS_STAGING_OVERLAYS: $overlay not found"
      COMPOSE+=(-f "$overlay")
    done
  fi
}

# ---- host memory profile ----------------------------------------------------------------------------
# ops_host_profile_file ENV_FILE -> path of deploy/host-profiles/<HOST_PROFILE>.env, or nothing
# when no profile is selected. HOST_PROFILE comes from the environment, else from ENV_FILE.
ops_host_profile_file() {
  local profile="${HOST_PROFILE:-}"
  if [ -z "$profile" ]; then profile="$(env_file_value "$1" HOST_PROFILE || true)"; fi
  [ -n "$profile" ] || return 0
  # Relative to the repository root (ops_compose_setup runs from there): an absolute Git Bash
  # path such as /d/projects/... is not understood by docker.exe on Windows.
  local file="deploy/host-profiles/$profile.env"
  [ -f "$OPS_ROOT/$file" ] || die "HOST_PROFILE=$profile has no deploy/host-profiles/$profile.env (use 4gb or 8gb)"
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
