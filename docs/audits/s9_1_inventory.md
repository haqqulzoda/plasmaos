# S9.1 inventory appendix

Baseline `b121cda5b76911c59fdab5733d70aa6883908e9c`.

This is a source-reference inventory, not an automatic deletion allowlist. Framework entrypoints, same-module references, dynamic names and external clients matter. See the main audit for reviewed boundaries, risk and deletion conditions.

[Main report](../S9_1_CROSS_PRODUCT_ARCHITECTURE_LEGACY_AUDIT.md) · [Raw inventory](s9_1_inventory.json) · [OpenAPI](s9_1_openapi.json)

## Frontend routes

| Route / source | Purpose | Canonical / legacy | Redirect or guard navigation | Customer reachable | Backend dependencies | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| /admin/approvals<br>frontend/app/admin/approvals/page.tsx | User/company approval queue | Canonical | /dashboard<br>/dashboard | Operator/admin only | /admin/accounts | KEEP; hardening findings apply |
| /admin/audit<br>frontend/app/admin/audit/page.tsx | Administrative audit event log | Canonical | /dashboard | Operator/admin only | /admin/audit-events | KEEP; hardening findings apply |
| /admin/companies/[companyProfileId]<br>frontend/app/admin/companies/[companyProfileId]/page.tsx | Company profile/readiness inspection | Canonical | — | Operator/admin only | /admin/companies/${companyProfileId}<br>/admin/companies/${companyProfileId}/readiness<br>/meta/services | KEEP; hardening findings apply |
| /admin<br>frontend/app/admin/page.tsx | Account operations and corpus overview | Canonical | — | Operator/admin only | /admin/activity<br>/admin/corpus-health | KEEP; hardening findings apply |
| /api/auth/[...nextauth]<br>frontend/app/api/auth/[...nextauth]/route.ts | Auth.js authentication/session handlers | Canonical | — | Public; handler-specific validation | ${backendApiBase}/auth/google<br>${backendApiBase}/auth/refresh | KEEP; hardening findings apply |
| /api/build<br>frontend/app/api/build/route.ts | Public frontend release metadata | Canonical | — | Public; handler-specific validation | — | KEEP; hardening findings apply |
| /api/documents/[id]<br>frontend/app/api/documents/[id]/route.ts | Authenticated document proxy | Canonical | — | Authenticated | ${backendApiBase}/auth/google<br>${backendApiBase}/auth/refresh<br>${backendApiBase}/tenders/documents/${id}/download | KEEP; hardening findings apply |
| /api/ui-locale<br>frontend/app/api/ui-locale/route.ts | Validated locale-cookie write | Canonical | — | Public; handler-specific validation | — | KEEP; hardening findings apply |
| /dashboard/access-blocked<br>frontend/app/dashboard/access-blocked/page.tsx | Disabled/rejected account messaging | Canonical | — | Authenticated | /auth/logout | KEEP; hardening findings apply |
| /dashboard/admin/approvals<br>frontend/app/dashboard/admin/approvals/page.tsx | Legacy alias | Legacy | /admin/approvals | Operator/admin only | — | KEEP compatibility |
| /dashboard/admin<br>frontend/app/dashboard/admin/page.tsx | Legacy alias | Legacy | /admin | Operator/admin only | — | KEEP compatibility |
| /dashboard/bid-preparation/[proposalId]<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx | Proposal artifact editing/export | Canonical | — | Authenticated | /my-tenders/${engagement.engagement_id}/actions/${definition.path}<br>/proposals/${proposal.id}<br>/proposals/${proposal.id}/ai-draft<br>/proposals/${proposal.id}/export/docx<br>/proposals/${proposal.id}/generate-pdf<br>/proposals/${proposalId}/continue<br>/proposals/${resolvedParams.proposalId}<br>/proposals/prepare<br>/tenders/${tenderId}/documents<br>/tenders/${tenderId}/engagement<br>/tenders/documents/${docId}/download<br>/vault | KEEP; hardening findings apply |
| /dashboard/bid-preparation<br>frontend/app/dashboard/bid-preparation/page.tsx | Proposal artifact list | Canonical | — | Authenticated | /proposals<br>/proposals/${proposalId}/continue<br>/proposals/prepare | KEEP; hardening findings apply |
| /dashboard/bids/[id]<br>frontend/app/dashboard/bids/[id]/page.tsx | Legacy alias | Legacy | /dashboard/bid-preparation/${id} | Authenticated | /proposals/${id} | KEEP compatibility |
| /dashboard/bids<br>frontend/app/dashboard/bids/page.tsx | Legacy alias | Legacy | /dashboard/bid-preparation | Authenticated | — | KEEP compatibility |
| /dashboard/hunter<br>frontend/app/dashboard/hunter/page.tsx | Legacy alias | Legacy | /dashboard/tenders?view=recommended | Authenticated | — | KEEP compatibility |
| /dashboard/my-tenders<br>frontend/app/dashboard/my-tenders/page.tsx | Engagement-backed pursuit list | Canonical | — | Authenticated | /my-tenders/${engagement.engagement_id}/actions/${definition.path}<br>/proposals/${proposalId}/continue<br>/proposals/prepare<br>/tenders/${tenderId}/engagement<br>/tenders/sources/${encodeURIComponent(sourceSystem)}/refresh<br>/tenders/sources/catalog<br>/tenders/sources/refresh-activity<br>/tenders/sources/refresh-status | KEEP; hardening findings apply |
| /dashboard/onboarding<br>frontend/app/dashboard/onboarding/page.tsx | Pending-user company onboarding | Canonical | /dashboard/pending-approval | Authenticated | /api/ui-locale<br>/meta/geography<br>/meta/services<br>/users/me/company/onboarding<br>/users/me/preferences | KEEP; hardening findings apply |
| /dashboard<br>frontend/app/dashboard/page.tsx | Customer overview | Canonical | — | Authenticated | /meta/services<br>/tenders<br>/tenders/${tender.id}/latest-analysis<br>/tenders/sources/${encodeURIComponent(sourceSystem)}/refresh<br>/tenders/sources/catalog<br>/tenders/sources/refresh-activity<br>/tenders/sources/refresh-status<br>/users/me/company<br>/vault/readiness | KEEP; hardening findings apply |
| /dashboard/pending-approval<br>frontend/app/dashboard/pending-approval/page.tsx | Approval waiting/recovery | Canonical | /dashboard/access-blocked<br>/dashboard/onboarding<br>/dashboard | Authenticated | /auth/logout<br>/users/me/access-status | KEEP; hardening findings apply |
| /dashboard/proposals<br>frontend/app/dashboard/proposals/page.tsx | Legacy alias | Legacy | /dashboard/bid-preparation | Authenticated | — | KEEP compatibility |
| /dashboard/readiness-vault<br>frontend/app/dashboard/readiness-vault/page.tsx | Readiness records | Canonical | — | Authenticated | /meta/services<br>/vault/readiness<br>/vault/readiness/${document.id}<br>/vault/readiness/${editingId} | KEEP; hardening findings apply |
| /dashboard/settings<br>frontend/app/dashboard/settings/page.tsx | Company profile and preferences | Canonical | — | Authenticated | /api/ui-locale<br>/meta/geography<br>/meta/services<br>/users/me<br>/users/me/company<br>/users/me/preferences | KEEP; hardening findings apply |
| /dashboard/tenders/[tenderId]/compliance<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx | Versioned Compliance | Canonical | — | Authenticated | /tenders/${resolvedId}<br>/tenders/${resolvedId}/compiled-text<br>/tenders/${resolvedTenderId}/analyses/${analysisId}/versions<br>/tenders/${resolvedTenderId}/analyze?${query.toString()}<br>/tenders/${resolvedTenderId}/compliance/export/pdf${query}<br>/tenders/${resolvedTenderId}/documents<br>/tenders/${resolvedTenderId}/latest-analysis<br>/tenders/${resolvedTenderId}/overrides?analysis_id=${analysisId}<br>/tenders/${tenderId}/override<br>/users/me | KEEP; hardening findings apply |
| /dashboard/tenders/[tenderId]<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx | Tender Details | Canonical | — | Authenticated | /my-tenders/${engagement.engagement_id}/actions/${definition.path}<br>/proposals/${proposalId}/continue<br>/proposals/prepare<br>/tenders/${tenderId}<br>/tenders/${tenderId}/details<br>/tenders/${tenderId}/engagement<br>/tenders/documents/${item.document_id}/download<br>/tenders/sources/${encodeURIComponent(sourceSystem)}/refresh<br>/tenders/sources/catalog<br>/tenders/sources/refresh-activity<br>/tenders/sources/refresh-status | KEEP; hardening findings apply |
| /dashboard/tenders<br>frontend/app/dashboard/tenders/page.tsx | Explorer; all/recommended/dismissed | Canonical | /dashboard/tenders?${canonical} | Authenticated | /explorer/tenders<br>/meta/geography<br>/meta/services<br>/my-tenders/${engagement.engagement_id}/actions/${definition.path}<br>/proposals/${proposalId}/continue<br>/proposals/prepare<br>/recommendations/${recommendationId}/dismiss<br>/recommendations/${recommendationId}/restore<br>/tenders/${tenderId}/engagement<br>/tenders/sources/${encodeURIComponent(sourceSystem)}/refresh<br>/tenders/sources/catalog<br>/tenders/sources/refresh-activity<br>/tenders/sources/refresh-status | KEEP; hardening findings apply |
| /dashboard/workspace<br>frontend/app/dashboard/workspace/page.tsx | Legacy alias | Legacy | /dashboard/tenders | Authenticated | — | KEEP compatibility |
| /document-preview/[id]<br>frontend/app/document-preview/[id]/route.ts | Document preview proxy alias | Canonical | — | Authenticated | ${backendApiBase}/auth/google<br>${backendApiBase}/auth/refresh<br>${backendApiBase}/tenders/documents/${id}/download | KEEP; hardening findings apply |
| /<br>frontend/app/page.tsx | Google sign-in entry | Canonical | /dashboard | Public; handler-specific validation | — | KEEP; hardening findings apply |

Parent middleware/layout auth, locale and refresh dependencies are additional. A guard navigation destination is not itself a legacy redirect.

## Backend endpoints

| Method / path | Handler / source | Classification | Effective account guards | Matching frontend callsites | Decision |
| --- | --- | --- | --- | --- | --- |
| GET /api/v1/admin/activity | get_admin_activity<br>backend/app/api/endpoints/admin.py:317 | canonical operator | get_current_user<br>require_operator_or_admin | frontend/app/admin/page.tsx:44 | KEEP current contract |
| GET /api/v1/admin/audit-events | get_admin_audit_events<br>backend/app/api/endpoints/admin.py:390 | canonical operator | get_current_user<br>require_admin | frontend/app/admin/audit/page.tsx:91 | KEEP current contract |
| GET /api/v1/admin/corpus-health | get_admin_corpus_health<br>backend/app/api/endpoints/admin.py:443 | canonical operator | get_current_user<br>require_operator_or_admin | frontend/app/admin/page.tsx:45 | KEEP current contract |
| GET /api/v1/admin/accounts | get_admin_accounts<br>backend/app/api/endpoints/admin.py:570 | canonical operator | get_current_user<br>require_operator_or_admin | frontend/app/admin/approvals/page.tsx:81 | KEEP current contract |
| GET /api/v1/admin/approval-queue | get_approval_queue<br>backend/app/api/endpoints/admin.py:651 | canonical operator | get_current_user<br>require_operator_or_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/admin/companies/{company_profile_id} | get_admin_company_profile<br>backend/app/api/endpoints/admin.py:685 | canonical operator | get_current_user<br>require_operator_or_admin | frontend/app/admin/companies/[companyProfileId]/page.tsx:93 | KEEP current contract |
| GET /api/v1/admin/companies/{company_profile_id}/readiness | get_admin_company_readiness_documents<br>backend/app/api/endpoints/admin.py:715 | canonical operator | get_current_user<br>require_operator_or_admin | frontend/app/admin/companies/[companyProfileId]/page.tsx:94 | KEEP current contract |
| POST /api/v1/admin/users/{user_id}/approve | approve_user<br>backend/app/api/endpoints/admin.py:733 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/admin/users/{user_id}/reject | reject_user<br>backend/app/api/endpoints/admin.py:748 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/admin/users/{user_id}/disable | disable_user<br>backend/app/api/endpoints/admin.py:765 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/admin/users/{user_id}/restore | restore_user<br>backend/app/api/endpoints/admin.py:781 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/admin/companies/{company_profile_id}/approve | approve_company<br>backend/app/api/endpoints/admin.py:948 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/admin/companies/{company_profile_id}/reject | reject_company<br>backend/app/api/endpoints/admin.py:981 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/admin/companies/{company_profile_id}/disable | disable_company<br>backend/app/api/endpoints/admin.py:1013 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/admin/tenders/{source_system}/{external_id}/reproducibility | get_tender_reproducibility<br>backend/app/api/endpoints/admin.py:1123 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/auth/google | google_auth_bridge<br>backend/app/api/endpoints/auth.py:147 | customer/support | PUBLIC / no account guard | frontend/auth.ts:123 | KEEP current contract |
| POST /api/v1/auth/logout | logout<br>backend/app/api/endpoints/auth.py:234 | customer/support | PUBLIC / no account guard | frontend/app/admin/layout.tsx:48<br>frontend/app/dashboard/access-blocked/page.tsx:31<br>frontend/app/dashboard/layout.tsx:72<br>frontend/app/dashboard/pending-approval/page.tsx:75 | KEEP current contract |
| POST /api/v1/auth/refresh | refresh_token<br>backend/app/api/endpoints/auth.py:240 | customer/support | get_current_user | frontend/auth.ts:51 | KEEP current contract |
| GET /api/v1/explorer/tenders | get_explorer_tenders<br>backend/app/api/endpoints/explorer.py:39 | customer/support | get_current_user<br>require_explorer_access | frontend/lib/explorer.ts:11 | KEEP current contract |
| POST /api/v1/recommendations/{recommendation_id}/dismiss | dismiss_owned_recommendation<br>backend/app/api/endpoints/explorer.py:128 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/lib/explorer.ts:14 | KEEP current contract |
| POST /api/v1/recommendations/{recommendation_id}/restore | restore_owned_recommendation<br>backend/app/api/endpoints/explorer.py:145 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/lib/explorer.ts:19 | KEEP current contract |
| GET /api/v1/hunter | list_recommendations<br>backend/app/api/endpoints/hunter.py:69 | legacy compatibility | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/hunter/ | list_recommendations<br>backend/app/api/endpoints/hunter.py:69 | legacy compatibility | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/hunter/{recommendation_id}/dismiss | dismiss_recommendation<br>backend/app/api/endpoints/hunter.py:132 | legacy compatibility | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/meta/geography | get_geography_meta<br>backend/app/api/endpoints/meta.py:25 | customer/support | PUBLIC / no account guard | frontend/lib/geography.ts:108 | KEEP current contract |
| GET /api/v1/meta/services | get_services_meta<br>backend/app/api/endpoints/meta.py:30 | customer/support | PUBLIC / no account guard | frontend/lib/services.ts:73 | KEEP current contract |
| GET /api/v1/my-tenders | get_my_tenders<br>backend/app/api/endpoints/my_tenders.py:105 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/my-tenders/{engagement_id} | get_my_tender<br>backend/app/api/endpoints/my_tenders.py:134 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/engagement | get_tender_engagement_for_current_user<br>backend/app/api/endpoints/my_tenders.py:158 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/components/tenders/TenderEngagementPanel.tsx:54 | KEEP current contract |
| POST /api/v1/tenders/{tender_id}/engagement | save_tender_for_current_user<br>backend/app/api/endpoints/my_tenders.py:189 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/components/tenders/EngagementWorkflowActions.tsx:145<br>frontend/components/tenders/TenderEngagementPanel.tsx:81 | KEEP current contract |
| POST /api/v1/my-tenders/{engagement_id}/actions/{action} | apply_tender_engagement_action<br>backend/app/api/endpoints/my_tenders.py:236 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/components/tenders/EngagementWorkflowActions.tsx:112 | KEEP current contract |
| POST /api/v1/proposals | create_proposal<br>backend/app/api/endpoints/proposals.py:203 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/proposals/prepare | prepare_bid_for_tender<br>backend/app/api/endpoints/proposals.py:240 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/components/bid-preparation/PrepareBidButton.tsx:48 | KEEP current contract |
| POST /api/v1/proposals/{proposal_id}/continue | continue_owned_bid_preparation<br>backend/app/api/endpoints/proposals.py:278 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/components/bid-preparation/PrepareBidButton.tsx:45 | KEEP current contract |
| GET /api/v1/proposals | list_proposals<br>backend/app/api/endpoints/proposals.py:311 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/page.tsx:38 | KEEP current contract |
| GET /api/v1/proposals/{proposal_id} | get_proposal<br>backend/app/api/endpoints/proposals.py:346 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:271<br>frontend/app/dashboard/bids/[id]/page.tsx:19 | KEEP current contract |
| PUT /api/v1/proposals/{proposal_id} | update_proposal<br>backend/app/api/endpoints/proposals.py:392 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:516 | KEEP current contract |
| POST /api/v1/proposals/{proposal_id}/ai-draft | ai_draft_proposal<br>backend/app/api/endpoints/proposals.py:485 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:361 | KEEP current contract |
| POST /api/v1/proposals/{proposal_id}/upload-tz | upload_tender_tz<br>backend/app/api/endpoints/proposals.py:750 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/proposals/{proposal_id}/uploaded-tz | get_uploaded_tz<br>backend/app/api/endpoints/proposals.py:918 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/proposals/{proposal_id}/generate-pdf | generate_proposal_pdf<br>backend/app/api/endpoints/proposals.py:976 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:547 | KEEP current contract |
| POST /api/v1/proposals/{proposal_id}/export/docx | export_proposal_docx<br>backend/app/api/endpoints/proposals.py:1310 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:569 | KEEP current contract |
| POST /api/v1/tenders/{tender_id}/analyze | analyze_tender<br>backend/app/api/endpoints/tenders.py:3886 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:561 | KEEP current contract |
| POST /api/v1/tenders/test-scrape | test_scrape<br>backend/app/api/endpoints/tenders.py:4674 | dangerous operator probe | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/proxy-download | proxy_download<br>backend/app/api/endpoints/tenders.py:4709 | dangerous operator probe | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/documents/{doc_id}/download | download_document<br>backend/app/api/endpoints/tenders.py:4740 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:417<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:462<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:346<br>frontend/lib/documentProxy.ts:47 | KEEP current contract |
| GET /api/v1/tenders | list_tenders<br>backend/app/api/endpoints/tenders.py:4865 | customer/support | PUBLIC / no account guard | frontend/app/dashboard/page.tsx:397<br>frontend/app/dashboard/page.tsx:398 | H02: add backend guard in 9.3; live callers remain |
| GET /api/v1/tenders/{tender_id}/details | get_tender_details<br>backend/app/api/endpoints/tenders.py:4972 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/tenders/[tenderId]/page.tsx:311 | KEEP current contract |
| GET /api/v1/tenders/{tender_id} | get_tender<br>backend/app/api/endpoints/tenders.py:5039 | customer/support | PUBLIC / no account guard | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:424<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:296 | H02: add backend guard in 9.3; live callers remain |
| GET /api/v1/tenders/{tender_id}/project | get_tender_project_context<br>backend/app/api/endpoints/tenders.py:5109 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/decision-snapshot | get_tender_decision_snapshot<br>backend/app/api/endpoints/tenders.py:5258 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/competitors | get_tender_competitors<br>backend/app/api/endpoints/tenders.py:5336 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/compiled-text | get_tender_compiled_text<br>backend/app/api/endpoints/tenders.py:5385 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:443 | KEEP current contract |
| POST /api/v1/tenders/refresh | refresh_tenders<br>backend/app/api/endpoints/tenders.py:5485 | legacy compatibility | get_current_user<br>require_approved_user | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/sources/giz/hydrate | hydrate_giz_tenders<br>backend/app/api/endpoints/tenders.py:6660 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/sources/{source_system}/refresh | request_source_refresh<br>backend/app/api/endpoints/tenders.py:7694 | customer/support | get_current_user<br>require_approved_user | frontend/lib/sourceRefresh.ts:27 | KEEP current contract |
| POST /api/v1/tenders/sources/world-bank/sync | request_world_bank_sync<br>backend/app/api/endpoints/tenders.py:7718 | legacy compatibility | get_current_user<br>require_operator_or_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/sources/giz/sync | request_giz_sync<br>backend/app/api/endpoints/tenders.py:7743 | legacy compatibility | get_current_user<br>require_operator_or_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/sources/ebrd/sync | request_ebrd_sync<br>backend/app/api/endpoints/tenders.py:7766 | legacy compatibility | get_current_user<br>require_operator_or_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/sources/adb/sync | request_adb_sync<br>backend/app/api/endpoints/tenders.py:7791 | legacy compatibility | get_current_user<br>require_operator_or_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/sources/catalog | get_source_catalog<br>backend/app/api/endpoints/tenders.py:7818 | customer/support | get_current_user<br>require_approved_user | frontend/lib/sourceRefresh.ts:15 | KEEP current contract |
| GET /api/v1/tenders/sources/refresh-status | get_source_refresh_status<br>backend/app/api/endpoints/tenders.py:7829 | customer/support | get_current_user<br>require_approved_user | frontend/lib/sourceRefresh.ts:18 | KEEP current contract |
| GET /api/v1/tenders/sources/refresh-activity | get_source_refresh_activity<br>backend/app/api/endpoints/tenders.py:7841 | customer/support | get_current_user<br>require_approved_user | frontend/lib/sourceRefresh.ts:21 | KEEP current contract |
| POST /api/v1/tenders/{tender_id}/sync-docs | sync_tender_documents<br>backend/app/api/endpoints/tenders.py:8079 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/sync-status | get_sync_status<br>backend/app/api/endpoints/tenders.py:8236 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/documents | get_tender_documents<br>backend/app/api/endpoints/tenders.py:8311 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:262<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:466 | KEEP current contract |
| GET /api/v1/tenders/{tender_id}/latest-analysis | get_latest_analysis<br>backend/app/api/endpoints/tenders.py:8349 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/page.tsx:342<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:485 | KEEP current contract |
| GET /api/v1/tenders/{tender_id}/analyses/{analysis_id}/versions | get_analysis_versions<br>backend/app/api/endpoints/tenders.py:8663 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:510 | KEEP current contract |
| GET /api/v1/tenders/{tender_id}/analyses/{analysis_id}/versions/{version_number} | get_analysis_version_detail<br>backend/app/api/endpoints/tenders.py:8698 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/tenders/{tender_id}/compliance/export/pdf | export_compliance_pdf<br>backend/app/api/endpoints/tenders.py:8736 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /api/v1/tenders/{tender_id}/override | override_risk<br>backend/app/api/endpoints/tenders.py:8927 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:1619 | KEEP current contract |
| GET /api/v1/tenders/{tender_id}/overrides | get_risk_overrides<br>backend/app/api/endpoints/tenders.py:9067 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:526 | KEEP current contract |
| POST /api/v1/tenders/seed | seed_tenders<br>backend/app/api/endpoints/tenders.py:9131 | dangerous operator probe | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/users/me | get_current_user_info<br>backend/app/api/endpoints/users.py:142 | customer/support | get_current_user<br>get_current_user_info | frontend/app/dashboard/settings/page.tsx:131<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:407<br>frontend/middleware.ts:51 | KEEP current contract |
| PATCH /api/v1/users/me/preferences | update_current_user_preferences<br>backend/app/api/endpoints/users.py:157 | customer/support | get_current_user | frontend/app/dashboard/settings/page.tsx:153<br>frontend/i18n/userLocale.ts:12 | KEEP current contract |
| GET /api/v1/users/me/access-status | get_access_status<br>backend/app/api/endpoints/users.py:185 | customer/support | get_current_user | frontend/app/dashboard/layout.tsx:91<br>frontend/app/dashboard/pending-approval/page.tsx:33 | KEEP current contract |
| POST /api/v1/users/admin/upgrade-me | upgrade_to_agent<br>backend/app/api/endpoints/users.py:236 | canonical operator | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/users/me/company | get_company_profile<br>backend/app/api/endpoints/users.py:468 | customer/support | get_current_user | frontend/app/dashboard/page.tsx:388<br>frontend/app/dashboard/settings/page.tsx:115 | KEEP current contract |
| PUT /api/v1/users/me/company | update_company_profile<br>backend/app/api/endpoints/users.py:486 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/settings/page.tsx:214 | KEEP current contract |
| POST /api/v1/users/me/company/onboarding | submit_company_onboarding<br>backend/app/api/endpoints/users.py:514 | customer/support | get_current_user | frontend/app/dashboard/onboarding/page.tsx:110 | KEEP current contract |
| GET /api/v1/vault | get_company_vault<br>backend/app/api/endpoints/vault.py:136 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:317 | KEEP current contract |
| PUT /api/v1/vault | update_company_vault<br>backend/app/api/endpoints/vault.py:150 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/vault/readiness | list_readiness_documents<br>backend/app/api/endpoints/vault.py:239 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/page.tsx:396<br>frontend/app/dashboard/readiness-vault/page.tsx:197 | KEEP current contract |
| POST /api/v1/vault/readiness | create_readiness_document<br>backend/app/api/endpoints/vault.py:260 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/readiness-vault/page.tsx:276 | KEEP current contract |
| PUT /api/v1/vault/readiness/{document_id} | update_readiness_document<br>backend/app/api/endpoints/vault.py:280 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/readiness-vault/page.tsx:266 | KEEP current contract |
| DELETE /api/v1/vault/readiness/{document_id} | delete_readiness_document<br>backend/app/api/endpoints/vault.py:302 | customer/support | get_current_user<br>require_approved_pilot_access | frontend/app/dashboard/readiness-vault/page.tsx:304 | KEEP current contract |
| POST /api/v1/audit/authorize | authorize_risk<br>backend/app/api/routers/audit.py:28 | customer/support | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| POST /audit/authorize | authorize_risk<br>backend/app/api/routers/audit.py:28 | legacy compatibility | get_current_user<br>require_approved_pilot_access | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /health | health_check<br>backend/app/main.py:90 | customer/support | PUBLIC / no account guard | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/health/version | health_version<br>backend/app/main.py:101 | customer/support | PUBLIC / no account guard | — | INVESTIGATE external/operator/internal use; no removal proof |
| GET /api/v1/health/version/internal | health_version_internal<br>backend/app/main.py:107 | customer/support | get_current_user<br>require_admin | — | INVESTIGATE external/operator/internal use; no removal proof |

