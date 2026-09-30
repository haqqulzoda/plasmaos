# D1-05b deadline time truth and D1-05c open-status truth

Branch `pilot/d1-04-freshness` (from `pilot/week1` 366a936). No stored value is migrated or
rewritten; every change is in how stored values are read.

## Problem

Every connector stores the deadline the source *published* as a wall-clock time and labels it
UTC (`strptime(...).replace(tzinfo=timezone.utc)` or `fromisoformat(...).replace(tzinfo=utc)`).
For most sources that wall time is not UTC, so a countdown or "open" test against the stored
value can be wrong by up to about 14 hours (UTC+14) in one direction and 12 hours (UTC-12) in
the other. Separately, customer surfaces showed the stored source `status` (OPEN) for tenders
whose deadline had already passed.

## Deadline time basis per connector

Recorded in `backend/app/services/source_registry.py` (`deadline_time_basis`,
`deadline_timezone`, `deadline_date_only_marker`).

| Source | Basis | Zone | Date-only marker | Evidence |
| --- | --- | --- | --- | --- |
| `world_bank` | SOURCE_LOCAL_UNSPECIFIED | — | 23:59:59.999999 | `tender_sources/world_bank.py` `parse_world_bank_deadline`: `submission_deadline_date` + `submission_deadline_time` carry no zone (borrower local time) and are combined with `tzinfo=timezone.utc`; a missing time becomes `time.max`. Local data: deadlines cluster at 10:00 (297), 14:00 (162), 17:00 (140), 16:00, 11:00, 15:00: business hours of many zones, not UTC. |
| `uzex` | EXPLICIT_TZ | Asia/Tashkent | — | `core/scraper.py` lot `end_date` → `datetime.fromisoformat(end_date_str).replace(tzinfo=timezone.utc)` (any offset discarded). Raw `submission_deadline` in `source_metadata_json` is naive, e.g. `2026-09-29T08:17:30`. The platform is etender.uzex.uz (Uzbekistan); Uzbekistan is UTC+5 all year (no DST since 1992). Confirmed: Asia/Tashkent. |
| `ebrd` | EXPLICIT_TZ | Europe/London | 00:00 | `tender_sources/ebrd.py` `_parse_uk_datetime`: the eCEPP "Closing Date" text says "UK Time"; the parser strips that label and stores the wall time as UTC (one hour late during BST). Date-only format `%d/%m/%Y` yields midnight. |
| `giz` | SOURCE_LOCAL_UNSPECIFIED | — | 00:00 | `tender_sources/giz.py` `_parse_giz_datetime`: `dd.mm.yyyy HH:MM Uhr` with no zone (a German portal, probably Europe/Berlin, but the source does not state it). Regional pages publish `Deadline: dd.mm.yyyy` (date only, parsed to midnight): 80 of 197 local GIZ deadlines are 00:00. |
| `adb` | DATE_ONLY | — | 00:00 | `tender_sources/adb.py` `_parse_date`: listing `deadline_text` such as `30 Sep 2026`; the time formats exist but carry no zone. ADB is hidden from customers (D1-04b). |

A row whose stored wall time equals the source's date-only marker is read as DATE_ONLY
(a real deadline at exactly that instant is not distinguishable and is read conservatively).

## Effective instant (countdown, days left, urgency, open/closed)

`backend/app/core/deadline_truth.py`, with the same rules in Python and in PostgreSQL
(`effective_deadline_sql`; parity is tested on PostgreSQL):

| Basis | Effective instant |
| --- | --- |
| UTC | the stored instant |
| EXPLICIT_TZ | the wall time in the source zone (`timezone(zone, wall)`) |
| SOURCE_LOCAL_UNSPECIFIED | the wall time at UTC+14: the earliest real instant it can be, so remaining time is never overstated |
| DATE_ONLY | the end of the published date in the source zone, or at UTC+14 when the zone is unknown |

Example: World Bank "2026-10-16 17:00" (borrower local) → effective 2026-10-16 03:00 UTC.

## Display

- API (tender list, details, Explorer, My Tenders, pursuit reads): `deadline` stays the
  stored value (sorting unchanged); new `deadline_time_basis`, `deadline_timezone`,
  `deadline_published_local`, `deadline_effective_at` (`source_deadline_*` on pursuits).
- Frontend (`frontend/lib/tenderTruth.ts`): the published wall time is formatted without
  conversion and labelled "local time (as published)" (en/ru/uz/ar), "Asia/Tashkent time (as
  published)", or "date as published"; never converted to the viewer's zone. Countdowns use
  `deadline_effective_at`.
- D1-03 notice header: `Deadline: 2026-10-16 17:00 local time (as published)` instead of
  `... 17:00 UTC`. This changes the notice text, so notice hashes change: analysis runs sealed
  on the old text show the existing "inputs changed" (stale) banner. Accepted.

## Open-status truth

`derived_status`: a stored OPEN or UNKNOWN tender whose effective deadline has passed is
CLOSED with `status_reason = DEADLINE_PASSED` ("Closed (deadline passed)"); stored CLOSED and
CANCELLED are unchanged; no deadline means the stored status. `actionable_tender_condition` (SQL)
and `is_tender_actionable` apply the same rule, so every customer surface agrees:

| Surface | Where |
| --- | --- |
| Explorer default view, `status`/`deadline_status` filters, counts | `_tender_lifecycle_condition` → `lifecycle_condition`; `apply_explorer_tender_filters` |
| Dashboard | Explorer + legacy `/tenders` list (same filters), frontend `isCurrentTender` → `isTenderOpen` |
| Recommended / For-you | Explorer `recommended` view (same filters); Hunter recommendation sweep uses `actionable_tender_condition` |
| My Tenders badges and `tender_status` filter | `services/my_tenders.py` (`truth_fields`, `lifecycle_condition`) |
| Tender Details status | `GET /tenders/{id}` (`_serialize_tender` → `apply_tender_truth`) |
| Notification destinations | notifications carry only `tender_id`; the destination is Tender Details |
| Bid/compliance start | `is_tender_actionable` (backend) and `isTenderActionable` (frontend) |

Stored `status` is never mutated by this change.

## Counts (local database, `Codex Verification LLC` view)

COUNTS_PLACEHOLDER
