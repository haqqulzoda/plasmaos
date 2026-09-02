# SR-2.1 — Semantic Batch Tender Persistence

Status: PASS locally on 2026-08-31. No production access, deployment, data repair,
backfill, or schema migration was performed.

## 1. Previous Persistence Algorithm

The shared `upsert_tender` path performed a canonical-key SELECT for every input,
then a `(source_system, external_id)` fallback SELECT when the key was absent. New
rows were added one at a time and every existing row had every source column,
including `last_synced_at`, assigned again. Callers interpreted `existing` as
`UPDATED`, even when all source metadata was identical. CREATED was decided before
the transaction's unique-key race was resolved.

The locked SR-1 10,000-row baseline was:

| Run | SELECT | INSERT | UPDATE | Wall time |
| --- | ---: | ---: | ---: | ---: |
| First | 20,000 | 10,000 | 0 | 30.363s |
| Identical repeat | 10,000 | 0 | 10,000 | 20.818s |

## 2. Canonical Identity

Canonical logical identity remains `(normalize_source_system(source_system),
trim(external_id))`. `canonical_source_key` remains the normalized
`source_system:external_id` representation. Both existing unique contracts are
queried together. Title, buyer, URL, company, publication date, and other content
never participate in identity.

If canonical-key and source/external lookup resolve to different rows, or a
canonical key belongs to another pair, persistence raises
`TenderIdentityConflictError`. Existing legacy rows with a noncanonical key still
resolve through the source/external pair and are normalized without a backfill.
Cross-source equal external IDs remain separate.

## 3. Source-Owned Semantic Snapshot

The exact source-owned Tender fields are:

`source_system`, `external_id`, `canonical_source_key`, `source_url`, `title`,
`description`, `budget`, `currency`, `deadline`, `publication_date`, `country`,
`region`, `sector`, `buyer`, `procurement_category`, `procurement_method`,
`notice_type`, `project_id`, `source_metadata_json`, `scrape_status`, `status`, and
`category`.

Excluded fields are `last_synced_at`, `created_at`, `compiled_master_text`, all
relationships, and all Project, TenderDocument, TenderEngagement, Proposal,
TenderAnalysis, AnalysisVersion, TenderRecommendation, Compliance, and
CompanyProfile state.

## 4. Equality Rules

`source_owned_tender_snapshot` and the update comparator apply the same rules:

- datetimes are normalized to UTC, with naive source datetimes treated as UTC;
- enums compare by value;
- optional normalized strings retain the existing trim/empty-to-null behavior;
- JSON mappings are key-sorted recursively;
- source metadata collections are recursively canonicalized and order-insensitive;
- `last_synced_at`, `created_at`, attachments, and downstream state do not compare.

Unit tests prove equivalent time zones and reordered JSON remain equal while a
single changed source field is unequal.

## 5. Batch Lookup

`persist_tender_batch` uses bounded chunks and one combined SELECT per chunk over
canonical keys and `(source_system, external_id)` tuples. There is no SELECT Tender
per normalized row. The default chunk size is 500. Lookup maps are chunk-local;
the input de-duplication map and returned result necessarily remain O(N), while SQL
parameter volume and active database working state remain O(batch).

## 6. Conflict-Safe Insert

Absent candidates use PostgreSQL multi-row `INSERT ... ON CONFLICT DO NOTHING
RETURNING Tender`. Only rows returned by PostgreSQL are CREATED. A loser is looked
up again in a bounded query and compared with the durable winner, becoming UPDATED
or UNCHANGED. Expected uniqueness loss is not converted to IntegrityError or
FAILED. Missing re-resolution and other database errors remain hard failures.

## 7. Update Path

Existing rows are compared field by field using canonical semantic values. Only
changed source-owned fields are assigned. `last_synced_at` advances only when a
source-owned change is applied. SQLAlchemy flushes each changed chunk using
parameterized ORM executemany behavior where update shapes match. No identity
SELECT is performed per update.