Template matching is conservative; unmatched wrappers/props and external clients require manual review. Public metadata/health and the login bridge must not be confused with accidentally unguarded customer APIs.

## Frontend API clients

| Function hint / callsite | Method / endpoint | Module importers | Contract | Duplicate / removal |
| --- | --- | --- | --- | --- |
| response<br>frontend/app/admin/approvals/page.tsx:81 | GET /admin/accounts | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/admin/audit/page.tsx:91 | GET /admin/audit-events | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| loadCompany<br>frontend/app/admin/companies/[companyProfileId]/page.tsx:93 | GET /admin/companies/${companyProfileId} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| loadCompany<br>frontend/app/admin/companies/[companyProfileId]/page.tsx:94 | GET /admin/companies/${companyProfileId}/readiness | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| handleLogout<br>frontend/app/admin/layout.tsx:48 | POST /auth/logout | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| loadOverview<br>frontend/app/admin/page.tsx:44 | GET /admin/activity | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| loadOverview<br>frontend/app/admin/page.tsx:45 | GET /admin/corpus-health | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| handleLogout<br>frontend/app/dashboard/access-blocked/page.tsx:31 | POST /auth/logout | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:262 | GET /tenders/${tenderId}/documents | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:271 | GET /proposals/${resolvedParams.proposalId} | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| res<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:317 | GET /vault | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:361 | POST /proposals/${proposal.id}/ai-draft | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:417 | GET /tenders/documents/${docId}/download | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:462 | GET /tenders/documents/${docId}/download | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| priceNum<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:516 | PUT /proposals/${proposal.id} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:547 | POST /proposals/${proposal.id}/generate-pdf | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:569 | POST /proposals/${proposal.id}/export/docx | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/bid-preparation/page.tsx:38 | GET /proposals | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| active<br>frontend/app/dashboard/bids/[id]/page.tsx:19 | GET /proposals/${id} | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| handleLogout<br>frontend/app/dashboard/layout.tsx:72 | POST /auth/logout | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/layout.tsx:91 | GET /users/me/access-status | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| handleSubmit<br>frontend/app/dashboard/onboarding/page.tsx:110 | POST /users/me/company/onboarding | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/page.tsx:342 | GET /tenders/${tender.id}/latest-analysis | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| profileResult<br>frontend/app/dashboard/page.tsx:388 | GET /users/me/company | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| profileResult<br>frontend/app/dashboard/page.tsx:396 | GET /vault/readiness | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| profileResult<br>frontend/app/dashboard/page.tsx:397 | GET /tenders | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| profileResult<br>frontend/app/dashboard/page.tsx:398 | GET /tenders | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/pending-approval/page.tsx:33 | GET /users/me/access-status | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| handleLogout<br>frontend/app/dashboard/pending-approval/page.tsx:75 | POST /auth/logout | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/readiness-vault/page.tsx:197 | GET /vault/readiness | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/readiness-vault/page.tsx:266 | PUT /vault/readiness/${editingId} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/readiness-vault/page.tsx:276 | POST /vault/readiness | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| confirmed<br>frontend/app/dashboard/readiness-vault/page.tsx:304 | DELETE /vault/readiness/${document.id} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/settings/page.tsx:115 | GET /users/me/company | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| active<br>frontend/app/dashboard/settings/page.tsx:131 | GET /users/me | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| saveAnalysisLanguage<br>frontend/app/dashboard/settings/page.tsx:153 | PATCH /users/me/preferences | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/settings/page.tsx:214 | PUT /users/me/company | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| active<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:407 | GET /users/me | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| resolvedId<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:424 | GET /tenders/${resolvedId} | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| textResponse<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:443 | GET /tenders/${resolvedId}/compiled-text | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| fetchTenderDocuments<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:466 | GET /tenders/${resolvedTenderId}/documents | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| fetchCachedAnalysis<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:485 | GET /tenders/${resolvedTenderId}/latest-analysis | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| active<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:510 | GET /tenders/${resolvedTenderId}/analyses/${analysisId}/versions | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| fetchOverrides<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:526 | GET /tenders/${resolvedTenderId}/overrides?analysis_id=${analysisId} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| query<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:561 | POST /tenders/${resolvedTenderId}/analyze?${query.toString()} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:591 | GET /tenders/${resolvedTenderId}/compliance/export/pdf${query} | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| handleSubmit<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:1619 | POST /tenders/${tenderId}/override | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:296 | GET /tenders/${tenderId} | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:311 | GET /tenders/${tenderId}/details | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:346 | GET /tenders/documents/${item.document_id}/download | — | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| refreshResponse<br>frontend/auth.ts:51 | FETCH ${backendApiBase}/auth/refresh | frontend/app/api/auth/[...nextauth]/route.ts<br>frontend/lib/documentProxy.ts | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/auth.ts:123 | FETCH ${backendApiBase}/auth/google | frontend/app/api/auth/[...nextauth]/route.ts<br>frontend/lib/documentProxy.ts | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/components/bid-preparation/PrepareBidButton.tsx:45 | POST /proposals/${proposalId}/continue | frontend/app/dashboard/bid-preparation/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/tenders/EngagementWorkflowActions.tsx<br>frontend/components/tenders/TenderEngagementPanel.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/components/bid-preparation/PrepareBidButton.tsx:48 | POST /proposals/prepare | frontend/app/dashboard/bid-preparation/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/tenders/EngagementWorkflowActions.tsx<br>frontend/components/tenders/TenderEngagementPanel.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/components/tenders/EngagementWorkflowActions.tsx:112 | POST /my-tenders/${engagement.engagement_id}/actions/${definition.path} | frontend/app/dashboard/my-tenders/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/tenders/TenderEngagementPanel.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/components/tenders/EngagementWorkflowActions.tsx:145 | POST /tenders/${tenderId}/engagement | frontend/app/dashboard/my-tenders/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/tenders/TenderEngagementPanel.tsx | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/components/tenders/TenderEngagementPanel.tsx:54 | GET /tenders/${tenderId}/engagement | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| response<br>frontend/components/tenders/TenderEngagementPanel.tsx:81 | POST /tenders/${tenderId}/engagement | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/i18n/userLocale.ts:12 | PATCH /users/me/preferences | frontend/components/i18n/LanguageSelector.tsx | Shared Axios or server fetch; see matching endpoint | Repeated endpoint callsites; KEEP until caller migration |
| response<br>frontend/i18n/userLocale.ts:24 | FETCH /api/ui-locale | frontend/components/i18n/LanguageSelector.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| accessToken<br>frontend/lib/documentProxy.ts:47 | FETCH ${backendApiBase}/tenders/documents/${id}/download | frontend/app/api/documents/[id]/route.ts<br>frontend/app/document-preview/[id]/route.ts | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| listExplorer<br>frontend/lib/explorer.ts:11 | GET /explorer/tenders | frontend/app/dashboard/tenders/page.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| dismissRecommendation<br>frontend/lib/explorer.ts:14 | POST /recommendations/${recommendationId}/dismiss | frontend/app/dashboard/tenders/page.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| restoreRecommendation<br>frontend/lib/explorer.ts:19 | POST /recommendations/${recommendationId}/restore | frontend/app/dashboard/tenders/page.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| mounted<br>frontend/lib/geography.ts:108 | GET /meta/geography | frontend/app/dashboard/onboarding/page.tsx<br>frontend/app/dashboard/settings/page.tsx<br>frontend/app/dashboard/tenders/page.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| mounted<br>frontend/lib/services.ts:73 | GET /meta/services | frontend/app/admin/companies/[companyProfileId]/page.tsx<br>frontend/app/dashboard/onboarding/page.tsx<br>frontend/app/dashboard/page.tsx<br>frontend/app/dashboard/readiness-vault/page.tsx<br>frontend/app/dashboard/settings/page.tsx<br>frontend/app/dashboard/settings/page.tsx<br>frontend/app/dashboard/tenders/page.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| listSourceCatalog<br>frontend/lib/sourceRefresh.ts:15 | GET /tenders/sources/catalog | frontend/components/source-refresh/SourceRefreshProvider.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| listSourceRefreshStatus<br>frontend/lib/sourceRefresh.ts:18 | GET /tenders/sources/refresh-status | frontend/components/source-refresh/SourceRefreshProvider.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| listSourceRefreshActivity<br>frontend/lib/sourceRefresh.ts:21 | GET /tenders/sources/refresh-activity | frontend/components/source-refresh/SourceRefreshProvider.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| requestSourceRefresh<br>frontend/lib/sourceRefresh.ts:27 | POST /tenders/sources/${encodeURIComponent(sourceSystem)}/refresh | frontend/components/source-refresh/SourceRefreshProvider.tsx | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |
| authorityResponse<br>frontend/middleware.ts:51 | FETCH ${backendApiBase}/users/me | — | Shared Axios or server fetch; see matching endpoint | Single observed callsite; KEEP until caller migration |

Function hints are nearest lexical declaration names; source location is authoritative. Repeated calls across pages are not necessarily duplicate wrappers. Only one Axios instance is defined.

## ORM models

| Model / table | Source | Classification | Runtime reference files |
| --- | --- | --- | --- |
| Project / projects | backend/app/models/all_models.py:56 | Active support; no table deletion proof | backend/app/api/endpoints/tenders.py:104<br>backend/app/schemas/project.py:67<br>backend/app/services/my_tenders.py:12<br>backend/app/services/project_enrichment.py:1<br>backend/app/services/projects.py:1<br>backend/app/services/tender_details.py:16<br>backend/app/services/tender_sources/adb.py:974<br>backend/app/services/tender_sources/ebrd.py:96<br>backend/app/services/tender_sources/world_bank.py:669<br>backend/app/services/world_bank_projects.py:281<br>backend/app/workers/project_enrichment_tasks.py:1<br>frontend/types/project.ts:83 |
| Tender / tenders | backend/app/models/all_models.py:160 | Canonical domain | backend/app/api/endpoints/admin.py:38<br>backend/app/api/endpoints/explorer.py:1<br>backend/app/api/endpoints/hunter.py:4<br>backend/app/api/endpoints/my_tenders.py:149<br>backend/app/api/endpoints/proposals.py:51<br>backend/app/api/endpoints/tenders.py:4<br>backend/app/core/agents/hunter.py:21<br>backend/app/core/agents/requirement_extractor.py:2<br>backend/app/core/agents/strategy_extractor.py:2<br>backend/app/core/ai.py:417<br>backend/app/core/ai_analyzer.py:92<br>backend/app/core/compliance_pdf.py:53<br>backend/app/core/pdf_generator.py:155<br>backend/app/core/scraper.py:2<br>backend/app/core/tender_actionability.py:11<br>backend/app/core/tender_newness.py:1<br>backend/app/main.py:56<br>backend/app/models/audit.py:121<br>backend/app/models/engagement.py:73<br>backend/app/models/taxonomy.py:144<br>backend/app/schemas/explorer.py:1<br>backend/app/schemas/project.py:67<br>backend/app/schemas/tender.py:2<br>backend/app/schemas/tender_details.py:1<br>backend/app/services/analysis_versions.py:26<br>backend/app/services/bid_preparation.py:13<br>backend/app/services/explorer.py:1<br>backend/app/services/giz_document_hydration.py:24<br>backend/app/services/my_tenders.py:12<br>backend/app/services/projects.py:16<br>backend/app/services/tender_details.py:1<br>backend/app/services/tender_engagements.py:13<br>backend/app/services/tender_sources/__init__.py:1<br>backend/app/services/tender_sources/adb.py:1031<br>backend/app/services/tender_sources/base.py:16<br>backend/app/services/tender_sources/ebrd.py:71<br>backend/app/services/tender_sources/giz.py:411<br>backend/app/services/tender_sources/uzex.py:10<br>backend/app/workers/hunter_tasks.py:14<br>backend/app/workers/tender_tasks.py:28<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:342<br>frontend/app/dashboard/hunter/page.tsx:7<br>frontend/app/dashboard/page.tsx:31<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:16<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:58<br>frontend/app/page.tsx:139<br>frontend/types/tender.ts:24 |
| TenderProject / tender_projects | backend/app/models/all_models.py:281 | Active support; no table deletion proof | backend/app/api/endpoints/tenders.py:111<br>backend/app/services/my_tenders.py:12<br>backend/app/services/project_enrichment.py:18<br>backend/app/services/projects.py:1<br>backend/app/services/tender_details.py:21<br>backend/app/services/tender_sources/world_bank.py:669 |
| ProjectRoleAssignment / project_role_assignments | backend/app/models/all_models.py:323 | Active support; no table deletion proof | backend/app/services/project_enrichment.py:18<br>backend/app/services/tender_details.py:17 |
| TenderSyncJob / tender_sync_jobs | backend/app/models/all_models.py:406 | Active support; no table deletion proof | backend/app/api/endpoints/tenders.py:113<br>backend/app/workers/tender_tasks.py:28 |
| SourceRefreshJob / source_refresh_jobs | backend/app/models/all_models.py:482 | Canonical domain | backend/app/api/endpoints/tenders.py:107<br>backend/app/services/source_refresh_activity.py:16<br>backend/app/services/source_refresh_jobs.py:15<br>backend/app/workers/source_refresh_tasks.py:13 |
| TenderDocument / tender_documents | backend/app/models/all_models.py:608 | Active support; no table deletion proof | backend/app/api/endpoints/tenders.py:110<br>backend/app/services/analysis_versions.py:26<br>backend/app/services/giz_document_hydration.py:24<br>backend/app/services/tender_details.py:20<br>backend/app/services/tender_sources/base.py:16<br>backend/app/services/tender_sources/ebrd.py:18<br>backend/app/services/tender_sources/giz.py:20<br>backend/app/workers/tender_tasks.py:28<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:35<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:16<br>frontend/types/tender.ts:79 |
| Proposal / proposals | backend/app/models/all_models.py:656 | Canonical domain | backend/app/api/endpoints/admin.py:38<br>backend/app/api/endpoints/my_tenders.py:16<br>backend/app/api/endpoints/proposals.py:46<br>backend/app/api/endpoints/tenders.py:105<br>backend/app/api/endpoints/users.py:476<br>backend/app/core/ai.py:339<br>backend/app/core/pdf_generator.py:58<br>backend/app/models/user.py:114<br>backend/app/schemas/proposal.py:2<br>backend/app/services/bid_preparation.py:1<br>backend/app/services/tender_details.py:18<br>frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:46 |
| TenderAnalysis / tender_analyses | backend/app/models/audit.py:59 | Canonical domain | backend/app/api/endpoints/admin.py:38<br>backend/app/api/endpoints/tenders.py:102<br>backend/app/api/routers/audit.py:18<br>backend/app/models/all_models.py:248<br>backend/app/models/taxonomy.py:201<br>backend/app/services/analysis_aggregates.py:12<br>backend/app/services/analysis_versions.py:36<br>backend/app/workers/tender_tasks.py:30 |
| AnalysisVersion / analysis_versions | backend/app/models/audit.py:152 | Canonical domain | backend/app/api/endpoints/admin.py:39<br>backend/app/api/endpoints/tenders.py:102<br>backend/app/models/all_models.py:744<br>backend/app/schemas/analysis_version.py:1<br>backend/app/services/analysis_versions.py:34 |
| AnalysisVersionDocumentSnapshot / analysis_version_document_snapshots | backend/app/models/audit.py:297 | Active support; no table deletion proof | backend/app/models/all_models.py:745<br>backend/app/services/analysis_versions.py:35 |
| AuditLog / audit_logs | backend/app/models/audit.py:358 | Active support; no table deletion proof | backend/app/core/security/audit_trail.py:17<br>backend/app/models/all_models.py:746 |
| AdminActivityEvent / admin_activity_events | backend/app/models/audit.py:400 | Active support; no table deletion proof | backend/app/api/endpoints/admin.py:38<br>backend/app/models/all_models.py:743<br>backend/app/services/admin_activity.py:13 |
| TenderRecommendation / tender_recommendations | backend/app/models/audit.py:471 | Canonical domain | backend/app/api/endpoints/hunter.py:22<br>backend/app/models/all_models.py:748<br>backend/app/services/explorer.py:22<br>backend/app/services/recommendations.py:10<br>backend/app/workers/hunter_tasks.py:23 |
| CompanyProfile / company_profiles | backend/app/models/company.py:37 | Canonical domain | backend/app/api/deps.py:25<br>backend/app/api/endpoints/admin.py:40<br>backend/app/api/endpoints/auth.py:34<br>backend/app/api/endpoints/hunter.py:23<br>backend/app/api/endpoints/my_tenders.py:18<br>backend/app/api/endpoints/proposals.py:56<br>backend/app/api/endpoints/tenders.py:117<br>backend/app/api/endpoints/users.py:36<br>backend/app/api/endpoints/vault.py:15<br>backend/app/api/routers/audit.py:19<br>backend/app/core/agents/hunter.py:22<br>backend/app/crud/crud_profile.py:4<br>backend/app/crud/exceptions.py:21<br>backend/app/models/all_models.py:752<br>backend/app/models/audit.py:508<br>backend/app/models/engagement.py:69<br>backend/app/models/taxonomy.py:105<br>backend/app/models/user.py:119<br>backend/app/services/analysis_aggregates.py:12<br>backend/app/services/bid_preparation.py:19<br>backend/app/services/compliance_engine.py:17<br>backend/app/services/explorer.py:23<br>backend/app/services/recommendations.py:11<br>backend/app/services/tender_details.py:25<br>backend/app/services/tender_engagements.py:13<br>backend/app/workers/hunter_tasks.py:15<br>frontend/app/dashboard/page.tsx:42<br>frontend/app/dashboard/settings/page.tsx:19 |
| Certification / certifications | backend/app/models/company.py:145 | Active support; no table deletion proof | backend/app/api/endpoints/vault.py:14<br>backend/app/models/all_models.py:751<br>backend/app/services/tender_details.py:24 |
| License / licenses | backend/app/models/company.py:172 | Active support; no table deletion proof | backend/app/api/endpoints/vault.py:17<br>backend/app/core/ai.py:435<br>backend/app/core/ai_analyzer.py:318<br>backend/app/models/all_models.py:754<br>backend/app/services/tender_details.py:27<br>frontend/lib/readiness.ts:10 |
| FinancialHistory / financial_history | backend/app/models/company.py:198 | Active support; no table deletion proof | backend/app/api/endpoints/vault.py:16<br>backend/app/models/all_models.py:753<br>backend/app/services/tender_details.py:26 |
| ReadinessDocument / readiness_documents | backend/app/models/company.py:226 | Active support; no table deletion proof | backend/app/api/endpoints/admin.py:40<br>backend/app/api/endpoints/vault.py:18<br>backend/app/models/all_models.py:755<br>backend/app/services/tender_details.py:28<br>frontend/app/admin/companies/[companyProfileId]/page.tsx:34<br>frontend/app/dashboard/page.tsx:53<br>frontend/app/dashboard/readiness-vault/page.tsx:31 |
| TenderEngagement / tender_engagements | backend/app/models/engagement.py:19 | Canonical domain | backend/app/api/endpoints/my_tenders.py:16<br>backend/app/api/endpoints/proposals.py:52<br>backend/app/models/all_models.py:757<br>backend/app/services/bid_preparation.py:1<br>backend/app/services/explorer.py:24<br>backend/app/services/my_tenders.py:14<br>backend/app/services/tender_engagements.py:13 |
| TaxonomyNode / taxonomy_nodes | backend/app/models/taxonomy.py:38 | Active support; no table deletion proof | backend/app/api/endpoints/proposals.py:50<br>backend/app/api/endpoints/tenders.py:108<br>backend/app/models/__init__.py:2<br>backend/app/models/all_models.py:762<br>backend/app/workers/hunter_tasks.py:16 |
| CompanyCredential / company_credentials | backend/app/models/taxonomy.py:82 | Active support; no table deletion proof | backend/app/api/endpoints/tenders.py:118<br>backend/app/core/evaluator.py:63<br>backend/app/models/__init__.py:2<br>backend/app/models/all_models.py:759<br>backend/app/services/compliance_engine.py:12<br>backend/app/services/tender_details.py:30<br>backend/app/workers/hunter_tasks.py:16 |
| TenderRequirement / tender_requirements | backend/app/models/taxonomy.py:122 | Active support; no table deletion proof | backend/app/core/agents/requirement_extractor.py:131<br>backend/app/models/__init__.py:2<br>backend/app/models/all_models.py:763<br>backend/app/services/analysis_language_content.py:12<br>backend/app/services/compliance_engine.py:6 |
| RiskOverrideLog / risk_override_logs | backend/app/models/taxonomy.py:161 | Active support; no table deletion proof | backend/app/api/endpoints/proposals.py:48<br>backend/app/api/endpoints/tenders.py:106<br>backend/app/models/__init__.py:2<br>backend/app/models/all_models.py:760 |
| User / users | backend/app/models/user.py:23 | Canonical domain | backend/app/api/deps.py:24<br>backend/app/api/endpoints/admin.py:38<br>backend/app/api/endpoints/auth.py:33<br>backend/app/api/endpoints/explorer.py:14<br>backend/app/api/endpoints/hunter.py:21<br>backend/app/api/endpoints/my_tenders.py:16<br>backend/app/api/endpoints/proposals.py:54<br>backend/app/api/endpoints/tenders.py:115<br>backend/app/api/endpoints/users.py:35<br>backend/app/api/endpoints/vault.py:12<br>backend/app/api/routers/audit.py:17<br>backend/app/cli/admin_management.py:152<br>backend/app/core/security.py:18<br>backend/app/core/security/__init__.py:18<br>backend/app/main.py:21<br>backend/app/models/all_models.py:462<br>backend/app/models/base.py:17<br>backend/app/models/company.py:99<br>backend/app/models/engagement.py:68<br>backend/app/models/taxonomy.py:199<br>backend/app/services/account_lifecycle.py:19<br>backend/app/services/admin_activity.py:13<br>backend/app/services/admin_survivability.py:16<br>backend/app/services/giz_document_hydration.py:915<br>backend/app/services/tender_sources/adb.py:1205<br>backend/app/services/tender_sources/ebrd.py:549<br>backend/app/services/tender_sources/giz.py:925<br>backend/app/services/tender_sources/world_bank.py:481<br>backend/app/services/world_bank_projects.py:304<br>backend/app/workers/tender_tasks.py:112<br>frontend/app/admin/approvals/page.tsx:240<br>frontend/app/admin/companies/[companyProfileId]/page.tsx:156<br>frontend/app/admin/layout.tsx:136<br>frontend/lib/adminOperations.ts:47<br>frontend/types/next-auth.d.ts:25 |

