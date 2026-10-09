#!/usr/bin/env bash
# Reclaim Docker disk space without touching data or the release you can roll back to.
#
#   scripts/ops/prune_safe.sh [--apply] [--keep SHA]... [--keep-build-cache] [--min-releases N]
#
# Dry run by default: prints what would be removed. With --apply it removes:
#   1. dangling images (untagged layers left behind by rebuilds and retags)
#   2. the build cache (production does not build; --keep-build-cache skips this)
#   3. release tags plasma-<service>:<SHA> whose SHA is not kept
# It NEVER removes volumes, containers, networks, images used by any container (running
# or stopped), or any non-release image. There is no `system prune` and no `volume prune`.
#
# Kept release SHAs (all images of that SHA):
#   * every SHA whose image is used by a container (the current release)
#   * the last two releases recorded in .release-history by compose-release.sh (current, previous)
#   * every release newer than the newest in-use one (a build/import waiting to be deployed)
#   * --keep SHA (repeatable) and PLASMA_KEEP_SHAS="sha1 sha2" (e.g. the production tag a275357)
#   * if that still leaves fewer than --min-releases (default 2), the newest remaining ones until
#     that many are kept. --min-releases 1 (with --keep) lets a deploy remove the release before the
#     rollback point when no newer release is on the host yet (Deploy 2: --keep 0bea1f1 --min-releases 1).
# SHAs match by prefix, so a275357 keeps plasma-<service>:a275357... tags.
#
# Space: release images share layers (the backend family's ~3.4 GB Playwright base is the same in
# every release), so removing a release frees its images' UNIQUE size (`docker system df -v`),
# about 0.85 GB for the backend family plus ~1.1 GB for the frontend, not the 4.3 + 1.3 GB that
# `docker images` lists. The dry run prints that estimate; --apply prints what was really freed
# (images, build cache, the Docker root file system) and a PRUNE_RESULT line.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

APPLY=0
KEEP_BUILD_CACHE=0
MIN_RELEASES=2
KEEP=()
RELEASE_IMAGE_PREFIX="${RELEASE_IMAGE_PREFIX:-plasma-}"
RELEASE_HISTORY="${RELEASE_HISTORY:-$OPS_ROOT/.release-history}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --keep) [[ "${2:-}" =~ ^[0-9a-f]{7,40}$ ]] || die "--keep needs a SHA"; KEEP+=("$2"); shift 2 ;;
    --keep-build-cache) KEEP_BUILD_CACHE=1; shift ;;
    --min-releases) [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] || die "--min-releases needs a number >= 1"; MIN_RELEASES="$2"; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