The 10,000-row mixed proof emitted 20 Tender SELECT statements, eight multi-row
INSERT statements, and four executemany UPDATE statements for 4,000 CREATED, 2,000
UPDATED, and 4,000 UNCHANGED rows.

## 8. Unchanged Path

An identical source-owned snapshot returns UNCHANGED. It performs no ORM Tender
assignment and emits no INSERT, UPDATE, or DELETE. A reordered but otherwise equal
metadata JSON list also remains UNCHANGED. The 10,000-row repeat proof returned
exactly `0/0/10,000` CREATED/UPDATED/UNCHANGED with zero Tender UPDATE statements.

## 9. `last_synced_at` Decision

The runtime audit found only two consumers: World Bank Project-link provenance and
GIZ hydration's reconstruction of an existing normalized Tender. The customer API
does not expose the field. No correctness reader requires it to mean “last observed
in source.” It now means the last created/applied source synchronization for normal
persistence. It is unchanged for UNCHANGED rows. Deadline/lifecycle reconciliation
may still advance it when it actually changes Tender status.

Keeping the prior timestamp also prevents World Bank project provenance from being
rewritten solely because a source row was seen again. Source-level observation
freshness remains deferred to SourceRefreshJob work in SR-2.2.

## 10. `created_at` Preservation

`created_at` is absent from insert payloads and semantic updates. PostgreSQL supplies
it for insert winners. Existing, updated, unchanged, legacy-fallback, and concurrent
loser paths use the row's existing value. The fresh PostgreSQL matrix asserts it is
stable across CREATED → UNCHANGED → UPDATED and is never derived from publication
date.

## 11. Result Enum

`TenderPersistenceOutcome` defines mutually exclusive CREATED, UPDATED, and
UNCHANGED values. `TenderPersistenceItem` returns the canonical key, tracked Tender
object, and outcome. `TenderBatchPersistenceResult` provides a deterministic tuple,
canonical-key mapping, semantic counts, and duplicate count.

The old `(Tender, created_bool)` wrapper remains only for focused legacy tests and
connector single-row compatibility methods. Every normal runtime ingestion route
uses the batch contract directly. A real `AsyncSession` compatibility call delegates
to the canonical service; only lightweight historical fake sessions use the isolated
test adapter.

## 12. Connector Integration

| Caller | Normalized input | Old flush / commit owner | Post-persist dependency | Used created bool / counter effect | SR-2.1 result |
| --- | --- | --- | --- | --- | --- |
| UzEx refresh | `ScrapedTender` → `NormalizedTender` | no row flush; refresh commits | none; latest-50 and contacts unchanged | bool incremented new else updated | one batch; semantic new/updated/unchanged after commit |
| World Bank sync | normalized API notice | connector Project link flushed Tender; route committed | Project/TenderProject, document metadata, post-commit enrichment dispatch | bool incremented created else updated | one Tender batch; returned Tender mapping feeds unchanged linkage/document ownership |
| GIZ sync | normalized public/e-procurement row | row and document flushes; route committed | quarantine, document metadata, optional explicit hydration | bool incremented created else updated | one Tender batch; quarantine/hydration behavior unchanged |
| ADB sync | normalized listing/fallback notice | row flush; route committed | document metadata, deadline and legacy reconciliation | bool incremented created else updated | one Tender batch; fallback/PDF/contact path unchanged |
| EBRD sync | normalized metadata-only notice | row flush; route committed | access-required document metadata | bool incremented created else updated | one Tender batch; restriction/fallback behavior unchanged |
| Admin seed route | dummy records → `NormalizedTender` | route committed | none | bool counted existing as skipped | one batch and committed semantic result |
| Offline seed | raw SQL INSERT per row in engine transaction | engine transaction | none | printed row exceptions | one canonical batch and one commit |
| Tests | normalized fixtures and fake sessions | test-owned | identity/actionability assertions | old bool assertions | compatibility wrapper retained and documented |
| Other runtime caller | none found | n/a | GIZ hydration normalizes an existing row but does not persist Tender | none | no hidden per-row Tender path |

