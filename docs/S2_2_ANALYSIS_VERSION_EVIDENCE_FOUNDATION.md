# Sprint 2.2 — Analysis Version & Evidence Snapshot Foundation

## 1. Existing Analysis Mutation Model

Before Sprint 2.2, every non-cached analysis—including `force=true`—created a new `TenderAnalysis`. A matching non-forced content hash reused the newest owned row. A failed extraction could return a prior non-failed row without writing; otherwise the product persisted a structured failed result. Risk overrides changed only the parent compatibility seal and created separate override/audit records. Proposal and PDF/export paths read the newest parent row.

Sprint 2.2 makes the newest existing owned `TenderAnalysis` the stable logical aggregate for runtime re-analysis. Historical duplicate parent IDs are not merged or deduplicated.

## 2. Version Aggregate Contract

`TenderAnalysis` remains the tenant-owned aggregate. `AnalysisVersion` belongs to exactly one parent and inherits authorization from that parent's `user_id`, `company_profile_id`, and `ownership_state`. No second ownership hierarchy exists on versions.

Every historical parent receives its own v1 even when tender, profile, display name, content hash, or result is the same as another parent.

## 3. AnalysisVersion Schema

`analysis_versions` stores identity and lineage; origin and status; analysis, pipeline, model, and prompt provenance; tender, company, result, and evidence JSON snapshots; deterministic hashes; completeness; requester identity; and timestamps. `analysis_version_document_snapshots` stores analysis-time source identity, optional live document FK, source/storage references, known content hash, observation fields, and non-byte metadata.

Allowed origins are `LEGACY_BACKFILL`, `RUNTIME_ANALYSIS`, and `RUNTIME_REANALYSIS`. Allowed statuses are `COMPLETED`, `NEEDS_REVIEW`, and `FAILED`.

## 4. Version Numbering / Concurrency

Version numbers start at 1 and are unique on `(analysis_id, version_number)`. Runtime allocation locks the parent with PostgreSQL `SELECT ... FOR UPDATE`, reads the greatest existing version only while holding that lock, and inserts N+1. The unique constraint is a final integrity guard, not the allocation mechanism.

The disposable PostgreSQL concurrency proof starts two transactions against one parent. They produce unique sequential versions 2 and 3 with a single correct predecessor chain.

## 5. Supersession

V1 has no predecessor. Every runtime N greater than 1 points to version N-1 through `supersedes_version_id`. The predecessor relation is unique, preventing two versions from claiming the same immediate predecessor. Supersession is lineage only: no prior version is removed, marked current, or rewritten.

## 6. Legacy V1 Backfill

The additive migration performs one set-based `INSERT ... SELECT` from every `TenderAnalysis`, including `OWNED` and `QUARANTINED_LEGACY`. The version ID is the existing analysis ID, which is deterministic and collision-free within the new table. The migration does not call a network, LLM, document fetch, or application helper.

Legacy v1 uses `origin=LEGACY_BACKFILL`, `version_number=1`, and `snapshot_completeness=LEGACY_BACKFILL`. It copies the exact persisted `analysis_json` as `result_snapshot`, the existing content hash as `input_hash`, known reproducibility metadata, and the parent timestamp. Unknown provider, model version, prompt hash, pipeline version, requester, and newly computed result/evidence/version hashes remain null.

## 7. Result Snapshot

Runtime `result_snapshot` contains the complete persisted compliance payload at completion: legacy requirements and evaluation, hybrid compliance, evidence validation, reproducibility snapshot, extraction artifact metadata, warnings, coverage, analysis status and error, strategy intelligence, and tenant company display snapshot. It is sufficient to reconstruct the current Compliance result in Sprint 2.3 without consulting a later parent mirror.

Legacy `result_snapshot` is the exact stored parent `analysis_json`; the migration performs no semantic transformation.

## 8. Evidence Snapshot

Runtime `evidence_snapshot` preserves the annotated evidence validation payload, hybrid compliance evidence/routes, and requirement route summary. These structures already include requirement fingerprints, source filename identity, page and exact quote where extracted, validation/routing state, and vault-match diagnostics used by the compliance engine.

Legacy evidence is copied only from fields already persisted in `analysis_json`. Missing historical evidence stays missing; the migration neither extracts nor invents it.

## 9. Document Snapshot

