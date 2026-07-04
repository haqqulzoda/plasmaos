#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m pytest -s -q \
  test_s5_cross_source_regression.py \
  test_scraper_download_variants.py \
  test_tender_worker_failure_handling.py \
  test_tender_document_status.py \
  test_storage_path_resolver.py \
  test_tender_source_foundation.py \
  test_world_bank_connector.py \
  test_adb_connector.py \
  test_ebrd_connector.py \
  test_giz_connector.py \
  test_parser_traceability.py \
  test_reproducibility_snapshot.py \
  test_s1_access_foundation.py \
  test_s1_access_hardening.py \
  test_s4_3_decision_snapshot.py \
  test_compliance_forensic_categories.py