Normalization, network requests, source authorization, direct route visibility,
Project ownership, and source-specific document handling were not redesigned.

## 13. Commit / Rollback Semantics

All source responses derive semantic Tender counts from the batch result and publish
them only after successful commit. World Bank, GIZ, ADB, and EBRD commit-failure
responses explicitly return zero CREATED, UPDATED, and UNCHANGED successful-write
counts. UzEx now rolls back on every failure and also returns all-zero counts.

The forced-rollback PostgreSQL proof observed one provisional insert outcome, rolled
the transaction back, and found zero durable rows. The focused UzEx forced-commit
failure test proves the terminal response is `0/0/0`, not the provisional CREATED
count. Unexpected database errors are surfaced as failures, never UNCHANGED.

## 14. Concurrency

The PostgreSQL test held a SHARE table lock so two sessions both completed absent
identity lookup and both waited as insert contenders before release. After both
transactions committed:

- run A: 100 CREATED, 0 UPDATED, 0 UNCHANGED;
- run B: 0 CREATED, 0 UPDATED, 100 UNCHANGED;
- durable rows: 100;
- sum(CREATED): 100;
- duplicate rows and expected-race failures: zero.

The loser used the winner's Tender object and `created_at`.

## 15. SQL Benchmark

Default batch size: 500. Counts include only statements targeting Tender.

| Rows | Run | SELECT | INSERT | UPDATE | DELETE | Outcome C/U/N | Wall |
| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 100 | first | 1 | 1 | 0 | 0 | 100/0/0 | 0.066s |
| 100 | repeat | 1 | 0 | 0 | 0 | 0/0/100 | 0.054s |
| 1,000 | first | 2 | 2 | 0 | 0 | 1,000/0/0 | 0.578s |
| 1,000 | repeat | 2 | 0 | 0 | 0 | 0/0/1,000 | 0.182s |
| 10,000 | first | 20 | 20 | 0 | 0 | 10,000/0/0 | 10.075s |
| 10,000 | repeat | 20 | 0 | 0 | 0 | 0/0/10,000 | 5.891s |
| 10,000 | mixed | 20 | 8 | 4 | 0 | 4,000/2,000/4,000 | 3.632s |

`C/U/N` means CREATED/UPDATED/UNCHANGED. Multi-row INSERT and executemany UPDATE
are each counted at the executed statement level.

## 16. Batch-Size Benchmark

Identical 10,000-row repeat, after warm data, with process RSS high-water shown as
a low-overhead approximate memory bound:

| Batch | SELECT | UPDATE | Wall | Process high-water |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 100 | 0 | 6.466s | 147.63 MiB |
| 250 | 40 | 0 | 1.455s | 147.63 MiB |
| 500 | 20 | 0 | 1.395s | 147.67 MiB |
| 1,000 | 10 | 0 | 1.700s | 148.17 MiB |

500 is retained as the conservative default: it was fastest in this warmed run,
uses half the bind-parameter volume of 1,000, produces only 20 lookup statements at
10,000 rows, and has essentially the same memory high-water as smaller batches. The
earlier cold run showed meaningful timing variance, so the choice does not rely on
one fastest microbenchmark alone.

## 17. First vs Repeat Performance

Against SR-1:

- first 10k: 30.363s → 10.075s, 66.82% faster; SELECT 20,000 → 20 and INSERT
  10,000 → 20;
- identical repeat 10k: 20.818s → 5.891s, 71.70% faster; SELECT 10,000 → 20 and
  UPDATE 10,000 → 0.

The repeat remains faster because it transfers no insert return rows and performs no
flush. SQL complexity now scales with `ceil(N / batch_size)`, not N.

## 18. Mixed Batch

