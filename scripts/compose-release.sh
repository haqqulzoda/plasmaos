#!/usr/bin/env bash
# Release wrapper around `docker compose`.
#
#   scripts/compose-release.sh <compose args>     e.g. up -d --build, config --quiet, ps
#   scripts/compose-release.sh tag [SHA]          tag the current images with their build SHA (SHA is
#                                                 used only for images that do not record one)
#   scripts/compose-release.sh images             list the SHA-tagged release images on this host
#   scripts/compose-release.sh rollback <SHA>     switch every built service back to plasma-<service>:<SHA>
#                                                 and recreate the containers (no build)
#
# Compose builds <project>-<service>:latest. After any successful command that builds
# (`build`, `up --build`), every built image is also tagged plasma-<service>:<SHA>, with
# the SHA read from the image's own PLASMA_BUILD_SHA, so a rollback is a tag switch.
# Run `tag` once before the first release that uses this script, so the images running
# today have a tag to roll back to. Old release tags keep their layers on disk: remove
# them with `docker image rm plasma-<service>:<SHA>` when they are no longer needed.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PLASMA_BUILD_SHA="${PLASMA_BUILD_SHA:-$(git rev-parse HEAD)}"
export PLASMA_BUILD_TIME="${PLASMA_BUILD_TIME:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
export FRONTEND_NEXT_PUBLIC_API_URL="${FRONTEND_NEXT_PUBLIC_API_URL:-/api/v1}"
export BACKEND_INTERNAL_URL="${BACKEND_INTERNAL_URL:-http://backend:8000/api/v1}"
RELEASE_IMAGE_PREFIX="${RELEASE_IMAGE_PREFIX:-plasma-}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  if command -v docker.exe >/dev/null 2>&1; then
    DOCKER_BIN="docker.exe"
  fi
fi

mode="compose"
case "${1:-}" in
  tag) mode="tag"; FALLBACK_SHA="${2:-}"; shift "$(( $# > 1 ? 2 : 1 ))" ;;
  images) mode="images"; shift ;;
  rollback)
    [ "$#" -eq 2 ] || { echo "usage: scripts/compose-release.sh rollback <SHA>" >&2; exit 2; }
    mode="rollback"; ROLLBACK_SHA="$2"; shift 2
    export PLASMA_BUILD_SHA="$ROLLBACK_SHA"
    ;;
esac

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

case "$mode" in
  tag)
    tag_release_images
    exit 0
    ;;
  images)
    "$DOCKER_BIN" images --format '{{.Repository}}:{{.Tag}}  {{.CreatedSince}}  {{.ID}}' \
      | grep "^$RELEASE_IMAGE_PREFIX" || echo "no release images tagged on this host"
    exit 0
    ;;
  rollback)
    missing=0
    while read -r service image; do
      "$DOCKER_BIN" image inspect "$RELEASE_IMAGE_PREFIX$service:$ROLLBACK_SHA" >/dev/null 2>&1 \
        || { echo "missing $RELEASE_IMAGE_PREFIX$service:$ROLLBACK_SHA" >&2; missing=1; }
    done < <(built_images)
    [ "$missing" = "0" ] || { echo "rollback aborted: not every service has an image for $ROLLBACK_SHA" >&2; exit 1; }
    while read -r service image; do
      "$DOCKER_BIN" tag "$RELEASE_IMAGE_PREFIX$service:$ROLLBACK_SHA" "$image:latest"
      echo "$image:latest -> $RELEASE_IMAGE_PREFIX$service:$ROLLBACK_SHA"
    done < <(built_images)
    # Keep the runtime release metadata truthful: it comes from the image being rolled back to.
    build_time="$(image_env "${RELEASE_IMAGE_PREFIX}backend:$ROLLBACK_SHA" PLASMA_BUILD_TIME)"
    export PLASMA_BUILD_TIME="${build_time:-unknown}"
    write_release_env
    set -- up -d --no-build
    ;;
esac

echo "PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA"
echo "PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME"
echo "FRONTEND_NEXT_PUBLIC_API_URL=$FRONTEND_NEXT_PUBLIC_API_URL"
echo "BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL"

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
fi
