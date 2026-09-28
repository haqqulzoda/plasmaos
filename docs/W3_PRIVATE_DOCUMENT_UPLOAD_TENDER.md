# W3 — Private Document Foundation and Upload Tender

**Status:** implemented and locally verified against disposable infrastructure  
**Baseline:** accepted W2  
**Alembic head:** `20260926_0001_w3_private_documents`  
**Production access or deployment:** none

## Scope

W3 introduces an organization-private document authority and two explicit intake paths:

1. `POST /api/v1/pursuits/upload` creates an `UPLOAD` pursuit, private documents, immutable first versions, and durable processing jobs. It never creates a source `Tender`.
2. `POST /api/v1/pursuits/source/{tender_id}/documents` resolves or creates the selected organization’s existing `SOURCE` pursuit and attaches private versions without changing shared source records.

W3 stops after secure intake, processing, factual context suggestion, and manual confirmation. It does not implement Requirements, Positions, Gap analysis, TeamScenario, Firms, Experts, proposal evidence packs, or AI pricing.

## Authority and ownership

The private ownership chain is:

`Organization -> OrganizationPursuit -> PrivateDocument -> DocumentVersion`

An active `Membership` in the pursuit organization authorizes every list, preview, download, retry, revision, role correction, and context operation. A pursuit owner is descriptive workflow ownership and does not replace membership authorization. Revocation removes access on the next request while preserving immutable history.

`TenderDocument` remains shared source data. Private upload services do not write `Tender`, `TenderDocument`, `Project`, `TenderProject`, or `ProjectRoleAssignment`.

## Data model

- `private_documents` stores the logical document, organization and pursuit scope, controlled role, display name, current version reference, creator membership, and archive-ready lifecycle state.
- `private_document_versions` stores immutable content facts: version number, original and safe filenames, media type, byte size, SHA-256, opaque storage key, uploader membership, and creation time.
- `private_document_batches` provides one customer-visible multi-file outcome.
- `private_document_processing_jobs` persists recoverable work before broker dispatch.
- `private_document_processing_results` stores malware, page count, extraction, and parser results separately from immutable content facts.
- `pursuit_tender_contexts` stores organization-private confirmed tender metadata.
- `pursuit_context_suggestions` stores provisional values with exact `DocumentVersion`, page/span where available, confidence, and review state.
- `membership_lifecycle_events` is an append-only record of invite, reinvite, activation, role change, revocation, and a deterministic W2 history boundary.

PostgreSQL rejects every update or delete of a private `DocumentVersion`. An explicit replacement creates the next version and retains the old version. W3 introduces no hard-delete path.

## Processing

The customer states are `UPLOADING`, `CHECKING`, `EXTRACTING`, `READY`, `PARTIAL`, and `FAILED`. `QUEUED` is an internal durable state and is presented as checking. The UI shows exact batch counts and no percentage or ETA.

Each accepted version and job commits before best-effort broker publication. A dedicated `private_documents` Celery queue isolates customer documents from source connector work. Celery Beat leases committed queued jobs and expired checking or extraction leases every ten seconds, so broker publication failure is recoverable.

Retries reuse the same version, bytes, job, and result. A completed malware scan is not repeated after parser failure. Terminal redelivery is idempotent. Batch notifications are emitted once per outcome and carry only organization, pursuit and batch IDs plus counts.

## Storage and parsing

- Accepted formats: PDF, scanned PDF, and DOCX.
- Limit: 25 MiB per file and 150 MiB per submitted pack.
- Extension, exact declared MIME, signature, HTML/polyglot, encryption, and empty-file checks run before persistence.
- DOCX validation bounds entry count, individual and total uncompressed size, compression ratio, paths, macros, ActiveX, embedded binaries, scripts, and executable content.
- User filenames never form a storage path. Opaque UUID-based keys resolve under a private non-webroot root with containment checks.
- ClamAV `INSTREAM` scanning is bounded and fail closed. Parsing never begins without a clean scan.
- Parsing runs in a child process with memory, CPU, output-size, and wall-clock limits. It never retrieves embedded links or calls network AI.
- Native PDF text is read on every page. Blank pages use bounded local OCR for at most 25 pages. If more OCR is needed, the full PDF page count remains recorded and the result is explicitly `PARTIAL` with `OCR_INCOMPLETE`.
- DOCX text is read directly from OpenXML. A missing reliable page count is explicit `PARTIAL`, not an invented value.
- A five-million-character extraction guard fails visibly instead of silently truncating content.