## Schemas and types

| Name / bases | Source | Classification | Same-module lines | Runtime refs | Tests/tool refs |
| --- | --- | --- | --- | --- | --- |
| ApprovalActionRequest (BaseModel) | backend/app/api/endpoints/admin.py:85 | active referenced | 750<br>767<br>783<br>983<br>1015 | — | backend/test_s0_2_disabled_authorization.py:23<br>backend/test_s3_1_admin_account_lifecycle.py:15<br>backend/test_s3_3_privileged_account_survivability.py:11 |
| ApprovalQueueCompany (BaseModel) | backend/app/api/endpoints/admin.py:89 | active referenced | 952<br>986<br>1018<br>268<br>116<br>132<br>271<br>947<br>980<br>1012 | — | — |
| ApprovalQueueUser (BaseModel) | backend/app/api/endpoints/admin.py:102 | active referenced | 250<br>737<br>753<br>770<br>786<br>804<br>115<br>251<br>732<br>747<br>764<br>780 | — | — |
| ApprovalQueueItem (BaseModel) | backend/app/api/endpoints/admin.py:114 | active referenced | 120<br>671 | — | — |
| ApprovalQueueResponse (BaseModel) | backend/app/api/endpoints/admin.py:119 | active referenced | 653<br>669<br>648 | — | — |
| AdminAccountItem (BaseModel) | backend/app/api/endpoints/admin.py:123 | active referenced | 554<br>137<br>555 | — | backend/test_s3_5_admin_operational_ux_hardening.py:9 |
| AdminAccountsPage (BaseModel) | backend/app/api/endpoints/admin.py:136 | active referenced | 578<br>635<br>569 | frontend/app/admin/approvals/page.tsx:14<br>frontend/lib/adminOperations.ts:29 | backend/test_s1_admin_approval_queue.py:68 |
| AdminCompanyResponse (BaseModel) | backend/app/api/endpoints/admin.py:143 | active referenced | 688<br>691<br>682 | — | backend/test_s2_4_readiness_admin.py:28 |
| AdminActivityEventResponse (BaseModel) | backend/app/api/endpoints/admin.py:161 | active referenced | 293<br>304<br>180<br>294 | — | — |
| AdminActivityResponse (BaseModel) | backend/app/api/endpoints/admin.py:170 | active referenced | 320<br>322<br>315 | — | backend/test_s1_access_hardening.py:85 |
| AdminAuditEventResponse (BaseModel) | backend/app/api/endpoints/admin.py:183 | active referenced | 360<br>207<br>361 | — | — |
| AdminAuditEventsPage (BaseModel) | backend/app/api/endpoints/admin.py:206 | active referenced | 399<br>430<br>389 | — | — |
| AdminCorpusHealthResponse (BaseModel) | backend/app/api/endpoints/admin.py:213 | active referenced | 445<br>455<br>440 | — | backend/test_s1_access_hardening.py:86 |
| GoogleAuthRequest (BaseModel) | backend/app/api/endpoints/auth.py:50 | active referenced | 148 | — | backend/scripts/test_s3_4_administrative_audit_hardening.py:25<br>backend/test_s0_2_disabled_authorization.py:29<br>backend/test_s3_1_admin_account_lifecycle.py:16 |
| TokenResponse (BaseModel) | backend/app/api/endpoints/auth.py:57 | active referenced | 133<br>151<br>244<br>134<br>146<br>239 | — | — |
| HunterTenderPayload (BaseModel) | backend/app/api/endpoints/hunter.py:37 | active referenced | 53 | — | — |
| HunterRecommendationPayload (BaseModel) | backend/app/api/endpoints/hunter.py:48 | active referenced | 67<br>68 | — | — |
| DismissResponse (BaseModel) | backend/app/api/endpoints/hunter.py:59 | active referenced | 130 | — | — |
| GeographyMetaResponse (BaseModel) | backend/app/api/endpoints/meta.py:13 | active referenced | 25<br>24<br>26 | — | — |
| ServiceMetaItem (BaseModel) | backend/app/api/endpoints/meta.py:19 | active referenced | 30<br>29<br>31 | — | — |
| AIStrategicLineItem (BaseModel) | backend/app/api/endpoints/proposals.py:92 | active referenced | 106<br>735<br>905<br>529<br>651 | — | — |
| AIDraftResponse (BaseModel) | backend/app/api/endpoints/proposals.py:101 | active referenced | 490<br>755<br>730<br>484<br>900<br>749<br>524<br>643 | — | backend/test_s0_5b1_unknown_actionability.py:217 |
| PDFGenerateRequest (BaseModel) | backend/app/api/endpoints/proposals.py:109 | active referenced | 978<br>1312 | — | — |
| RefreshResponse (BaseModel) | backend/app/api/endpoints/tenders.py:278 | active referenced | 5421<br>5453<br>5472<br>7443 | — | — |
| SourceSyncResponse (BaseModel) | backend/app/api/endpoints/tenders.py:290 | active referenced | 5505<br>6449<br>6899<br>5677<br>6602<br>7027<br>5531<br>6473<br>6923<br>7443<br>5638<br>6573<br>7009 | — | backend/test_p0_3b_source_refresh.py:12<br>backend/test_source_refresh_worker.py:11 |
| SourceRefreshResponse (BaseModel) | backend/app/api/endpoints/tenders.py:327 | active referenced | 5489<br>7383<br>7491<br>7699<br>7725<br>7749<br>7773<br>7799<br>5484<br>7394<br>7692<br>7716<br>7742<br>7765<br>7790 | — | backend/test_p0_3b_source_refresh.py:11<br>backend/test_sr2_2_source_refresh_orchestration.py:237 |
| AdbSyncResponse (BaseModel) | backend/app/api/endpoints/tenders.py:360 | active referenced | 7077<br>7314<br>7443<br>7123<br>7242 | — | — |
| SyncDocsAcceptedResponse (BaseModel) | backend/app/api/endpoints/tenders.py:398 | active referenced | 7856<br>8090<br>7857<br>8076 | — | — |
| GizHydrateRequest (BaseModel) | backend/app/api/endpoints/tenders.py:411 | active referenced | 6661 | — | — |
| GizHydrateJobResponse (BaseModel) | backend/app/api/endpoints/tenders.py:418 | active referenced | 436<br>6724<br>6752<br>6834<br>6865<br>6786 | — | — |
| GizHydrateAcceptedResponse (BaseModel) | backend/app/api/endpoints/tenders.py:428 | active referenced | 6664<br>6879<br>6657 | — | — |
| SyncMarkerDiagnostics (BaseModel) | backend/app/api/endpoints/tenders.py:439 | active referenced | 8040<br>460<br>8059 | — | — |
| SyncStatusResponse (BaseModel) | backend/app/api/endpoints/tenders.py:451 | active referenced | 8240<br>8299<br>8235<br>8289 | — | — |
| TestScrapeRequest (BaseModel) | backend/app/api/endpoints/tenders.py:463 | active referenced | 4674 | — | — |
| TestScrapeResponse (BaseModel) | backend/app/api/endpoints/tenders.py:468 | active referenced | 4674<br>4673<br>4684<br>4693 | — | — |
| AnalyzeTenderResponse (BaseModel) | backend/app/api/endpoints/tenders.py:477 | active referenced | 3885 | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:9<br>frontend/types/compliance.ts:35 | backend/test_s2_1_compliance_ownership.py:157<br>backend/test_strategy_extractor.py:154 |
| TenderCompiledTextResponse (BaseModel) | backend/app/api/endpoints/tenders.py:502 | active referenced | 5389<br>5413<br>5384 | — | — |
| RiskOverrideRequest (BaseModel) | backend/app/api/endpoints/tenders.py:507 | active referenced | 8929 | — | backend/test_s2_1_compliance_ownership.py:158 |
| RiskOverrideStatusResponse (BaseModel) | backend/app/api/endpoints/tenders.py:527 | active referenced | 9072<br>9123<br>9066 | — | — |
| ProxyDownloadRequest (BaseModel) | backend/app/api/endpoints/tenders.py:4702 | active referenced | 4709 | — | — |
| UserResponse (BaseModel) | backend/app/api/endpoints/users.py:45 | active referenced | 144<br>239<br>141<br>235<br>153<br>249 | — | backend/test_s7_2_locale_foundation.py:13 |
| UserPreferencesUpdate (BaseModel) | backend/app/api/endpoints/users.py:62 | active referenced | 158 | — | backend/test_s7_2_locale_foundation.py:12<br>backend/test_s8_2_analysis_language.py:15<br>backend/test_s8_3_arabic_ui_locale.py:13 |
| UserPreferencesResponse (BaseModel) | backend/app/api/endpoints/users.py:119 | active referenced | 161<br>174<br>156 | — | — |
| AccessStatusResponse (BaseModel) | backend/app/api/endpoints/users.py:124 | active referenced | 188<br>221<br>184 | — | — |
| CompanyProfileResponse (BaseModel) | backend/app/api/endpoints/users.py:256 | active referenced | 419<br>471<br>490<br>518<br>434<br>467<br>485<br>513<br>421 | — | backend/test_s7_2_locale_foundation.py:89 |
| CompanyProfileUpdate (BaseModel) | backend/app/api/endpoints/users.py:280 | active referenced | 487 | — | backend/test_s2_2_geography.py:14<br>backend/test_s2_3_services.py:14 |
| CompanyOnboardingRequest (BaseModel) | backend/app/api/endpoints/users.py:341 | active referenced | 515 | — | backend/test_s1_company_onboarding.py:8<br>backend/test_s2_2_geography.py:13<br>backend/test_s2_3_services.py:13 |
| TenderRecommendationItem (BaseModel) | backend/app/core/agents/hunter.py:30 | active referenced | 38 | — | — |
| TenderRequirement (BaseModel) | backend/app/core/agents/requirement_extractor.py:134 | active referenced | 743<br>900<br>913<br>1370<br>1392<br>773<br>1013<br>1592<br>1604<br>1690<br>1962<br>292<br>327<br>739<br>754<br>762<br>884<br>895<br>911<br>1305<br>1344<br>1364<br>1390<br>1836<br>772<br>775<br>1011<br>1590<br>1841<br>1846 | backend/app/models/__init__.py:2<br>backend/app/models/all_models.py:763<br>backend/app/models/taxonomy.py:62<br>backend/app/services/analysis_language_content.py:12<br>backend/app/services/compliance_engine.py:6 | backend/scripts/purge_small_scale_uzex_tenders.py:24<br>backend/test_compliance_forensic_categories.py:12<br>backend/test_extractor_validators.py:2<br>backend/test_s8_2_analysis_language.py:21 |
| RequirementExtractionCoverage (BaseModel) | backend/app/core/agents/requirement_extractor.py:263 | active referenced | 1720<br>1752<br>293<br>503<br>1735<br>499 | — | — |
| ExtractionChunkArtifactMetadata (BaseModel) | backend/app/core/agents/requirement_extractor.py:277 | active referenced | 1782<br>294<br>1803<br>1842<br>1858<br>1881<br>1788 | — | backend/test_reproducibility_snapshot.py:213 |
| RequirementExtractionResult (BaseModel) | backend/app/core/agents/requirement_extractor.py:289 | active referenced | 1820<br>1992<br>1944<br>1825<br>2002 | — | backend/test_reproducibility_snapshot.py:214 |
| TenderStrategyIntelligence (BaseModel) | backend/app/core/agents/strategy_extractor.py:68 | active referenced | 368<br>479<br>514<br>148<br>488<br>541 | backend/app/api/endpoints/tenders.py:60 | backend/test_strategy_extractor.py:5 |
| _TenderItemSchema (BaseModel) | backend/app/core/ai.py:60 | active referenced | 78 | — | — |
| _CostBreakdownSchema (BaseModel) | backend/app/core/ai.py:67 | active referenced | 81<br>82 | — | — |
| TenderAnalysisSchema (BaseModel) | backend/app/core/ai.py:74 | active referenced | 492<br>885 | — | — |
| _StrategicLineItemSchema (BaseModel) | backend/app/core/ai.py:88 | active referenced | 103 | — | — |
| StrategicDraftSchema (BaseModel) | backend/app/core/ai.py:97 | active referenced | 651 | — | — |
| DynamicTenderRequirements (BaseModel) | backend/app/core/ai_analyzer.py:46 | active referenced | 65<br>66<br>97<br>129<br>265<br>285<br>308<br>112<br>101<br>154 | — | — |
| TaxNodeInfo (BaseModel) | backend/app/core/evaluator.py:6 | active referenced | 50 | backend/app/api/endpoints/tenders.py:68<br>backend/app/services/compliance_engine.py:49 | backend/scripts/test_evaluator.py:12 |
| MetRequirement (BaseModel) | backend/app/core/evaluator.py:14 | active referenced | 34<br>69<br>82 | backend/app/api/endpoints/tenders.py:4390<br>frontend/types/compliance.ts:10 | — |
| MissingRequirement (BaseModel) | backend/app/core/evaluator.py:21 | active referenced | 35<br>70<br>85 | backend/app/api/endpoints/tenders.py:4390<br>frontend/types/compliance.ts:15 | — |
| DynamicComplianceResult (BaseModel) | backend/app/core/evaluator.py:30 | active referenced | 42<br>51<br>114 | backend/app/api/endpoints/proposals.py:38<br>backend/app/api/endpoints/tenders.py:68 | backend/scripts/test_evaluator.py:11 |
| Base (DeclarativeBase) | backend/app/models/base.py:8 | active referenced | — | backend/app/crud/exceptions.py:16<br>backend/app/main.py:20<br>backend/app/models/all_models.py:33<br>backend/app/models/audit.py:33<br>backend/app/models/company.py:17<br>backend/app/models/engagement.py:13<br>backend/app/models/taxonomy.py:24<br>backend/app/models/user.py:20<br>backend/app/schemas/tender.py:17<br>backend/app/services/bid_preparation.py:30<br>backend/app/services/tender_engagements.py:18 | backend/alembic/env.py:13<br>backend/diagnose.py:12<br>backend/init_db.py:3<br>backend/reset_db.py:4<br>backend/scripts/test_s0_5b3_migration.py:30<br>backend/test_s0_5b3_tender_recommendation_migration.py:15<br>backend/test_s0_5b5_alembic_drift.py:13<br>backend/test_s1_1_project_foundation.py:15<br>backend/test_s1_2_world_bank_project_enrichment.py:17<br>backend/test_s2_1_compliance_ownership.py:11<br>backend/test_s2_1_readiness_vault.py:45<br>backend/test_s2_2_analysis_version_foundation.py:12<br>backend/test_s3_1_admin_account_lifecycle.py:26<br>backend/test_s3_4_administrative_audit_hardening.py:11<br>backend/test_s4_1_tender_engagement_foundation.py:12<br>backend/test_s6_1_hunter_explorer_convergence_foundation.py:7<br>backend/test_s8_2_analysis_language.py:35 |
| AnalysisVersionIntegrityResponse (BaseModel) | backend/app/schemas/analysis_version.py:14 | active referenced | 70 | backend/app/api/endpoints/tenders.py:163 | — |
| AnalysisVersionMetadataResponse (BaseModel) | backend/app/schemas/analysis_version.py:24 | active referenced | 63 | backend/app/api/endpoints/tenders.py:164 | — |
| AnalysisVersionDocumentResponse (BaseModel) | backend/app/schemas/analysis_version.py:50 | active referenced | 69 | backend/app/api/endpoints/tenders.py:162 | — |
| AnalysisVersionDetailResponse (BaseModel) | backend/app/schemas/analysis_version.py:62 | active referenced | — | backend/app/api/endpoints/tenders.py:161 | — |
| RiskAuthorizationRequest (BaseModel) | backend/app/schemas/audit.py:12 | active referenced | — | backend/app/api/routers/audit.py:20 | — |
| TenderEngagementSummary (BaseModel) | backend/app/schemas/engagement.py:17 | active referenced | 28<br>76<br>80<br>67 | backend/app/api/endpoints/my_tenders.py:25<br>backend/app/api/endpoints/proposals.py:64<br>backend/app/schemas/proposal.py:18<br>frontend/components/tenders/EngagementWorkflowActions.tsx:14<br>frontend/types/bid-preparation.ts:1<br>frontend/types/engagement.ts:32 | — |
| MyTenderListItem (TenderEngagementSummary) | backend/app/schemas/engagement.py:28 | active referenced | 59 | backend/app/api/endpoints/my_tenders.py:20<br>backend/app/services/my_tenders.py:16<br>frontend/app/dashboard/my-tenders/page.tsx:34<br>frontend/types/engagement.ts:49 | — |
| MyTenderStatusCounts (BaseModel) | backend/app/schemas/engagement.py:46 | active referenced | 63 | backend/app/services/my_tenders.py:17<br>frontend/types/engagement.ts:67 | — |
| MyTendersListResponse (BaseModel) | backend/app/schemas/engagement.py:58 | active referenced | — | backend/app/api/endpoints/my_tenders.py:21<br>backend/app/services/my_tenders.py:18<br>frontend/app/dashboard/my-tenders/page.tsx:35<br>frontend/types/engagement.ts:79 | frontend/tests/my-tenders.test.mjs:43 |
| TenderScopedEngagementResponse (BaseModel) | backend/app/schemas/engagement.py:66 | active referenced | — | backend/app/api/endpoints/my_tenders.py:26<br>frontend/components/tenders/TenderEngagementPanel.tsx:15<br>frontend/types/engagement.ts:87 | backend/test_s4_2_my_tenders_list_experience.py:151 |
| TenderEngagementActionRequest (BaseModel) | backend/app/schemas/engagement.py:71 | active referenced | — | backend/app/api/endpoints/my_tenders.py:23 | — |
| TenderEngagementActionResponse (BaseModel) | backend/app/schemas/engagement.py:75 | active referenced | — | backend/app/api/endpoints/my_tenders.py:24<br>frontend/components/tenders/EngagementWorkflowActions.tsx:13<br>frontend/types/engagement.ts:98 | — |
| SaveToMyTendersResponse (BaseModel) | backend/app/schemas/engagement.py:79 | active referenced | — | backend/app/api/endpoints/my_tenders.py:22<br>frontend/components/tenders/EngagementWorkflowActions.tsx:11<br>frontend/components/tenders/TenderEngagementPanel.tsx:13<br>frontend/types/engagement.ts:92 | backend/test_s4_2_my_tenders_list_experience.py:153<br>frontend/tests/my-tenders.test.mjs:78 |
| ExplorerView (str, Enum) | backend/app/schemas/explorer.py:14 | active referenced | 76 | backend/app/api/endpoints/explorer.py:17<br>backend/app/services/explorer.py:32<br>frontend/app/dashboard/tenders/page.tsx:64<br>frontend/types/explorer.ts:4 | backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py:29<br>backend/scripts/test_s6_2_unified_explorer_backend.py:23<br>backend/test_s6_2_unified_explorer_backend.py:18 |
| RecommendationAvailability (str, Enum) | backend/app/schemas/explorer.py:20 | active referenced | 82 | backend/app/services/explorer.py:33<br>frontend/types/explorer.ts:5 | backend/test_s6_2_unified_explorer_backend.py:18<br>frontend/tests/unified-explorer.test.mjs:37 |
| ExplorerTenderSummary (BaseModel) | backend/app/schemas/explorer.py:25 | active referenced | 64 | backend/app/services/explorer.py:31<br>frontend/types/explorer.ts:7 | backend/test_sr2_4_refresh_activity_source_catalog_newness.py:177 |
| ExplorerRecommendationSummary (BaseModel) | backend/app/schemas/explorer.py:49 | active referenced | 88<br>65 | backend/app/services/explorer.py:28 | — |
| ExplorerPursuitSummary (BaseModel) | backend/app/schemas/explorer.py:57 | active referenced | 66 | backend/app/services/explorer.py:27 | — |
| ExplorerTenderItem (BaseModel) | backend/app/schemas/explorer.py:63 | active referenced | 77 | backend/app/services/explorer.py:29 | — |
| ExplorerCounts (BaseModel) | backend/app/schemas/explorer.py:69 | active referenced | 81 | backend/app/services/explorer.py:26<br>frontend/types/explorer.ts:51 | frontend/tests/unified-explorer.test.mjs:35 |
| ExplorerTenderListResponse (BaseModel) | backend/app/schemas/explorer.py:75 | active referenced | — | backend/app/api/endpoints/explorer.py:16<br>backend/app/services/explorer.py:30 | backend/test_sr2_4_refresh_activity_source_catalog_newness.py:179 |
| RecommendationCommandResponse (BaseModel) | backend/app/schemas/explorer.py:86 | active referenced | — | backend/app/api/endpoints/explorer.py:18<br>frontend/lib/explorer.ts:5<br>frontend/types/explorer.ts:68 | — |
| ProjectRoleAssignmentResponse (BaseModel) | backend/app/schemas/project.py:10 | active referenced | 47 | — | backend/test_s1_2_world_bank_project_enrichment.py:18 |
| ProjectResponse (BaseModel) | backend/app/schemas/project.py:31 | test-only/unreferenced candidate; review dynamic use | — | — | backend/test_s1_2_world_bank_project_enrichment.py:18 |
| ProjectContextRoleResponse (BaseModel) | backend/app/schemas/project.py:66 | active referenced | 144<br>145 | backend/app/api/endpoints/tenders.py:188 | — |
| ProjectContextProjectResponse (BaseModel) | backend/app/schemas/project.py:84 | active referenced | 143 | backend/app/api/endpoints/tenders.py:187 | backend/test_s1_3_project_context_api.py:17<br>backend/test_s1_3b_project_context_runtime_recovery.py:18<br>backend/test_wb_project_enrichment_autodrain.py:11 |
| TenderProjectContextResponse (BaseModel) | backend/app/schemas/project.py:140 | active referenced | — | backend/app/api/endpoints/tenders.py:189 | — |
| ProposalCreate (BaseModel) | backend/app/schemas/proposal.py:21 | active referenced | — | backend/app/api/endpoints/proposals.py:58 | backend/test_s0_5b1_unknown_actionability.py:25 |
| ProposalItemUpdate (BaseModel) | backend/app/schemas/proposal.py:26 | active referenced | 40 | — | — |
| ProposalUpdate (BaseModel) | backend/app/schemas/proposal.py:34 | active referenced | — | backend/app/api/endpoints/proposals.py:61 | — |
| ProposalResponse (BaseModel) | backend/app/schemas/proposal.py:45 | active referenced | 62 | backend/app/api/endpoints/proposals.py:60 | — |
| ProposalWithTenderResponse (ProposalResponse) | backend/app/schemas/proposal.py:62 | active referenced | 77 | backend/app/api/endpoints/proposals.py:62 | — |
| PrepareBidResponse (BaseModel) | backend/app/schemas/proposal.py:74 | active referenced | — | backend/app/api/endpoints/proposals.py:59<br>frontend/components/bid-preparation/PrepareBidButton.tsx:9<br>frontend/types/bid-preparation.ts:33 | backend/test_s4_3_bid_preparation_reconciliation.py:53 |
| SourceCatalogItem (BaseModel) | backend/app/schemas/source_refresh.py:11 | active referenced | — | backend/app/api/endpoints/tenders.py:139<br>backend/app/services/source_refresh_activity.py:18<br>frontend/components/source-refresh/SourceRefreshProvider.tsx:38<br>frontend/lib/sourceRefresh.ts:5<br>frontend/types/source-refresh.ts:4 | backend/test_sr2_4_refresh_activity_source_catalog_newness.py:94 |
| SourceRefreshActiveJob (BaseModel) | backend/app/schemas/source_refresh.py:18 | active referenced | 49 | backend/app/services/source_refresh_activity.py:19<br>frontend/types/source-refresh.ts:11 | — |
| SourceRefreshTerminalSummary (BaseModel) | backend/app/schemas/source_refresh.py:26 | active referenced | 57<br>50<br>51<br>52<br>53 | backend/app/services/source_refresh_activity.py:23<br>frontend/types/source-refresh.ts:19 | — |
| SourceRefreshStatusItem (BaseModel) | backend/app/schemas/source_refresh.py:44 | active referenced | — | backend/app/api/endpoints/tenders.py:141<br>backend/app/services/source_refresh_activity.py:22<br>frontend/components/source-refresh/SourceRefreshProvider.tsx:40<br>frontend/lib/sourceRefresh.ts:8<br>frontend/types/source-refresh.ts:37 | backend/test_sr2_4_refresh_activity_source_catalog_newness.py:94 |
| SourceRefreshActivityEvent (SourceRefreshTerminalSummary) | backend/app/schemas/source_refresh.py:57 | active referenced | 63 | backend/app/services/source_refresh_activity.py:20<br>frontend/components/source-refresh/SourceRefreshProvider.tsx:39<br>frontend/lib/sourceRefreshPolicy.ts:3<br>frontend/types/source-refresh.ts:50 | backend/test_sr2_4_refresh_activity_source_catalog_newness.py:95 |
| SourceRefreshActivityResponse (BaseModel) | backend/app/schemas/source_refresh.py:62 | active referenced | — | backend/app/api/endpoints/tenders.py:140<br>backend/app/services/source_refresh_activity.py:21 | backend/test_sr2_4_refresh_activity_source_catalog_newness.py:95 |
| TenderBase (BaseModel) | backend/app/schemas/tender.py:16 | active referenced | 45 | — | — |
| TenderContactSubmissionResponse (BaseModel) | backend/app/schemas/tender.py:28 | active referenced | 74 | backend/app/api/endpoints/tenders.py:123 | — |
| TenderResponse (TenderBase) | backend/app/schemas/tender.py:45 | active referenced | — | backend/app/api/endpoints/tenders.py:126 | backend/test_p0_security_static.py:32<br>backend/test_s1_1_project_foundation.py:16<br>backend/test_tender_contact_submission.py:13<br>backend/test_tender_document_status.py:84 |
| TenderDocumentResponse (BaseModel) | backend/app/schemas/tender.py:103 | active referenced | — | backend/app/api/endpoints/tenders.py:125 | backend/test_p0_security_static.py:30<br>backend/test_tender_document_status.py:67 |
| TenderDecisionSnapshotResponse (BaseModel) | backend/app/schemas/tender.py:133 | active referenced | — | backend/app/api/endpoints/tenders.py:124 | backend/test_s4_3_decision_snapshot.py:21 |
| TenderCompetitorResponse (BaseModel) | backend/app/schemas/tender.py:157 | active referenced | 180 | backend/app/api/endpoints/tenders.py:122 | backend/test_s4_2_competitor_intelligence.py:21<br>backend/test_s4_3_decision_snapshot.py:82 |
| TenderCompetitorGroup (BaseModel) | backend/app/schemas/tender.py:175 | active referenced | 188 | backend/app/api/endpoints/tenders.py:120 | backend/test_s4_2_competitor_intelligence.py:116<br>backend/test_s4_3_decision_snapshot.py:19 |
| TenderCompetitorIntelligenceResponse (BaseModel) | backend/app/schemas/tender.py:183 | active referenced | — | backend/app/api/endpoints/tenders.py:121 | backend/test_s4_2_competitor_intelligence.py:20<br>backend/test_s4_3_decision_snapshot.py:20 |
| DetailsSectionState (str, Enum) | backend/app/schemas/tender_details.py:15 | active referenced | 157<br>163<br>169<br>175<br>181<br>187<br>193<br>199<br>205 | backend/app/services/tender_details.py:38<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:52<br>frontend/types/tender-details.ts:8 | backend/test_s5_2_tender_details_read_model.py:13 |
| ProjectContextSummary (BaseModel) | backend/app/schemas/tender_details.py:21 | active referenced | 158 | backend/app/services/tender_details.py:42 | — |
| ProjectLeadershipItem (BaseModel) | backend/app/schemas/tender_details.py:35 | active referenced | 50 | backend/app/services/tender_details.py:43 | — |
| ProjectLeadershipSummary (BaseModel) | backend/app/schemas/tender_details.py:49 | active referenced | 164 | backend/app/services/tender_details.py:45 | — |
| ProcurementContactsSummary (BaseModel) | backend/app/schemas/tender_details.py:56 | active referenced | 170 | backend/app/api/endpoints/tenders.py:129<br>backend/app/services/tender_details.py:40 | — |
| RequirementSummaryItem (BaseModel) | backend/app/schemas/tender_details.py:72 | active referenced | 83 | backend/app/services/tender_details.py:48 | — |
| RequirementsSummary (BaseModel) | backend/app/schemas/tender_details.py:80 | active referenced | 176 | backend/app/services/tender_details.py:50 | — |
| TenderDocumentSummaryItem (BaseModel) | backend/app/schemas/tender_details.py:89 | active referenced | 102 | backend/app/services/tender_details.py:52 | backend/test_s5_2_tender_details_read_model.py:15 |
| TenderDocumentsSummary (BaseModel) | backend/app/schemas/tender_details.py:101 | active referenced | 182 | backend/app/services/tender_details.py:54 | — |
| ComplianceSummary (BaseModel) | backend/app/schemas/tender_details.py:110 | active referenced | 188 | backend/app/services/tender_details.py:37 | backend/test_s5_2_tender_details_read_model.py:12 |
| CompanyReadinessSummary (BaseModel) | backend/app/schemas/tender_details.py:125 | active referenced | 194 | backend/app/services/tender_details.py:35 | — |
| PursuitSummary (BaseModel) | backend/app/schemas/tender_details.py:141 | active referenced | 200 | backend/app/services/tender_details.py:47<br>frontend/types/explorer.ts:39 | frontend/tests/unified-explorer.test.mjs:38 |
| BidPreparationSummary (BaseModel) | backend/app/schemas/tender_details.py:149 | active referenced | 206 | backend/app/services/tender_details.py:33 | — |
| ProjectContextSection (BaseModel) | backend/app/schemas/tender_details.py:156 | active referenced | 212 | backend/app/services/tender_details.py:41 | frontend/tests/tender-cleanup.test.mjs:24 |
| ProjectLeadershipSection (BaseModel) | backend/app/schemas/tender_details.py:162 | active referenced | 213 | backend/app/services/tender_details.py:44 | — |
| ProcurementContactsSection (BaseModel) | backend/app/schemas/tender_details.py:168 | active referenced | 214 | backend/app/services/tender_details.py:39 | — |
| RequirementsSection (BaseModel) | backend/app/schemas/tender_details.py:174 | active referenced | 215 | backend/app/services/tender_details.py:49 | — |
| TenderDocumentsSection (BaseModel) | backend/app/schemas/tender_details.py:180 | active referenced | 216 | backend/app/services/tender_details.py:53 | — |
| ComplianceSection (BaseModel) | backend/app/schemas/tender_details.py:186 | active referenced | 217 | backend/app/services/tender_details.py:36 | — |
| CompanyReadinessSection (BaseModel) | backend/app/schemas/tender_details.py:192 | active referenced | 218 | backend/app/services/tender_details.py:34 | — |
| PursuitSection (BaseModel) | backend/app/schemas/tender_details.py:198 | active referenced | 219 | backend/app/services/tender_details.py:46 | — |
| BidPreparationSection (BaseModel) | backend/app/schemas/tender_details.py:204 | active referenced | 220 | backend/app/services/tender_details.py:32 | — |
| TenderDetailsResponse (BaseModel) | backend/app/schemas/tender_details.py:210 | active referenced | — | backend/app/api/endpoints/tenders.py:130<br>backend/app/services/tender_details.py:51<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:56<br>frontend/types/tender-details.ts:157 | backend/test_s5_2_tender_details_read_model.py:14<br>frontend/tests/tender-details.test.mjs:22 |
| CertificationItem (BaseModel) | backend/app/schemas/vault.py:13 | active referenced | 61 | backend/app/api/endpoints/tenders.py:144<br>backend/app/api/endpoints/vault.py:21 | — |
| LicenseItem (BaseModel) | backend/app/schemas/vault.py:22 | active referenced | 62 | backend/app/api/endpoints/tenders.py:147<br>backend/app/api/endpoints/vault.py:25 | — |
| FinancialHistoryItem (BaseModel) | backend/app/schemas/vault.py:30 | active referenced | 63 | backend/app/api/endpoints/tenders.py:146<br>backend/app/api/endpoints/vault.py:24 | — |
| CompanyVaultResponse (BaseModel) | backend/app/schemas/vault.py:38 | active referenced | — | backend/app/api/endpoints/tenders.py:145<br>backend/app/api/endpoints/vault.py:22 | — |
| CertificationUpdate (BaseModel) | backend/app/schemas/vault.py:83 | active referenced | 117 | — | — |
| LicenseUpdate (BaseModel) | backend/app/schemas/vault.py:89 | active referenced | 118 | — | — |
| FinancialHistoryUpdate (BaseModel) | backend/app/schemas/vault.py:94 | active referenced | 119 | — | — |
| CompanyVaultUpdate (BaseModel) | backend/app/schemas/vault.py:99 | active referenced | — | backend/app/api/endpoints/vault.py:23 | backend/test_s2_2_geography.py:18<br>backend/test_s2_3_services.py:18 |
| ReadinessDocumentBase (BaseModel) | backend/app/schemas/vault.py:137 | active referenced | 195<br>255 | — | — |
| ReadinessDocumentCreate (ReadinessDocumentBase) | backend/app/schemas/vault.py:195 | active referenced | — | backend/app/api/endpoints/vault.py:26 | backend/test_s2_1_readiness_vault.py:9<br>backend/test_s2_3_services.py:18 |
| ReadinessDocumentUpdate (BaseModel) | backend/app/schemas/vault.py:199 | active referenced | — | backend/app/api/endpoints/vault.py:28 | backend/test_s2_3_services.py:18 |
| ReadinessDocumentResponse (ReadinessDocumentBase) | backend/app/schemas/vault.py:255 | active referenced | — | backend/app/api/endpoints/admin.py:41<br>backend/app/api/endpoints/vault.py:27 | backend/test_s2_1_readiness_vault.py:132 |
| RequirementMatchDetail (BaseModel) | backend/app/services/compliance_engine.py:116 | active referenced | 659<br>682<br>737<br>815<br>909<br>997<br>192<br>199<br>206<br>210<br>665<br>718<br>774<br>976<br>1187<br>1283<br>1284<br>1285<br>1286<br>917<br>930<br>943<br>959<br>1016<br>1028<br>1040<br>1053<br>1069<br>1082<br>1145<br>1165<br>1295<br>1106<br>1125 | backend/app/api/endpoints/tenders.py:154<br>backend/app/services/analysis_language_content.py:19<br>frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx:13<br>frontend/lib/useHybridCompliance.ts:10<br>frontend/types/compliance.ts:70 | — |
| ComplianceResult (BaseModel) | backend/app/services/compliance_engine.py:150 | active referenced | 1215<br>1387<br>1252 | backend/app/api/endpoints/tenders.py:150<br>backend/app/core/evaluator.py:41<br>backend/app/services/analysis_language_content.py:15<br>frontend/types/compliance.ts:59 | — |

