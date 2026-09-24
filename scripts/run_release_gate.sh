#!/usr/bin/env bash
set -euo pipefail
release_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$release_root"
python_bin="${PYTHON_BIN:-python}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  python_bin=python3
fi
browser_python_bin="${PLASMA_BROWSER_PYTHON_BIN:-$python_bin}"
release_browser_port="${PLASMA_RELEASE_BROWSER_PORT:-3114}"
release_browser_base="http://localhost:${release_browser_port}"
npm_bin="${NPM_BIN:-npm}"
node_bin="${NODE_BIN:-node}"
if [[ -z "${NPM_BIN:-}" ]] && ! command -v node >/dev/null 2>&1 && command -v npm.cmd >/dev/null 2>&1; then
  npm_bin=npm.cmd
fi
if ! command -v "$node_bin" >/dev/null 2>&1; then
  node_bin=node.exe
fi
if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
  release_wsl_env="AUTH_SECRET:AUTH_URL:BACKEND_INTERNAL_URL:NEXT_DIST_DIR:PLASMA_RELEASE_BROWSER_PORT:PLASMA_RELEASE_BROWSER_DIST:PLASMA_BROWSER_CASE_FILTER:PLASMA_FRONTEND_TEST_ROOT/p:PLASMA_BROWSER_RESULTS/p"
  export WSLENV="${WSLENV:+${WSLENV}:}${release_wsl_env}"
fi

run_npm() {
  if [[ "$npm_bin" == *.cmd ]]; then
    cmd.exe /d /s /c npm "$@"
  else
    "$npm_bin" "$@"
  fi
}

"$python_bin" backend/scripts/release_test_target.py
export ENVIRONMENT=test
release_frontend="${PLASMA_FRONTEND_TEST_ROOT:-$release_root/frontend}"
release_group="${1:-all}"

run_group() {
  case "$1" in
    backend)
      (cd backend && "$python_bin" -m pytest -q)
      ;;
    security)
      (cd backend && "$python_bin" -m pytest -q test_release_security.py test_release_uploads.py test_release_config.py test_release_reads.py test_release_runtime.py)
      ;;
    analysis)
      (cd backend && "$python_bin" -m pytest -q test_s2_2*.py test_s3_2*.py test_s3_3*.py test_s8_2*.py)
      ;;
    connectors)
      bash backend/scripts/run_connector_regression_gate.sh
      ;;
    migrations)
      (cd backend && "$python_bin" scripts/verify_release_migrations.py)
      ;;
    performance)
      (cd backend && "$python_bin" scripts/verify_release_scale.py)
      ;;
    frontend)
      (cd "$release_frontend" && run_npm ci && run_npm run typecheck && run_npm run lint &&
        "$node_bin" --no-warnings --experimental-strip-types --test tests/*.test.mjs && run_npm run audit:rtl &&
        AUTH_SECRET=release-browser-synthetic-secret AUTH_URL="$release_browser_base" BACKEND_INTERNAL_URL=http://127.0.0.1:8114/api/v1 NEXT_DIST_DIR=.next-release-test run_npm run build)
      ;;
    browser)
      "$browser_python_bin" frontend/tests/release-hardening-browser.py
      ;;
    config-dependencies)
      (cd backend && "$python_bin" -m pytest -q test_release_config.py && "$python_bin" -m pip check)
      (cd "$release_frontend" && run_npm audit --audit-level=high)
      ;;
    *) echo "Unknown release gate group: $1" >&2; return 2 ;;
  esac
}

if [[ "$release_group" == all ]]; then
  for release_group in backend security analysis connectors migrations performance frontend browser config-dependencies; do
    echo "Release gate: $release_group"
    run_group "$release_group"
  done
else
  run_group "$release_group"
fi