for sha in ${PLASMA_KEEP_SHAS:-}; do
  [[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || die "PLASMA_KEEP_SHAS contains '$sha', which is not a SHA"
  KEEP+=("$sha")
done
D=("${_DOCKER[@]}")
run() { if [ "$APPLY" = "1" ]; then "$@"; else echo "  would run: $*"; fi; }

# ---- inventory ---------------------------------------------------------------------------------------
mapfile -t IN_USE < <("${D[@]}" ps -aq | xargs -r "${D[@]}" inspect -f '{{.Image}}' | sort -u)
# "<sha> <created> <ref> <id>" for every release tag.
mapfile -t RELEASE < <(
  "${D[@]}" images --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
    | awk -v p="$RELEASE_IMAGE_PREFIX" 'index($1, p) == 1' \
    | while read -r ref id; do
        sha="${ref##*:}"
        [[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || continue
        created="$("${D[@]}" image inspect -f '{{.Created}}' "$id")"
        echo "$sha $created $ref $id"
      done | sort -k2,2
)
mapfile -t SHAS < <(printf '%s\n' "${RELEASE[@]}" | awk 'NF {print $1}' | awk '!seen[$0]++')   # oldest first
newest_created() { printf '%s\n' "${RELEASE[@]}" | awk -v s="$1" '$1 == s {print $2}' | sort | tail -n 1; }

matches() { local sha="$1" k; for k in "${KEEP_SET[@]}"; do case "$sha" in "$k"*) return 0 ;; esac; done; return 1; }
KEEP_SET=()
reason=()
add_keep() { if ! matches "$1"; then KEEP_SET+=("$1"); reason+=("$1: $2"); fi; }

newest_in_use=""
for line in "${RELEASE[@]}"; do
  [ -n "$line" ] || continue
  read -r sha created ref id <<<"$line"
  if printf '%s\n' "${IN_USE[@]}" | grep -qxF "$id"; then
    add_keep "$sha" "used by a container"
    if [[ "$created" > "$newest_in_use" ]]; then newest_in_use="$created"; fi
  fi
done
if [ -f "$RELEASE_HISTORY" ]; then
  while read -r sha; do add_keep "$sha" "recent release in $(basename "$RELEASE_HISTORY")"; done \
    < <(awk '{print $2}' "$RELEASE_HISTORY" | tac | awk '!seen[$0]++' | head -n 2)
fi
for sha in "${KEEP[@]}"; do add_keep "$sha" "--keep / PLASMA_KEEP_SHAS"; done
if [ -n "$newest_in_use" ]; then
  for sha in "${SHAS[@]}"; do
    if [[ "$(newest_created "$sha")" > "$newest_in_use" ]]; then add_keep "$sha" "newer than the running release (deploy candidate)"; fi
  done
fi
# At least --min-releases releases that are actually on this host (a --keep SHA with no images
# here does not count, or it would cost the host its rollback image).
kept_present() { local n=0 sha; for sha in "${SHAS[@]}"; do if matches "$sha"; then n=$((n + 1)); fi; done; echo "$n"; }
for ((i = ${#SHAS[@]} - 1; i >= 0 && $(kept_present) < MIN_RELEASES; i--)); do
  add_keep "${SHAS[$i]}" "newest remaining (keeping at least $MIN_RELEASES release(s) present on this host)"
done

echo "== release SHAs kept"
if [ "${#reason[@]}" -gt 0 ]; then printf '  %s\n' "${reason[@]}"; else echo "  (no release images on this host)"; fi

echo "== release tags to remove"
REMOVE=()
for line in "${RELEASE[@]}"; do
  [ -n "$line" ] || continue
  read -r sha created ref id <<<"$line"
  matches "$sha" && continue
  if printf '%s\n' "${IN_USE[@]}" | grep -qxF "$id"; then continue; fi   # never an in-use image
  REMOVE+=("$ref")
  echo "  $ref (created $created)"
done
[ "${#REMOVE[@]}" -gt 0 ] || echo "  none"

echo "== dangling images"
dangling="$("${D[@]}" images -q -f dangling=true | sort -u | wc -l | tr -d ' ')"
echo "  $dangling dangling image(s)"
echo "== build cache"
"${D[@]}" system df --format '{{.Type}}: {{.Size}} total, {{.Reclaimable}} reclaimable' | grep -i 'build cache' || true

# Release images share most of their layers (the backend family's ~3.4 GB Playwright base is the
# same in every release), so removing a release frees only the layers no other image uses: the
# images' UNIQUE size, not their SIZE. An image that keeps another tag frees nothing.
echo "== space the removed tags free (unique layers; shared layers stay with the kept releases)"
to_bytes() { awk -v s="$1" 'BEGIN { n = s + 0; u = s; sub(/^[0-9.]+/, "", u); m = 1
  if (u == "kB" || u == "KB") m = 1e3; else if (u == "MB") m = 1e6; else if (u == "GB") m = 1e9; else if (u == "TB") m = 1e12
  printf "%.0f", n * m }'; }
human() { awk -v b="$1" 'BEGIN { if (b >= 1e9) printf "%.2f GB", b / 1e9; else printf "%.0f MB", b / 1e6 }'; }
estimate=0
if [ "${#REMOVE[@]}" -gt 0 ]; then
  mapfile -t SIZES < <("${D[@]}" system df -v --format '{{range .Images}}{{.ID}} {{.Size}} {{.UniqueSize}}{{println}}{{end}}' 2>/dev/null || true)
  mapfile -t REMOVE_IDS < <(for line in "${RELEASE[@]}"; do
      read -r _ _ ref id <<<"$line"
      if printf '%s\n' "${REMOVE[@]}" | grep -qxF "$ref"; then echo "$id"; fi
    done | sort -u)
  for id in "${REMOVE_IDS[@]}"; do
    [ -n "$id" ] || continue
    sizes="$(printf '%s\n' "${SIZES[@]}" | awk -v id="$id" '$1 == id {print $2, $3; exit}')"
    other_tags="$("${D[@]}" image inspect -f '{{range .RepoTags}}{{println .}}{{end}}' "$id" 2>/dev/null \
      | grep -v '^$' | grep -vxF -f <(printf '%s\n' "${REMOVE[@]}") || true)"
    if [ -n "$other_tags" ]; then
      echo "  ${id:7:12}: also tagged $(echo "$other_tags" | head -n 1): frees nothing"
    elif [ -n "$sizes" ]; then
      read -r size unique <<<"$sizes"
      estimate=$((estimate + $(to_bytes "$unique")))
      echo "  ${id:7:12}: size $size, unique $unique"
    fi
  done
fi
echo "  estimate: at least $(human "$estimate") from release images (layers shared only among the removed images add to this)"

space_now() {  # "<images bytes> <build cache bytes> <root fs available KiB or ->"
  local images cache root avail
  images="$("${D[@]}" system df --format '{{.Type}}|{{.Size}}' | awk -F'|' '$1 == "Images" {print $2}')"
  cache="$("${D[@]}" system df --format '{{.Type}}|{{.Size}}' | awk -F'|' '$1 == "Build Cache" {print $2}')"
  root="$("${D[@]}" info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
  avail="$(df -Pk "${root:-/}" 2>/dev/null | awk 'NR == 2 {print $4}')"
  echo "$(to_bytes "${images:-0B}") $(to_bytes "${cache:-0B}") ${avail:--}"
}
[ "$APPLY" = "1" ] && BEFORE="$(space_now)"

echo "== actions ($([ "$APPLY" = "1" ] && echo APPLY || echo 'DRY RUN: nothing is changed; re-run with --apply'))"
if [ "${#REMOVE[@]}" -gt 0 ]; then
  run "${D[@]}" image rm "${REMOVE[@]}"
fi
run "${D[@]}" image prune -f
if [ "$KEEP_BUILD_CACHE" = "0" ]; then
  run "${D[@]}" builder prune -af
fi
if [ "$APPLY" = "1" ]; then
  echo "== after"
  "${D[@]}" system df
  read -r images_before cache_before avail_before <<<"$BEFORE"
  read -r images_after cache_after avail_after <<<"$(space_now)"
  echo "== freed (measured)"
  echo "  images: $(human "$((images_before - images_after))") (estimate was $(human "$estimate"))"
  echo "  build cache: $(human "$((cache_before - cache_after))")"
  if [ "$avail_before" != "-" ] && [ "$avail_after" != "-" ]; then
    echo "  file system of $("${D[@]}" info -f '{{.DockerRootDir}}'): $(human "$(( (avail_after - avail_before) * 1024 ))") more available"
  fi
  echo "PRUNE_RESULT images_freed_bytes=$((images_before - images_after)) build_cache_freed_bytes=$((cache_before - cache_after)) estimate_bytes=$estimate"
fi
