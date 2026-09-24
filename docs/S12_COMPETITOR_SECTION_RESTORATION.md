# Sprint 12 / 12R — Competitor Section Restoration

## Status

Sprint 12 restored the existing Competitor section and its canonical
winner/participant/similar-market-actor semantics. Sprint 12R completes the
remediation: normal Tender Details reads are passive again and perform zero
source-adapter or external-network work.

Competitor data shown by `GET /tenders/{id}/details` now comes only from
canonical stored evidence:

- Plasma's versioned competitor cache inside the Tender's existing
  `source_metadata_json`;
- explicit winner, participant, and similar-market-actor metadata on bounded
  related Tenders.

There is no new database model, schema migration, browser request, or page-load
enrichment. No production access or deployment was performed.

## Root fix

The Sprint 12 aggregate called `_build_tender_competitor_intelligence` with
`include_live_sources=True`. That made a normal `/details` GET capable of
calling World Bank, UzEx, or ADB public endpoints.

Sprint 12R hard-wires the aggregate to `include_live_sources=False`. The
builder first loads the bounded, schema-validated stored cache and then applies
the retained related-Tender metadata projection. The standalone explicit
`GET /tenders/{id}/competitors` authority remains live-source capable for
compatibility; Tender Details never enters that branch.

## Stored cache and source-refresh lifecycle

The cache uses the existing Tender JSON metadata under the Plasma-owned key
`_plasma_competitor_intelligence_v1`. Its payload is versioned, timestamped,
source-labelled, validated through `TenderCompetitorResponse`, and capped at
30 records. Invalid cache entries are ignored. Source upserts preserve this
Plasma-owned key while replacing stale source-owned metadata.

After an explicit source-refresh job finishes, the existing worker starts a
separate additive cache-enrichment session for supported sources (World Bank,
UzEx, and ADB). The enrichment:

- selects at most 2,000 customer-visible source Tenders in one bounded query;
- groups them by inferred service category;
- performs at most one existing live-authority call per category;
- bypasses the transient live-response cache so only evidence fetched by the
  current lifecycle receives a new persisted timestamp;
- persists at most 30 canonical records per Tender in one commit;
- never erases a valid stored cache when a source is empty or unavailable;
- performs no enrichment write for a dry-run source job;
- cannot roll back or falsely fail the source-refresh job if enrichment fails.

The projection target deliberately omits country so shared category evidence
does not make a false country-match claim. Existing provenance, evidence URL,
participation type, confidence, and service-category semantics are retained.

## Page-load contract and passivity proof

Tender Details still issues exactly two browser domain reads:

1. `GET /tenders/{id}`
2. `GET /tenders/{id}/details`

No `/competitors` fan-out was reintroduced. The hard regression suite patches
the live competitor authority to raise if called and proves the stored-only
builder never awaits it. It also inspects both Tender GET handlers for source
fetchers. The real PostgreSQL HTTP release-read harness patches outbound
`httpx` sends, so any non-ASGI external request fails the test; `/details`
passes under that guard.

The maintained production Chromium case `production-passivity/details` also
passes, and its complete run records zero external requests.

## Truthful states and UI

The restored UI, section placement, four-locale chrome, RTL isolation,
responsive layout, keyboard behavior, and existing response DTO remain
unchanged by 12R. Stored evidence renders as `AVAILABLE`; no qualifying stored
evidence renders the existing truthful `EMPTY` state; aggregate inability
retains the separate `UNAVAILABLE` state. Historical evidence never claims
participation in the current Tender.

## Request, query, and enrichment budgets

- Initial browser reads: exactly 2.
- `/details` external/source requests: 0.
- `/details` release-read SQL ceiling: 14 statements.
- Related-Tender query: one set query, capped at 250 rows.
- Rendered/stored competitors: capped at 30.
- Background targets: capped at 2,000 per source refresh.
- Background live calls: at most one per inferred service category.
- No N+1, GET-side write, task enqueue, AI call, scrape, flush, or commit.

## Validation

- Focused competitor/Tender Details suite: 54 passed, 2 subtests passed;
  final authority/source-cache/worker suite: 39 passed.
- Related persistence/orchestration suite: 37 passed.
- Real disposable-PostgreSQL HTTP release reads: 1 passed; zero external
  requests; `/details` remained within 14 SQL statements.
- Full pinned backend suite: 759 passed, 1 skipped, 100 subtests passed.
- Security release group: 118 passed.
- Analysis release group: 50 passed, 12 subtests passed.
- Connector release group: 196 passed, 1 skipped, 6 subtests passed.
- Migration gate: heads/current/check and disposable schema preflight passed.
- Synthetic scale gate: passed through 100,000 Tenders with 3–5 read queries
  per case and no passive mutation.
- Exact 75-package Python constraints: passed; `pip check`: clean.
- Frontend: typecheck passed; ESLint passed; 217/217 static tests passed; RTL
  audit passed; 26-route production build passed; npm reported 0
  vulnerabilities at the configured high threshold.
- Maintained Chromium: 145/145 passed, 0 failed, 0 external requests.
- Permanent `scripts/run_release_gate.sh` groups passed in the accepted
  isolated environment. The wrapper now supports Linux/WSL Python, Node/npm,
  configurable browser ports, path propagation into Windows tools, and clean
  Windows browser-process teardown.

## Migration preflight

- Sole Alembic head/current revision:
  `20260912_0001_s10_5_communications`.
- `alembic check`: no new upgrade operations detected.
- Disposable schema preflight: passed.
- No migration was added or required.

## Exact Sprint 12R files changed

- `backend/app/api/endpoints/tenders.py`
- `backend/app/services/competitor_cache.py`
- `backend/app/services/tender_sources/base.py`
- `backend/app/workers/source_refresh_tasks.py`
- `backend/test_s12_competitor_section_restoration.py`
- `backend/test_s12r_competitor_passivity.py`
- `frontend/tests/release-hardening-browser.py`
- `scripts/run_release_gate.sh`
- `docs/S12_COMPETITOR_SECTION_RESTORATION.md`
- `docs/audits/s9_3/browser/` generated maintained-Chromium evidence

The pre-existing reviewed Sprint 11/Sprint 12 dirty working tree was preserved;
unrelated changes were not reset or rewritten.

## Remaining risks

- Existing rows without explicit historical keys or the new cache truthfully
  remain empty until a supported explicit source-refresh job runs after a
  future deployment.
- Public award-source availability and payload quality affect future cache
  population, but never Tender Details availability or latency.
- EBRD and GIZ have no live competitor-cache enrichment in 12R; they continue
  to use any canonical historical metadata already stored and otherwise show
  the truthful empty state.
- No production data was accessed, no migration was created, and no deployment
  or Compose rebuild was performed for Sprint 12R.
