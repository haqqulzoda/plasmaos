#!/usr/bin/env bash
# Release wrapper around `docker compose`.
#
#   scripts/compose-release.sh <compose args>        e.g. build, config --quiet, ps, up -d --no-deps --no-build clamav
#   scripts/compose-release.sh build-only [SVC...]   build and tag plasma-<service>:<SHA>; starts nothing
#   scripts/compose-release.sh export <SHA> [SVC...] write plasma-<service>:<SHA> images to stdout (docker save | gzip)
#   scripts/compose-release.sh import [--expect SHA] load images from stdin (docker load); --expect checks every service
#   scripts/compose-release.sh use <SHA>             point every <project>-<service>:latest at plasma-<service>:<SHA>;
#                                                    restarts nothing (run migrations with the new image, then `up`)
#   scripts/compose-release.sh up <SHA> [ARGS...]    `use <SHA>`, then `up -d --no-build [ARGS...]`
#                                                    (e.g. `up <SHA> --no-deps backend` for an ordered restart)
#   scripts/compose-release.sh rollback <SHA>        same as `up <SHA>` for every service
#   scripts/compose-release.sh tag [SHA]             tag the current images with their build SHA (SHA is
#                                                    used only for images that do not record one)
#   scripts/compose-release.sh images                list the SHA-tagged release images on this host
#
# Compose builds <project>-<service>:latest. After any successful command that builds
# (`build`, `build-only`, `up --build`), every built image is also tagged
# plasma-<service>:<SHA>, with the SHA read from the image's own PLASMA_BUILD_SHA, so a
# release (or rollback) is a tag switch.
#
# Building off the production host (production has no spare memory or disk for builds):
#   build host:  git checkout <SHA> && scripts/compose-release.sh build-only
#   transfer:    scripts/compose-release.sh export <SHA> \
#                  | ssh prod 'cd /opt/plasma-console/plasmaos && scripts/compose-release.sh import --expect <SHA>'
#   production:  scripts/compose-release.sh up <SHA>     (no build; see docs/ops/ROLLOUT_WEEK1.md for the ordered form)
# docker load verifies every layer digest, so a corrupted transfer fails the import.
#
# PLASMA_NO_BUILD=1 (environment or .env) marks a host that must never build: build,
# build-only and --build are refused, `up`/`create` always get --no-build, and anything
# that starts containers is refused unless every service's image is already present.
# On such a host HOST_PROFILE must also be set.
#
# HOST_PROFILE=4gb|8gb (environment or .env) adds deploy/host-profiles/<profile>.env after
# .env, so the profile's memory limits and worker settings win.
#
# Every release switch (`up <SHA>`, `rollback`, `up --build`) is appended to .release-history
# (git-ignored), which scripts/ops/prune_safe.sh uses to keep the current and previous release.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PLASMA_BUILD_SHA="${PLASMA_BUILD_SHA:-$(git rev-parse HEAD)}"
export PLASMA_BUILD_TIME="${PLASMA_BUILD_TIME:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
export FRONTEND_NEXT_PUBLIC_API_URL="${FRONTEND_NEXT_PUBLIC_API_URL:-/api/v1}"
export BACKEND_INTERNAL_URL="${BACKEND_INTERNAL_URL:-http://backend:8000/api/v1}"
# Git Bash (MSYS) rewrites environment values that start with "/" into Windows paths when it
# starts docker.exe: a Windows build host once baked NEXT_PUBLIC_API_URL="C:/Program Files/Git/api/v1"
# into the frontend bundle. No effect on Linux. build-only and export also check the baked value.
export MSYS_NO_PATHCONV=1 MSYS2_ENV_CONV_EXCL='*'
RELEASE_IMAGE_PREFIX="${RELEASE_IMAGE_PREFIX:-plasma-}"
RELEASE_HISTORY="${RELEASE_HISTORY:-$repo_root/.release-history}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  if command -v docker.exe >/dev/null 2>&1; then
    DOCKER_BIN="docker.exe"
  fi
fi

die() { echo "compose-release: $*" >&2; exit 1; }

# Value of KEY from the environment, else from .env (last assignment wins, quotes stripped).
setting() {
  local key="$1" value="${!1:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value="$(grep -E "^[[:space:]]*${key}=" .env | tail -n 1 | cut -d= -f2- || true)"
    value="${value%$'\r'}"
    value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
  fi
  printf '%s' "$value"
}
NO_BUILD="$(setting PLASMA_NO_BUILD)"
HOST_PROFILE="$(setting HOST_PROFILE)"
is_sha() { [[ "${1:-}" =~ ^[0-9a-f]{7,40}$ ]]; }

