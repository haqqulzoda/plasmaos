# S1-7 report: notice-country validation, market sizing v3, legal forms, Loom previews, Deploy 4 runbook

Local only: nothing pushed or deployed, the shared `plasmaos` stack was not stopped, Docker was not pruned. All
ledger work ran on the disposable clone `plasma_s05b4b_s1int_local`; the Deploy 4 rehearsal on a fresh disposable
copy of the production-shaped `plasma_ai` (`plasma_s05b4b_d4_rehearsal`); the shared `plasma_ai` was only read
(`pg_dump`). Commits on `pilot/s1-int`: 483c5c2 (steps 1-2), 2e7fa50 (steps 3-4), e83e6ef (lot-aware
duplicates), and the commit adding this report (no awardee names in the public tables, wording).

## 1. Notice-country validation and market sizing v3

Every notice's World Bank project id was resolved against the World Bank Projects API
(`https://search.worldbank.org/api/v2/projects?format=json&id=<P…>&rows=1`) through the existing project-enrichment
pipeline, so responses are cached in `projects` (country, raw provenance, enrichment time; refetched after 30 days).
Command: `python scripts/validate_award_ledger.py --confirm VALIDATE_AWARD_LEDGER` (`--report-only` reads the cache).
82 projects: 59 fetched, 17 already cached, 6 not returned (0 invalid).

| Flag | Notices | Treatment |
| --- | --- | --- |
| `PROJECT_COUNTRY_MISMATCH` (project of another specific country) | **0** | would be excluded |
| `FOREIGN_BIDDER_SECTION` | **9** (Uzbekistan 6, Tajikistan 2, Kyrgyz Republic 1) | excluded from every figure, kept in the ledger |
| `DUPLICATE_AWARD_NOTICE` (found during step 3) | **20** (Tajikistan 9, Kyrgyz Republic 7, Uzbekistan 4) | excluded from every figure, kept in the ledger |
| `PROJECT_NOT_RESOLVABLE` | **15** on 4 projects (P509395 ×9, P182037 ×3, P181913 ×2, P181922 ×1) | flagged, kept |

**The pattern.** No notice sits on another country's project: our query and parser attach notices to the right
country. The 9 suspects are genuine packages of real projects of the ledger country (5 of the 6 Uzbek ones under a
National market approach) whose **whole award section belongs to another country's procurement**: every bidder from
one foreign country, priced in that country's currency.

| Notice | Ledger country | Project (Projects API country) | Awarded firm | Currency | Bidders |
| --- | --- | --- | --- | --- | --- |
| OP00225513 | Tajikistan | P126130 (Tajikistan) | TOP SYSTEM | XOF | Benin |
| OP00311963 | Uzbekistan | P159544 (Uzbekistan) | NGE CONTRACTING | XOF | Sénégal |
| OP00335267 | Uzbekistan | P168233 (Uzbekistan) | SHIRAZ & FARAZ BUILDER'S CONSTRUCTION | PKR | Pakistan |
| OP00365890 | Tajikistan | P173977 (Tajikistan) | SAGE LITERARY HOUSE | GHS | Ghana |
| OP00381883 | Uzbekistan | P168233 (Uzbekistan) | NO MISS CONSTRUCTION PLC | ETB | Ethiopia (7 bidders, Fergana electricity package) |
| OP00402661 | Uzbekistan | P168233 (Uzbekistan) | LASMUG TOWERS NIG. LTD | NGN | Nigeria |
| OP00402824 | Uzbekistan | P158372 (Uzbekistan) | GLORY OFFICE SOLUTION | BDT | Bangladesh |
| OP00410304 | Kyrgyz Republic | P167428 (Kyrgyz Republic) | C, J. TRUST RESOURCES | NGN | Nigeria |
| OP00414058 | Uzbekistan | P162929 (Uzbekistan) | M/S S H ENTERPRISE | BDT | Bangladesh |