Each runtime tender document produces an analysis-version document snapshot with source system, external key, source URL, display filename, media type, known byte SHA-256, storage reference, observation time, file/download metadata, and parsed-text hashes. Large document bytes are never duplicated.

Legacy document rows are created only from persisted `reproducibility_snapshot.input_fingerprints.document_fingerprints`. A matching live `TenderDocument` ID may be linked, but live URL/storage values are deliberately not copied as historical facts. A persisted parsed-text SHA-256 is retained as the known content hash.

Storage paths are references, not proven immutable object versions. Where no byte hash or parsed-text identity exists, the value remains unknown and completeness is reduced.

## 10. Tender Snapshot

Runtime versions capture only analysis-relevant tender values: stable IDs and source identity, title, buyer, deadline, currency, budget, procurement method, notice type, project ID, and source URL. The ORM object is not blindly serialized.

Legacy versions snapshot those same values as observed at migration time. They remain classified `LEGACY_BACKFILL`, because migration-time tender metadata cannot prove the precise historical input state.

## 11. Company Snapshot

Runtime versions preserve company profile identity and display name plus only readiness inputs actually supplied to the compliance cache/evaluation path: certifications, licenses, financial history, and held credential taxonomy-node IDs. The provenance snapshot also retains the source-neutral taxonomy nodes and source-coverage input supplied to the pipeline. Personal contact, banking, authentication, and approval data are excluded. This snapshot is evidence/context, never authorization.

Legacy versions preserve the historical parent company display value and known profile ID for fidelity, but do not reconstruct a current vault or duplicate user authorization state.

## 12. Prompt/Model/Pipeline Provenance

Runtime provenance records the configured requirement and strategy model names, provider (`google`), temperature, prompt SHA-256 values, known requirement prompt/schema version, pipeline version `hybrid_compliance_s2_2_v1`, and the existing engine/build metadata. Full prompts and credentials are not stored.

The configured requirement model is captured at execution time. `model_version` stays null because the provider does not supply a stronger immutable model revision. Strategy prompt version stays null because no separate historical template version exists; its deterministic prompt hash is recorded. Legacy values come only from persisted engine metadata. In particular, provider and prompt hash remain null rather than being inferred from today's code.

## 13. Hash Contract

All new JSON hashes use `stable_json_sha256`: UTF-8 JSON with sorted keys, compact separators, Unicode preserved, and deterministic string conversion for supported non-JSON values.

- `input_hash` is the existing compliance content hash over extractor schema, compiled tender text, credential/taxonomy inputs, vault inputs, and source coverage inputs.
- `output_hash` hashes the full immutable result snapshot.
- `evidence_hash` hashes the immutable evidence snapshot.
- `document_set_hash` hashes a canonically sorted set of document identity, source/storage identity, known content hashes, observation fields, and metadata; it does not hash document bytes stored elsewhere.
- `version_hash` hashes analysis identity, number, predecessor, origin/status, all provenance and snapshots, the preceding hashes, completeness, and requester. It excludes mutable timestamps, database-generated version ID, and itself.

Legacy backfill preserves existing input/document-set fingerprints but does not retroactively compute new output, evidence, or version hashes.

## 14. Snapshot Completeness

`LEGACY_BACKFILL` always identifies pre-version-architecture history and never claims complete reproducibility. Runtime `FAILED` versions are always `PARTIAL`. A runtime non-failed version is `COMPLETE` only when it has an input hash, configured requirement model, requirement prompt hash, at least one document snapshot, and for each document either a known content hash or a non-empty parsed-text hash. Otherwise it is `PARTIAL`.

This definition is conservative: a compiled-text-only analysis without a normalized document row remains partial even though the result itself is preserved.

## 15. Runtime Dual-Write

For a new logical analysis, runtime creates the owned compatibility parent, flushes it, locks that parent through the version service, inserts v1 and document snapshots, applies compatibility mirror fields, and commits once. Any database error rolls back both parent and version.

Persisted structured failures use an immutable `FAILED`/`PARTIAL` version because the existing product deliberately materializes that result. A failed extraction that falls back to a previous non-failed cached result creates no version and changes no parent.

## 16. Re-analysis Append Semantics

The analysis endpoint now finds the newest explicit owned parent even when `force=true`. A non-forced equal content hash still returns the cached parent. Otherwise successful materialization or a persistable structured failure appends N+1 to that parent. Equal hashes are allowed across versions and never cause deduplication on forced analysis.

