# Exact P0 file inventory

This inventory lists files authored or modified for P0. The accepted, already-dirty W0-W8 workspace is excluded except where P0 necessarily amended a shared file or advanced a migration-head assertion.

## Runtime, schema, and focused tests

- `.gitignore`
- `backend/alembic/versions/20261002_0001_p0_extraction_trust_gate.py`
- `backend/app/api/endpoints/pursuits.py`
- `backend/app/core/agents/pursuit_analyzer.py`
- `backend/app/models/pursuit_analysis.py`
- `backend/app/schemas/tenancy.py`
- `backend/app/services/private_documents.py`
- `backend/app/services/pursuit_analysis.py`
- `backend/test_p0_real_rfp_extraction.py`
- `backend/test_w4_pursuit_analysis.py`
- `backend/tests/fixtures/communications_consultant_rfp.txt`
- `frontend/app/dashboard/pursuits/[pursuitId]/page.tsx`
- `frontend/components/customer/pages.css`
- `frontend/components/pursuits/PursuitRequirements.tsx`
- `frontend/components/pursuits/PursuitTeam.tsx`
- `frontend/messages/ar/pursuits.json`
- `frontend/messages/en/pursuits.json`
- `frontend/messages/ru/pursuits.json`
- `frontend/messages/uz/pursuits.json`
- `frontend/tests/p0-real-rfp-trust-gate.test.mjs`
- `frontend/tests/release-hardening-browser.py`
- `frontend/types/pursuit.ts`

## Migration-head compatibility updates

- `backend/scripts/audit_sr2_1_semantic_batch.py`
- `backend/scripts/audit_sr2_2_source_refresh_orchestration.py`
- `backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py`
- `backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py`
- `backend/scripts/test_s0_5b3_migration.py`
- `backend/scripts/test_s0_5b4_baseline.py`
- `backend/scripts/test_s0_5b5_drift.py`
- `backend/scripts/test_s1_2_project_enrichment.py`
- `backend/scripts/test_s7_2_locale_migration.py`
- `backend/scripts/verify_release_migrations.py`
- `backend/scripts/verify_s10_5_communications.py`
- `backend/scripts/verify_s1_1_project_foundation.py`
- `backend/scripts/verify_s2_1_compliance_ownership.py`
- `backend/scripts/verify_s2_2_analysis_version_foundation.py`
- `backend/scripts/verify_s2_2b_analysis_aggregate_concurrency.py`
- `backend/scripts/verify_s2_3_version_aware_compliance_reads.py`
- `backend/scripts/verify_s3_3_privileged_account_survivability.py`
- `backend/scripts/verify_s3_4_administrative_audit_hardening.py`
- `backend/scripts/verify_s3_5_admin_operational_ux_hardening.py`
- `backend/scripts/verify_s4_1_tender_engagement_foundation.py`
- `backend/scripts/verify_s4_2_my_tenders_list_experience.py`
- `backend/scripts/verify_s4_3_bid_preparation_reconciliation.py`
- `backend/scripts/verify_s4_4_tender_engagement_workflow_ux.py`
- `backend/scripts/verify_s5_2_tender_details_read_model.py`
- `backend/scripts/verify_s6_2_unified_explorer_backend.py`
- `backend/scripts/verify_wb_project_enrichment_autodrain.py`
- `backend/test_s0_3_schema_data_preflight.py`
- `backend/test_s0_5b3_tender_recommendation_migration.py`
- `backend/test_s0_5b4_baseline_bootstrap.py`
- `backend/test_s0_5b5_alembic_drift.py`
- `backend/test_s13_on_demand_tender_attachments.py`
- `backend/test_s1_1_project_foundation.py`
- `backend/test_s1_2_world_bank_project_enrichment.py`
- `backend/test_s1_3b_project_context_runtime_recovery.py`
- `backend/test_s2_1_compliance_ownership.py`
- `backend/test_s2_2_analysis_version_foundation.py`
- `backend/test_s2_2b_analysis_aggregate_concurrency.py`
- `backend/test_s4_1_tender_engagement_foundation.py`
- `backend/test_s4_2_my_tenders_list_experience.py`
- `backend/test_s4_4_tender_engagement_workflow_ux.py`
- `backend/test_s6_2_unified_explorer_backend.py`
- `backend/test_s6_4_hunter_retirement_final_qa.py`
- `backend/test_s8_2_analysis_language.py`
- `backend/test_s8_3_arabic_ui_locale.py`
- `backend/test_sr2_3_connector_capability_document_decoupling.py`
- `backend/test_w2_organization_pursuit_foundation.py`
- `backend/test_w5_candidate_retrieval.py`
- `backend/test_w6_participation.py`
- `backend/test_w7_team_scenarios.py`
- `backend/test_w8_proposal_evidence.py`

## Documentation and retained evidence

- `docs/P0_REAL_RFP_EXTRACTION_TRUST_GATE.md`
- `docs/audits/p0/root-cause.md`
- `docs/audits/p0/real-rfp-golden-benchmark.md`
- `docs/audits/p0/extraction-quality-gate.md`
- `docs/audits/p0/context-provenance-conflicts.md`
- `docs/audits/p0/ui-trust-states.md`
- `docs/audits/p0/validation.md`
- `docs/audits/p0/files-changed.md`
- `docs/audits/p0/browser-all/results.json`