The 15 unresolvable notices are on projects the Projects API does not return (total 0 on v2 and v3: preparation-stage
or very new), each naming the ledger country in its own project name (e.g. P509395 "Dushanbe Sustainable
Urbanization"); nothing says they belong elsewhere, so they stay in. The Caribbean CAIHR award (OP00362961,
Uzbekistan) stays too: an international CQS, value flagged (UZS/USD label error), already out of USD figures.

**Duplicate award notices** (step 3 found Kreston's audit twice in its preview: OP00424867 and OP00425438, same
package reference, award date and USD 33,000). A notice is a duplicate when every award in it (package reference and
title, awarded firm, award date, published price) is published again in another notice; that notice (more awards,
else the newest id) is counted. The first rule (any shared award) wrongly took out multi-lot notices whose other lots
are awards of their own (e.g. OP00311294); fixed in e83e6ef.

### v3 headline figures (a–e), v2 → v3

v2 and v3 cover the same window (award notices 2024-10-10 to 2026-10-10). Full tables:
[MARKET_SIZING_CENTRAL_ASIA.md](MARKET_SIZING_CENTRAL_ASIA.md) ("Changes since v2" and the headline block at the top).

| Figure | v2 | v3 | Change |
|---|---|---|---|
| a. Uzbekistan, All categories: rejected / all bids | 2,997 / 5,513 (54.4%) | 2,989 / 5,492 (54.4%) | -8 rejected, -21 bids |
| a. Uzbekistan, Works: rejected / all bids | 1,770 / 2,842 (62.3%) | 1,765 / 2,832 (62.3%) | -5 rejected, -10 bids |
| a. Uzbekistan, Goods: rejected / all bids | 219 / 781 (28.0%) | 219 / 779 (28.1%) | — rejected, -2 bids |
| a. Uzbekistan, Consulting: rejected / all bids | 41 / 286 (14.3%) | 41 / 282 (14.5%) | — rejected, -4 bids |
| a. Uzbekistan, Non-consulting services: rejected / all bids | 967 / 1,604 (60.3%) | 964 / 1,599 (60.3%) | -3 rejected, -5 bids |
| b. Uzbekistan rejection reason #1 | Failure to meet minimum technical score (1,565) | Failure to meet minimum technical score (1,562) | -3 |
| b. Uzbekistan rejection reason #2 | Does not meet Eligibility Requirements (872) | Does not meet Eligibility Requirements (872) | — |
| b. Uzbekistan rejection reason #3 | Non Responsive (337) | Non Responsive (337) | — |
| c. CQS share of Uzbekistan consulting assignments | 96 / 156 (61.5%) | 94 / 153 (61.4%) | -2 CQS, -3 assignments |
| d. Median award, Uzbekistan, Consulting (USD) | 104,449 | 104,449 | — |
| d. Median award, Uzbekistan, Works (USD) | 222,565 | 222,565 | — |
| d. Median award, Uzbekistan, Goods (USD) | 93,072 | 93,072 | — |
| e. Uzbekistan — All categories | 1,857 firms (1,451 local / 396 foreign); 1 bid 940 · 2–4 610 · ≥5 307 | 1,838 firms (1,448 local / 380 foreign); 1 bid 921 · 2–4 610 · ≥5 307 | -19 firms |
| e. Uzbekistan — Consulting | 251 firms (108 local / 143 foreign); 1 bid 190 · 2–4 57 · ≥5 4 | 250 firms (108 local / 142 foreign); 1 bid 189 · 2–4 57 · ≥5 4 | -1 firms |
| e. Kyrgyz Republic — All categories | 1,084 firms (954 local / 128 foreign); 1 bid 630 · 2–4 325 · ≥5 129 | 1,078 firms (952 local / 124 foreign); 1 bid 624 · 2–4 325 · ≥5 129 | -6 firms |
| e. Kyrgyz Republic — Consulting | 126 firms (71 local / 55 foreign); 1 bid 96 · 2–4 22 · ≥5 8 | 126 firms (71 local / 55 foreign); 1 bid 96 · 2–4 22 · ≥5 8 | — firms |

