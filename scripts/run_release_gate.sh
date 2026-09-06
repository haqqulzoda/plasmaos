#!/usr/bin/env bash
set -euo pipefail
release_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$release_root"
python backend/scripts/release_test_target.py
export ENVIRONMENT=test
release_frontend="${PLASMA_FRONTEND_TEST_ROOT:-$release_root/frontend}"
release_group="${1:-all}"

run_group() {
  case "$1" in
    backend)
      (cd backend && python -m pytest -q)
      ;;
    security)
      (cd backend && python -m pytest -q test_release_security.py test_release_uploads.py test_release_config.py test_release_reads.py test_release_runtime.py)
      ;;
    analysis)
      (cd backend && python -m pytest -q test_s2_2*.py test_s3_2*.py test_s3_3*.py test_s8_2*.py)
      ;;
    connectors)
      bash backend/scripts/run_connector_regression_gate.sh
      ;;
    migrations)
      (cd backend && python scripts/verify_release_migrations.py)
      ;;
    performance)
      (cd backend && python scripts/verify_release_scale.py)
      ;;
    frontend)
      (cd "$release_frontend" && npm ci && npm run typecheck && npm run lint &&
        node --no-warnings --experimental-strip-types --test tests/*.test.mjs && npm run audit:rtl &&
        AUTH_SECRET=release-browser-synthetic-secret AUTH_URL=http://localhost:3114 BACKEND_INTERNAL_URL=http://127.0.0.1:8114/api/v1 NEXT_DIST_DIR=.next-release-test npm run build)
      ;;
    browser)
      python frontend/tests/release-hardening-browser.py
      ;;
    config-dependencies)
      (cd backend && python -m pytest -q test_release_config.py && python -m pip check)
      (cd "$release_frontend" && npm audit --audit-level=high)
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