mode="compose"
case "${1:-}" in
  tag) mode="tag"; FALLBACK_SHA="${2:-}"; shift "$(( $# > 1 ? 2 : 1 ))" ;;
  images) mode="images"; shift ;;
  build-only) mode="build-only"; shift ;;
  export)
    is_sha "${2:-}" || die "usage: scripts/compose-release.sh export <SHA> [SERVICE...] > release.tar.gz"
    mode="export"; RELEASE_SHA="$2"; shift 2 ;;
  import)
    mode="import"; shift
    EXPECT_SHA=""
    if [ "${1:-}" = "--expect" ]; then
      is_sha "${2:-}" || die "usage: scripts/compose-release.sh import [--expect <SHA>] < release.tar.gz"
      EXPECT_SHA="$2"; shift 2
    fi
    [ "$#" -eq 0 ] || die "usage: scripts/compose-release.sh import [--expect <SHA>] < release.tar.gz"
    ;;
  use)
    { [ "$#" -eq 2 ] && is_sha "$2"; } || die "usage: scripts/compose-release.sh use <SHA>"
    mode="use"; RELEASE_SHA="$2"; shift 2 ;;
  rollback)
    { [ "$#" -eq 2 ] && is_sha "$2"; } || die "usage: scripts/compose-release.sh rollback <SHA>"
    mode="switch"; RELEASE_SHA="$2"; SWITCH_ACTION="rollback"; shift 2 ;;
  up)
    if is_sha "${2:-}"; then
      mode="switch"; RELEASE_SHA="$2"; SWITCH_ACTION="up"; shift 2
    fi
    ;;
esac
if [ "$mode" = "use" ] || [ "$mode" = "switch" ]; then
  export PLASMA_BUILD_SHA="$RELEASE_SHA"
fi

# ---- no-build host guard (part 1: explicit builds) ------------------------------------------
if [ "$NO_BUILD" = "1" ]; then
  [ "$mode" != "build-only" ] || die "PLASMA_NO_BUILD=1: this host does not build images; build elsewhere and import (see the header)"
  if [ "$mode" = "compose" ]; then
    for arg in "$@"; do
      case "$arg" in
        build|--build) die "PLASMA_NO_BUILD=1: '$arg' is refused on this host; build elsewhere and import (see the header)" ;;
      esac
    done
  fi
fi

release_env_file="$(mktemp .compose-release.XXXXXX.env)"
trap 'rm -f "$release_env_file"' EXIT
write_release_env() {
  cat >"$release_env_file" <<EOF
PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA
PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME
FRONTEND_NEXT_PUBLIC_API_URL=$FRONTEND_NEXT_PUBLIC_API_URL
BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL
EOF
}
write_release_env

compose_args=(compose)
if [ -f .env ]; then
  compose_args+=(--env-file .env)
fi
if [ -f frontend/.env ]; then
  compose_args+=(--env-file frontend/.env)
fi
if [ -n "$HOST_PROFILE" ]; then
  profile_file="deploy/host-profiles/$HOST_PROFILE.env"
  [ -f "$profile_file" ] || die "HOST_PROFILE=$HOST_PROFILE has no $profile_file (use 4gb or 8gb)"
  compose_args+=(--env-file "$profile_file")
fi
compose_args+=(--env-file "$release_env_file")