Historical multiple `TenderAnalysis` rows stay separate aggregates. New runtime re-analysis attaches only to the deterministically newest existing owned parent.

## 17. Compatibility Mirror

Current APIs remain parent-based for Sprint 2.2. After a version is staged, runtime mirrors these latest values on `TenderAnalysis`: `tender_file_name`, `company_name`, `raw_extracted_text`, `analysis_json`, and `content_hash`. `override_seal` remains independent and is not reset by model analysis.

These columns are no longer authoritative historical storage. Sprint 2.3 will cut read paths to versions; Sprint 2.2 removes none of the legacy columns.

## 18. Risk Override Separation

`RiskOverrideLog` and the audit ledger continue to represent subsequent human decisions. An override may update the parent `override_seal` for compatibility, but it does not update result/evidence snapshots or any hash on a completed `AnalysisVersion`. Model output and human decision history therefore remain forensically distinct.

## 19. Ownership / Quarantine

Version services join through the parent and require exact user ID, company profile ID, and `ownership_state=OWNED`. Display names are never authorization inputs. Other tenants—including tenants with the same company display name—receive no version. A quarantined parent receives legacy v1 for preservation but no customer-accessible version through the service.

No customer-facing version route is introduced in Sprint 2.2, so existing disabled-account endpoint guards remain unchanged.

## 20. Migration

Revision `20260827_0002_s2_2_analysis_version_foundation` follows Sprint 2.1 and creates the two version tables, FKs, checks, uniqueness constraints, and indexes before performing set-based legacy inserts. It is additive and leaves parent analyses, forensic seals, overrides, proposals, recommendations, Projects, and tender/project links unchanged.

Fresh and representative existing Sprint 2.1 databases upgrade to the single new head and pass `alembic check`. The latest disposable 1,003-analysis run completed its set-based v1 backfill in 4.498 seconds with zero gaps and no external operations. The read-only local preflight observed 127 existing analyses; production scale remains intentionally unqueried in this task.

## 21. Rolling Deployment Compatibility

- Old S2.1 code with S2.2 schema continues to write owned `TenderAnalysis` rows but cannot create versions, producing version gaps.
- New S2.2 code with S2.1 schema fails atomically when the version table is absent; successful parent-only writes do not occur, but analysis requests fail.
- New S2.2 code with S2.2 schema performs the atomic parent/version workflow.

Production must therefore quiesce or block compliance-analysis writes during the short database-migration/application-cutover interval, apply the migration, deploy S2.2 code, verify the head and preflight zero-version count, then restore writes. This sprint performs no deployment.

## 22. Preflight Reporting

The read-only PostgreSQL preflight now catalogs both version tables and reports total parents/versions; parents with zero, one, or multiple versions; duplicate version numbers; parent and document-snapshot orphans; broken/cross-parent/non-sequential predecessors; quarantined versions; completeness classes; and missing input/output/evidence/document-set/version/document hashes. It emits counts only, never result or evidence content, performs no repair, and always rolls back its read-only transaction.

## 23. Test Results

The focused suite passed 38 tests plus 7 subtests. It validates the model, revision graph, migration truthfulness, parent lock, append-before-mirror transaction order, conservative completeness, deterministic document hashing, and safe preflight fields. The disposable PostgreSQL matrix validates fresh and existing upgrades, exact parent/artifact fidelity, owned/quarantined behavior, missing legacy provenance, normalized document snapshots, v1/v2/v3 lineage, equal-hash retention, owner-only reads, snapshot stability after live data changes, concurrent allocation, atomic rollback, preflight invariants, load backfill, and clean autogeneration.

The maintained top-level backend suite passed 387 tests, 21 subtests, and one approved skip. The connector gate passed 195 tests and 4 subtests with the same approved skip. The focused security/UNKNOWN gate passed 86 tests and 10 subtests with one approved skip. Sprint 2.1 and both Sprint 1 disposable database matrices passed fresh/existing upgrades and clean autogeneration. The Project Context frontend passed 18 tests and TypeScript typecheck.

## 24. Deferred Sprint 2.3 Work

Sprint 2.2 intentionally does not add customer version-history UI, historical selection/comparison, version-aware Compliance reads, historical PDF generation, version deep links, latest-version indicators, difference highlighting, rollback, or analysis-language architecture. Sprint 2.3 should make `AnalysisVersion` authoritative for reads and exports while preserving the parent authorization join.