Firms (e): "local" = published country is the ledger country; a firm without a published country is in neither.

## 2. Legal forms in words (normalizer)

Uzbek, Russian and English legal forms written in words, in Latin and Cyrillic (Cyrillic names are transliterated
first): MAS'ULIYATI CHEKLANGAN JAMIYATI / KORXONASI, AKSIYADORLIK JAMIYATI, XUSUSIY / OILAVIY / QO'SHMA KORXONA,
OBSHCHESTVO S OGRANICHENNOY OTVETSTVENNOSTYU, TOVARISHCHESTVO S OGRANICHENNOY OTVETSTVENNOSTYU, (OTKRYTOE /
ZAKRYTOE / PUBLICHNOE / CHASTNOE) AKTSIONERNOE OBSHCHESTVO, CHASTNOE PREDPRIYATIE, INDIVIDUALNYY PREDPRINIMATEL,
LIMITED LIABILITY COMPANY / PARTNERSHIP, (CLOSED / OPEN / PRIVATE / PUBLIC) JOINT STOCK COMPANY, PRIVATE ENTERPRISE,
SOLE PROPRIETOR(SHIP); abbreviations MKK, CHP, PAO added. Short words that are also name words (I, OK, AK, AJ, MAS,
VA, TOV…) are deliberately **not** stripped (I-TECH, OK STROY, AKSIYA GROUP stay intact).

Re-ingest 2026-10-12 (idempotent): 3,329 notices seen, 3,326 unchanged, 3 Tajik goods notices re-published with
changed text (OP00473418/21/22, version 2 each, 9 rows); reads use the newest version.

| | Before (v2) | After |
| --- | --- | --- |
| Distinct firms, whole ledger | 3,925 | 3,915 (−10) |
| Consulting firms, Central Asia | 663 | 663 |
| Merge candidates resolved | — | 4 pairs now one firm: O'ZELEKTROAPPARAT-ELECTROSHIELD, BUXORO MAXSUS SUV QURILISH, ASPMK-519, 2-SON MKK |
| Names in Cyrillic | — | 22 rows, now grouped with their Latin spellings |
| Outreach targets / consulting targets (private) | 2,537 / 441 (after validation and the normalizer) | **2,533 / 441** (plus duplicate notices) |

Details and examples: [NAME_QA.md](NAME_QA.md) (S1-7 section). The private lists are regenerated in
`private/s1/` (not committed).

## 3. Ledger previews for a Loom