The disposable database seeded 6,000 rows, then ingested 4,000 unchanged, 2,000
changed, and 4,000 absent identities. It returned exactly 4,000 CREATED, 2,000
UPDATED, and 4,000 UNCHANGED with no overlap. Wall time was 3.632s. A duplicate
identity in one input uses deterministic last-payload-wins, retains first identity
order, returns one persisted item, and increments `duplicate_count` once.

## 19. Source Compatibility

- World Bank: Project creation/reuse, TenderProject linkage, document discovery, and
  post-commit enrichment dispatch remain connector-owned. Batch results eliminate
  Tender re-query solely to recover IDs.
- GIZ: quarantine, source document metadata, partial-surface behavior, and explicit
  hydration remain unchanged; hydration was not turned into refresh behavior.
- ADB: current listing/fallback, metadata discovery, PDF/contact behavior, deadline
  reconciliation, and legacy handling remain unchanged. No retrieval repair or
  decoupling was performed.
- EBRD: metadata-only/access-required restrictions and fallback behavior remain;
  no login, restricted download, or recovery change was introduced.
- UzEx: latest-50 fetch, contact behavior, and absence of refresh-time document
  processing remain unchanged.

## 20. Static N+1 and Write Audits

- N+1: no `source.upsert(db, normalized)` remains in runtime routes; six runtime
  call sites (five sources plus admin seed) call `persist_tender_batch`.
- unchanged writes: the `if not changed_fields` branch appends UNCHANGED and performs
  no `setattr` or `last_synced_at` assignment.
- created authority: runtime counters use `TenderBatchPersistenceResult`; CREATED is
  appended only when the key appears in rows returned by conflict-safe INSERT.
- identity: lookup predicates use only canonical key and source/external tuple.
- passive reads: Explorer, Tender Details, and Bid Preparation routes were not
  modified to persist or refresh.
- domain fingerprint: TenderEngagement, Proposal, TenderAnalysis, AnalysisVersion,
  TenderRecommendation, and CompanyProfile counts were all zero before and after
  the fresh persistence matrix.

## 21. Regression Results

- New SR-2.1 focused tests: 8 passed.
- Mandatory connector regression gate: 195 passed, 1 approved storage-fixture skip,
  4 subtests passed; zero unexpected failures.
- Combined focused source, authorization, worker/failure, Sprint 1/World Bank, and
  Sprint 6 regression run: 230 passed, 10 subtests passed; zero failures.
- All 68 root backend test modules except the known nonportable legacy
  `test_ai.py`: 550 passed, 1 approved skip, 75 subtests passed; zero failures.
- Disposable PostgreSQL create/unchanged/update/concurrency/cross-source/duplicate/
  mixed/rollback/domain matrix: PASS.
- Configured local count-only preflight: 1,881 Tenders; missing canonical identities
  0; duplicate source/external groups 0; duplicate canonical-key groups 0; read-only
  transaction rolled back. These are local counts, not production truth.
- Alembic heads/current: `20260828_0003_s4_1_tender_engagement_foundation` only.
- `alembic check`: `No new upgrade operations detected`.
- New migration and backfill: none.

The naive `pytest backend` collector remains unusable for a pre-existing repository
reason: it mixes duplicate-named executable files under `backend/scripts` with root
tests, `scripts/test_extraction.py` imports an already-removed `MODEL_NAME`, and
`test_ai.py` hard-codes a Windows working directory. The canonical gate, every root
backend module except that known legacy file, and all task-focused suites were run
through their valid entrypoints.

## 22. Deferred SR-2.2 Work

SR-2.1 does not add SourceRefreshJob `unchanged_count`, lease owner/expiry,
heartbeat, trigger kind, stale-job recovery, operator-route lifecycle convergence,
scheduling, or completion APIs. Source result objects now carry internal unchanged
counts; workers can log them, while durable job-schema storage remains the SR-2.2
contract. SR-2.3 connector-result redesign and ADB critical-path work, and all
SR-2.4/SR-3 notification/UI work, also remain untouched.
