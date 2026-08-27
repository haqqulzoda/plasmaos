# Sprint 2.3 — Version-Aware Compliance Reads

## 1. Previous Read Model

`TenderAnalysis.analysis_json` and `TenderAnalysis.content_hash` were mutable
latest-result mirrors. The latest-analysis endpoint, cached responses, proposal
drafting, PDF export, and admin reproducibility diagnostics could read those
parent fields even after immutable `AnalysisVersion` rows existed. A later
mirror mutation could therefore change what a historical execution appeared to
contain.

## 2. New Read Authority

`AnalysisVersion` is the canonical Compliance read authority. Customer result,
evidence, analysis-time tender/company context, provenance, document history,
cache reuse, proposal compliance input, and export data now resolve through a
version. Parent fields remain compatibility-only writes; `override_seal`
remains a separate parent-level human audit overlay.

## 3. Latest Version Contract

Latest-for-tender resolution is deterministic:

1. Resolve the newest `OWNED` parent for the exact
   `(user_id, company_profile_id, tender_id)` tuple, ordered by
   `(created_at DESC, id DESC)`.
2. Within that parent only, choose the greatest `version_number`.

The persisted Sprint 2.2 status contract is retained: `COMPLETED`,
`NEEDS_REVIEW`, and `FAILED` executions all participate in version ordering.
Thus a persisted failed reanalysis remains the latest execution and is rendered
with the existing safe failed-analysis behavior. No new failure model was
introduced.

## 4. Historical Parent Ambiguity

Duplicate historical parents are neither merged nor renumbered. Parent A with
`v1,v2` and Parent B with `v1` remain two independent histories. Internal
warning logs and preflight counts expose multi-parent owned logical keys. The
customer latest route applies the parent rule first; explicit history routes
operate on exactly one parent ID.

## 5. Version APIs / Services

The service layer provides owned latest, specific-version, list, detached
payload, and integrity-verification reads. The minimal API surface is:

- `GET /tenders/{tender_id}/analyses/{analysis_id}/versions`
- `GET /tenders/{tender_id}/analyses/{analysis_id}/versions/{version_number}`
- `GET /tenders/{tender_id}/compliance/export/pdf?analysis_id=...&version_number=...`

The list returns safe metadata only. Detail exposes sanitized results/evidence,
snapshot context, safe provenance, document identity, and structured integrity
status. Prompt bodies, provider secrets, private storage references, raw local
paths, and requester/other-tenant IDs are excluded.

## 6. Result Snapshot Reads

Latest, cached, version-detail, proposal, export, and admin reproducibility
reads use `AnalysisVersion.result_snapshot`. Tests deliberately mutate the
parent compatibility mirror and prove the version result does not change.

## 7. Evidence Snapshot Reads

Version-aware evidence comes from `AnalysisVersion.evidence_snapshot` and is
passed through the existing customer-safe evidence sanitizers. A request for
v2 never consults v3 evidence or the parent mirror.

Persisted version snapshots, provenance, and hashes reject ordinary ORM
assignment through the application model contract. Detached read payloads are
deep copies. Integrity mismatch probes do not repair or overwrite history.

## 8. Tender Snapshot Reads

Historical detail and export use `AnalysisVersion.tender_snapshot` for title,
external ID, buyer, deadline, and other analysis-time tender values. Live Tender
data is used only for current access/existence checks and is not blended into
the historical report.

## 9. Company Snapshot Reads

Historical detail and export use `AnalysisVersion.company_snapshot`.
Authorization still uses the current explicit parent ownership tuple; snapshot
company data is never authorization. The customer detail response removes the
internal company-profile ID.

## 10. Document Snapshot Reads

Version detail reads `AnalysisVersionDocumentSnapshot`, not live tender
documents. It exposes source identity, safe HTTP(S) source URL, filename, media
type, content hash, observation/fetch time, and an availability classification.
`HASHED` proves a captured content identity, not guaranteed historical byte
availability; storage references and versions remain internal.

## 11. Reproducibility Status

- `COMPLETE`: the runtime execution captured an input hash, model and prompt
  identifiers, and hashable document inputs under the Sprint 2.2 contract.
- `PARTIAL`: one or more runtime inputs/provenance elements were not captured,
  or the execution failed.
- `LEGACY_BACKFILL`: only historically persisted fields were preserved during
  migration; missing information was not fabricated.