ProjectResponse is test-only/API-ready historical schema; ProjectContext responses are the live Tender Details contract. Keep until the enrichment test expectation is deliberately transferred. Source runner DTOs are live internal contracts.

## Services

| Module | Classification | Runtime importers | Tests/tools |
| --- | --- | --- | --- |
| backend/app/services/__init__.py | active/support | backend/app/api/endpoints/admin.py<br>backend/app/api/endpoints/auth.py<br>backend/app/api/endpoints/explorer.py<br>backend/app/api/endpoints/hunter.py<br>backend/app/api/endpoints/my_tenders.py<br>backend/app/api/endpoints/proposals.py<br>backend/app/api/endpoints/tenders.py<br>backend/app/cli/admin_management.py<br>backend/app/core/reproducibility.py<br>backend/app/core/scraper.py<br>backend/app/services/account_lifecycle.py<br>backend/app/services/admin_survivability.py<br>backend/app/services/analysis_language_content.py<br>backend/app/services/bid_preparation.py<br>backend/app/services/explorer.py<br>backend/app/services/giz_document_hydration.py<br>backend/app/services/my_tenders.py<br>backend/app/services/project_enrichment.py<br>backend/app/services/projects.py<br>backend/app/services/source_refresh_activity.py<br>backend/app/services/source_refresh_jobs.py<br>backend/app/services/tender_details.py<br>backend/app/services/tender_sources/__init__.py<br>backend/app/services/tender_sources/adb.py<br>backend/app/services/tender_sources/base.py<br>backend/app/services/tender_sources/ebrd.py<br>backend/app/services/tender_sources/giz.py<br>backend/app/services/tender_sources/keys.py<br>backend/app/services/tender_sources/uzex.py<br>backend/app/services/tender_sources/uzex_scope.py<br>backend/app/services/tender_sources/world_bank.py<br>backend/app/services/world_bank_projects.py<br>backend/app/workers/project_enrichment_tasks.py<br>backend/app/workers/source_refresh_tasks.py<br>backend/app/workers/tender_tasks.py | backend/scripts/audit_sr1_source_refresh.py<br>backend/scripts/audit_sr2_1_semantic_batch.py<br>backend/scripts/audit_sr2_2_source_refresh_orchestration.py<br>backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py<br>backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py<br>backend/scripts/enqueue_world_bank_project_enrichment.py<br>backend/scripts/purge_small_scale_uzex_tenders.py<br>backend/scripts/qa_s8_2_live_model_languages.py<br>backend/scripts/report_world_bank_project_enrichment_backlog.py<br>backend/scripts/test_s1_1_project_foundation.py<br>backend/scripts/test_s1_2_project_enrichment.py<br>backend/scripts/test_s2_2_analysis_version_foundation.py<br>backend/scripts/test_s2_2b_analysis_aggregate_concurrency.py<br>backend/scripts/test_s2_3_version_aware_compliance_reads.py<br>backend/scripts/test_s3_3_privileged_account_survivability.py<br>backend/scripts/test_s4_1_tender_engagement_foundation.py<br>backend/scripts/test_s4_2_my_tenders_list_experience.py<br>backend/scripts/test_s4_3_bid_preparation_reconciliation.py<br>backend/scripts/test_s4_4_tender_engagement_workflow_ux.py<br>backend/scripts/test_s6_2_unified_explorer_backend.py<br>backend/scripts/test_wb_project_enrichment_autodrain.py<br>backend/seed_tenders.py<br>backend/test_adb_connector.py<br>backend/test_compliance_forensic_categories.py<br>backend/test_ebrd_connector.py<br>backend/test_giz_connector.py<br>backend/test_giz_hydration_worker.py<br>backend/test_s0_2_disabled_authorization.py<br>backend/test_s0_5b1_unknown_actionability.py<br>backend/test_s1_1_project_foundation.py<br>backend/test_s1_2_world_bank_project_enrichment.py<br>backend/test_s1_3b_project_context_runtime_recovery.py<br>backend/test_s2_2_analysis_version_foundation.py<br>backend/test_s2_2b_analysis_aggregate_concurrency.py<br>backend/test_s2_3_version_aware_compliance_reads.py<br>backend/test_s3_1_admin_account_lifecycle.py<br>backend/test_s3_2_session_revocation_restore_security.py<br>backend/test_s3_3_privileged_account_survivability.py<br>backend/test_s3_4_administrative_audit_hardening.py<br>backend/test_s4_1_tender_engagement_foundation.py<br>backend/test_s4_2_my_tenders_list_experience.py<br>backend/test_s4_4_tender_engagement_workflow_ux.py<br>backend/test_s5_2_tender_details_read_model.py<br>backend/test_s5_cross_source_regression.py<br>backend/test_s6_2_unified_explorer_backend.py<br>backend/test_s8_2_analysis_language.py<br>backend/test_sr2_1_semantic_batch_persistence.py<br>backend/test_sr2_2_source_refresh_orchestration.py<br>backend/test_sr2_3_connector_capability_document_decoupling.py<br>backend/test_sr2_4_refresh_activity_source_catalog_newness.py<br>backend/test_tender_source_foundation.py<br>backend/test_uzex_contact.py<br>backend/test_wb_project_enrichment_autodrain.py<br>backend/test_world_bank_connector.py |
| backend/app/services/account_lifecycle.py | active/support | backend/app/api/endpoints/admin.py<br>backend/app/services/admin_survivability.py | backend/scripts/test_s3_3_privileged_account_survivability.py<br>backend/test_s0_2_disabled_authorization.py<br>backend/test_s3_1_admin_account_lifecycle.py<br>backend/test_s3_2_session_revocation_restore_security.py<br>backend/test_s3_3_privileged_account_survivability.py |
| backend/app/services/admin_activity.py | active/support | backend/app/api/endpoints/admin.py<br>backend/app/api/endpoints/auth.py<br>backend/app/cli/admin_management.py<br>backend/app/services/account_lifecycle.py<br>backend/app/services/admin_survivability.py | backend/test_s0_2_disabled_authorization.py<br>backend/test_s3_1_admin_account_lifecycle.py<br>backend/test_s3_4_administrative_audit_hardening.py |
| backend/app/services/admin_survivability.py | active/support | backend/app/api/endpoints/admin.py | backend/scripts/test_s3_3_privileged_account_survivability.py<br>backend/test_s3_3_privileged_account_survivability.py |
| backend/app/services/analysis_aggregates.py | active/support | backend/app/api/endpoints/proposals.py<br>backend/app/api/endpoints/tenders.py<br>backend/app/services/tender_details.py | backend/scripts/test_s2_2b_analysis_aggregate_concurrency.py<br>backend/scripts/test_s2_3_version_aware_compliance_reads.py<br>backend/test_s2_2b_analysis_aggregate_concurrency.py |
| backend/app/services/analysis_language_content.py | active/support | backend/app/api/endpoints/tenders.py | backend/scripts/qa_s8_2_live_model_languages.py<br>backend/test_s8_2_analysis_language.py |
| backend/app/services/analysis_versions.py | active/support | backend/app/api/endpoints/admin.py<br>backend/app/api/endpoints/proposals.py<br>backend/app/api/endpoints/tenders.py<br>backend/app/services/tender_details.py | backend/scripts/test_s2_2_analysis_version_foundation.py<br>backend/scripts/test_s2_2b_analysis_aggregate_concurrency.py<br>backend/scripts/test_s2_3_version_aware_compliance_reads.py<br>backend/test_s2_2_analysis_version_foundation.py<br>backend/test_s2_3_version_aware_compliance_reads.py<br>backend/test_s8_2_analysis_language.py |
| backend/app/services/bid_preparation.py | active/support | backend/app/api/endpoints/proposals.py | backend/scripts/test_s4_3_bid_preparation_reconciliation.py<br>backend/scripts/test_s4_4_tender_engagement_workflow_ux.py |
| backend/app/services/compliance_engine.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/services/analysis_language_content.py | backend/test_compliance_forensic_categories.py |
| backend/app/services/explorer.py | active/support | backend/app/api/endpoints/explorer.py | backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py<br>backend/scripts/test_s6_2_unified_explorer_backend.py<br>backend/test_s6_2_unified_explorer_backend.py |
| backend/app/services/giz_document_hydration.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/workers/tender_tasks.py | backend/test_giz_hydration_worker.py |
| backend/app/services/my_tenders.py | active/support | backend/app/api/endpoints/my_tenders.py | backend/scripts/test_s4_2_my_tenders_list_experience.py<br>backend/scripts/test_s4_4_tender_engagement_workflow_ux.py<br>backend/test_s4_2_my_tenders_list_experience.py |
| backend/app/services/project_enrichment.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/workers/project_enrichment_tasks.py | backend/scripts/enqueue_world_bank_project_enrichment.py<br>backend/scripts/report_world_bank_project_enrichment_backlog.py<br>backend/scripts/test_s1_2_project_enrichment.py<br>backend/scripts/test_wb_project_enrichment_autodrain.py<br>backend/test_s1_2_world_bank_project_enrichment.py<br>backend/test_s1_3b_project_context_runtime_recovery.py<br>backend/test_wb_project_enrichment_autodrain.py |
| backend/app/services/projects.py | active/support | backend/app/services/tender_sources/world_bank.py<br>backend/app/services/world_bank_projects.py | backend/scripts/test_s1_1_project_foundation.py<br>backend/test_s1_1_project_foundation.py |
| backend/app/services/recommendations.py | active/support | backend/app/api/endpoints/explorer.py<br>backend/app/api/endpoints/hunter.py | backend/scripts/test_s6_2_unified_explorer_backend.py |
| backend/app/services/source_refresh_activity.py | active/support | backend/app/api/endpoints/tenders.py | backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py<br>backend/test_sr2_4_refresh_activity_source_catalog_newness.py |
| backend/app/services/source_refresh_jobs.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/services/source_refresh_activity.py<br>backend/app/workers/source_refresh_tasks.py | backend/scripts/audit_sr2_2_source_refresh_orchestration.py<br>backend/test_sr2_2_source_refresh_orchestration.py |
| backend/app/services/source_registry.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/services/source_refresh_activity.py<br>backend/app/services/source_refresh_jobs.py<br>backend/app/services/tender_sources/keys.py<br>backend/app/workers/source_refresh_tasks.py | backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py<br>backend/test_sr2_3_connector_capability_document_decoupling.py<br>backend/test_sr2_4_refresh_activity_source_catalog_newness.py |
| backend/app/services/tender_details.py | active/support | backend/app/api/endpoints/tenders.py | backend/test_s5_2_tender_details_read_model.py |
| backend/app/services/tender_engagements.py | active/support | backend/app/api/endpoints/my_tenders.py<br>backend/app/api/endpoints/proposals.py<br>backend/app/services/bid_preparation.py<br>backend/app/services/explorer.py<br>backend/app/services/my_tenders.py<br>backend/app/services/tender_details.py | backend/scripts/test_s4_1_tender_engagement_foundation.py<br>backend/scripts/test_s4_2_my_tenders_list_experience.py<br>backend/scripts/test_s4_4_tender_engagement_workflow_ux.py<br>backend/test_s4_1_tender_engagement_foundation.py<br>backend/test_s4_4_tender_engagement_workflow_ux.py |
| backend/app/services/tender_sources/__init__.py | active/support | backend/app/api/endpoints/admin.py<br>backend/app/api/endpoints/tenders.py<br>backend/app/core/reproducibility.py<br>backend/app/core/scraper.py<br>backend/app/services/explorer.py<br>backend/app/services/giz_document_hydration.py<br>backend/app/services/projects.py<br>backend/app/services/source_refresh_jobs.py<br>backend/app/services/tender_sources/adb.py<br>backend/app/services/tender_sources/base.py<br>backend/app/services/tender_sources/ebrd.py<br>backend/app/services/tender_sources/giz.py<br>backend/app/services/tender_sources/uzex.py<br>backend/app/services/tender_sources/uzex_scope.py<br>backend/app/services/tender_sources/world_bank.py<br>backend/app/workers/source_refresh_tasks.py<br>backend/app/workers/tender_tasks.py | backend/scripts/audit_sr1_source_refresh.py<br>backend/scripts/audit_sr2_1_semantic_batch.py<br>backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py<br>backend/scripts/purge_small_scale_uzex_tenders.py<br>backend/scripts/test_s1_1_project_foundation.py<br>backend/seed_tenders.py<br>backend/test_adb_connector.py<br>backend/test_ebrd_connector.py<br>backend/test_giz_connector.py<br>backend/test_s0_5b1_unknown_actionability.py<br>backend/test_s1_1_project_foundation.py<br>backend/test_s1_2_world_bank_project_enrichment.py<br>backend/test_s5_cross_source_regression.py<br>backend/test_sr2_1_semantic_batch_persistence.py<br>backend/test_sr2_3_connector_capability_document_decoupling.py<br>backend/test_tender_source_foundation.py<br>backend/test_uzex_contact.py<br>backend/test_world_bank_connector.py |
| backend/app/services/tender_sources/adb.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/workers/tender_tasks.py | backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py<br>backend/test_adb_connector.py<br>backend/test_s0_5b1_unknown_actionability.py<br>backend/test_s5_cross_source_regression.py<br>backend/test_sr2_3_connector_capability_document_decoupling.py |
| backend/app/services/tender_sources/base.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/services/giz_document_hydration.py<br>backend/app/services/tender_sources/adb.py<br>backend/app/services/tender_sources/ebrd.py<br>backend/app/services/tender_sources/giz.py<br>backend/app/services/tender_sources/uzex.py<br>backend/app/services/tender_sources/world_bank.py<br>backend/app/workers/tender_tasks.py | backend/scripts/audit_sr1_source_refresh.py<br>backend/scripts/audit_sr2_1_semantic_batch.py<br>backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py<br>backend/scripts/test_s1_1_project_foundation.py<br>backend/seed_tenders.py<br>backend/test_ebrd_connector.py<br>backend/test_s0_5b1_unknown_actionability.py<br>backend/test_s1_2_world_bank_project_enrichment.py<br>backend/test_s5_cross_source_regression.py<br>backend/test_sr2_1_semantic_batch_persistence.py<br>backend/test_sr2_3_connector_capability_document_decoupling.py<br>backend/test_tender_source_foundation.py<br>backend/test_world_bank_connector.py |
| backend/app/services/tender_sources/diagnostics.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/services/tender_sources/adb.py<br>backend/app/services/tender_sources/ebrd.py<br>backend/app/services/tender_sources/giz.py<br>backend/app/workers/source_refresh_tasks.py | — |
| backend/app/services/tender_sources/ebrd.py | active/support | backend/app/api/endpoints/tenders.py | backend/test_ebrd_connector.py<br>backend/test_s5_cross_source_regression.py |
| backend/app/services/tender_sources/giz.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/services/giz_document_hydration.py | backend/test_giz_connector.py<br>backend/test_s5_cross_source_regression.py |
| backend/app/services/tender_sources/keys.py | active/support | backend/app/core/reproducibility.py<br>backend/app/services/projects.py<br>backend/app/services/source_refresh_jobs.py<br>backend/app/services/tender_sources/__init__.py<br>backend/app/services/tender_sources/base.py | backend/test_adb_connector.py<br>backend/test_ebrd_connector.py<br>backend/test_giz_connector.py<br>backend/test_tender_source_foundation.py<br>backend/test_world_bank_connector.py |
| backend/app/services/tender_sources/uzex.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/workers/tender_tasks.py | — |
| backend/app/services/tender_sources/uzex_constants.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/core/scraper.py<br>backend/app/services/tender_sources/uzex_scope.py | backend/scripts/purge_small_scale_uzex_tenders.py |
| backend/app/services/tender_sources/uzex_contact.py | active/support | backend/app/api/endpoints/tenders.py<br>backend/app/core/scraper.py | backend/test_uzex_contact.py |
| backend/app/services/tender_sources/uzex_scope.py | active/support | backend/app/api/endpoints/admin.py<br>backend/app/api/endpoints/tenders.py<br>backend/app/services/explorer.py<br>backend/app/services/tender_sources/uzex.py | backend/scripts/purge_small_scale_uzex_tenders.py |
| backend/app/services/tender_sources/world_bank.py | active/support | backend/app/api/endpoints/tenders.py | backend/scripts/test_s1_1_project_foundation.py<br>backend/test_s1_1_project_foundation.py<br>backend/test_s5_cross_source_regression.py<br>backend/test_world_bank_connector.py |
| backend/app/services/world_bank_projects.py | active/support | backend/app/services/project_enrichment.py<br>backend/app/workers/project_enrichment_tasks.py | backend/scripts/test_s1_2_project_enrichment.py<br>backend/test_s1_2_world_bank_project_enrichment.py |

