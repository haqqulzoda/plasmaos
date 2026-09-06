# Backend scripts and historical tools

Use the existing connector gate for offline source regressions. Verification scripts
retain their original sprint-specific datasets, heads and invocation requirements; a
`verify_` prefix does not mean every historical script is a current release gate.

The current setup and hardening gaps remain Sprint 9.3 work. Do not run old add/reset/
init/seed scripts as a migration path. Preserve immutable migration/baseline evidence.

Moved live diagnostics and exact usage: [probes](probes/README.md).
Sprint 9.2 decisions: [cleanup report](../../docs/S9_2_LEGACY_CONTRACT_TEST_TOPOLOGY_CLEANUP.md).

| Current file | Classification |
| --- | --- |
| `backend/add_company_columns.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/add_financial_columns.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/add_vault_profile_columns.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/debug_auth.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/debug_dom.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/diagnose.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/init_db.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/local_test_ai.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/local_test_parser.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/reset_db.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/scripts/__pycache__/seed_taxonomy.cpython-314.pyc` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/scripts/__pycache__/test_evaluator.cpython-314.pyc` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/__pycache__/test_extraction.cpython-314.pyc` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/__pycache__/verify_vault_db.cpython-314.pyc` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/audit_sr1_source_refresh.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/audit_sr2_1_semantic_batch.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/audit_sr2_2_source_refresh_orchestration.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/bootstrap_database.py` | Canonical empty-disposable bootstrap; keep guards and immutable baseline |
| `backend/scripts/diff_reproducibility.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/enqueue_world_bank_project_enrichment.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/models_output.txt` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/purge_small_scale_uzex_tenders.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/scripts/qa_s8_2_live_model_languages.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/report_analysis_aggregate_concurrency.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/report_world_bank_project_enrichment_backlog.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/run_connector_regression_gate.sh` | Maintained offline connector regression gate |
| `backend/scripts/run_s0_3_schema_data_preflight.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/seed_taxonomy.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `backend/scripts/test_evaluator.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/probes/extraction_probe.py` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `backend/scripts/test_s0_5b3_migration.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/test_s0_5b4_baseline.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/test_s0_5b5_drift.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s1_1_project_foundation.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/test_s1_2_project_enrichment.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s2_1_compliance_ownership.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s2_2_analysis_version_foundation.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s2_2b_analysis_aggregate_concurrency.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s2_3_version_aware_compliance_reads.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s3_3_privileged_account_survivability.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s3_4_administrative_audit_hardening.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s3_5_admin_operational_ux_hardening.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s4_1_tender_engagement_foundation.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s4_2_my_tenders_list_experience.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s4_3_bid_preparation_reconciliation.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s4_4_tender_engagement_workflow_ux.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s5_2_tender_details_read_model.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_s6_2_unified_explorer_backend.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/test_s7_2_locale_migration.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/test_s8_2_analysis_language_migration.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_wb_project_enrichment_autodrain.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/scripts/verify_vault_db.py` | Historical/focused verification; explicit invocation; retained sprint-specific assumptions |
| `backend/seed_tenders.py` | Operator-dangerous; explicit target/intent only; not setup authority |
| `frontend/scripts/audit-customer-literals.mjs` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `frontend/scripts/audit-rtl.mjs` | Explicit-use diagnostic/report/operator tooling; not an automatic setup step |
| `scripts/compose-release.sh` | Release operational wrapper; not a test; deployment outside 9.2 |

Historical reports describe their original SHA. Where they mention former `test_`
probe/proof paths, use the Sprint 9.2 rename ledger; their original test results have
not been rewritten. Live HTTP/model diagnostics never count as passing unit coverage.
