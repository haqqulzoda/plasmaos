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

Measured on the local stack (2026-09-30), same instant, customer-visible tenders:

| Source | Stored status OPEN | Shown as open (deadline-derived) |
| --- | --- | --- |
| World Bank | 568 | 288 |
| UzEx (enterprise) | 230 | 18 |
| EBRD | 91 | 46 |
| GIZ (visible) | 95 | 4 |
| ADB | hidden (35 tenders, 0 open) | hidden |
| **Explorer default (open)** | **984** | **356** |

Explorer `status=all` went from 2019 to 1984: the 35 ADB tenders are no longer customer visible.
The Explorer "before" (984) was read from the running pilot/week1 API on 2026-09-29 and matches
the stored-OPEN count above.

After one scheduled refresh per source (the dispatcher run), the derived open counts were
World Bank 563, UzEx 50, EBRD 71, GIZ 4 (688 in total; 1058 stored OPEN): new World Bank and
UzEx tenders arrived, and the derived rule still hides the ones already past their deadline.

Notice backfill after the header change: 577 notices updated (World Bank 564, GIZ 13), 1 EBRD
notice unchanged (no deadline line), 0 created; a re-run updates 0. The two Step 0 REOI runs
sealed on the old notice text now report `inputs_changed: true`.

## Lenient open/closed truth (integration fix 3a, pilot/week1)

The UTC+14 rule above never overstates the time left, but it also closed World Bank and GIZ
tenders up to 26 hours before they really closed (their deadlines carry no zone). Since then
every deadline has **two** instants (`deadline_effective_at`, `deadline_closes_at`):

| Case | Countdown / urgency (`effective_at`) | Open/closed status (`closes_at`) | Basis label |
| --- | --- | --- | --- |
| Zone known (UTC, EXPLICIT_TZ) | the instant | the same instant | unchanged |
| No source zone, country known | wall time in the capital zone of the tender's country | the same instant | `COUNTRY_INFERRED` + zone ("Asia/Ulaanbaatar time (inferred from country)") |
| No source zone, no country zone (regions such as "Central Asia", empty country) | wall time at UTC+14 | wall time at UTC−12 | `SOURCE_LOCAL_UNSPECIFIED` |
| DATE_ONLY | end of the date in the source zone, else the country zone, else UTC+14 | … else UTC−12 | `DATE_ONLY` |

Between the two instants the tender stays **open** with `status_reason =
DEADLINE_VERIFY_ON_SOURCE` ("Closing — verify on source", en/ru/uz/ar); only after
`closes_at` is it "Closed (deadline passed)". Open lists, counts, filters, "Matches your
profile" and bid/workspace actions follow `closes_at`; countdowns, "days left" chips and
urgency follow `effective_at`.

Country → zone: `backend/app/core/country_timezones.py`, generated from tzdata 2026c
(`iso3166.tab`, `zone.tab`): 246 countries, 304 spellings including the World Bank/GIZ/EBRD
variants ("Kyrgyz Republic", "Congo, Democratic Republic of", "Gambia, The", "Turkiye",
"West Bank and Gaza", "Kosovo", …). Multi-zone countries use the capital's zone (US
New York, Russia Moscow, Brazil São Paulo, Kazakhstan Almaty, Indonesia Jakarta, Mexico
Mexico City, …). PostgreSQL uses the same table as one constant JSONB lookup on
`lower(btrim(country))`; Python/SQL parity is tested on a source × country × time matrix
(`backend/test_int_3a_lenient_deadline_truth.py`). The official notice header deliberately
does not use the country (its text is part of sealed analysis inputs), so notice hashes do
not change.

Counts (local database, customer-visible tenders, both rules evaluated back to back at
2026-09-30 17:30 UTC):

| Source | Open, strict (UTC+14) | Open, lenient | of which "verify on source" |
| --- | --- | --- | --- |
| World Bank | 562 | 571 | 5 |
| GIZ | 4 | 5 | 1 |
| UzEx | 48 | 48 | 0 |
| EBRD | 70 | 70 | 0 |
| **Total** | **684** | **694** | **6** |

The other 4 newly open tenders are closed at their country's capital time rather than at
UTC+14.
