# S1-6 report: integration, name QA, market sizing v2, targets, ledger previews, works/goods probe

Local only: nothing pushed or deployed, the shared `plasmaos` stack was not stopped, Docker was not pruned.
WSL was unavailable (Wsl/Service/0x8007274c), so the gate ran in capped one-off containers in `plasma_db`'s
network namespace (loopback PostgreSQL, a disposable 64 MiB Redis, disposable `plasma_s05b4b_*` databases). Ledger
work, previews and the works/goods probe used a disposable clone of the local database
(`plasma_s05b4b_s1int_local`, upgraded to the s1-int head); the shared `plasma_ai` database was not migrated.

## 0. Integration

`pilot/s1-int` = `pilot/s1-ledger` (59170be) + merge of `pilot/s1-outreach` (f280f83): no conflicts. The outreach
branch adds no migration, so the single Alembic head stays `20261012_0002_s1_product_analytics`; the prospect test
reads the head from the D3-04 test, which s1-ledger updated. Gate results: see the end of this report.

## 1. Firm-name QA

Details: [NAME_QA.md](NAME_QA.md). Joint-venture role markers are stripped before grouping (raw names unchanged);
public-body names are excluded from firm counts, PROJECT/AGENCY brand names are listed for review but counted (many
Uzbek firms carry "PROJECT" in their name; a deliberate deviation for the owner to confirm). OP00449976
"IRRIGATION PROJECT" is **as published** (bold name with its own World Bank supplier id under "Rejected Firm(s)"),
not a parser error. Merge candidates (top 50, never merged) are private: `private/s1/merge_candidates.csv`. The
re-ingest appended nothing (idempotent); consulting firms 666 → 664 region-wide, whole ledger 3,947 → 3,944.

## 2. Market sizing v2

[MARKET_SIZING_CENTRAL_ASIA.md](MARKET_SIZING_CENTRAL_ASIA.md) and [.csv](MARKET_SIZING_CENTRAL_ASIA.csv) (renamed
from the UZ/KZ v1, with "Changes since v1"). Every category, four countries plus a Central Asia total; sections
all categories, consulting, works, goods, non-consulting services.

- **Completeness**: per country × procurement group, the World Bank API's in-window notices were compared with the
  ledger: 0 missing in all 16 cells, no truncated pass (one extra Uzbekistan non-consulting notice in the ledger, at
  the window edge). Rows by country × group are in the document's first section.
- USD equivalents: one table, Central Bank of the Republic of Uzbekistan, 2026-10-09. 31 flagged source errors are
  left out of USD figures, among them two Uzbekistan works awards published as "USD 9,541,788,388" and "USD
  1,759,921,637" against UZS evaluated prices (USD 11.3 billion of phantom value if taken as published).
- Figures for the landing page (Uzbekistan, all categories, 24 months to 2026-10-10): 5,513 bids on 1,437
  contracts, of which 1,447 awarded, so 4,066 (73.8%, about 3 in 4) were rejected (2,997) or evaluated and not
  awarded (1,069). Consulting: 156 assignments, 96 of them Consultant Qualification Selection (62%). Median award,
  USD equivalent: consulting 104,449; works 222,565; goods 93,072; non-consulting 8,272; all categories 92,894.

## 3. Outreach targets (private, not committed)

`private/s1/outreach_targets.csv` (gitignored `private/`; copy in the session scratchpad): **2,551 firms**, every
category, ≥ 1 award or ≥ 2 bids across the four countries in 24 months, no individuals, no excluded names;
consulting targets first. `private/s1/consulting_targets.csv`: **442** consulting targets. One-page summary:
`private/s1/outreach_summary.md` (1,025 local Uzbek firms, 245 foreign firms active in Uzbekistan, 41 firms bidding
in two or more of the four countries). Public notice data only: no contact data, no web or LinkedIn lookups.

## 4. Ledger-backed previews

`seed_demo.py --from-ledger "<normalized name>" [--country X] [--keep-others] [--inline-analysis]`:

- References are the firm's **consulting awards only** (evaluated or rejected bids and other categories never
  become references): assignment title, client agency (`agency_name` on the notice), project name, country, contract
  value and currency (a flagged source error is not shown as a value), award date, notice id and source URL, each
  marked "From public records, unverified".
- REOI pick: an open, firm-level World Bank REOI with an OFFICIAL_NOTICE of at least 5,000 characters, ranked by a
  TF-IDF score of the words of the firm's awards in the REOI title (rarity over all open REOI titles × the number of
  the firm's assignment titles with the word; generic words such as "project", "management", "international" are
  ignored); the plan prints why. No match → a clear refusal naming the 5,000-character rule.
- Exclusive by default: the demo user's other active previews are archived before a new one is created
  (`--keep-others` opts out). The EOI cover and the draft status read **"Draft — not reviewed by your team"**
  (`draft_status` on the EOI request, set only by the seed; DOCX, PDF and the version card show it).

Three real firms from the consulting target list (names in the private list; screenshots of references, the EOI
criteria panel and requirements in `private/s1/previews/`):

| Firm | Awards used | REOI picked (why) | Criteria matched | Run time |
|---|---|---|---|---|
| Local Uzbek audit firm (5 consulting awards) | 5 | Lao PDR, financial and operational reform feasibility ("financial") | **1 of 6** | 131 s (analysis 79 s, review + EOI 47 s); 374 s wall incl. container and an untimed first ledger build |
| Foreign firm (Spain), spatial planning in Uzbekistan | 2 | Zanzibar spatial data infrastructure policy ("spatial") | **0 of 8** | 112.6 s end to end (ledger 3.3 s, analysis 87.4 s), 161 s wall |
| Regional firm (Uzbek, bids in Uzbekistan and Kyrgyz Republic) | 2 | OECS project audit ("audit") | **0 of 6** | 64.5 s end to end, 103 s wall |