## Components

| Module | Classification | Callers |
| --- | --- | --- |
| frontend/components/bid-preparation/PrepareBidButton.tsx | active | frontend/app/dashboard/bid-preparation/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/tenders/EngagementWorkflowActions.tsx<br>frontend/components/tenders/TenderEngagementPanel.tsx |
| frontend/components/i18n/BidiText.tsx | active | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx<br>frontend/app/dashboard/bid-preparation/page.tsx<br>frontend/app/dashboard/my-tenders/page.tsx<br>frontend/app/dashboard/page.tsx<br>frontend/app/dashboard/readiness-vault/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/source-refresh/SourceRefreshMenu.tsx<br>frontend/components/source-refresh/SourceRefreshProvider.tsx |
| frontend/components/i18n/LanguageSelector.tsx | active | frontend/app/dashboard/onboarding/page.tsx<br>frontend/app/dashboard/settings/page.tsx |
| frontend/components/source-refresh/SourceRefreshMenu.tsx | active | frontend/app/dashboard/tenders/page.tsx |
| frontend/components/source-refresh/SourceRefreshProvider.tsx | active | frontend/app/dashboard/layout.tsx<br>frontend/app/dashboard/my-tenders/page.tsx<br>frontend/app/dashboard/page.tsx<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/source-refresh/SourceRefreshMenu.tsx |
| frontend/components/tenders/EngagementWorkflowActions.tsx | active | frontend/app/dashboard/my-tenders/page.tsx<br>frontend/app/dashboard/tenders/page.tsx<br>frontend/components/tenders/TenderEngagementPanel.tsx |
| frontend/components/tenders/NewTenderBadge.tsx | active | frontend/app/dashboard/tenders/page.tsx |
| frontend/components/tenders/RecommendationSummary.tsx | active | frontend/app/dashboard/tenders/page.tsx |
| frontend/components/tenders/TenderEngagementPanel.tsx | active | frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx |
| frontend/components/workspace/DocumentViewer.tsx | active | frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx |

## Hooks

| Hook / source | Classification | Runtime references |
| --- | --- | --- |
| useSourceRefresh<br>frontend/components/source-refresh/SourceRefreshProvider.tsx:621 | Active | frontend/app/dashboard/my-tenders/page.tsx:30<br>frontend/app/dashboard/page.tsx:21<br>frontend/app/dashboard/tenders/[tenderId]/page.tsx:37<br>frontend/app/dashboard/tenders/page.tsx:31<br>frontend/components/source-refresh/SourceRefreshMenu.tsx:6 |
| useGeographyMeta<br>frontend/lib/geography.ts:102 | Active | frontend/app/dashboard/onboarding/page.tsx:21<br>frontend/app/dashboard/settings/page.tsx:15 |
| useServiceMeta<br>frontend/lib/services.ts:67 | Active | frontend/app/admin/companies/[companyProfileId]/page.tsx:14<br>frontend/app/dashboard/onboarding/page.tsx:23<br>frontend/app/dashboard/page.tsx:26<br>frontend/app/dashboard/readiness-vault/page.tsx:28<br>frontend/app/dashboard/settings/page.tsx:17 |

## Environment and flags

| Name | Classification / owner | Default / requirement | Keep / risk | References |
| --- | --- | --- | --- | --- |
| AUTH_SECRET | secret | Value withheld; secret | KEEP or explicit config compatibility review | backend/test_p0_2a_release_admin_repair.py:66<br>docker-compose.yml:96<br>frontend/auth.ts:94<br>frontend/middleware.ts:36<br>frontend/tests/make-s35-session.mjs:3<br>frontend/tests/make-s42-session.mjs:3<br>frontend/tests/make-s72-session.mjs:3 |
| AUTO_CREATE_TABLES | runtime; required/optional in review matrix | false | REVIEW; production must disable | backend/app/core/config.py:64 |
| BACKEND_CORS_ORIGINS | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/config.py:55 |
| BACKEND_INTERNAL_URL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | docker-compose.yml:84<br>frontend/lib/backendApiBase.ts:6<br>frontend/next.config.ts:8<br>scripts/compose-release.sh:10 |
| BASH_SOURCE | Shell special variable (not configuration) | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | scripts/compose-release.sh:4 |
| CELERY_BROKER_URL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/celery_app.py:22 |
| CELERY_RESULT_BACKEND | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/celery_app.py:23 |
| CELERY_WORKER_MAX_TASKS_PER_CHILD | runtime; required/optional in review matrix | 10 | KEEP or explicit config compatibility review | backend/app/core/celery_app.py:59 |
| DATABASE_URL | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/scripts/run_s0_3_schema_data_preflight.py:95 |
| DEMO_OCR_BYPASS | runtime; required/optional in review matrix | off | REVIEW; production must disable | backend/app/core/parser.py:100 |
| DOCKER_BIN | test-only | docker | KEEP or explicit config compatibility review | scripts/compose-release.sh:11 |
| FRONTEND_NEXT_PUBLIC_API_URL | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | docker-compose.yml:83<br>docker-compose.yml:94<br>scripts/compose-release.sh:9 |
| GEMINI_API_KEY | secret | Value withheld; secret | KEEP or explicit config compatibility review | backend/app/core/agents/hunter.py:59<br>backend/app/core/agents/requirement_extractor.py:1655<br>backend/app/core/agents/strategy_extractor.py:441<br>backend/app/core/ai.py:116<br>backend/app/core/ai_analyzer.py:75<br>backend/app/core/config.py:51<br>backend/app/core/parser.py:120<br>backend/app/core/parser.py:124 |
| GEMINI_EXTRACTION_MODEL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/ai_analyzer.py:21 |
| GEMINI_MODEL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/ai.py:45 |
| GEMINI_REQUIREMENT_CHUNK_CONCURRENCY | runtime; required/optional in review matrix | 3 | KEEP or explicit config compatibility review | backend/app/core/agents/requirement_extractor.py:67 |
| GEMINI_REQUIREMENT_CHUNK_OVERLAP_CHARS | runtime; required/optional in review matrix | 1000 | KEEP or explicit config compatibility review | backend/app/core/agents/requirement_extractor.py:64 |
| GEMINI_REQUIREMENT_MAX_PAYLOAD_CHARS | runtime; required/optional in review matrix | 120000 | KEEP or explicit config compatibility review | backend/app/core/agents/requirement_extractor.py:63 |
| GEMINI_REQUIREMENT_MODEL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/agents/requirement_extractor.py:60 |
| GIZ_MAX_ARCHIVE_COMPRESSED_BYTES | runtime; required/optional in review matrix | 100 MiB | KEEP or explicit config compatibility review | backend/app/services/tender_sources/giz.py:57 |
| GIZ_MAX_ARCHIVE_EXTRACTED_BYTES | runtime; required/optional in review matrix | 250 MiB | KEEP or explicit config compatibility review | backend/app/services/tender_sources/giz.py:61 |
| GIZ_MAX_ARCHIVE_FILE_COUNT | runtime; required/optional in review matrix | 200 | KEEP or explicit config compatibility review | backend/app/services/tender_sources/giz.py:65 |
| GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES | runtime; required/optional in review matrix | 50 MiB | KEEP or explicit config compatibility review | backend/app/services/tender_sources/giz.py:66 |
| GIZ_MAX_ARCHIVE_NESTING_DEPTH | runtime; required/optional in review matrix | 1 | KEEP or explicit config compatibility review | backend/app/services/tender_sources/giz.py:70 |
| GOOGLE_API_KEY | secret | Value withheld; secret | KEEP or explicit config compatibility review | backend/app/core/agents/hunter.py:60<br>backend/app/core/agents/requirement_extractor.py:1656<br>backend/app/core/agents/strategy_extractor.py:442<br>backend/app/core/ai.py:117<br>backend/app/core/ai_analyzer.py:76<br>backend/app/core/config.py:52<br>backend/app/core/parser.py:121<br>backend/app/core/parser.py:124<br>backend/test_ai.py:9 |
| GOOGLE_CLIENT_ID | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | docker-compose.yml:98<br>frontend/auth.ts:102 |
| GOOGLE_CLIENT_SECRET | secret | Value withheld; secret | KEEP or explicit config compatibility review | docker-compose.yml:99<br>frontend/auth.ts:103 |
| LOCALAPPDATA | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/tests/s7-4-final-browser-acceptance.py:106<br>frontend/tests/s8-3-arabic-rtl-browser-acceptance.py:205 |
| NEXTAUTH_URL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/lib/backendApiBase.ts:14 |
| NEXT_DIST_DIR | runtime; required/optional in review matrix | .next | KEEP or explicit config compatibility review | frontend/next.config.ts:5 |
| NEXT_PUBLIC_BUILD_SHA | public | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/app/api/build/route.ts:6 |
| NODE_ENV | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/app/api/build/route.ts:8<br>frontend/app/api/ui-locale/route.ts:26<br>frontend/i18n/pseudoLocale.ts:81<br>frontend/middleware.ts:37<br>frontend/middleware.ts:72 |
| PLASMA_ADMIN_EMAILS | runtime; required/optional in review matrix | empty allowlist | KEEP or explicit config compatibility review | backend/app/api/deps.py:46<br>backend/app/cli/admin_management.py:163<br>backend/app/cli/admin_management.py:193 |
| PLASMA_BOOTSTRAP_DATABASE_URL | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/scripts/bootstrap_database.py:31 |
| PLASMA_BUILD_SHA | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/release.py:74<br>backend/app/core/reproducibility.py:390<br>docker-compose.yml:108<br>docker-compose.yml:131<br>docker-compose.yml:157<br>docker-compose.yml:55<br>docker-compose.yml:85<br>frontend/app/api/build/route.ts:6<br>scripts/compose-release.sh:7 |
| PLASMA_BUILD_TIME | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/release.py:75<br>backend/app/core/reproducibility.py:391<br>docker-compose.yml:109<br>docker-compose.yml:132<br>docker-compose.yml:158<br>docker-compose.yml:56<br>docker-compose.yml:86<br>frontend/app/api/build/route.ts:7<br>scripts/compose-release.sh:8 |
| PLASMA_ENABLE_PSEUDO_LOCALE | runtime; required/optional in review matrix | off; nonproduction only | KEEP or explicit config compatibility review | frontend/i18n/pseudoLocale.ts:81 |
| PLASMA_OPERATOR_EMAILS | runtime; required/optional in review matrix | empty allowlist | KEEP or explicit config compatibility review | backend/app/api/deps.py:51 |
| PLASMA_SERVICE_NAME | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/release.py:73 |
| POSTGRES_DB | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/config.py:45<br>backend/scripts/run_s0_3_schema_data_preflight.py:107<br>docker-compose.yml:14 |
| POSTGRES_PASSWORD | secret | Value withheld; secret | KEEP or explicit config compatibility review | backend/app/core/config.py:44<br>backend/scripts/run_s0_3_schema_data_preflight.py:106<br>docker-compose.yml:13 |
| POSTGRES_PORT | runtime; required/optional in review matrix | 6543 (app); 5432 (Compose) | KEEP or explicit config compatibility review | backend/app/core/config.py:46<br>backend/scripts/run_s0_3_schema_data_preflight.py:112 |
| POSTGRES_SERVER | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/config.py:42<br>backend/scripts/run_s0_3_schema_data_preflight.py:102 |
| POSTGRES_USER | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/core/config.py:43<br>backend/scripts/run_s0_3_schema_data_preflight.py:105<br>docker-compose.yml:12 |
| S72_ACCESS_TOKEN | secret | Value withheld; secret | KEEP or explicit config compatibility review | frontend/tests/make-s72-session.mjs:6 |
| S72_IS_ADMIN | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/tests/make-s72-session.mjs:14 |
| S72_PLATFORM_ROLE | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/tests/make-s72-session.mjs:13 |
| S72_USER_LABEL | test-only | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/tests/make-s72-session.mjs:5 |
| SECRET_KEY | secret | Value withheld; secret | KEEP or explicit config compatibility review | backend/app/core/config.py:49 |
| SOURCE_REFRESH_COOLDOWN_SECONDS | runtime; required/optional in review matrix | 300 | KEEP or explicit config compatibility review | backend/app/api/endpoints/tenders.py:7597 |
| SOURCE_REFRESH_HEARTBEAT_SECONDS | runtime; required/optional in review matrix | 30 | KEEP or explicit config compatibility review | backend/app/services/source_refresh_jobs.py:56 |
| SOURCE_REFRESH_LEASE_SECONDS | runtime; required/optional in review matrix | 180 | KEEP or explicit config compatibility review | backend/app/services/source_refresh_jobs.py:49 |
| SOURCE_REFRESH_QUEUED_REPUBLISH_SECONDS | runtime; required/optional in review matrix | 60 | KEEP or explicit config compatibility review | backend/app/services/source_refresh_jobs.py:64 |
| TELEGRAM_BOT_TOKEN | secret | Value withheld; secret | KEEP or explicit config compatibility review | backend/app/core/config.py:50 |
| TENDER_DOCUMENTS_ROOT | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/services/giz_document_hydration.py:41<br>backend/app/workers/tender_tasks.py:46 |
| TENDER_DOC_DOWNLOAD_JITTER_MAX_SECONDS | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/workers/tender_tasks.py:247 |
| TENDER_DOC_DOWNLOAD_JITTER_MIN_SECONDS | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | backend/app/workers/tender_tasks.py:241 |
| TENDER_OCR_DISABLED | runtime; required/optional in review matrix | off | KEEP or explicit config compatibility review | backend/app/core/parser.py:99 |
| TENDER_OCR_MAX_PAGES | runtime; required/optional in review matrix | 2 | KEEP or explicit config compatibility review | backend/app/core/parser.py:91 |
| TENDER_OCR_PAGE_TIMEOUT_SECONDS | runtime; required/optional in review matrix | 12 | KEEP or explicit config compatibility review | backend/app/core/parser.py:90 |
| TENDER_OCR_RENDER_DPI | runtime; required/optional in review matrix | 150 | KEEP or explicit config compatibility review | backend/app/core/parser.py:92 |
| TENDER_OCR_SKIP_AFTER_TEXT_CHARS | runtime; required/optional in review matrix | 5000 | KEEP or explicit config compatibility review | backend/app/core/parser.py:93 |
| VERCEL_URL | runtime; required/optional in review matrix | See source default; optional unless required by selected service | KEEP or explicit config compatibility review | frontend/lib/backendApiBase.ts:15 |
| WORLD_BANK_AUTODRAIN_BATCH_SIZE | runtime; required/optional in review matrix | 25 | KEEP or explicit config compatibility review | backend/app/services/project_enrichment.py:29<br>docker-compose.yml:122 |
| WORLD_BANK_AUTODRAIN_INTERVAL_SECONDS | runtime; required/optional in review matrix | 60 minimum | KEEP or explicit config compatibility review | backend/app/core/celery_app.py:26<br>docker-compose.yml:171 |
| WORLD_BANK_ENRICHMENT_RETRY_BACKOFF_SECONDS | runtime; required/optional in review matrix | 900 | KEEP or explicit config compatibility review | backend/app/services/project_enrichment.py:37<br>docker-compose.yml:123 |

Configured `.env` names are stored separately in JSON; values are not retained. Compose/script inputs are operational even when the conservative source scan labels them test/tool-only. `NEXT_PUBLIC_API_URL` and `ACCESS_TOKEN_EXPIRE_MINUTES` are stale configured inputs discussed in the main report.

## Celery tasks

| Function / location | Task registration | Queue / lifecycle | Call references |
| --- | --- | --- | --- |
| run_hunter_sweep<br>backend/app/workers/hunter_tasks.py:172 | celery_app.task(name='app.workers.hunter_tasks.run_hunter_sweep', bind=True) | ai_fast_queue; Beat every 30m | backend/app/core/celery_app.py:62 |
| enrich_world_bank_project_task<br>backend/app/workers/project_enrichment_tasks.py:148 | celery_app.task(name='app.workers.project_enrichment_tasks.enrich_world_bank_project', bind=True, max_retries=3, rate_limit='30/m', soft_time_limit=60, time_limit=90) | celery; dispatched worker | backend/app/services/project_enrichment.py:492 |
| dispatch_world_bank_project_enrichment_backlog_task<br>backend/app/workers/project_enrichment_tasks.py:175 | celery_app.task(name='app.workers.project_enrichment_tasks.dispatch_world_bank_project_enrichment_backlog', soft_time_limit=30, time_limit=45) | celery; Beat autodrain | — |
| refresh_tender_source<br>backend/app/workers/source_refresh_tasks.py:302 | celery_app.task(name='app.workers.source_refresh_tasks.refresh_tender_source', bind=True) | celery; dispatched worker | backend/app/api/endpoints/tenders.py:271<br>backend/app/core/celery_app.py:87 |
| enrich_adb_document<br>backend/app/workers/tender_tasks.py:200 | celery_app.task(name='app.workers.tender_tasks.enrich_adb_document', bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3}) | heavy_dl_queue; explicit document work | backend/app/api/endpoints/tenders.py:268<br>backend/app/core/celery_app.py:110 |
| process_tender_docs<br>backend/app/workers/tender_tasks.py:1400 | celery_app.task(bind=True) | heavy_dl_queue; explicit document work | backend/app/api/endpoints/tenders.py:269<br>backend/app/core/celery_app.py:106<br>backend/app/workers/hunter_tasks.py:24 |
| hydrate_giz_documents<br>backend/app/workers/tender_tasks.py:1530 | celery_app.task(bind=True) | heavy_dl_queue; explicit document work | backend/app/api/endpoints/tenders.py:267<br>backend/app/core/celery_app.py:102 |

## Duplicate test basenames