`seed_demo.py --from-ledger "<normalized name>"`: references from the firm's ledger **consulting awards** only, each
described field by field from the award notice (assignment title, project, client agency, project sector tags,
selection method, award year, published value, notice id; nothing inferred). Scope: REOIs in the firm's own bid
countries first, then the rest of Central Asia; outside Central Asia only with `--allow-global` (and only REOIs
sharing a word with the firm's awards). `--candidates N` (default 3) analyses the top N, keeps the one with the most
criteria matched (ties: higher share, then rank), archives the others, prints the table. Refusals now print
`REFUSED: …` (they were tracebacks in prospect mode: the script and `prospect.py` saw two copies of the module).

Firms: the same three as S1-6 (KRESTON TASHKENT, IDOM, ENCOMPASS CONSULTING) and the top two local Uzbek consulting
firms of `consulting_targets.csv` **by consulting bids** (ERNST & YOUNG ADVISORY JV 9 bids / 6 awards, TSIAR-FINANS
7 / 4). The literal first two rows (sorted by awards across all categories) have one consulting bid each, too
little for a preview.

**No Central Asian REOI is open for any of the five firms** (local data, 2026-10-12; closing ≥ 7 days after today,
firm-level, official notice ≥ 5,000 characters). Every `--dry-run` without `--allow-global` printed:

> REFUSED: no Central Asian World Bank REOI is open for KRESTON TASHKENT (firm-level, closing on or after 2026-10-12
> \+ 7 days, official notice of at least 5,000 characters; own bid countries ['Uzbekistan'], then the rest of Central
> Asia). No fallback: pin a tender with --tender-external world_bank:OP..., or widen with --allow-global

(same for the other four; ENCOMPASS's own bid countries are Kyrgyz Republic and Uzbekistan). After a fresh World Bank
refresh the open Central Asian REOIs were three Tajik Individual Consultant Selections (not firm-level) and one
regional CQS with a 3,766-character notice.

So the runs below are **explicitly global** (`--allow-global --candidates 3 --inline-analysis`), labelled as such;
none is a fallback. AI cost from `ai_call_costs` (gemini-3.8-flash for every call, USD 0.75 / 3.75 per million in
both price-table versions used during the runs):

| Firm | Tender | Country | Criteria matched / total | AI cost USD | Seconds | Kept |
| --- | --- | --- | --- | --- | --- | --- |
| KRESTON TASHKENT | OP00472082 | Lao PDR | 1 / 6 | 0.0486 | 40.4 | |
| | OP00473712 | Caribbean (OECS) | 0 / 6 | 0.0759 | 46.6 | |
| | OP00470252 | Burundi | 1 / 2 | 0.0512 | 36.4 | **yes** |
| IDOM | OP00471770 | Tanzania | 0 / 8 | 0.0352 | 37.6 | |
| | OP00471767 | Tanzania | 0 / 8 | 0.0329 | 22.5 | |
| | OP00472613 | Eastern and Southern Africa | 1 / 4 | 0.0338 | 25.9 | **yes** |
| ENCOMPASS CONSULTING | OP00470020 | Türkiye | 0 / 5 | 0.0405 | 38.4 | |
| | OP00474216 | Pakistan | 1 / 5 | 0.0386 | 33.8 | **yes** |
| | OP00473712 | Caribbean (OECS) | 0 / 6 | 0.0758 | 46.0 | |
| ERNST & YOUNG ADVISORY JV | OP00472082 | Lao PDR | 1 / 6 | 0.0517 | 43.3 | |
| | OP00471770 | Tanzania | 1 / 8 | 0.0371 | 32.5 | |
| | OP00473461 | Western and Central Africa | **5 / 7** | 0.0877 | 60.4 | **yes** |
| TSIAR-FINANS | OP00473712 | Caribbean (OECS) | 0 / 6 | 0.0783 | 58.3 | |
| | OP00470252 | Burundi | 1 / 2 | 0.0558 | 42.5 | |
| | OP00472292 | DR Congo | 2 / 6 | 0.0782 | 68.5 | **yes** |

| Firm | Run time (best of 3, wall) | AI calls | AI cost USD |
| --- | --- | --- | --- |
| KRESTON TASHKENT | 152 s (128.8 s in the script) | 15 | 0.1757 |
| IDOM | 120 s (92.0 s) | 8 | 0.1019 |
| ENCOMPASS CONSULTING | 154 s (128.9 s) | 8 | 0.1550 |
| ERNST & YOUNG ADVISORY JV | 164 s (141.6 s) | 18 | 0.1765 |
| TSIAR-FINANS | 199 s (174.6 s) | 14 | 0.2123 |
| **All five** | **13.1 min** | 63 | **0.82** |

Kreston was re-created afterwards on its kept tender with the duplicate fix (`--tender-external
world_bank:OP00470252 --candidates 1`): 70 s wall (analysis 30 s, review and EOI 18 s), 4 references (was 5 with the
duplicate). Screenshots (references, Requirements, EOI with the "Draft — not reviewed by your team" badge, 1440 px):
`private/s1/previews/<firm>-{references,requirements,eoi}-1440.png` (not committed).

**What this means for the Loom.** Only Ernst & Young's preview is strong (5 of 7 criteria on an institutional
capacity-building REOI). The others match 1–2 criteria on REOIs far from the firm's market (Burundi, Pakistan,
Africa). Recommendation: record the Loom on Ernst & Young, or wait for a Central Asian audit/advisory REOI and pin it
(the plan lists candidates the day one opens).