The 500-page rule belongs to W4 analysis-pack validation and is not applied by W3 intake.

## Customer routes

- `/dashboard/uploaded-tenders` lists only factual W3 fields for `origin=UPLOAD`.
- `/dashboard/uploaded-tenders/upload` provides explicit organization selection, multi-file intake, controlled roles, optional source URL, and manual context.
- `/dashboard/pursuits/{pursuit_id}` contains only Overview and Documents & Evidence. It supports context confirmation, evidence-backed suggestions, download, retry, role correction, and explicit new versions.
- Tender Details labels its existing list as Official source documents and exposes a separate Organization uploads action. Private data is loaded only after an explicit pursuit interaction.
- The customer shell contains a persistent Upload Tender action without a broader navigation redesign.

## Context truth

Manual values are recorded as confirmed. Extracted title, reference, and declared funder are provisional suggestions tied to an exact private version and evidence span when available. Missing deadlines and budgets remain unknown. Declaring World Bank, ADB, AIIB, or another funder does not create a source Tender, project, connector identity, or support claim.

## Legacy upload-TZ

Legacy Proposal upload-TZ remains intact and is not used by the new intake path. Its preview now resolves the unique successful path stored in `structured_data`, verifies containment within the authenticated user’s upload directory, streams with private no-store headers, and retains the earlier proposal-ID fallback for untouched historical artifacts. No historical files were migrated.

## W4 handoff

`GET /api/v1/pursuits/{pursuit_id}/analysis-pack-candidate` is a passive candidate projection. It includes organization, pursuit, origin, source Tender identity, source document snapshot hashes, exact current private `DocumentVersion` IDs, content hashes, version numbers, roles, parser state, page counts and whether known, language when known, and provenance. It exposes no storage key or extracted text.

W4 must persist a sealed analysis pack from this candidate and must reject later attempts to substitute “whatever is current.” The full contract is in [w4-analysis-pack-contract.md](audits/w3/w4-analysis-pack-contract.md).

## Verification artifacts

- [Private document security](audits/w3/private-document-security.md)
- [Document processing](audits/w3/document-processing.md)
- [Tenant isolation](audits/w3/tenant-isolation.md)
- [Source/private separation](audits/w3/source-private-separation.md)
- [Upload intake](audits/w3/upload-intake.md)
- [World Bank preservation](audits/w3/world-bank-preservation.md)
- [W4 analysis-pack contract](audits/w3/w4-analysis-pack-contract.md)

## Final verification

The permanent `scripts/run_release_gate.sh all` command passed on 2026-09-26
against disposable PostgreSQL, Redis, and isolated private storage:

- backend: 820 passed, 1 skipped, and 100 subtests passed;
- security: 118 passed;
- analysis: 50 passed and 12 subtests passed;
- connectors: 198 passed, 1 skipped, and 6 subtests passed;
- Alembic heads, current, check, and schema preflight: passed;
- scale gate: passed through 100,000 records with bounded query counts;
- frontend: 258 passed, with typecheck, lint, RTL audit, and production build passed;
- maintained Chromium: 197 passed, 0 failed, and 0 external requests;
- Python dependency check: no broken requirements;
- npm dependency audit: 0 vulnerabilities;
- Compose configuration validation: passed with synthetic local-only secrets.

The test run used no production endpoint, database, storage, deployment, or
credential. W3 is ready for W4 implementation from the exact-version candidate
contract; external-pilot operation still requires a healthy ClamAV deployment
with current signatures and monitored durable private storage.