# "<service> <compose image name>" for every service Compose builds (images without a tag).
built_images() {
  local project image
  project="$("$DOCKER_BIN" "${compose_args[@]}" config | sed -n 's/^name: *//p' | head -n 1)"
  [ -n "$project" ] || { echo "cannot determine the Compose project name" >&2; return 1; }
  "$DOCKER_BIN" "${compose_args[@]}" config --images | sort -u | while read -r image; do
    case "$image" in
      "$project"-*) case "$image" in *:*|*/*) ;; *) echo "${image#"$project"-} $image" ;; esac ;;
    esac
  done
}

image_env() {  # image_env IMAGE KEY -> value of KEY in the image's environment
  "$DOCKER_BIN" image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null \
    | sed -n "s/^$2=//p" | head -n 1
}

tag_release_images() {
  local service image sha tagged=0
  while read -r service image; do
    if ! "$DOCKER_BIN" image inspect "$image:latest" >/dev/null 2>&1; then
      echo "skip $service: $image:latest does not exist" >&2
      continue
    fi
    sha="$(image_env "$image:latest" PLASMA_BUILD_SHA)"
    case "$sha" in
      ""|unknown)
        if [ -z "${FALLBACK_SHA:-}" ]; then
          echo "skip $service: $image:latest has no PLASMA_BUILD_SHA (pass the SHA it was built from: tag <SHA>)" >&2
          continue
        fi
        sha="$FALLBACK_SHA" ;;
    esac
    "$DOCKER_BIN" tag "$image:latest" "$RELEASE_IMAGE_PREFIX$service:$sha"
    echo "tagged $RELEASE_IMAGE_PREFIX$service:$sha"
    tagged=$((tagged + 1))
  done < <(built_images)
  [ "$tagged" -gt 0 ] || { echo "no images were tagged" >&2; return 1; }
}

# Fails (listing what is missing) unless plasma-<service>:<SHA> exists for every built service.
require_release_images() {
  local sha="$1" missing=0 service image
  while read -r service image; do
    "$DOCKER_BIN" image inspect "$RELEASE_IMAGE_PREFIX$service:$sha" >/dev/null 2>&1 \
      || { echo "missing $RELEASE_IMAGE_PREFIX$service:$sha" >&2; missing=1; }
  done < <(built_images)
  [ "$missing" = "0" ]
}

# Fails unless the frontend image bakes exactly FRONTEND_NEXT_PUBLIC_API_URL (browser bundle).
frontend_api_url_ok() {  # frontend_api_url_ok IMAGE
  local baked
  baked="$(image_env "$1" NEXT_PUBLIC_API_URL)"
  [ "$baked" = "$FRONTEND_NEXT_PUBLIC_API_URL" ] \
    || { echo "$1 bakes NEXT_PUBLIC_API_URL=$baked, expected $FRONTEND_NEXT_PUBLIC_API_URL" >&2; return 1; }
}

record_release() {  # record_release SHA ACTION
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >>"$RELEASE_HISTORY" \
    || echo "WARN: could not append to $RELEASE_HISTORY" >&2
}

# Point every <project>-<service>:latest at plasma-<service>:<SHA> and take the release
# metadata from that image, so /health reports the build that actually runs.
switch_latest_to() {
  local sha="$1" service image build_time
  require_release_images "$sha" || die "not every service has an image for $sha (import it first; nothing was changed)"
  while read -r service image; do
    "$DOCKER_BIN" tag "$RELEASE_IMAGE_PREFIX$service:$sha" "$image:latest"
    echo "$image:latest -> $RELEASE_IMAGE_PREFIX$service:$sha"
  done < <(built_images)
  build_time="$(image_env "${RELEASE_IMAGE_PREFIX}backend:$sha" PLASMA_BUILD_TIME)"
  export PLASMA_BUILD_TIME="${build_time:-unknown}"
  write_release_env
}

case "$mode" in
  tag)
    tag_release_images
    exit 0
    ;;
  images)
    "$DOCKER_BIN" images --format '{{.Repository}}:{{.Tag}}  {{.CreatedSince}}  {{.ID}}  {{.Size}}' \
      | grep "^$RELEASE_IMAGE_PREFIX" || echo "no release images tagged on this host"
    exit 0
    ;;
  export)
    [ ! -t 1 ] || die "export writes a binary stream: redirect it to a file or pipe it (see the header)"
    services=("$@")
    if [ "${#services[@]}" -eq 0 ]; then
      mapfile -t services < <(built_images | cut -d' ' -f1)
    fi
    [ "${#services[@]}" -gt 0 ] || die "no services to export"
    refs=()
    for service in "${services[@]}"; do
      ref="$RELEASE_IMAGE_PREFIX$service:$RELEASE_SHA"
      "$DOCKER_BIN" image inspect "$ref" >/dev/null 2>&1 || die "missing $ref (run build-only on this host first)"
      if [ "$service" = frontend ]; then
        frontend_api_url_ok "$ref" || die "refusing to export $ref: rebuild it (build-only) with the intended FRONTEND_NEXT_PUBLIC_API_URL"
      fi
      refs+=("$ref")
    done
    compressor=(gzip -c -3)
    if command -v pigz >/dev/null 2>&1; then compressor=(pigz -c -3); fi
    echo "exporting ${refs[*]} (${compressor[0]})" >&2
    started=$SECONDS
    # docker save writes shared layers once, so the seven services cost little more than one.
    "$DOCKER_BIN" save "${refs[@]}" | "${compressor[@]}"
    echo "export of $RELEASE_SHA finished in $((SECONDS - started)) s" >&2
    exit 0
    ;;
  import)
    [ ! -t 0 ] || die "import reads the stream from stdin: pipe the output of 'export' into it"
    started=$SECONDS
    "$DOCKER_BIN" load   # accepts the gzip stream; verifies every layer digest
    echo "import finished in $((SECONDS - started)) s" >&2
    if [ -n "$EXPECT_SHA" ]; then
      require_release_images "$EXPECT_SHA" || die "import incomplete: not every service has an image for $EXPECT_SHA"
      echo "every service has $RELEASE_IMAGE_PREFIX<service>:$EXPECT_SHA" >&2
    fi
    exit 0
    ;;
esac

# ---- no-build host guard (part 2: anything that starts containers) ----------------------------
first_command=""
for arg in "$@"; do
  case "$arg" in up|create|run|start|restart|build|pull|down|stop|exec|ps|logs|config) first_command="$arg"; break ;; esac
done
starts_containers=0
case "$mode:$first_command" in
  use:*|switch:*|compose:up|compose:create|compose:run|compose:start|compose:restart) starts_containers=1 ;;
esac
if [ "$NO_BUILD" = "1" ] && [ "$starts_containers" = "1" ]; then
  [ -n "$HOST_PROFILE" ] || die "PLASMA_NO_BUILD=1 host without HOST_PROFILE: set HOST_PROFILE=4gb or 8gb in .env"
  if [ "$mode" = "compose" ]; then
    missing=0
    while read -r service image; do
      "$DOCKER_BIN" image inspect "$image:latest" >/dev/null 2>&1 \
        || { echo "missing $image:latest" >&2; missing=1; }
    done < <(built_images)
    [ "$missing" = "0" ] || die "PLASMA_NO_BUILD=1: images are missing and will not be built here; import a release and run 'use <SHA>' first"
    # Compose builds a missing image on `up`/`create` unless told not to.
    if [ "$first_command" = "up" ] || [ "$first_command" = "create" ]; then
      has_no_build=0
      for arg in "$@"; do if [ "$arg" = "--no-build" ]; then has_no_build=1; fi; done
      if [ "$has_no_build" = "0" ]; then
        new_args=()
        for arg in "$@"; do
          new_args+=("$arg")
          if [ "$arg" = "$first_command" ] && [ "$has_no_build" = "0" ]; then new_args+=(--no-build); has_no_build=1; fi
        done
        set -- "${new_args[@]}"
      fi
    fi
  fi
elif [ "$starts_containers" = "1" ] && [ -z "$HOST_PROFILE" ]; then
  echo "WARN: HOST_PROFILE is not set: memory limits use the compose defaults (4gb values) and PURSUIT_ANALYSIS_WORKER_CONCURRENCY defaults to 2" >&2
fi

case "$mode" in
  use)
    switch_latest_to "$RELEASE_SHA"
    echo "images switched to $RELEASE_SHA; nothing was restarted"
    exit 0
    ;;
  switch)
    switch_latest_to "$RELEASE_SHA"
    set -- up -d --no-build "$@"
    ;;
  build-only)
    set -- build "$@"
    ;;
esac

echo "PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA"
echo "PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME"
echo "FRONTEND_NEXT_PUBLIC_API_URL=$FRONTEND_NEXT_PUBLIC_API_URL"
echo "BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL"
echo "HOST_PROFILE=${HOST_PROFILE:-<unset>}"

builds=0
for arg in "$@"; do
  case "$arg" in build|--build) builds=1 ;; esac
done
if [ "$builds" = "1" ] && ! git diff --quiet HEAD -- 2>/dev/null; then
  echo "WARNING: tracked files differ from $PLASMA_BUILD_SHA; the plasma-<service>:<SHA> tag will not match the commit" >&2
fi

"$DOCKER_BIN" "${compose_args[@]}" "$@"

if [ "$builds" = "1" ]; then
  tag_release_images
  if [ "$mode" = "build-only" ]; then
    require_release_images "$PLASMA_BUILD_SHA" || die "build finished but not every service is tagged $PLASMA_BUILD_SHA"
    if "$DOCKER_BIN" image inspect "${RELEASE_IMAGE_PREFIX}frontend:$PLASMA_BUILD_SHA" >/dev/null 2>&1; then
      frontend_api_url_ok "${RELEASE_IMAGE_PREFIX}frontend:$PLASMA_BUILD_SHA" || die "the frontend image bakes the wrong API URL (see above); do not export it"
    fi
    echo "built and tagged $RELEASE_IMAGE_PREFIX<service>:$PLASMA_BUILD_SHA; next: export $PLASMA_BUILD_SHA"
  fi
fi
case "$mode:$first_command" in
  switch:*) record_release "$RELEASE_SHA" "$SWITCH_ACTION" ;;
  compose:up) if [ "$builds" = "1" ]; then record_release "$PLASMA_BUILD_SHA" "up-build"; fi ;;
esac