All three analyses completed (READY_FOR_REVIEW) with a real Gemini run; EOI v1 DOCX and PDF were generated with the
not-reviewed cover. For the audit firm, audit REOIs ranked 2nd and 3rd: "financial" is rarer than "audit" in REOI
titles. `--tender-external world_bank:OP…` pins a better one. Low match counts are expected: one to five public
awards rarely cover an REOI's shortlisting criteria (years in business, regional experience, staff), and no award
is in the REOI's own sector and region.

## Works and goods today (probe, nothing built)

One real Uzbekistan Works notice (OP00454502, M41 highway reconstruction, Request for Bids, closed) and one Goods
notice (OP00473394, software licences, Request for Quotations, open), analysed for real on the clone:

- **Opportunities feed**: both are customer-visible (World Bank IFBs are listed with consulting REOIs; the
  category is a filter).
- **Pursuit analysis**: both completed. Works: 16 requirements + 1 submission note, 16 gaps — turnover (USD 46.6M
  average), liquid assets (USD 10.4M), similar contracts by value and physical quantities (35 km, 4 bridges,
  355,000 m²), bid security; coverage: 7 evidence missing, 8 needs interpretation, 1 partial. Goods: 2 requirements
  + 5 submission notes (the RFQ notice is 3,376 characters; the items and specifications are in the RFQ document).
- **Failures**: none in the code path. The works notice had **no OFFICIAL_NOTICE** until synced by hand (it was
  last refreshed before the official-notice backfill and is closed now).

Gaps before works/goods can be sold:

1. **Bidding documents are not ingested** (World Bank document policy is metadata only): qualification forms,
   specifications, BOQs and evaluation criteria live in the bidding document, not the notice. Goods analyses are
   thin without it.
2. **Firm records are consulting-shaped** (project references, experts and CVs). Works and goods qualify on
   audited turnover, liquid assets and credit lines, similar contracts by value and physical quantity, equipment,
   key personnel, manufacturer authorisation and delivery capacity: no fields, so most requirements stay "evidence
   missing" or "needs interpretation".
3. **The output is wrong for bids**: the EOI builder accepted the works notice (14 criteria). Works and goods need
   bid forms, qualification forms, bid securities and price schedules; the EOI should be hidden for non-REOI
   notices.
4. **Price**: works and goods are won on the lowest evaluated price. Plasma deliberately never suggests prices;
   there is no BOQ or price-schedule support beyond manual price entry.
5. **Notice backfill**: older notices can lack an OFFICIAL_NOTICE (as above), so analysis cannot start on them.
6. Not verified here: whether "Matches your profile" and the dashboard rank works and goods sensibly for a works
   contractor.

## Gate

`scripts/run_release_gate.sh` groups, run on `pilot/s1-int` (backend groups in a capped one-off container with a
disposable loopback database and Redis; frontend and browser groups on the Windows host):

| Group | Result |
|---|---|
| backend | first run 1,168 passed / 8 failed. 7 were backend tests reading frontend files the S1 routes moved (vault page path, Bid Preparation list) or the EOI contract (new `draft_status`); fixed in b0b2ce9. Re-run: **1,175 passed, 1 skipped**, 1 failed: `test_historical_migrations_are_untouched`, which hashes migration files and fails only on this Windows CRLF working copy; on the exact committed bytes (`git -c core.autocrlf=false archive`) the drift file passes **6/6** |
| security | **118 passed** |
| analysis | **50 passed** (+12 subtests) |
| connectors | **198 passed**, 1 skipped (+6 subtests) |
| migrations | heads, current, check, schema preflight: **PASS** (single head `20261012_0002_s1_product_analytics`) |
| performance | **PASS** (10,000 and 100,000-row scale checks) |
| frontend | npm ci, typecheck, lint, **406/406** static tests, RTL and literal audits, production build: **PASS** |
| browser | **214 passed, 0 failed** (Chromium; the Bid Preparation list surface and its pagination case were removed with the S1 redirect) |
| config-dependencies | **24 passed**, `pip check` clean; npm audit: production dependencies 0 vulnerabilities; 5 dev-only highs covered by the active exception `npm-dev-braces-chain` (until 2026-11-08), report-only as designed |

Focused S1-6 tests: `test_s1_6_ledger_qa.py` (4), `test_s1_6_ledger_preview.py` (2), `test_s1_prospect_seed.py`
(16) and the updated `test_s1_award_ledger.py`, all passing.

## Risks

- Real firm names appear in private files only (targets, merge candidates, previews). Previews of real firms are
  built from public, unverified records and live in organizations only the demo account can open; archive them
  after use.
- Name-QA tiers and the currency flags are judgment rules; both are listed for the owner and easy to change.
  Some flags are conservative (an award published as USD signed / UZS evaluated with the same amount is left out
  even when USD is likely right).
- USD figures use one date's rates; they size the market, they are not values at signing.
- The bulk review confirmation in previews is a seed step, not a human review; the EOI says so on the cover.
- The ledger and previews ran on a disposable clone; production needs the S1 migrations and a real ingest first.
