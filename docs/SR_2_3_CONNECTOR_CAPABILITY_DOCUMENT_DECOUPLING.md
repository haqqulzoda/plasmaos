# SR-2.3 Connector Capability, Document Decoupling, and Efficiency

## 1. Previous Connector Architecture

The durable SR-2.2 job worker delegated to an API helper containing a source `if/elif` chain. Connector responses had several shapes, document descriptors were persisted through per-row lookups, and ADB resolved redirects and parsed PDFs before metadata persistence completed.

## 2. Source Registry

`SOURCE_REGISTRY` is an immutable, code-owned mapping of the five canonical keys: `uzex`, `world_bank`, `giz`, `adb`, and `ebrd`. It is the source of truth for display names, enablement, visibility, strategies, document policy, runner, options, fallback, and concurrency declarations.

## 3. Capability Contract

Each frozen `SourceDefinition` declares its runner, default and accepted options, refresh strategy, document policy, force support, checkpoint support, fallback support, and bounded fetch/document concurrency. Customers cannot mutate this contract.

## 4. Enablement Semantics

All five existing connectors remain enabled. Unknown keys return the existing unsupported-source response; a known but disabled definition returns service unavailable before a job is created.

## 5. Refresh Strategy

UzEx declares a bounded latest window, World Bank a bounded current set, GIZ bounded surfaces, and ADB/EBRD bounded listings. None claims incremental cursor behavior.

## 6. Checkpoint Semantics

Every current source declares `supports_checkpoint=False`; canonical execution results therefore keep `checkpoint=None`. No synthetic checkpoint or watermark was introduced.

## 7. Document Policies

UzEx remains a separate targeted workflow, World Bank stores metadata-only descriptors, GIZ requires explicit hydration, ADB uses asynchronous enrichment, and EBRD remains access-required.

## 8. Canonical Execution Result

`SourceExecutionResult` adapts each legacy connector response into one internal terminal contract with semantic row counters, document counters, degraded/fallback state, health fields, timings, HTTP counters, and optional checkpoint.

## 9. Status / Health Contract

Legacy `success`, `partial`, `source_unavailable`, and failure values map to the existing durable statuses. Execution, freshness, coverage, fallback, failure class/stage, and retryability remain distinct.

## 10. UzEx Integration

The registry adapter invokes the existing UzEx bounded refresh. Its separate targeted document task, parser, and customer behavior are unchanged.

## 11. World Bank Integration

The existing bounded paging, semantic Tender batch persistence, deterministic project linkage, background project enrichment, and metadata-only attachment discovery remain in place.

## 12. GIZ Integration

Metadata refresh still discovers descriptors only. Archive download, extraction, parsing, and compilation remain behind explicit GIZ hydration on the heavy queue.

## 13. ADB Integration

Official current-listing retrieval and legacy fallback remain connector-local. Listing normalization now emits a deterministic lightweight document candidate without making any document request.

## 14. EBRD Integration

Existing retrieval, detail limits, URL validation, and security behavior remain. Restricted participation documents persist as `access_required` and are never published for download.

## 15. Metadata Completion Contract

A metadata refresh is complete when accepted Tender snapshots, lightweight descriptors, and lifecycle reconciliation are committed. ADB PDF resolution, download, parsing, and contact extraction are explicitly outside that duration.

## 16. Document Descriptor Persistence

`persist_document_descriptors` validates and de-duplicates candidates, performs one bounded lookup per tender batch, merges safe metadata, creates missing descriptors, and reports created/updated/unchanged outcomes.

## 17. Document Status Monotonicity

Status precedence prevents rediscovery from replacing queued, processing, downloaded, processed, parsed, or usable states with metadata-only/access-required/failed states. Failed work may return to metadata-only for a deliberate retry.

## 18. ADB Decoupling

ADB `discover_attachments` now derives a stable SHA-256 candidate from source key, notice type, and node URL. It performs no redirect, PDF download, byte parsing, or contact extraction.

## 19. ADB Contact Enrichment

The heavy task uses one HTTP client, locks and fences the document/candidate identity, resolves the node, fetches/parses the PDF, and merges only non-empty contact fields. It records evidence hashes and enrichment provenance without clearing earlier contacts on failure or empty extraction.

## 20. Document Queue Idempotency

Only descriptors in `metadata_only` or `failed` state are eligible. Publication success precedes the queued counter/state write; queued and terminal states are skipped. The worker row lock and candidate token make duplicate deliveries bounded and safe.

## 21. Restricted Document Policy

The EBRD policy is terminal metadata describing external access. Its connector contains no Celery publication path, and monotonic persistence cannot downgrade richer historical evidence.

## 22. World Bank Equal-Provenance Optimization

Tender semantic equality prevents observation timestamp churn. Project linkage assigns only when project identity, method, value, or evidence differs, and document descriptors avoid equal-value assignments.

## 23. HTTP Client Reuse

ADB listing already reuses its listing client. Async document enrichment now passes one client through redirect resolution, PDF acquisition, and contact extraction instead of creating a client for every stage.

## 24. Bounded Concurrency

Registry definitions conservatively declare fetch and document concurrency one. The heavy worker also runs with concurrency one and worker prefetch one, so the declaration matches enforced runtime behavior and no source request burst was added.

## 25. HTTP Metrics

The canonical contract and durable job support nullable request, retry, and failure counts. ADB counts each attempted request, each retry scheduled, and each failed attempt. Sources without proven counters persist null rather than fabricated zero.

## 26. Stage Timings

Nullable fetch, normalization, persistence, and document-dispatch milliseconds are durable job fields. ADB measures these boundaries; asynchronous enrichment duration is excluded from metadata refresh elapsed time.

## 27. Benchmark Results

Static complexity changed document lookup from one query per descriptor to one bounded query per tender descriptor set. The disposable PostgreSQL audit created a descriptor once, classified its exact repeat as unchanged, preserved `processed` on rediscovery, and completed 1,000 network-free ADB discoveries in 10 ms with zero document HTTP calls.

## 28. Migration Decision

One additive SourceRefreshJob-only migration adds seven nullable integer metrics. No Tender schema, created-at semantics, first-seen field, lifecycle state, or historical value is rewritten.

## 29. ADB Future Repair Boundary

Authoritative listing recovery and broader historical repair remain deferred. Future ADB repair must stay connector-local and use the same registry, descriptor, fencing, and contact ownership contracts.

## 30. EBRD Future Repair Boundary

Restricted-access recovery or authenticated acquisition remains deferred. It must not silently turn `access_required` descriptors into general download work.

## 31. Regression Results

The focused suite covers registry immutability/options, generic dispatch, ADB critical-path absence, contact preservation, status monotonicity, commit-before-publish, successful-publication counting, shared lookup, EBRD restrictions, nullable metrics, and Alembic head. The connector gate passed 195 tests plus 4 subtests (1 intentional skip); the backend regression selection passed 573 tests plus 75 subtests (1 intentional skip).

## 32. Deferred SR-2.4 Work

Completion activity/history APIs, customer final-state DTOs, Explorer newness, final source catalog, and polling contracts remain SR-2.4. All frontend activity/toasts/badges and transport UX remain SR-3.