| Existing pair | Exact proposed script rename | Condition |
| --- | --- | --- |
| backend/scripts/test_s1_1_project_foundation.py<br>backend/test_s1_1_project_foundation.py | backend/scripts/verify_s1_1_project_foundation.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s2_1_compliance_ownership.py<br>backend/test_s2_1_compliance_ownership.py | backend/scripts/verify_s2_1_compliance_ownership.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s2_2_analysis_version_foundation.py<br>backend/test_s2_2_analysis_version_foundation.py | backend/scripts/verify_s2_2_analysis_version_foundation.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s2_2b_analysis_aggregate_concurrency.py<br>backend/test_s2_2b_analysis_aggregate_concurrency.py | backend/scripts/verify_s2_2b_analysis_aggregate_concurrency.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s2_3_version_aware_compliance_reads.py<br>backend/test_s2_3_version_aware_compliance_reads.py | backend/scripts/verify_s2_3_version_aware_compliance_reads.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s3_3_privileged_account_survivability.py<br>backend/test_s3_3_privileged_account_survivability.py | backend/scripts/verify_s3_3_privileged_account_survivability.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s3_4_administrative_audit_hardening.py<br>backend/test_s3_4_administrative_audit_hardening.py | backend/scripts/verify_s3_4_administrative_audit_hardening.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s3_5_admin_operational_ux_hardening.py<br>backend/test_s3_5_admin_operational_ux_hardening.py | backend/scripts/verify_s3_5_admin_operational_ux_hardening.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s4_1_tender_engagement_foundation.py<br>backend/test_s4_1_tender_engagement_foundation.py | backend/scripts/verify_s4_1_tender_engagement_foundation.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s4_2_my_tenders_list_experience.py<br>backend/test_s4_2_my_tenders_list_experience.py | backend/scripts/verify_s4_2_my_tenders_list_experience.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s4_3_bid_preparation_reconciliation.py<br>backend/test_s4_3_bid_preparation_reconciliation.py | backend/scripts/verify_s4_3_bid_preparation_reconciliation.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s4_4_tender_engagement_workflow_ux.py<br>backend/test_s4_4_tender_engagement_workflow_ux.py | backend/scripts/verify_s4_4_tender_engagement_workflow_ux.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s5_2_tender_details_read_model.py<br>backend/test_s5_2_tender_details_read_model.py | backend/scripts/verify_s5_2_tender_details_read_model.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_s6_2_unified_explorer_backend.py<br>backend/test_s6_2_unified_explorer_backend.py | backend/scripts/verify_s6_2_unified_explorer_backend.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |
| backend/scripts/test_wb_project_enrichment_autodrain.py<br>backend/test_wb_project_enrichment_autodrain.py | backend/scripts/verify_wb_project_enrichment_autodrain.py | Update every scripts import/reference; keep root test name; run both domain and migration proof |

## Test topology

| File | Classification |
| --- | --- |
| backend/scripts/__pycache__/test_evaluator.cpython-314.pyc | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/__pycache__/test_extraction.cpython-314.pyc | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_evaluator.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_extraction.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s0_5b3_migration.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s0_5b4_baseline.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s0_5b5_drift.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s1_1_project_foundation.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s1_2_project_enrichment.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s2_1_compliance_ownership.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s2_2_analysis_version_foundation.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s2_2b_analysis_aggregate_concurrency.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s2_3_version_aware_compliance_reads.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s3_3_privileged_account_survivability.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s3_4_administrative_audit_hardening.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s3_5_admin_operational_ux_hardening.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s4_1_tender_engagement_foundation.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s4_2_my_tenders_list_experience.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s4_3_bid_preparation_reconciliation.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s4_4_tender_engagement_workflow_ux.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s5_2_tender_details_read_model.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s6_2_unified_explorer_backend.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s7_2_locale_migration.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_s8_2_analysis_language_migration.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/scripts/test_wb_project_enrichment_autodrain.py | PostgreSQL proof / developer script; inspect main before invocation |
| backend/test_adb_connector.py | Domain regression / frontend static or fixture |
| backend/test_ai.py | Import-time developer probe; move/guard |
| backend/test_compliance_forensic_categories.py | Domain regression / frontend static or fixture |
| backend/test_download.pdf | Domain regression / frontend static or fixture |
| backend/test_ebrd_connector.py | Domain regression / frontend static or fixture |
| backend/test_extractor_validators.py | Domain regression / frontend static or fixture |
| backend/test_giz_connector.py | Domain regression / frontend static or fixture |
| backend/test_giz_hydration_worker.py | Domain regression / frontend static or fixture |
| backend/test_p0_2a_release_admin_repair.py | Domain regression / frontend static or fixture |
| backend/test_p0_3a_onboarding_access.py | Domain regression / frontend static or fixture |
| backend/test_p0_3b_source_refresh.py | Domain regression / frontend static or fixture |
| backend/test_p0_security_static.py | Domain regression / frontend static or fixture |
| backend/test_parser_traceability.py | Domain regression / frontend static or fixture |
| backend/test_proxy.pdf | Domain regression / frontend static or fixture |
| backend/test_reproducibility_snapshot.py | Domain regression / frontend static or fixture |
| backend/test_s0_2_disabled_authorization.py | Domain regression / frontend static or fixture |
| backend/test_s0_3_schema_data_preflight.py | Domain regression / frontend static or fixture |
| backend/test_s0_5b1_unknown_actionability.py | Domain regression / frontend static or fixture |
| backend/test_s0_5b3_tender_recommendation_migration.py | Domain regression / frontend static or fixture |
| backend/test_s0_5b4_baseline_bootstrap.py | Domain regression / frontend static or fixture |
| backend/test_s0_5b5_alembic_drift.py | Domain regression / frontend static or fixture |
| backend/test_s1_1_project_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s1_2_world_bank_project_enrichment.py | Domain regression / frontend static or fixture |
| backend/test_s1_3_project_context_api.py | Domain regression / frontend static or fixture |
| backend/test_s1_3b_project_context_runtime_recovery.py | Domain regression / frontend static or fixture |
| backend/test_s1_access_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s1_access_hardening.py | Domain regression / frontend static or fixture |
| backend/test_s1_admin_approval_queue.py | Domain regression / frontend static or fixture |
| backend/test_s1_company_onboarding.py | Domain regression / frontend static or fixture |
| backend/test_s2_1_compliance_ownership.py | Domain regression / frontend static or fixture |
| backend/test_s2_1_readiness_vault.py | Domain regression / frontend static or fixture |
| backend/test_s2_2_analysis_version_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s2_2_geography.py | Domain regression / frontend static or fixture |
| backend/test_s2_2b_analysis_aggregate_concurrency.py | Domain regression / frontend static or fixture |
| backend/test_s2_3_services.py | Domain regression / frontend static or fixture |
| backend/test_s2_3_version_aware_compliance_reads.py | Domain regression / frontend static or fixture |
| backend/test_s2_4_readiness_admin.py | Domain regression / frontend static or fixture |
| backend/test_s3_1_admin_account_lifecycle.py | Domain regression / frontend static or fixture |
| backend/test_s3_1_tender_explorer_filters.py | Domain regression / frontend static or fixture |
| backend/test_s3_2_session_revocation_restore_security.py | Domain regression / frontend static or fixture |
| backend/test_s3_3_privileged_account_survivability.py | Domain regression / frontend static or fixture |
| backend/test_s3_4_administrative_audit_hardening.py | Domain regression / frontend static or fixture |
| backend/test_s3_5_admin_operational_ux_hardening.py | Domain regression / frontend static or fixture |
| backend/test_s4_1_tender_engagement_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s4_2_competitor_intelligence.py | Domain regression / frontend static or fixture |
| backend/test_s4_2_my_tenders_list_experience.py | Domain regression / frontend static or fixture |
| backend/test_s4_3_bid_preparation_reconciliation.py | Domain regression / frontend static or fixture |
| backend/test_s4_3_decision_snapshot.py | Domain regression / frontend static or fixture |
| backend/test_s4_4_tender_engagement_workflow_ux.py | Domain regression / frontend static or fixture |
| backend/test_s4_4_workflow_postgresql.py | Domain regression / frontend static or fixture |
| backend/test_s4_closeout_admin_documents.py | Domain regression / frontend static or fixture |
| backend/test_s5_1_tender_details_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s5_2_tender_details_read_model.py | Domain regression / frontend static or fixture |
| backend/test_s5_cross_source_regression.py | Domain regression / frontend static or fixture |
| backend/test_s6_1_hunter_explorer_convergence_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s6_2_unified_explorer_backend.py | Domain regression / frontend static or fixture |
| backend/test_s6_4_hunter_retirement_final_qa.py | Domain regression / frontend static or fixture |
| backend/test_s7_2_locale_foundation.py | Domain regression / frontend static or fixture |
| backend/test_s8_2_analysis_language.py | Domain regression / frontend static or fixture |
| backend/test_s8_3_arabic_ui_locale.py | Domain regression / frontend static or fixture |
| backend/test_scraper_download_variants.py | Domain regression / frontend static or fixture |
| backend/test_source_refresh_worker.py | Domain regression / frontend static or fixture |
| backend/test_sr2_1_semantic_batch_persistence.py | Domain regression / frontend static or fixture |
| backend/test_sr2_2_source_refresh_orchestration.py | Domain regression / frontend static or fixture |
| backend/test_sr2_3_connector_capability_document_decoupling.py | Domain regression / frontend static or fixture |
| backend/test_sr2_4_refresh_activity_source_catalog_newness.py | Domain regression / frontend static or fixture |
| backend/test_storage_path_resolver.py | Domain regression / frontend static or fixture |
| backend/test_strategy_extractor.py | Domain regression / frontend static or fixture |
| backend/test_tender_api.py | Import-time developer probe; move/guard |
| backend/test_tender_contact_submission.py | Domain regression / frontend static or fixture |
| backend/test_tender_document_status.py | Domain regression / frontend static or fixture |
| backend/test_tender_source_foundation.py | Domain regression / frontend static or fixture |
| backend/test_tender_worker_failure_handling.py | Domain regression / frontend static or fixture |
| backend/test_uzbek_nlp.py | Import-time developer probe; move/guard |
| backend/test_uzex_contact.py | Domain regression / frontend static or fixture |
| backend/test_wb_project_enrichment_autodrain.py | Domain regression / frontend static or fixture |
| backend/test_world_bank_connector.py | Domain regression / frontend static or fixture |
| frontend/tests/admin-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/admin-operational-ux.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/bid-preparation-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/bid-preparation.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/cdp-port-forward.mjs | Domain regression / frontend static or fixture |
| frontend/tests/engagement-workflow-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/engagement-workflow.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/hunter-retirement-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/hunter-retirement.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/localization-foundation.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/make-s35-session.mjs | Domain regression / frontend static or fixture |
| frontend/tests/make-s42-session.mjs | Domain regression / frontend static or fixture |
| frontend/tests/make-s72-session.mjs | Domain regression / frontend static or fixture |
| frontend/tests/my-tenders-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/my-tenders.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/project-context.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/s7-2-localization-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/s7-3-p0-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/s7-3-p0-localization.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/s7-4-final-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/s7-4-p1-localization.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/s7-4-pseudo-locale.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/s8-2-analysis-language-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/s8-2-analysis-language.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/s8-3-arabic-rtl-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/s8-3-arabic-rtl.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/source-refresh-newness-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/source-refresh-newness.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/tender-cleanup-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/tender-cleanup.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/tender-details-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/tender-details.test.mjs | Domain regression / frontend static or fixture |
| frontend/tests/unified-explorer-browser-acceptance.py | Browser harness/fixture; platform constraints apply |
| frontend/tests/unified-explorer.test.mjs | Domain regression / frontend static or fixture |

## Documentation

| File | Classification | Decision |
| --- | --- | --- |
| backend/docs/ebrd_source_audit.md | review setup/connector reference | UPDATE canonical setup guidance / preserve connector research |
| docs/S1_1_CANONICAL_PROJECT_FOUNDATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S1_2_WORLD_BANK_PROJECT_ENRICHMENT_TTL.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S1_3B_PROJECT_CONTEXT_RUNTIME_RECOVERY.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S1_3C_RUNTIME_RECOVERY_DELTA_AUDIT.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S1_3_PROJECT_CONTEXT_LEADERSHIP_UI.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S2_1_COMPLIANCE_OWNERSHIP_QUARANTINE.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S2_2B_ANALYSIS_AGGREGATE_CONCURRENCY.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S2_2_ANALYSIS_VERSION_EVIDENCE_FOUNDATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S2_3_VERSION_AWARE_COMPLIANCE_READS.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S3_1_ADMIN_ACCOUNT_LIFECYCLE.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S3_2_SESSION_REVOCATION_RESTORE_SECURITY.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S3_3_PRIVILEGED_ACCOUNT_SURVIVABILITY.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S3_4_ADMINISTRATIVE_AUDIT_HARDENING.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S3_5_ADMIN_OPERATIONAL_UX_HARDENING.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S4_1_TENDER_ENGAGEMENT_FOUNDATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S4_2_MY_TENDERS_LIST_EXPERIENCE.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S4_3_BID_PREPARATION_PROPOSAL_RECONCILIATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S4_4_TENDER_ENGAGEMENT_WORKFLOW_UX.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S5_1_CANONICAL_TENDER_DETAILS_FOUNDATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S5_2_TENDER_DETAILS_READ_MODEL.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S5_3_CONSOLIDATED_TENDER_DETAILS_UI.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S5_4_TENDER_DETAILS_FINAL_CLEANUP.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S6_1_HUNTER_EXPLORER_CONVERGENCE_FOUNDATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S6_2_UNIFIED_EXPLORER_BACKEND.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S6_3_UNIFIED_EXPLORER_UI.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S6_4_HUNTER_RETIREMENT_FINAL_QA.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S7_1_LOCALIZATION_ARCHITECTURE_AUDIT.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S7_2_LOCALE_PERSISTENCE_RUNTIME_FOUNDATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S7_3_P0_CUSTOMER_LOCALIZATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S7_4_FINAL_LOCALIZATION_QA.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S8_1_ANALYSIS_LANGUAGE_ARABIC_RTL_ARCHITECTURE_AUDIT.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S8_2_INDEPENDENT_ANALYSIS_LANGUAGE.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/S8_3_ARABIC_UI_RTL_IMPLEMENTATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/SR_1_SOURCE_REFRESH_EXECUTION_EFFICIENCY_AUDIT.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/SR_2_1_SEMANTIC_BATCH_TENDER_PERSISTENCE.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/SR_2_2_DURABLE_SOURCE_REFRESH_ORCHESTRATION.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/SR_2_3_CONNECTOR_CAPABILITY_DOCUMENT_DECOUPLING.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/SR_2_4_REFRESH_ACTIVITY_SOURCE_CATALOG_NEWNESS.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/SR_3_SOURCE_REFRESH_UX_NOTIFICATIONS_NEW_BADGE.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| docs/WB_PROJECT_ENRICHMENT_AUTODRAIN_HOTFIX.md | historical sprint evidence | PRESERVE historical evidence; label baseline/SHA |
| frontend/README.md | review setup/connector reference | UPDATE canonical setup guidance / preserve connector research |

## Scripts

| File | Classification |
| --- | --- |
| backend/scripts/__pycache__/seed_taxonomy.cpython-314.pyc | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/__pycache__/test_evaluator.cpython-314.pyc | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/__pycache__/test_extraction.cpython-314.pyc | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/__pycache__/verify_vault_db.cpython-314.pyc | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/audit_sr1_source_refresh.py | Audit/report tooling |
| backend/scripts/audit_sr2_1_semantic_batch.py | Audit/report tooling |
| backend/scripts/audit_sr2_2_source_refresh_orchestration.py | Audit/report tooling |
| backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py | Audit/report tooling |
| backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py | Audit/report tooling |
| backend/scripts/bootstrap_database.py | Migration proof/bootstrap; preserve |
| backend/scripts/diff_reproducibility.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/enqueue_world_bank_project_enrichment.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/models_output.txt | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/purge_small_scale_uzex_tenders.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/qa_s8_2_live_model_languages.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/report_analysis_aggregate_concurrency.py | Audit/report tooling |
| backend/scripts/report_world_bank_project_enrichment_backlog.py | Audit/report tooling |
| backend/scripts/run_connector_regression_gate.sh | Connector release gate |
| backend/scripts/run_s0_3_schema_data_preflight.py | Audit/report tooling |
| backend/scripts/seed_taxonomy.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_evaluator.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_extraction.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s0_5b3_migration.py | Migration proof/bootstrap; preserve |
| backend/scripts/test_s0_5b4_baseline.py | Migration proof/bootstrap; preserve |
| backend/scripts/test_s0_5b5_drift.py | Migration proof/bootstrap; preserve |
| backend/scripts/test_s1_1_project_foundation.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s1_2_project_enrichment.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s2_1_compliance_ownership.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s2_2_analysis_version_foundation.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s2_2b_analysis_aggregate_concurrency.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s2_3_version_aware_compliance_reads.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s3_3_privileged_account_survivability.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s3_4_administrative_audit_hardening.py | Audit/report tooling |
| backend/scripts/test_s3_5_admin_operational_ux_hardening.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s4_1_tender_engagement_foundation.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s4_2_my_tenders_list_experience.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s4_3_bid_preparation_reconciliation.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s4_4_tender_engagement_workflow_ux.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s5_2_tender_details_read_model.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s6_2_unified_explorer_backend.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/test_s7_2_locale_migration.py | Migration proof/bootstrap; preserve |
| backend/scripts/test_s8_2_analysis_language_migration.py | Migration proof/bootstrap; preserve |
| backend/scripts/test_wb_project_enrichment_autodrain.py | Historical proof / developer probe; preserve until explicit caller review |
| backend/scripts/verify_vault_db.py | Historical proof / developer probe; preserve until explicit caller review |
| frontend/scripts/audit-customer-literals.mjs | Audit/report tooling |
| frontend/scripts/audit-rtl.mjs | Audit/report tooling |
| scripts/compose-release.sh | Release operational wrapper; not executed |

## Root developer utilities

| File | Classification / decision |
| --- | --- |
| backend/add_company_columns.py | Legacy schema/data mutation; do not use as release bootstrap |
| backend/add_financial_columns.py | Legacy schema/data mutation; do not use as release bootstrap |
| backend/add_vault_profile_columns.py | Legacy schema/data mutation; do not use as release bootstrap |
| backend/debug_auth.py | Developer probe; not product coverage; make explicit and portable |
| backend/debug_dom.py | Developer probe; not product coverage; make explicit and portable |
| backend/diagnose.py | Developer probe; not product coverage; make explicit and portable |
| backend/init_db.py | Legacy schema/data mutation; do not use as release bootstrap |
| backend/local_test_ai.py | Developer probe; not product coverage; make explicit and portable |
| backend/local_test_parser.py | Developer probe; not product coverage; make explicit and portable |
| backend/reset_db.py | Legacy schema/data mutation; do not use as release bootstrap |
| backend/seed_tenders.py | Legacy schema/data mutation; do not use as release bootstrap |

## Package scripts

| Name | Command | Classification |
| --- | --- | --- |
| dev | next dev | Build/dev |
| build | next build | Build/dev |
| start | next start | Build/dev |
| lint | eslint | Existing static/domain gate |
| audit:literals | node scripts/audit-customer-literals.mjs | Existing static/domain gate |
| typecheck | tsc --noEmit | Existing static/domain gate |
| test:project-context | node --no-warnings --experimental-strip-types --test tests/project-context.test.mjs | Existing static/domain gate |
| test:localization-foundation | node --no-warnings --experimental-strip-types --test tests/localization-foundation.test.mjs | Existing static/domain gate |
| test:s7-3-localization | node --no-warnings --experimental-strip-types --test tests/s7-3-p0-localization.test.mjs | Existing static/domain gate |
| test:s7-4-localization | node --no-warnings --experimental-strip-types --test tests/s7-4-p1-localization.test.mjs tests/s7-4-pseudo-locale.test.mjs | Existing static/domain gate |
| test:s7-4-browser | python tests/s7-4-final-browser-acceptance.py | Platform-bound browser acceptance |
| test:s8-2-analysis-language | node --no-warnings --experimental-strip-types --test tests/s8-2-analysis-language.test.mjs | Existing static/domain gate |
| test:s8-2-browser | python tests/s8-2-analysis-language-browser-acceptance.py | Platform-bound browser acceptance |
| audit:rtl | node scripts/audit-rtl.mjs | Existing static/domain gate |
| test:s8-3-arabic-rtl | node --no-warnings --experimental-strip-types --test tests/s8-3-arabic-rtl.test.mjs | Existing static/domain gate |
| test:s8-3-browser | python tests/s8-3-arabic-rtl-browser-acceptance.py | Platform-bound browser acceptance |
| test:admin | node --no-warnings --experimental-strip-types --test tests/admin-operational-ux.test.mjs | Existing static/domain gate |
| test:my-tenders | node --no-warnings --experimental-strip-types --test tests/my-tenders.test.mjs | Existing static/domain gate |
| test:bid-preparation | node --no-warnings --experimental-strip-types --test tests/bid-preparation.test.mjs | Existing static/domain gate |
| test:engagement-workflow | node --no-warnings --experimental-strip-types --test tests/engagement-workflow.test.mjs | Existing static/domain gate |
| test:tender-details | node --no-warnings --experimental-strip-types --test tests/tender-details.test.mjs | Existing static/domain gate |
| test:tender-cleanup | node --no-warnings --experimental-strip-types --test tests/tender-cleanup.test.mjs | Existing static/domain gate |
| test:explorer | node --no-warnings --experimental-strip-types --test tests/unified-explorer.test.mjs | Existing static/domain gate |
| test:sr3 | node --no-warnings --experimental-strip-types --test tests/source-refresh-newness.test.mjs | Existing static/domain gate |
| test:hunter-retirement | node --no-warnings --experimental-strip-types --test tests/hunter-retirement.test.mjs | Existing static/domain gate |

## Migration graph

| File | Revision | Parent | Runtime imports | Decision |
| --- | --- | --- | --- | --- |
| backend/alembic/versions/14c7b4cac4ea_add_content_hash_and_analysis_id_.py | 14c7b4cac4ea | 65c42c5b80fa | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260227_0001_google_oauth_cutover.py | 20260227_0001_google_oauth_cutover | None | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260610_0001_multi_source_tender_foundation.py | 20260610_0001_multi_source_tender_foundation | a8f3d1c2e5b4 | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260624_0001_s1_1_access_foundation.py | 20260624_0001_s1_1_access_foundation | 20260610_0001_multi_source_tender_foundation | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260624_0002_s1_2_company_onboarding_notes.py | 20260624_0002_s1_2_company_onboarding_notes | 20260624_0001_s1_1_access_foundation | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260629_0001_s2_1_readiness_vault.py | 20260629_0001_s2_1_readiness_vault | 20260624_0002_s1_2_company_onboarding_notes | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260702_0001_s5_1_giz_source.py | 20260702_0001_s5_1_giz_source | 20260629_0001_s2_1_readiness_vault | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260704_0001_s5_2_1_ebrd_source.py | 20260704_0001_s5_2_1_ebrd_source | 20260702_0001_s5_1_giz_source | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260706_0001_release_identity_admin_repair.py | 20260706_0001_release_identity_admin_repair | 20260704_0001_s5_2_1_ebrd_source | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260709_0001_source_refresh_jobs.py | 20260709_0001_source_refresh_jobs | 20260706_0001_release_identity_admin_repair | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260824_0001_s0_4b_source_integrity.py | 20260824_0001_s0_4b | 20260709_0001_source_refresh_jobs | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260824_0002_s0_4c_adb_source_health.py | 20260824_0002_s0_4c | 20260824_0001_s0_4b | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260825_0001_s0_5b3_tender_recommendation_reconciliation.py | 20260825_0001_s0_5b3 | 20260824_0002_s0_4c | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260826_0001_s1_1_project_foundation.py | 20260826_0001_s1_1_project_foundation | 20260825_0001_s0_5b3 | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260826_0002_s1_2_wb_project_enrichment.py | 20260826_0002_s1_2_wb_project_enrichment | 20260826_0001_s1_1_project_foundation | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260827_0001_s2_1_compliance_ownership.py | 20260827_0001_s2_1_compliance_ownership | 20260826_0002_s1_2_wb_project_enrichment | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260827_0002_s2_2_analysis_version_foundation.py | 20260827_0002_s2_2_analysis_version_foundation | 20260827_0001_s2_1_compliance_ownership | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260828_0001_s3_1_admin_account_lifecycle.py | 20260828_0001_s3_1_admin_account_lifecycle | 20260827_0002_s2_2_analysis_version_foundation | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260828_0002_s3_4_admin_audit_hardening.py | 20260828_0002_s3_4_admin_audit_hardening | 20260828_0001_s3_1_admin_account_lifecycle | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260828_0003_s4_1_tender_engagement_foundation.py | 20260828_0003_s4_1_tender_engagement_foundation | 20260828_0002_s3_4_admin_audit_hardening | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260831_0001_sr2_2_refresh_leases.py | 20260831_0001_sr2_2_refresh_leases | 20260828_0003_s4_1_tender_engagement_foundation | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260901_0001_sr2_3_connector_metrics.py | 20260901_0001_sr2_3_connector_metrics | 20260831_0001_sr2_2_refresh_leases | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260902_0001_s7_2_user_ui_locale.py | 20260902_0001_s7_2_user_ui_locale | 20260901_0001_sr2_3_connector_metrics | None | KEEP immutable history; do not squash |
| backend/alembic/versions/20260904_0001_s8_2_analysis_language.py | 20260904_0001_s8_2_analysis_language | 20260902_0001_s7_2_user_ui_locale | None | KEEP immutable history; do not squash |
| backend/alembic/versions/27fc6790093d_add_tender_document_storage_fields.py | 27fc6790093d | 14c7b4cac4ea | None | KEEP immutable history; do not squash |
| backend/alembic/versions/619f79030fe7_add_dynamic_compliance_ontology_and_.py | 619f79030fe7 | 20260227_0001_google_oauth_cutover | None | KEEP immutable history; do not squash |
| backend/alembic/versions/65c42c5b80fa_add_tenderrecommendation_table.py | 65c42c5b80fa | 619f79030fe7 | None | KEEP immutable history; do not squash |
| backend/alembic/versions/9f3d2f4b6a10_add_tender_sync_jobs_table.py | 9f3d2f4b6a10 | 27fc6790093d | None | KEEP immutable history; do not squash |
| backend/alembic/versions/a8f3d1c2e5b4_add_override_seal_to_tender_analyses.py | a8f3d1c2e5b4 | d21a4f2b7c31 | None | KEEP immutable history; do not squash |
| backend/alembic/versions/d21a4f2b7c31_enforce_unique_user_tender_proposals.py | d21a4f2b7c31 | 9f3d2f4b6a10 | None | KEEP immutable history; do not squash |