## 4. Deploy 4 runbook and rehearsal

[docs/ops/DEPLOY_4_RUNBOOK.md](../../ops/DEPLOY_4_RUNBOOK.md). **The D4 brief you mention was not in this
conversation, the repository or any branch**, so the runbook follows the Deploy 3 runbook's proven structure
(same pre-stop gate, `--no-deps` rule, backup, two rollbacks) plus everything S1-7 asked: ingestion of all
categories and four countries with expected counts per country × group, the validation step, the owner section
"Create Loom previews on production" (plan, best of 3, `--tender-external` pinning, `--allow-global`, list, archive,
and the warning that each preview must be archived after recording), and the AI price-table task. Please send the D4
brief if it asked for more; the image bundle values (SHA, bytes, sha256) are placeholders until the release images
are built from the final commit.

**AI price table**: `backend/app/core/ai_pricing.py` now holds only prices from Google's official page
(https://ai.google.dev/gemini-api/docs/pricing, "Last updated 2026-10-09 UTC", read 2026-10-12), version
`gemini-api-pricing-2026-10-09`. Corrections: gemini-3.1-pro-preview 2.50 / 15.00 → **2.00 / 12.00** (≤ 200k-token
prompts); gemini-3.7-flash (an analysis fallback) is **not on the page**, so it now gets no estimate rather than a
guess; 3.6-flash, 3-flash-preview and 2.5-flash added. gemini-3.8-flash 0.75 / 3.75 is introductory until 2026-12-31
(1.50 / 7.50 from 2027-01-01): the runbook tells the owner to set `AI_PRICE_TABLE_JSON` before then.

**Rehearsal** (2026-10-12, a fresh copy of the production-shaped `plasma_ai` at the Deploy 3 head, the release code,
one-off capped containers; times include each container's start):

| Step | Result |
| --- | --- |
| copy of `plasma_ai` (265 MB, `pg_dump` / `pg_restore`) | 42 s |
| `alembic current` before | `20261011_0001_r3_organization_record_events` |
| two migrations | **5 s**, `20261012_0002_s1_product_analytics (head)` |
| first ingest, all categories, 4 countries (24 months from 2024-10-12) | **94 s**, 53 pages, 3,329 notices, 11,283 bidder rows, 0 undated, no truncated pass, peak ~80 MiB |
| second ingest | 82 s, 0 created, 3,329 unchanged, 0 rows (idempotent) |
| validation | 68 s; 82 projects (59 fetched, 17 cached, 6 not returned); flags as in section 1 |
| Loom: plan in Central Asia | 8 s, `REFUSED` (no Central Asian REOI) |
| Loom: plan with `--allow-global` | 8 s, picked OP00472082 |
| Loom: pinned preview (`--candidates 1`, inline analysis) | 69 s, peak ~150 MiB |
| list / archive / list | 5 s / 5 s / 6 s; the preview shows `archived: true`, demo user revoked, records kept |
| expected downtime (step 9 → 11) | ~75 s (Deploy 3's stop 12 s + switch 8 s + start 48 s, plus 5 s of migrations) |

Expected ledger counts per country × group are in the runbook's step 15 (notices / bidder rows, e.g. Uzbekistan
Works 571 / 2,989, Kyrgyz Goods 571 / 1,654). Not rehearsed here: the image build, transfer and the app cut-over
(steps 6-11), which need the release images and would stop the shared stack; Deploy 3 proved those steps.

## Gate

Gate on **e83e6ef**, from an LF export (`git -c core.autocrlf=false archive`), backend groups in capped one-off
containers in `plasma_db`'s network namespace (loopback PostgreSQL, disposable `plasma_s05b4b_*` database and Redis):

| Group | Result |
| --- | --- |
| backend | **1,191 passed, 1 skipped, 0 failed**, in 11 batches of test files (a fresh pytest process each: 353 + 73 + 184 + 94 + 62 + 80 + 79 + 56 + 80 + 66 + 64), incl. the migration-hash test on LF bytes |
| security | **117 of 118 passed**; not run: `test_upload_rejects_bad_inputs_and_cleans_files[large.pdf…]` (builds a 20 MB body several times in memory; see below). The shared-Redis test ran with a disposable Redis: 6/6 runtime tests |
| analysis | **50 passed** (+12 subtests) |
| connectors | **198 passed**, 1 skipped (+6 subtests) |
| migrations | heads, current, check, schema preflight: **PASS** |
| performance | **PASS** |
| config-dependencies | **24 passed**, `pip check` clean; `npm audit --omit=dev`: 0 vulnerabilities |
| frontend, browser | not re-run: no file outside `backend/` changed since the S1-6 gate (406/406 static tests, build, 214 browser cases) |

Focused tests after e83e6ef (the last commit only removes awardee names from the public tables and rewords the
duplicate rule): `test_s1_7_ledger_validation.py`, `test_s1_6_ledger_qa.py`, `test_s1_award_ledger.py` **26
passed**; earlier `test_s1_7_loom_previews.py` (2), `test_s1_6_ledger_preview.py`, `test_s1_prospect_seed.py`,
`test_s1_product_analytics.py`, `test_d3_04_demo_seed.py` all passing.

**Host memory (incident, no harm).** Docker Desktop's VM has 3.68 GiB; besides the shared stack it now also runs a
`plasma_staging_*` stack (~1.1 GiB, started on its own after the 12:29 reboot; not mine, left alone). The single-run
backend group (1.2 GB cap) and the 20 MB upload case pushed the VM to its limit twice: the Docker API returned HTTP
500 for a few minutes and the shared backend's `/health` stopped answering. Both times I killed my own gate container,
and `/health` was back at 200 at once; every shared-stack container shows `oom=false restarts=0` and its original
start time. The remaining runs used a 700 MB cap, smaller batches and a watchdog that kills the gate container if the
shared backend fails two health checks. The large-upload case passed in the S1-6 gate, and no upload code changed
since (S1-7 touched only the ledger, validation and pricing modules under `backend/app`). It needs a quieter host
(staging stack stopped, or WSL with more memory) to re-run.

## Risks

- **No Central Asian REOI for the target firms today**: the Loom previews are global or pinned. The Loom message
  must not imply the firm's own market; the runbook makes `--allow-global` explicit.
- **Weak matches**: 4 of 5 kept previews match 1–2 criteria. Recording a weak preview may undersell the product.
- **Duplicate detection** keys on the published package reference, title, firm, date and price; a re-publication
  that changes any of these is not caught, and a genuinely repeated identical award would be merged. 20 found.
- **Unresolvable projects** (15 notices) are kept on trust in the notice's own project name; the Projects API may
  return them later (the validation re-checks cached projects after 30 days).
- **Prices**: the Flash introductory price ends 2026-12-31; until the owner sets `AI_PRICE_TABLE_JSON`, 2027 costs will
  be underestimated by half. gemini-3.7-flash fallback calls show no cost.
- **History**: local commits since 78db7bc (none pushed) name a few apparent natural persons among awardees in the
  market-sizing tables (flagged source errors, unresolvable projects, duplicates: e.g. a Tajik individual consulting
  award, sole proprietors on goods RFQs). The final document names awardees only in the foreign-bidder table
  (companies). If the history matters, squash before pushing.
- **D4 brief missing**: the runbook may lack items that brief required.
- The ledger is not refreshed automatically (no Beat task); re-running ingest + validation is manual.