`COMPLETE` verifies captured data, not semantic AI correctness or guaranteed
retention of historical file bytes.

## 12. Hash Verification

`verify_analysis_version_integrity(version)` recomputes output, evidence,
document-set, and version hashes where the required canonical inputs exist. It
returns `VERIFIED`, `PARTIAL`, or `MISMATCH`, with per-hash `VERIFIED`,
`MISMATCH`, or `NOT_AVAILABLE` status. Legacy document-order fingerprints use a
different preserved contract and are reported as not recomputable rather than
as false mismatches.

## 13. PDF / Export

Current export resolves the canonical parent and latest version. Supplying both
`analysis_id` and `version_number` exports one owned historical version. Result,
evidence, tender, and company data all come from that version. The PDF records
the version number and snapshot completeness; partial/legacy exports include a
truthful warning that exact historical bytes or provenance may be unavailable.

## 14. Proposal Integration

AI proposal drafting resolves the same canonical parent and latest version and
builds its compliance ledger from `result_snapshot.evaluation`. It does not
choose an independent aggregate or read the parent JSON mirror. Existing live
tender text and proposal behavior remain otherwise unchanged.

## 15. Cache Semantics

Cache matching compares the current input fingerprint with the authoritative
latest version `input_hash`. A match returns that version snapshot and creates
no new version. The post-extraction concurrency recheck uses the same rule.
An owned parent without a version fails as an integrity anomaly instead of
falling back to its mirror.

## 16. Risk Override Overlay

The base Compliance result remains immutable. `RiskOverrideLog` and
`TenderAnalysis.override_seal` remain a separate human-liability overlay. The
seal now anchors to the latest version input hash, not the mutable parent hash;
applying an override does not rewrite any version snapshot or version hash.

## 17. Ownership / Authorization

All customer version reads join through an `OWNED` parent with exact current
`user_id` and `company_profile_id`; explicit routes also require the matching
`tender_id`. Display names are never authorization. Same-name tenant B and
quarantined parents receive no history. Existing approved/disabled account
dependencies protect the new routes in the same way as other Compliance routes.

## 18. Zero-Version Anomaly

A correctly migrated parent must have at least one version. If an owned parent
has zero versions, services log `analysis_version_zero_version_anomaly` and
customer reads return safe `409` unavailability. Admin diagnostics label the
parent `ZERO_VERSION_PARENT`. No route silently treats parent mirrors as
canonical fallback data.

## 19. Parent Compatibility Mirror

The analyze transaction still writes `analysis_json` and `content_hash` after
appending the immutable version for compatibility with older integrations.
Static audit found no canonical customer read of those fields. Migration and
compatibility writes are the only remaining result-mirror uses in the runtime
endpoint code.

## 20. Preflight

The existing read-only preflight now reports total parents/versions,
zero/one/multi-version parents, duplicate numbers, broken supersession, orphan
versions, completeness classes, missing hashes, recomputable hash mismatches,
document snapshot gaps, quarantined version parents, and multi-parent owned
logical keys. Snapshot values are processed in memory only; output contains
counts and never analysis content. It performs no repairs.

## 21. Test Results

The Sprint 2.3 fast contract suite and disposable PostgreSQL matrix pass. The
database matrix covers fresh/existing upgrades, v1/v2/v3 lineage, distinct
duplicate-parent histories, mirror/live snapshot drift, version-specific
evidence, detached payload immutability, mismatch detection without repair,
same-name isolation, quarantine denial, zero-version failure, preflight, and a
clean Alembic check. Final maintained gates: 29 focused Sprint 2.1–2.3 tests;
42 broader Compliance tests; 62 Sprint 1/WB tests; 86 security/UNKNOWN tests
plus 10 subtests with one approved skip; and 195 connector-gate tests plus four
subtests with one approved storage-fixture skip. Sprint 2.1, Sprint 2.2,
Sprint 2.2B, Project foundation, WB enrichment, and WB auto-drain disposable
database scripts all passed. The configured developer database remains at the
older Sprint 1.2 revision and was intentionally not mutated; fresh/existing
disposable databases both report a clean `alembic check` at repository head.

## 22. Deferred Version UI / Comparison

No frontend files or broad version-history UI were added. Version selector,
timeline redesign, comparison/diff, rollback/restore, historical reruns,
semantic comparison, parent merging, and quarantine reconciliation remain
explicitly deferred beyond Sprint 2.3.