## Localization keys

| Namespace/key | Classification |
| --- | --- |
| auth.welcomeBack | literal reference candidate |
| auth.connecting | literal reference candidate |
| auth.continueWithGoogle | literal reference candidate |
| auth.accessApproved | literal reference candidate |
| auth.redirecting | literal reference candidate |
| auth.accessPending | literal reference candidate |
| auth.pendingHelp | literal reference candidate |
| auth.profileSubmitted | literal reference candidate |
| auth.approvedHelp | literal reference candidate |
| auth.userApproval | literal reference candidate |
| auth.companyApproval | literal reference candidate |
| auth.nextReview | literal reference candidate |
| auth.nextSignin | literal reference candidate |
| auth.help | literal reference candidate |
| auth.refreshStatus | literal reference candidate |
| auth.refreshFailed | literal reference candidate |
| auth.logout | literal reference candidate |
| auth.notSubmitted | literal reference candidate |
| auth.pending | literal reference candidate |
| auth.approved | literal reference candidate |
| auth.rejected | literal reference candidate |
| auth.disabled | literal reference candidate |
| auth.blockedTitle | literal reference candidate |
| auth.disabledTitle | literal reference candidate |
| auth.blockedHelp | literal reference candidate |
| auth.disabledHelp | literal reference candidate |
| auth.reason | literal reference candidate |
| bidPreparation.title | literal reference candidate |
| bidPreparation.subtitle | literal reference candidate |
| bidPreparation.activeCount | literal reference candidate |
| bidPreparation.loadFailed | literal reference candidate |
| bidPreparation.emptyTitle | literal reference candidate |
| bidPreparation.emptyHelp | literal reference candidate |
| bidPreparation.browse | literal reference candidate |
| bidPreparation.tenderStatus | literal reference candidate |
| bidPreparation.preparationStatus | literal reference candidate |
| bidPreparation.deadline | literal reference candidate |
| bidPreparation.created | literal reference candidate |
| bidPreparation.open | literal reference candidate |
| bidPreparation.continue | literal reference candidate |
| bidPreparation.prepare | literal reference candidate |
| bidPreparation.loading | literal reference candidate |
| bidPreparation.notAvailable | literal reference candidate |
| bidPreparation.saveFailed | literal reference candidate |
| bidPreparation.saved | literal reference candidate |
| bidPreparation.save | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.saving | literal reference candidate |
| bidPreparation.proposal | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.documents | literal reference candidate |
| bidPreparation.requirements | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.pricing | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.team | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.submission | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.status.draft | literal reference candidate |
| bidPreparation.status.generating | literal reference candidate |
| bidPreparation.status.completed | literal reference candidate |
| bidPreparation.status.submitted | literal reference candidate |
| bidPreparation.status.unknown | literal reference candidate |
| bidPreparation.proposalBoundary | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.emptyDocuments | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.download | literal reference candidate |
| bidPreparation.upload | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.generate | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.export | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.value | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.buyer | dynamic/unreferenced candidate; no deletion proof |
| bidPreparation.source | literal reference candidate |
| bidPreparation.back | literal reference candidate |
| bidPreparation.yourPrice | literal reference candidate |
| bidPreparation.aiConfidence | literal reference candidate |
| bidPreparation.engagement | literal reference candidate |
| bidPreparation.backExplorer | literal reference candidate |
| bidPreparation.backDetails | literal reference candidate |
| bidPreparation.summaryLine | literal reference candidate |
| bidPreparation.noRegion | literal reference candidate |
| bidPreparation.generateStrategic | literal reference candidate |
| bidPreparation.generatingStrategic | literal reference candidate |
| bidPreparation.dismiss | literal reference candidate |
| bidPreparation.executiveSummary | literal reference candidate |
| bidPreparation.copied | literal reference candidate |
| bidPreparation.copy | literal reference candidate |
| bidPreparation.summaryPlaceholder | literal reference candidate |
| bidPreparation.lineItems | literal reference candidate |
| bidPreparation.item | literal reference candidate |
| bidPreparation.quantity | literal reference candidate |
| bidPreparation.unitPrice | literal reference candidate |
| bidPreparation.total | literal reference candidate |
| bidPreparation.noLineItems | literal reference candidate |
| bidPreparation.computedTotal | literal reference candidate |
| bidPreparation.commercialInputs | literal reference candidate |
| bidPreparation.companyName | literal reference candidate |
| bidPreparation.suggestedPrice | literal reference candidate |
| bidPreparation.deliveryWindow | literal reference candidate |
| bidPreparation.deliveryPlaceholder | literal reference candidate |
| bidPreparation.saveDraft | literal reference candidate |
| bidPreparation.downloadPdf | literal reference candidate |
| bidPreparation.downloadWord | literal reference candidate |
| bidPreparation.loadingDocuments | literal reference candidate |
| bidPreparation.noPreparedDocuments | literal reference candidate |
| bidPreparation.documentReady | literal reference candidate |
| bidPreparation.documentDiscovered | literal reference candidate |
| bidPreparation.unsupportedFormat | literal reference candidate |
| bidPreparation.preparationFailed | literal reference candidate |
| bidPreparation.opening | literal reference candidate |
| bidPreparation.preview | literal reference candidate |
| bidPreparation.previewPreparingTitle | literal reference candidate |
| bidPreparation.previewPreparingHelp | literal reference candidate |
| bidPreparation.previewUnavailableTitle | literal reference candidate |
| bidPreparation.previewUnavailableHelp | literal reference candidate |
| bidPreparation.documentsFailed | literal reference candidate |
| bidPreparation.quotaReached | literal reference candidate |
| bidPreparation.modelsBusy | literal reference candidate |
| bidPreparation.generationFailed | literal reference candidate |
| bidPreparation.actionUnavailable | literal reference candidate |
| bidPreparation.legacyOpening | literal reference candidate |
| bidPreparation.legacyInvalid | literal reference candidate |
| bidPreparation.legacyList | literal reference candidate |
| common.runtimeReady | dynamic/unreferenced candidate; no deletion proof |
| common.tenderCount | dynamic/unreferenced candidate; no deletion proof |
| common.newTendersFromSource | dynamic/unreferenced candidate; no deletion proof |
| common.richReview | dynamic/unreferenced candidate; no deletion proof |
| common.actions.save | dynamic/unreferenced candidate; no deletion proof |
| common.actions.cancel | dynamic/unreferenced candidate; no deletion proof |
| common.actions.close | dynamic/unreferenced candidate; no deletion proof |
| common.actions.retry | dynamic/unreferenced candidate; no deletion proof |
| common.actions.back | dynamic/unreferenced candidate; no deletion proof |
| common.actions.continue | dynamic/unreferenced candidate; no deletion proof |
| common.actions.search | dynamic/unreferenced candidate; no deletion proof |
| common.actions.clear | dynamic/unreferenced candidate; no deletion proof |
| common.actions.apply | dynamic/unreferenced candidate; no deletion proof |
| common.actions.open | dynamic/unreferenced candidate; no deletion proof |
| common.actions.download | dynamic/unreferenced candidate; no deletion proof |
| common.actions.view | dynamic/unreferenced candidate; no deletion proof |
| common.actions.previous | dynamic/unreferenced candidate; no deletion proof |
| common.actions.next | dynamic/unreferenced candidate; no deletion proof |
| common.states.loading | dynamic/unreferenced candidate; no deletion proof |
| common.states.error | dynamic/unreferenced candidate; no deletion proof |
| common.states.noResults | dynamic/unreferenced candidate; no deletion proof |
| common.states.unavailable | dynamic/unreferenced candidate; no deletion proof |
| common.states.available | dynamic/unreferenced candidate; no deletion proof |
| common.states.notAvailable | dynamic/unreferenced candidate; no deletion proof |
| common.states.unknown | dynamic/unreferenced candidate; no deletion proof |
| common.states.saved | dynamic/unreferenced candidate; no deletion proof |
| common.states.processing | dynamic/unreferenced candidate; no deletion proof |
| common.states.failed | dynamic/unreferenced candidate; no deletion proof |
| common.pagination | dynamic/unreferenced candidate; no deletion proof |
| common.paginationResults | dynamic/unreferenced candidate; no deletion proof |
| common.notFound.title | dynamic/unreferenced candidate; no deletion proof |
| common.notFound.help | dynamic/unreferenced candidate; no deletion proof |
| common.notFound.back | dynamic/unreferenced candidate; no deletion proof |
| common.taxonomy.regions.centralAsia | literal reference candidate |
| common.taxonomy.regions.asia | literal reference candidate |
| common.taxonomy.regions.europe | literal reference candidate |
| common.taxonomy.regions.africa | literal reference candidate |
| common.taxonomy.regions.northAmerica | literal reference candidate |
| common.taxonomy.regions.latinAmerica | literal reference candidate |
| common.taxonomy.countries.uzbekistan | literal reference candidate |
| common.taxonomy.countries.kazakhstan | literal reference candidate |
| common.taxonomy.countries.kyrgyzstan | literal reference candidate |
| common.taxonomy.countries.tajikistan | literal reference candidate |
| common.taxonomy.countries.turkmenistan | literal reference candidate |
| common.taxonomy.services.construction | literal reference candidate |
| common.taxonomy.services.medical | literal reference candidate |
| common.taxonomy.services.it | literal reference candidate |
| common.taxonomy.services.industrialServices | literal reference candidate |
| common.taxonomy.services.consulting | literal reference candidate |
| common.taxonomy.services.equipmentSupply | literal reference candidate |
| common.taxonomy.services.other | literal reference candidate |
| compliance.back | literal reference candidate |
| compliance.engineTitle | literal reference candidate |
| compliance.completeSubtitle | literal reference candidate |
| compliance.analyzingSubtitle | literal reference candidate |
| compliance.readySubtitle | literal reference candidate |
| compliance.preparingPdf | literal reference candidate |
| compliance.downloadPdf | literal reference candidate |
| compliance.analyzing | literal reference candidate |
| compliance.elapsedSeconds | literal reference candidate |
| compliance.loadingDocument | literal reference candidate |
| compliance.tenderDocument | literal reference candidate |
| compliance.noTextTitle | literal reference candidate |
| compliance.noTextHelp | literal reference candidate |
| compliance.error | literal reference candidate |
| compliance.dismissError | literal reference candidate |
| compliance.processing | literal reference candidate |
| compliance.running | literal reference candidate |
| compliance.mapping | literal reference candidate |
| compliance.mappingHelp | literal reference candidate |
| compliance.title | literal reference candidate |
| compliance.ready | literal reference candidate |
| compliance.introTitle | literal reference candidate |
| compliance.introHelp | literal reference candidate |
| compliance.start | literal reference candidate |
| compliance.analyzeAgain | literal reference candidate |
| compliance.analysisLanguage | literal reference candidate |
| compliance.chooseLanguageHelp | literal reference candidate |
| compliance.resultLanguage | literal reference candidate |
| compliance.version | literal reference candidate |
| compliance.notRecorded | literal reference candidate |
| compliance.versionHistory | literal reference candidate |
| compliance.crossLanguageNotice | literal reference candidate |
| compliance.noTextGuard | literal reference candidate |
| compliance.fallbackTender | literal reference candidate |
| compliance.guardClosed | literal reference candidate |
| compliance.guardCancelled | literal reference candidate |
| compliance.guardUnavailable | literal reference candidate |
| compliance.loadTextFailed | literal reference candidate |
| compliance.loadDocumentsFailed | literal reference candidate |
| compliance.analysisFailed | literal reference candidate |
| compliance.exportSignIn | literal reference candidate |
| compliance.exportUnavailable | literal reference candidate |
| compliance.exportFailed | literal reference candidate |
| compliance.documentSignIn | literal reference candidate |
| compliance.documentForbidden | literal reference candidate |
| compliance.documentUnavailable | literal reference candidate |
| compliance.documentOpenFailed | literal reference candidate |
| compliance.verdict.notEligible | literal reference candidate |
| compliance.verdict.withReview | literal reference candidate |
| compliance.verdict.needsReview | literal reference candidate |
| compliance.verdict.compliant | literal reference candidate |
| compliance.verdict.pending | literal reference candidate |
| compliance.manualOnly | literal reference candidate |
| compliance.sourceDocument | literal reference candidate |
| compliance.documentLevel | literal reference candidate |
| compliance.page | literal reference candidate |
| compliance.sourceEvidence | literal reference candidate |
| compliance.backToDocument | literal reference candidate |
| compliance.pdfBestEffort | literal reference candidate |
| compliance.evidenceQuote | literal reference candidate |
| compliance.evidenceFrame | literal reference candidate |
| compliance.fallbackDefault | literal reference candidate |
| compliance.fallbackResolving | literal reference candidate |
| compliance.fallbackArchiveInner | literal reference candidate |
| compliance.fallbackUnmatched | literal reference candidate |
| compliance.fallbackDocx | literal reference candidate |
| compliance.fallbackArchive | literal reference candidate |
| compliance.fallbackTitle | literal reference candidate |
| compliance.sourceFilename | literal reference candidate |
| compliance.sourcePosition | literal reference candidate |
| compliance.openingSource | literal reference candidate |
| compliance.openSource | literal reference candidate |
| compliance.analysisId | literal reference candidate |
| compliance.satisfied | literal reference candidate |
| compliance.failed | literal reference candidate |
| compliance.manual | literal reference candidate |
| compliance.recorded | literal reference candidate |
| compliance.skipped | literal reference candidate |
| compliance.dealbreakerFailures | literal reference candidate |
| compliance.manualReviewRequired | literal reference candidate |
| compliance.recordedObligations | literal reference candidate |
| compliance.satisfiedRequirements | literal reference candidate |
| compliance.contentSeal | literal reference candidate |
| compliance.overrideSeal | literal reference candidate |
| compliance.overrideCount | literal reference candidate |
| compliance.auditUnavailable | literal reference candidate |
| compliance.auditUnavailableHelp | literal reference candidate |
| compliance.quote | literal reference candidate |
| compliance.overridden | literal reference candidate |
| compliance.fatal | literal reference candidate |
| compliance.overrideSealed | literal reference candidate |
| compliance.overrideFlag | literal reference candidate |
| compliance.permanentAudit | literal reference candidate |
| compliance.overrideTrail | literal reference candidate |
| compliance.overrideFailed | literal reference candidate |
| compliance.overrideTitle | literal reference candidate |
| compliance.overrideExplanation | literal reference candidate |
| compliance.requirementOverridden | literal reference candidate |
| compliance.responsibilityTitle | literal reference candidate |
| compliance.responsibilityHelp | literal reference candidate |
| compliance.justification | literal reference candidate |
| compliance.justificationPlaceholder | literal reference candidate |
| compliance.minimumCharacters | literal reference candidate |
| compliance.valid | literal reference candidate |
| compliance.cancel | literal reference candidate |
| compliance.sealing | literal reference candidate |
| compliance.seal | literal reference candidate |
| compliance.sealNotice | literal reference candidate |
| compliance.hide | literal reference candidate |
| compliance.show | literal reference candidate |
| compliance.verdictLabels.satisfied | literal reference candidate |
| compliance.verdictLabels.failed | literal reference candidate |
| compliance.verdictLabels.manualReview | literal reference candidate |
| compliance.verdictLabels.unknown | literal reference candidate |
| dashboard.eyebrow | literal reference candidate |
| dashboard.title | literal reference candidate |
| dashboard.subtitle | literal reference candidate |
| dashboard.openExplorer | literal reference candidate |
| dashboard.partialData | literal reference candidate |
| dashboard.failures.profile | literal reference candidate |
| dashboard.failures.readiness | literal reference candidate |
| dashboard.failures.opportunities | literal reference candidate |
| dashboard.failures.analyses | literal reference candidate |
| dashboard.actionTitle | literal reference candidate |
| dashboard.actionHelp | literal reference candidate |
| dashboard.noUrgent | literal reference candidate |
| dashboard.noUrgentHelp | literal reference candidate |
| dashboard.issues.analysisFailed | literal reference candidate |
| dashboard.issues.manualReview | literal reference candidate |
| dashboard.issues.coverage | literal reference candidate |
| dashboard.issues.expired | literal reference candidate |
| dashboard.issues.expiring | literal reference candidate |
| dashboard.issues.missing | literal reference candidate |
| dashboard.status.failed | literal reference candidate |
| dashboard.status.needsReview | literal reference candidate |
| dashboard.status.partial | literal reference candidate |
| dashboard.status.complete | literal reference candidate |
| dashboard.status.coverageComplete | literal reference candidate |
| dashboard.status.coverageRecorded | literal reference candidate |
| dashboard.status.readyAnalysis | literal reference candidate |
| dashboard.status.documentDiscovered | literal reference candidate |
| dashboard.status.preparationFailed | literal reference candidate |
| dashboard.status.documentsUnavailable | literal reference candidate |
| dashboard.status.reviewCount | literal reference candidate |
| dashboard.status.requiredBid | literal reference candidate |
| dashboard.opportunitiesTitle | literal reference candidate |
| dashboard.opportunitiesHelp | literal reference candidate |
| dashboard.targetingMissing | literal reference candidate |
| dashboard.noMatches | literal reference candidate |
| dashboard.targetingHelp | literal reference candidate |
| dashboard.broadenHelp | literal reference candidate |
| dashboard.openProfile | literal reference candidate |
| dashboard.unknown | literal reference candidate |
| dashboard.matchReason | literal reference candidate |
| dashboard.supportedGeography | literal reference candidate |
| dashboard.sourceCoverage | literal reference candidate |
| dashboard.deadline.unknown | literal reference candidate |
| dashboard.deadline.expired | literal reference candidate |
| dashboard.deadline.today | literal reference candidate |
| dashboard.deadline.one | literal reference candidate |
| dashboard.deadline.many | literal reference candidate |
| dashboard.readinessTitle | literal reference candidate |
| dashboard.readinessHelp | literal reference candidate |
| dashboard.readinessVault | literal reference candidate |
| dashboard.readinessRisk | literal reference candidate |
| dashboard.readinessGaps | literal reference candidate |
| dashboard.readinessCurrent | literal reference candidate |
| dashboard.readinessSummary | literal reference candidate |
| dashboard.available | literal reference candidate |
| dashboard.missing | literal reference candidate |
| dashboard.expired | literal reference candidate |
| dashboard.expiringSoon | literal reference candidate |
| dashboard.missingList | literal reference candidate |
| dashboard.analysesTitle | literal reference candidate |
| dashboard.analysesHelp | literal reference candidate |
| dashboard.noAnalyses | literal reference candidate |
| dashboard.noAnalysesHelp | literal reference candidate |
| dashboard.reviewTenders | literal reference candidate |
| dashboard.requirementCount | literal reference candidate |
| dashboard.activityTitle | literal reference candidate |
| dashboard.activityHelp | literal reference candidate |
| dashboard.noActivity | literal reference candidate |
| dashboard.noActivityHelp | literal reference candidate |
| dashboard.analysisCompleted | literal reference candidate |
| dashboard.analysisState | literal reference candidate |
| dashboard.readinessUpdated | literal reference candidate |
| dashboard.updatedUnavailable | literal reference candidate |
| dashboard.notSet | dynamic/unreferenced candidate; no deletion proof |
| dashboard.open | literal reference candidate |
| dashboard.gettingStarted | literal reference candidate |
| dashboard.steps.profile | literal reference candidate |
| dashboard.steps.readiness | literal reference candidate |
| dashboard.steps.tenders | literal reference candidate |
| dashboard.steps.analysis | literal reference candidate |
| dashboard.loading | literal reference candidate |
| documentViewer.sourceDocument | literal reference candidate |
| documentViewer.lineCount | literal reference candidate |
| documentViewer.plainTextEncoding | literal reference candidate |
| errors.generic | literal reference candidate |
| errors.localeSaveFailed | literal reference candidate |
| errors.unsupportedUiLocale | literal reference candidate |
| explorer.title | literal reference candidate |
| explorer.subtitle | literal reference candidate |
| explorer.newArrivals | literal reference candidate |
| explorer.resultsStable | literal reference candidate |
| explorer.show | literal reference candidate |
| explorer.dismissNew | literal reference candidate |
| explorer.viewsLabel | literal reference candidate |
| explorer.views.all | literal reference candidate |
| explorer.views.recommended | literal reference candidate |
| explorer.views.dismissed | literal reference candidate |
| explorer.itemCount | literal reference candidate |
| explorer.filtersLabel | literal reference candidate |
| explorer.search | literal reference candidate |
| explorer.source | literal reference candidate |
| explorer.allSources | literal reference candidate |
| explorer.lifecycle | literal reference candidate |
| explorer.sort | literal reference candidate |
| explorer.new | literal reference candidate |
| explorer.newRecent | literal reference candidate |
| explorer.newLast24 | literal reference candidate |
| explorer.moreFilters | literal reference candidate |
| explorer.status.open | literal reference candidate |
| explorer.status.unknown | literal reference candidate |
| explorer.status.closed | literal reference candidate |
| explorer.status.cancelled | literal reference candidate |
| explorer.status.all | literal reference candidate |
| explorer.documents.all | literal reference candidate |
| explorer.documents.ready | literal reference candidate |
| explorer.documents.preparationFailed | literal reference candidate |
| explorer.documents.discovered | literal reference candidate |
| explorer.documents.accessRequired | literal reference candidate |
| explorer.documents.unavailable | literal reference candidate |
| explorer.documents.processing | literal reference candidate |
| explorer.documents.failed | literal reference candidate |
| explorer.sorts.newest | literal reference candidate |
| explorer.sorts.deadline | literal reference candidate |
| explorer.sorts.price | literal reference candidate |
| explorer.sorts.documents | literal reference candidate |
| explorer.sorts.source | literal reference candidate |
| explorer.sorts.match | literal reference candidate |
| explorer.deadlineFilter | literal reference candidate |
| explorer.deadlineAny | literal reference candidate |
| explorer.deadlineActive | literal reference candidate |
| explorer.deadlineExpired | literal reference candidate |
| explorer.deadlineUnknown | literal reference candidate |
| explorer.documentStatus | literal reference candidate |
| explorer.category | literal reference candidate |
| explorer.centralAsia | literal reference candidate |
| explorer.minimumValue | literal reference candidate |
| explorer.maximumValue | literal reference candidate |
| explorer.countries | literal reference candidate |
| explorer.services | literal reference candidate |
| explorer.accessDenied | literal reference candidate |
| explorer.loadFailed | literal reference candidate |
| explorer.recommendationDenied | literal reference candidate |
| explorer.recommendationMissing | literal reference candidate |
| explorer.recommendationFailed | literal reference candidate |
| explorer.profileTitle | literal reference candidate |
| explorer.profileHelp | literal reference candidate |
| explorer.openProfile | literal reference candidate |
| explorer.loading | literal reference candidate |
| explorer.retry | literal reference candidate |
| explorer.empty.all | literal reference candidate |
| explorer.empty.dismissed | literal reference candidate |
| explorer.empty.active | literal reference candidate |
| explorer.empty.recommended | literal reference candidate |
| explorer.showing | literal reference candidate |
| explorer.resultsLabel | literal reference candidate |
| explorer.pagesLabel | literal reference candidate |
| explorer.page | literal reference candidate |
| explorer.previous | literal reference candidate |
| explorer.next | literal reference candidate |
| explorer.sourceStatus | literal reference candidate |
| explorer.documentCount | literal reference candidate |
| explorer.buyerMissing | literal reference candidate |
| explorer.locationMissing | literal reference candidate |
| explorer.uncategorized | literal reference candidate |
| explorer.valueMissing | literal reference candidate |
| explorer.deadlineMissing | literal reference candidate |
| explorer.dueToday | dynamic/unreferenced candidate; no deletion proof |
| explorer.expired | literal reference candidate |
| explorer.remaining | dynamic/unreferenced candidate; no deletion proof |
| explorer.pursuit | literal reference candidate |
| explorer.viewTender | literal reference candidate |
| explorer.deadlinePassed | literal reference candidate |
| explorer.startBid | literal reference candidate |
| explorer.recommendation.label | dynamic/unreferenced candidate; no deletion proof |
| explorer.recommendation.matchScore | dynamic/unreferenced candidate; no deletion proof |
| explorer.recommendation.why | dynamic/unreferenced candidate; no deletion proof |
| explorer.recommendation.dismissed | dynamic/unreferenced candidate; no deletion proof |
| explorer.recommendation.recommendedOn | dynamic/unreferenced candidate; no deletion proof |
| explorer.recommendation.restore | dynamic/unreferenced candidate; no deletion proof |
| explorer.recommendation.dismiss | dynamic/unreferenced candidate; no deletion proof |
| myTenders.title | literal reference candidate |
| myTenders.subtitle | literal reference candidate |
| myTenders.filtersLabel | literal reference candidate |
| myTenders.statuses.active | literal reference candidate |
| myTenders.statuses.all | literal reference candidate |
| myTenders.statuses.saved | literal reference candidate |
| myTenders.statuses.evaluating | literal reference candidate |
| myTenders.statuses.preparing | literal reference candidate |
| myTenders.statuses.submitted | literal reference candidate |
| myTenders.statuses.won | literal reference candidate |
| myTenders.statuses.lost | literal reference candidate |
| myTenders.statuses.dismissed | literal reference candidate |
| myTenders.tenderStatuses.all | literal reference candidate |
| myTenders.tenderStatuses.open | literal reference candidate |
| myTenders.tenderStatuses.closed | literal reference candidate |
| myTenders.tenderStatuses.cancelled | literal reference candidate |
| myTenders.tenderStatuses.unknown | literal reference candidate |
| myTenders.searchLabel | literal reference candidate |
| myTenders.search | literal reference candidate |
| myTenders.source | literal reference candidate |
| myTenders.allSources | literal reference candidate |
| myTenders.sourceStatus | literal reference candidate |
| myTenders.sort | literal reference candidate |
| myTenders.sortRecentUpdated | literal reference candidate |
| myTenders.sortRecentAdded | literal reference candidate |
| myTenders.sortDeadline | literal reference candidate |
| myTenders.loading | literal reference candidate |
| myTenders.accessDenied | literal reference candidate |
| myTenders.loadFailed | literal reference candidate |
| myTenders.emptyTitle | literal reference candidate |
| myTenders.emptyHelp | literal reference candidate |
| myTenders.explore | literal reference candidate |
| myTenders.paginationLabel | literal reference candidate |
| myTenders.page | literal reference candidate |
| myTenders.previous | literal reference candidate |
| myTenders.next | literal reference candidate |
| myTenders.statusesLabel | literal reference candidate |
| myTenders.engagement | literal reference candidate |
| myTenders.tender | literal reference candidate |
| myTenders.buyerMissing | literal reference candidate |
| myTenders.deadline | literal reference candidate |
| myTenders.deadlineMissing | literal reference candidate |
| myTenders.valueMissing | literal reference candidate |
| myTenders.project | literal reference candidate |
| myTenders.openTender | literal reference candidate |
| myTenders.actions.evaluate | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.markSubmitted | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.recordWon | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.recordLost | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.dismiss | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctPreparing | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctSubmitted | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctWon | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctLost | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.saveAgain | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.openBid | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.resume | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctStatus | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.more | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.closeConfirmation | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.cancel | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.statusChanged | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.missing | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.updateFailed | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.resumeFailed | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.submittedTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.submittedConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.wonTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.wonConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.lostTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.lostConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.dismissPreparingTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.dismissPreparingConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctSubmissionTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctSubmissionConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctOutcomeTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctOutcomeConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctWonTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctWonConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctLostTitle | dynamic/unreferenced candidate; no deletion proof |
| myTenders.actions.correctLostConfirm | dynamic/unreferenced candidate; no deletion proof |
| myTenders.panel.title | literal reference candidate |
| myTenders.panel.loading | literal reference candidate |
| myTenders.panel.status | literal reference candidate |
| myTenders.panel.none | literal reference candidate |
| myTenders.panel.save | literal reference candidate |
| myTenders.panel.saving | literal reference candidate |
| myTenders.panel.noAction | literal reference candidate |
| myTenders.panel.openMy | literal reference candidate |
| myTenders.panel.openBid | literal reference candidate |
| myTenders.panel.loadFailed | literal reference candidate |
| myTenders.panel.changed | literal reference candidate |
| myTenders.panel.saveFailed | literal reference candidate |
| navigation.dashboard | literal reference candidate |
| navigation.tenders | literal reference candidate |
| navigation.myTenders | literal reference candidate |
| navigation.bidPreparation | literal reference candidate |
| navigation.companyProfile | literal reference candidate |
| navigation.readinessVault | literal reference candidate |
| navigation.dashboardLabel | literal reference candidate |
| navigation.navigationLabel | literal reference candidate |
| navigation.logout | literal reference candidate |
| navigation.commandCenter | literal reference candidate |
| navigation.adminConsole | literal reference candidate |
| onboarding.title | literal reference candidate |
| onboarding.subtitle | literal reference candidate |
| onboarding.validationError | literal reference candidate |
| onboarding.submitError | literal reference candidate |
| onboarding.submittedTitle | literal reference candidate |
| onboarding.submittedHelp | literal reference candidate |
| onboarding.company | literal reference candidate |
| onboarding.companyName | literal reference candidate |
| onboarding.industry | literal reference candidate |
| onboarding.website | literal reference candidate |
| onboarding.registrationNumber | literal reference candidate |
| onboarding.address | literal reference candidate |
| onboarding.targets | literal reference candidate |
| onboarding.targetRegions | literal reference candidate |
| onboarding.targetCountries | literal reference candidate |
| onboarding.targetServices | literal reference candidate |
| onboarding.centralAsiaSelection | dynamic/unreferenced candidate; no deletion proof |
| onboarding.clearCentralAsia | literal reference candidate |
| onboarding.selectCentralAsia | literal reference candidate |
| onboarding.countriesSelected | literal reference candidate |
| onboarding.contact | literal reference candidate |
| onboarding.directorName | literal reference candidate |
| onboarding.phone | literal reference candidate |
| onboarding.notes | literal reference candidate |
| onboarding.submit | literal reference candidate |
| onboarding.submitting | literal reference candidate |
| readiness.title | literal reference candidate |
| readiness.recordCount | literal reference candidate |
| readiness.addRecord | literal reference candidate |
| readiness.editRecord | literal reference candidate |
| readiness.addRecordTitle | literal reference candidate |
| readiness.closeForm | literal reference candidate |
| readiness.loadFailed | literal reference candidate |
| readiness.profileRequiredAdd | literal reference candidate |
| readiness.profileRequiredSave | literal reference candidate |
| readiness.profileRequiredView | literal reference candidate |
| readiness.nameRequired | literal reference candidate |
| readiness.saveFailed | literal reference candidate |
| readiness.notFound | literal reference candidate |
| readiness.deleteFailed | literal reference candidate |
| readiness.deleteConfirm | literal reference candidate |
| readiness.saved | literal reference candidate |
| readiness.saveRecord | literal reference candidate |
| readiness.saving | literal reference candidate |
| readiness.loading | literal reference candidate |
| readiness.empty | literal reference candidate |
| readiness.noMatches | literal reference candidate |
| readiness.documentType | literal reference candidate |
| readiness.documentName | literal reference candidate |
| readiness.documentNumber | literal reference candidate |
| readiness.issuer | literal reference candidate |
| readiness.issueDate | literal reference candidate |
| readiness.expiryDate | literal reference candidate |
| readiness.status | literal reference candidate |
| readiness.relatedService | literal reference candidate |
| readiness.fileReference | literal reference candidate |
| readiness.fileReferencePlaceholder | literal reference candidate |
| readiness.notes | literal reference candidate |
| readiness.none | literal reference candidate |
| readiness.allTypes | literal reference candidate |
| readiness.allStatuses | literal reference candidate |
| readiness.allServices | literal reference candidate |
| readiness.resetFilters | literal reference candidate |
| readiness.table.type | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.name | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.number | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.issuer | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.issue | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.expiry | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.status | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.service | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.file | dynamic/unreferenced candidate; no deletion proof |
| readiness.table.actions | literal reference candidate |
| readiness.editNamed | literal reference candidate |
| readiness.deleteNamed | literal reference candidate |
| readiness.types.license | literal reference candidate |
| readiness.types.certificate | literal reference candidate |
| readiness.types.taxClearance | literal reference candidate |
| readiness.types.financialStatement | literal reference candidate |
| readiness.types.registrationDocument | literal reference candidate |
| readiness.types.powerOfAttorney | literal reference candidate |
| readiness.types.personnelDocument | literal reference candidate |
| readiness.types.other | literal reference candidate |
| readiness.types.unknown | literal reference candidate |
| readiness.statuses.available | literal reference candidate |
| readiness.statuses.missing | literal reference candidate |
| readiness.statuses.expired | literal reference candidate |
| readiness.statuses.unknown | literal reference candidate |
| readiness.expiry.expired | literal reference candidate |
| readiness.expiry.expiringSoon | literal reference candidate |
| readiness.expiry.valid | literal reference candidate |
| readiness.expiry.unknown | literal reference candidate |
| refresh.newTenderCount | dynamic/unreferenced candidate; no deletion proof |
| refresh.completeFromSource | literal reference candidate |
| refresh.complete | literal reference candidate |
| refresh.sourceRefresh | literal reference candidate |
| refresh.loadingSources | literal reference candidate |
| refresh.catalogUnavailable | literal reference candidate |
| refresh.retry | literal reference candidate |
| refresh.noneAvailable | literal reference candidate |
| refresh.unavailable | literal reference candidate |
| refresh.queued | literal reference candidate |
| refresh.refreshing | literal reference candidate |
| refresh.refresh | literal reference candidate |
| refresh.requesting | literal reference candidate |
| refresh.actionLabel | literal reference candidate |
| refresh.sourceUnavailable | literal reference candidate |
| refresh.alreadyStatus | literal reference candidate |
| refresh.queuedNotice | literal reference candidate |
| refresh.startedNotice | literal reference candidate |
| refresh.failed | literal reference candidate |
| refresh.partial | literal reference candidate |
| refresh.limited | literal reference candidate |
| refresh.zeroNew | literal reference candidate |
| refresh.aggregated | literal reference candidate |
| refresh.sourcesCompleted | literal reference candidate |
| refresh.someIssues | literal reference candidate |
| refresh.eventPartial | literal reference candidate |
| refresh.eventLimited | literal reference candidate |
| refresh.eventFailed | literal reference candidate |
| refresh.eventUnavailable | literal reference candidate |
| refresh.eventComplete | literal reference candidate |
| refresh.viewNew | literal reference candidate |
| refresh.alreadyCurrent | literal reference candidate |
| refresh.requestFailed | literal reference candidate |
| refresh.nothingChanged | literal reference candidate |
| refresh.statusUnavailable | literal reference candidate |
| refresh.notifications | literal reference candidate |
| refresh.dismiss | literal reference candidate |
| refresh.activeOneQueued | literal reference candidate |
| refresh.activeOneRunning | literal reference candidate |
| refresh.activeMany | literal reference candidate |
| refresh.sourceRefreshes | literal reference candidate |
| settings.language.title | dynamic/unreferenced candidate; no deletion proof |
| settings.language.onboardingHelp | dynamic/unreferenced candidate; no deletion proof |
| settings.language.settingsHelp | dynamic/unreferenced candidate; no deletion proof |
| settings.language.optionsLabel | dynamic/unreferenced candidate; no deletion proof |
| settings.language.optionLabel | dynamic/unreferenced candidate; no deletion proof |
| settings.language.saving | dynamic/unreferenced candidate; no deletion proof |
| settings.language.saveFailed | dynamic/unreferenced candidate; no deletion proof |
| settings.analysisLanguage.title | literal reference candidate |
| settings.analysisLanguage.help | literal reference candidate |
| settings.analysisLanguage.label | literal reference candidate |
| settings.analysisLanguage.save | literal reference candidate |
| settings.analysisLanguage.saved | literal reference candidate |
| settings.analysisLanguage.loadFailed | literal reference candidate |
| settings.analysisLanguage.saveFailed | literal reference candidate |
| settings.analysisLanguage.arabicGate | literal reference candidate |
| settings.title | literal reference candidate |
| settings.pilotStatus | literal reference candidate |
| settings.approvalStatus | literal reference candidate |
| settings.company | literal reference candidate |
| settings.companyName | literal reference candidate |
| settings.industry | literal reference candidate |
| settings.registrationNumber | literal reference candidate |
| settings.website | literal reference candidate |
| settings.phone | literal reference candidate |
| settings.address | literal reference candidate |
| settings.marketsServices | literal reference candidate |
| settings.targetRegions | literal reference candidate |
| settings.targetCountries | literal reference candidate |
| settings.centralAsiaCountries | literal reference candidate |
| settings.targetServices | literal reference candidate |
| settings.clearCentralAsia | literal reference candidate |
| settings.selectCentralAsia | literal reference candidate |
| settings.noneSelected | literal reference candidate |
| settings.saveProfile | literal reference candidate |
| settings.profileSaved | literal reference candidate |
| settings.loadFailed | literal reference candidate |
| settings.saveFailed | literal reference candidate |
| settings.status.approved | literal reference candidate |
| settings.status.pending | literal reference candidate |
| settings.status.rejected | literal reference candidate |
| settings.status.disabled | literal reference candidate |
| settings.status.unknown | literal reference candidate |
| tenderDetails.back | literal reference candidate |
| tenderDetails.loadFailed | literal reference candidate |
| tenderDetails.notFound | literal reference candidate |
| tenderDetails.loading | literal reference candidate |
| tenderDetails.detailsLoading | literal reference candidate |
| tenderDetails.detailsFailed | literal reference candidate |
| tenderDetails.retryDetails | literal reference candidate |
| tenderDetails.openSource | literal reference candidate |
| tenderDetails.openCompliance | literal reference candidate |
| tenderDetails.source | literal reference candidate |
| tenderDetails.status | literal reference candidate |
| tenderDetails.reference | literal reference candidate |
| tenderDetails.descriptionMissing | literal reference candidate |
| tenderDetails.procuringEntity | literal reference candidate |
| tenderDetails.deadline | literal reference candidate |
| tenderDetails.estimatedValue | literal reference candidate |
| tenderDetails.location | literal reference candidate |
| tenderDetails.notSpecified | literal reference candidate |
| tenderDetails.sectionsLabel | literal reference candidate |
| tenderDetails.sections.pursuit | literal reference candidate |
| tenderDetails.sections.project | literal reference candidate |
| tenderDetails.sections.requirements | literal reference candidate |
| tenderDetails.sections.compliance | literal reference candidate |
| tenderDetails.sections.contacts | literal reference candidate |
| tenderDetails.sections.bid | literal reference candidate |
| tenderDetails.sectionState.available | literal reference candidate |
| tenderDetails.sectionState.unavailable | literal reference candidate |
| tenderDetails.sectionState.empty | dynamic/unreferenced candidate; no deletion proof |
| tenderDetails.projectTitle | literal reference candidate |
| tenderDetails.projectHelp | literal reference candidate |
| tenderDetails.projectUnavailable | literal reference candidate |
| tenderDetails.projectPreparing | literal reference candidate |
| tenderDetails.projectStatus | literal reference candidate |
| tenderDetails.countryRegion | literal reference candidate |
| tenderDetails.projectApproval | literal reference candidate |
| tenderDetails.projectClosing | literal reference candidate |
| tenderDetails.projectEnrichment | literal reference candidate |
| tenderDetails.leadership | literal reference candidate |
| tenderDetails.leadershipHelp | literal reference candidate |
| tenderDetails.leadershipEmpty | literal reference candidate |
| tenderDetails.previousLeadership | literal reference candidate |
| tenderDetails.sourceProjectTeam | literal reference candidate |
| tenderDetails.taskTeamLeader | literal reference candidate |
| tenderDetails.coTaskTeamLeader | literal reference candidate |
| tenderDetails.projectTaskManager | literal reference candidate |
| tenderDetails.projectRole | literal reference candidate |
| tenderDetails.projectLinkedEmpty | literal reference candidate |
| tenderDetails.requirementsTitle | literal reference candidate |
| tenderDetails.requirementsHelp | literal reference candidate |
| tenderDetails.importantRequirements | literal reference candidate |
| tenderDetails.aiRequirement | literal reference candidate |
| tenderDetails.requirementsEmpty | literal reference candidate |
| tenderDetails.requirementsUnavailable | literal reference candidate |
| tenderDetails.requirementsTruncated | literal reference candidate |
| tenderDetails.tenderDocuments | literal reference candidate |
| tenderDetails.documentsEmpty | literal reference candidate |
| tenderDetails.documentsUnavailable | literal reference candidate |
| tenderDetails.documentsTruncated | literal reference candidate |
| tenderDetails.opening | literal reference candidate |
| tenderDetails.openDocument | literal reference candidate |
| tenderDetails.metadataOnly | literal reference candidate |
| tenderDetails.sizeMissing | literal reference candidate |
| tenderDetails.contactsTitle | literal reference candidate |
| tenderDetails.contactsHelp | literal reference candidate |
| tenderDetails.procurementContact | literal reference candidate |
| tenderDetails.email | literal reference candidate |
| tenderDetails.phone | literal reference candidate |
| tenderDetails.submissionMethod | literal reference candidate |
| tenderDetails.submissionDeadline | literal reference candidate |
| tenderDetails.questionDeadline | literal reference candidate |
| tenderDetails.procedure | literal reference candidate |
| tenderDetails.notProvided | literal reference candidate |
| tenderDetails.contactsEmpty | literal reference candidate |
| tenderDetails.contactsUnavailable | literal reference candidate |
| tenderDetails.bidTitle | literal reference candidate |
| tenderDetails.bidHelp | literal reference candidate |
| tenderDetails.preparationStatus | literal reference candidate |
| tenderDetails.notStarted | literal reference candidate |
| tenderDetails.sourceClassification | literal reference candidate |
| tenderDetails.category | literal reference candidate |
| tenderDetails.method | literal reference candidate |
| tenderDetails.noticeType | literal reference candidate |
| tenderDetails.documentOpenFailed | literal reference candidate |
| tenderDetails.pursuitChanged | literal reference candidate |
| tenderDetails.projectName | literal reference candidate |
| tenderDetails.notReported | literal reference candidate |
| tenderDetails.observedUntil | literal reference candidate |
| tenderDetails.complianceTitle | literal reference candidate |
| tenderDetails.complianceHelp | literal reference candidate |
| tenderDetails.compliance | literal reference candidate |
| tenderDetails.readiness | literal reference candidate |
| tenderDetails.complianceFailed | literal reference candidate |
| tenderDetails.complianceFailedDetail | literal reference candidate |
| tenderDetails.compliancePartial | literal reference candidate |
| tenderDetails.compliancePartialDetail | literal reference candidate |
| tenderDetails.complianceLegacy | literal reference candidate |
| tenderDetails.complianceLegacyDetail | literal reference candidate |
| tenderDetails.complianceAvailable | literal reference candidate |
| tenderDetails.complianceAvailableDetail | literal reference candidate |
| tenderDetails.completeness | literal reference candidate |
| tenderDetails.complete | literal reference candidate |
| tenderDetails.partial | literal reference candidate |
| tenderDetails.version | literal reference candidate |
| tenderDetails.keyIssues | literal reference candidate |
| tenderDetails.analysisCreated | literal reference candidate |
| tenderDetails.legacyLimitations | literal reference candidate |
| tenderDetails.overrideRecorded | literal reference candidate |
| tenderDetails.complianceEmpty | literal reference candidate |
| tenderDetails.complianceUnavailable | literal reference candidate |
| tenderDetails.readinessHelp | literal reference candidate |
| tenderDetails.certifications | literal reference candidate |
| tenderDetails.licenses | literal reference candidate |
| tenderDetails.credentials | literal reference candidate |
| tenderDetails.readinessFiles | literal reference candidate |
| tenderDetails.missingEvidence | literal reference candidate |
| tenderDetails.financialYears | literal reference candidate |
| tenderDetails.expiredCount | literal reference candidate |
| tenderDetails.activeCount | literal reference candidate |
| tenderDetails.totalCount | literal reference candidate |
| tenderDetails.availableCount | literal reference candidate |
| tenderDetails.readinessEmpty | literal reference candidate |
| tenderDetails.readinessUnavailable | literal reference candidate |
| tenderDetails.openReadiness | literal reference candidate |
| tenderDetails.bidCreated | literal reference candidate |
| tenderDetails.bidNotStartedHelp | literal reference candidate |

