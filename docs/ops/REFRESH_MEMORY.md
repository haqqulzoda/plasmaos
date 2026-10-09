# World Bank refresh memory (R3)

R1 measured the World Bank refresh at ~560 MiB in `celery_worker`. R3 found what held the full
result set and made the refresh hold one page (or one bounded batch) at a time. Same persisted
results; no connector semantic change; the official-notice hook (`sync_official_notices` inside
`persist_tender_batch`) unchanged.

## What held everything

1. **The sync** (`sync_world_bank_tenders`): the whole listing (`list_opportunities()`), then every
   `NormalizedTender` and its documents, then `persist_tender_batch` over all rows, and every ORM
   `Tender`/`TenderDocument`/`Project` it touched stayed in the session until the single commit.
2. **The competitor cache** (`_refresh_source_competitor_cache`, the same task, after the sync):
   loaded up to 2,000 visible World Bank tenders at once, each with `source_metadata_json`
   (the notice text: 62 MB of JSON for 2,080 tenders locally), plus every award lookup result.

## Change

- `WorldBankTenderSource.iter_pages()` yields one listing page at a time (same requests, dedup,
  truncation and repeated-page rules); `list_opportunities()` is now a thin wrapper over it.
- The sync normalizes, persists (`persist_tender_batch` per page, hook included), links projects
  and documents page by page, then flushes and detaches that page's rows
  (`_release_persisted_source_rows`). One transaction and one commit, as before; a listing failure
  rolls back everything, as before; the response lists errors in the old order.
- The competitor cache walks the same newest-first target list in windows of 200 keeping only ids
  and group keys, then per batch of 32 groups loads only each group's first target for the lookup
  and applies results to the group's targets 200 at a time. Same targets, groups, lookups, single
  commit.

## Measurements

Recorded fixture: today's World Bank listing (7 pages, 616 notices, 10.1 MB JSON), served in place
of the API; competitor award lookups recorded once and replayed (deterministic). Process in a
one-off container of the production backend image, on a copy of the local database
(production-shaped, 2,080 World Bank tenders) or an empty database at head; RSS sampled every
20 ms; tracemalloc for attribution.

| Run | Old peak RSS | New peak RSS | Persisted results |
| --- | --- | --- | --- |
| Steady (local copy: 4 created, 611 unchanged) | 320-330 MiB (4 runs) | **201-207 MiB** (2 runs) | 77/77 tables identical |
| Cold (empty schema: 615 created, 295 projects) | 301-328 MiB (3 runs) | **226 MiB** (2 runs) | identical except 80 `projects.enrichment_status`/`enrichment_last_attempted_at` values, which also differ between two runs of the old code (the enrichment claim orders same-transaction projects by random UUID) |
| Process after imports (baseline) | 177-183 MiB | 180-184 MiB | |

Phase view (steady, old → new): listing +12 MiB → streamed; persist +54 MiB → +20 MiB overall
for the sync; competitor cache +85 MiB → +4 MiB. Target was < 250 MiB: met.

Real Celery worker container (production image, `--concurrency=2`, 768m limit, live World Bank
and award APIs, cgroup `memory.peak`, page cache included):

| Container | Idle | Peak |
| --- | --- | --- |
| Old code, World Bank refresh | 275 MiB | **591 MiB** (reproduces R1's ~560) |
| New code, World Bank refresh | 290 MiB | **406 MiB** |
| New code, World Bank + UzEx refresh on the two pool children at once | 296 MiB | **454 MiB** |

**4gb profile: `celery_worker` stays 768m.** 454 MiB with ≥ 40 % headroom needs ≥ 757 MiB; the
next 32 MiB step is 768m. (704m would cover the World Bank refresh alone, 406 MiB, but not two
refreshes on the two children.)

Regression test: `backend/test_r3_refresh_memory.py` runs the real sync and competitor cache
against a disposable PostgreSQL database with synthetic pages (24 KB of notice text per row) at 2
and 8 pages; the traced peak must not grow with the listing (measured: 25.6 MiB at 2 pages,
24.2 MiB at 8) and must stay below 64 MiB.