## GIZ duplicate closure candidates

| Exact endpoint-module function | Line | Disposition |
| --- | --- | --- |
| _giz_payload_looks_like_html | 5710 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_archive_limits_payload | 5744 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_official_listed_document_count | 5755 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_inner_source_url | 5766 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_file_url_for_source | 5776 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_zip_member_name | 5784 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_zip_member_is_symlink | 5796 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_archive_member_extension | 5800 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_member_storage_filename | 5804 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_relabel_parsed_text | 5809 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_upsert_inner_document | 5817 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_find_duplicate_document_by_sha | 5864 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_mark_document_failed | 5888 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_parse_stored_document | 5893 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_zip_member_rejection_reason | 5936 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_extract_supported_zip_members | 5958 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _update_giz_document_coverage | 6091 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_rejected_payload_content_type | 6159 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _giz_valid_file_signature | 6168 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _download_giz_document_into_storage | 6189 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _process_giz_documents_for_compliance | 6308 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |
| _compile_tender_text_from_documents | 6344 | Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names |

The 22 functions above have no incoming same-module function-reference edge from outside the set at the audited SHA. Identically named functions in `services/giz_document_hydration.py` are separate live definitions, not callers of these copies. Line numbers identify evidence, not a range to blindly delete. Preserve constants until their own callers are checked.

## Evidence limitations

Search-evidence arrays and mutation candidates in JSON retain locations without raw secret/log content. All original regression outcomes were observed before the session environment restarted; temporary full logs and disposable tools were lost on that restart. Persisted JSON/screenshots and the execution record distinguish retained evidence from observed tool output. No test rerun is asserted after restart.

