# P2 report: partner finder

Branch `pilot/p2-partner-finder` on `pilot/p1-pilot-readiness` (worktree `D:\projects\plasmaos-p2`).
Local only: nothing pushed or deployed. One additive migration (`20261023_0001_p2_partner_finder`).

When an analysis shows a requirement the firm cannot evidence alone, the Team tab now suggests firms that
won similar development-bank contracts (public award records, labelled unverified), lets a member ask Plasma
for an introduction (or ask Plasma to source a key expert), and lets an accepted partner join a team
scenario as a prospective JV member. The Plasma team works the requests on `/admin/partner-requests`.

## 1. What was built

| Part | Where |
| --- | --- |
| Gap features, ranking, requests, queue, prospective members | `backend/app/services/partner_finder.py` |
| Tables: `partner_requests`, `partner_request_events`, `team_scenario_prospective_members`; alert kind `PARTNER_REQUEST` | `app/models/partner_finder.py`, `alembic/versions/20261023_0001_p2_partner_finder.py` |
| API (customer) | `GET /pursuits/{id}/partner-finder`, `GET …/partner-suggestions`, `GET …/expert-suggestions`, `GET/POST …/partner-requests`, `POST/DELETE …/team-scenarios/{sid}/prospective-members` |
| API (operators and admins) | `GET /admin/partner-requests[?status=]`, `POST /admin/partner-requests/{id}/status` |
| Audit | `PARTNER_REQUEST_CREATED`, `PARTNER_REQUEST_STATUS_CHANGED` in `admin_activity_events` (also listed on `/admin/audit`) |
| Team alert | `PARTNER_REQUEST` admin alert: Telegram when configured, else e-mail to `PLASMA_ADMIN_EMAILS` (existing P1 delivery) |
| Team tab | `frontend/components/pursuits/PursuitPartnerFinder.tsx`, prospective members in `PursuitTeam.tsx` |
| Admin queue | `frontend/app/admin/partner-requests/page.tsx` (nav: "Partner requests") |
| Strings | `messages/{en,ru,uz,ar}/pursuits.json` → `team.partnerFinder`, `team.scenarios.prospective` |

**Which gaps.** The latest completed analysis's open gaps (GAP, PARTIAL, EVIDENCE_MISSING, NEEDS_INTERPRETATION)
of three kinds: an explicit joint-venture rule (`PARTNER_FIRM`), a local-presence requirement, or an experience
requirement (the D2-01 rule). The analyzer marks a gap `PARTNER_FIRM` only when the notice spells out that
members may combine experience, so most "not enough similar contracts" gaps arrive as `COMPANY_EVIDENCE`; leaving
them out would leave the finder empty on most tenders. For those the UI says: *check the notice's
joint-venture rules: a partner's experience counts only where the notice lets members combine experience.*
The finder does not require the gap to be reviewed (it states nothing about the customer's firm); the existing
library search (W5) still does. Key-expert gaps get experts instead of firms (section 3).

**Statuses.** requested → contacted → accepted | declined → introduced (accepted may also end declined).
Every change appends an event the requesting organization reads on its Team tab, with the team's message,
and an audit event (actor, previous and new status, reason). Duplicate requests (same Gap and firm) return
the first request; the database enforces it.

**Nothing is sent to the firm.** The ledger holds no contact data, no new column can hold it (the migration
test checks the column names), the API returns public notice fields only, and the only outbound message is the
alert to the Plasma team. The admin page says so; the request form says so.

**Team scenario.** Only an INTRODUCTION request that is ACCEPTED or INTRODUCED can be added, from the scenario
card ("Add a partner who accepted"). It shows as "Not yet confirmed", lists the gaps it would close (the gaps of
the latest revision that its accepted requests target, for the same firm across the pursuit), adds "With
prospective members N / M" next to the covered count, and marks each open gap "would close if confirmed: firm".
Sealed revisions and their assessment never change: a prospective member is not evidence.

## 2. Ranking method (`p2-award-ledger-v2`)

Deterministic for the same ledger and the same Gap (no model call).

1. **Gap features.** Assignment words: the requirement text and quote, the missing contribution and the tender
   title (without "Procurement of", "Consulting services for"…), as D2-01 word stems, minus procurement filler
   (a stop list built from the 337 gaps of the preview analyses) and country names. Sector tags: the World
   Bank sectors of the tender and of its project's award notices. Country and procurement category: the tender's
   (Consultant Services when unknown). Presence: local ("local presence", "registered in", "местный офис",
   "mahalliy"…) or foreign ("international firm", "иностранн…") or any.
2. **Candidates.** Award-ledger rows with status AWARDED only, firm rows of the latest snapshot of each notice,
   notices that pass the ledger's country validation. Left out: individual consultants (ICS or "Individual
   Consultant"), names flagged as a public body or project (both tiers), people recorded as a firm (initials,
   two or three name words with a surname/patronymic ending, or an award titled as a position: "Procurement
   Specialist", "Project Assistants", "lead … consultant"), UN agencies, and the requester's own firm and
   organization name. A joint-venture award counts for each member.
3. **Similar award.** Two shared domain words; or a domain word and a shared project sector tag; or one domain
   word found in at most 1% of the ledger's awards. Activity words ("design", "training", "assessment",
   "project"…) only add weight. A longer award word that ends with a gap word matches ("reinsurance" for
   "insurance"). When both projects carry sector tags and share none, two domain words including a rare one are
   needed, and the match is never strong. Relevance = Σ IDF(domain words) + ½ Σ IDF(activity words) + 1.5 per
   shared sector (max 2).
4. **Firm order.** (a) presence the gap needs first (local or foreign firms), (b) a similar award in the gap's
   procurement category (consulting first), (c) strong before moderate (strong = two domain words, or a domain
   word and a sector), (d) a similar award in the gap's country, (e) best award relevance, (f) latest similar
   award, (g) number of similar awards, (h) name. Top 10, each with up to 5 matching awards (title, lender,
   country, year, notice link), the words and sectors it matched on, and "From public award records, unverified".

Tuning on real data (the 2026-10-22 preview database, 4,501 award rows / 4,217 awards, 214 pursuits): v1 let one
common word through, so every gap filled 10 places with weak matches and people appeared as firms. v2 adds the
rarity rule, the sector-conflict rule, the person and agency filter and the stop list above. Latency: median
0.9 s per pursuit (overview), about 0.8 s per gap; the ledger read is cached per ledger state for 15 minutes.

## 3. Expert gaps

`GET …/expert-suggestions` ranks the organization's own experts and the shared network's (consented) experts
with the existing W5 expert evaluation, read-only, for any key-expert gap (the W5 search run still needs a
reviewed gap). Below the list: "Ask Plasma to source an expert" (same request queue, kind `EXPERT_SOURCING`).

## 4. Demo: three firms, real gaps from the Loom previews

Run on `plasma_s05b4b_p2_demo`, a copy of the Loom preview database `plasma_s05b4b_s1int_local` upgraded with
P1 + P2 (the original was not touched), this branch's backend and frontend on 127.0.0.1:8100/3100, signed in as
the preview recording account. **The team's statuses and messages in the demo were entered by me as a local ops
user to show the flow: no firm was contacted.** No alert was delivered (no worker ran) and no e-mail was created.

### Ultra Group (Uzbekistan) — OP00470797, ESG report verification

Gap (JV rule): "The firm must carry out activities in audit, independent assurance, ESG, sustainable development
and/or non-financial reporting, with at least 5 years of relevant professional experience."

| # | Firm | Country | Match | Similar awards | Best matching award |
|---|---|---|---|---|---|
| 1 | PKF MAK ALYANS LLC | Uzbekistan (local) | strong | 1 | Financial audit and Incentives program verification services ([OP00452014](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00452014), 2026) |
| 2 | ERNST & YOUNG ADVISORY JV | Uzbekistan (local) | strong | 4 | ESG diagnostics, roadmap, 2024 sustainability report ([OP00426155](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00426155), 2026) |
| 3 | SMART CONSULTING | Uzbekistan (local) | strong | 1 | Independent Verification Agent (IVA) ([OP00452414](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00452414), 2026) |
| 4 | KRESTON TASHKENT | Uzbekistan (local) | strong | 2 | Audit of the project financial statements, electricity sector transformation ([OP00425438](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00425438), 2026) |
| 5 | TSIAR-FINANS | Uzbekistan (local) | strong | 1 | Project Financial Audit ([OP00446949](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00446949), 2026) |

Requested an introduction to PKF Mak Alyans → contacted → accepted; added to the scenario "Ultra Group lead +
PKF Mak Alyans (prospective)": not yet confirmed, would close that gap (with prospective members 1 / 14).

### AC Consulting (Kyrgyz Republic) — OP00464583, insurance claims management

Gap (experience): "…at least two (2) similar projects… including analysis of insurance claims settlement processes
and… methodologies for damage assessment and determination of insurance compensation payments."

| # | Firm | Country | Match | Similar awards | Best matching award |
|---|---|---|---|---|---|
| 1 | WILLIS TOWERS WATSON | Singapore (foreign) | strong | 1 | Development of the reinsurance program ([OP00460929](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00460929), 2026) |
| 2 | SELAT FOR BUSINESS SOLUTIONS | Saudi Arabia (foreign) | moderate | 3 | Strengthening the capacity of GAHC (claims, compensation, insurance) ([OP00377391](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00377391), 2025) |
| 3 | DELOITTE & TOUCHE M.E. | West Bank and Gaza (foreign) | moderate | 1 | Independent Verification Agent for outcomes payments claims ([OP00328735](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00328735), 2024) |

Five suggestions only, none from the Kyrgyz Republic: no Kyrgyz firm in the ledger won an insurance-claims award.
Requested Willis Towers Watson → contacted.

### Global Advisors (Uzbekistan) — OP00465299, social-work CPD and supervision system

Gap (experience): "Must have at least ten (10) years of institutional experience in social work, social
protection, capacity development, social services, or related fields."

| # | Firm | Country | Match | Similar awards | Best matching award |
|---|---|---|---|---|---|
| 1 | ERNST AND YOUNG KAZAKHSTAN | Kazakhstan (foreign) | strong | 2 | Legal, regulatory and institutional framework for social services ([OP00461417](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00461417), 2026) |
| 2 | CENTER FOR PROGRESSIVE REFORMS NGO | Uzbekistan (local) | strong | 1 | the same award, as EY's JV member ([OP00461417](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00461417), 2026) |
| 3 | OXFORD POLICY MANAGEMENT | United Kingdom (foreign) | strong | 1 | Strategy for INSON social service centres ([OP00429772](https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00429772), 2026) |

Requested Center for Progressive Reforms → contacted. Expert variant: Encompass Consulting (OP00452535),
"Internal Audit Expert": no library or network expert matched; "Ask Plasma to source an expert" → requested.

Evidence in the demo database: 8 audit events (4 `PARTNER_REQUEST_CREATED` by the requester, 4
`PARTNER_REQUEST_STATUS_CHANGED` by the ops user), 4 `PARTNER_REQUEST` alerts staged, 0 e-mail deliveries.

## 5. Screenshots (`screens/`)

| File | Shows |
| --- | --- |
| `01-ultra-suggestions.png`, `01-ac-…`, `01-global-…` | a gap card with its features and the ten (five for AC) suggestions, label, matched words, award links |
| `02-*-request-form.png` | "Request introduction" with the note for the Plasma team and "Nothing is sent to the firm automatically" |
| `03-*-requested.png` | the suggestion after the request ("Requested — the Plasma team handles the introduction") |
| `04-expert-gap-sourcing.png` | a key-expert gap: no match, "Ask Plasma to source an expert" requested |
| `06-admin-status-dialog.png` | moving a request to Accepted with a message to the organization (audited) |
| `07-admin-queue-worked.png` | the admin queue: organization, requester, tender and gap, firm and notices, note, status, next steps |
| `08-requester-sees-status.png` | the requester's list: "Firm accepted" and the team's message |
| `09-scenario-prospective-member.png` | the scenario: PKF "Not yet confirmed", would close the gap, "With prospective members 1 / 14", assessment unchanged |

## 6. Tests

`backend/test_p2_partner_finder.py` (14 tests):

- Ranking rules (pure): determinism for any input order (5 shuffles, identical JSON; ties broken by name); public
  bodies, projects (both name tiers) and the own firm never suggested; people and UN agencies never suggested
  (names taken from the ledger); activity words alone never match; one shared word only when rare; another-sector
  awards need specific words and are never strong; "reinsurance" matches "insurance"; the sort order (presence,
  consulting, strength, country, recency, count); JV awards count for each member; at most 10; only public notice
  fields (exact key sets, no e-mail pattern); presence and gap-basis rules; features from title, sectors, category.
- Migration: additive, reversible (downgrade removes the tables and the alert kind), `alembic check` clean, no
  contact-like column in the new tables.
- Postgres scenario: a seeded ledger whose notices carry an e-mail, phone, street and contact name in the raw text
  and metadata; suggestions exclude the ministry, the individual (ICS) and the person in an ICS notice, the own
  firm, the rejected bidder and the works contractor, and no contact string appears in any response, request or
  alert; deterministic repeat; local-presence gap ranks the local firm first; expert gap returns the organization's
  library and the network but not another organization's expert; requests: 201 then 200 for a repeat, alert
  staged once per request, no e-mail delivery, audit per request, a firm never suggested → 404, wrong kind → 409,
  unique index enforced; organization isolation (B cannot read, request on, or use A's requests: 404); the queue
  with organization, requester and tender; invalid transitions → 409; 6 audited status changes with actor and
  states; the requester sees status and messages; scenarios: declined and sourcing requests refused, idempotent
  add, would-close for both gaps of the accepted firm, revision unchanged, remove and re-add.

`frontend/tests/p2-partner-finder.test.mjs` (4): every locale carries the same keys and placeholders; the
unverified label and notice links are rendered, no contact fields in the P2 types; the Team tab and scenario
wiring; the admin nav, status path and audit actions.

Runs (Windows host, Python 3.14; WSL Ubuntu hung with `Wsl/Service/0x8007274c` mid-session and Docker Desktop
was restarted at the start of the session after it had not come back since the 22 Oct reboot):

- `test_p2_partner_finder.py`: 14 passed (the Postgres scenario also passed in WSL before the hang).
- Targeted regression (W5, W6, W7, W8, D2-01, D2-05, P1-02, R3-05, S0 baseline/drift/preflight, S1 ledger):
  73 passed, 3 failed → two fixed (the drift test's chain and migration-file count); the third,
  `test_p1_02…::test_access_states_explore_alerts_and_pilot_setup`, fails identically on the base commit on this
  host (alert delivery leases 0 rows); `test_historical_migrations_are_untouched` fails on any CRLF checkout.
- `test_release_security.py`: 75 passed (run on its own).
- Full backend suite (the rest), branch vs base commit on
  the same host: branch 1,099 passed / 39 failed / 10 errors; base 1,088 passed / 36 failed / 10 errors (the
  branch has 11 more tests). The failure sets match except four branch-only failures: S1-1 and S1-2 asserted the
  old head's parent (fixed and passing); R3-01 failed only because this worktree's `.env` configures SMTP (passes
  with the base worktree's `.env`); R3-04's fake-SMTP test is flaky on this host (2 of 4 runs fail on the branch,
  1 of 2 on base). The shared failures are Windows-host environment failures (bash ops scripts, process groups,
  CRLF hashes, cp1251 file reads, disposable-database guard).
- Frontend: `tsc --noEmit` clean, ESLint clean on the changed files, RTL audit clean, `next build` passes,
  `p2-partner-finder`, `r3-05-admin-panels` and `localization-foundation` static tests pass.

## 7. Risks

**Data quality**
- Coverage: the ledger is World Bank only today (ADB/EBRD columns exist, no rows), awards since the ledger's
  window, CIS and MENA borrowers. A firm with only ADB/EBRD/bilateral or private work is invisible; "no firm
  found" means "no World Bank award", not "no capable firm" (AC Consulting: no Kyrgyz firm).
- Word matching, not meaning: project names leak into matching (Tsiar-Finans' "Project Financial Audit" on a
  social-protection project ranks for a social-work gap), generic requirements ("experience with government
  institutions") give weak, mostly moderate lists, and wording of a gap in Russian or Uzbek matches only through
  the English notice quote and the tender title.
- People recorded as firms: the filter catches initials, Slavic/Central Asian surname endings and position titles;
  a person named without those ("Sherif Hussain" for a specifications task) can still appear. Firms named like
  people with a surname ending (e.g. "Xolmatov va hamkorlar") would be dropped.
- Identity: firms are grouped by normalized name and country; the same firm under two spellings, or a branch
  in another country (PwC Uzbekistan / Kazakhstan / Azerbaijan), appear as separate suggestions.
- An award is not capacity: the notice says who won, not who did the work, the firm's share in a JV, current
  capacity, or whether it would partner with a competitor. The label says unverified; the scenario keeps the
  partner "not yet confirmed" and outside the assessment.

**Consent and conduct**
- The suggestions show only what the World Bank publishes (names, countries, notices); no contact data is
  stored or shown and nothing is sent. Contacting a firm is a human step by the Plasma team, which must say who
  asked and why, and stop if the firm declines; the requester's note is shared with the firm only with the
  requester's agreement (not enforced by software; a team rule to agree).
- Confidentiality of the requester: the request reveals that the requester is pursuing the tender. The team should
  name the requester only after the firm agrees in principle, or with the requester's permission.
- Competition: suggested firms are often the requester's competitors on the same tender; Plasma should not pass
  one bidder's plans to another beyond what the requester authorizes.
- Personal data: requests hold the requester's name, e-mail and note (Plasma account data already); the
  Uzbekistan personal-data localization question from M1 applies to these rows as to the rest of the database.
- Expert sourcing reaches people: sourcing must use consented network experts or ask each candidate first.

**Product**
- The post-commit alert kick publishes to Celery synchronously (as the P1 pilot request does): if the broker is
  unreachable the request is saved but the HTTP call hangs until Celery gives up (seen locally with no broker).
  Production has a broker; making the kick non-blocking is a small follow-up for both endpoints.
- The finder lists every eligible gap of the latest analysis, often several near-duplicate criteria (C1–C4 of one
  REOI), each with the same firms. Grouping by firm across gaps is a follow-up.

## 8. Not done / notes

- Not run: the WSL/Linux gate (WSL hung); a browser run in Russian, Uzbek or Arabic
  (strings are translated, layout checked in English only).
- Nothing pushed, no deploy note needed beyond: run the migration; set `ADMIN_ALERT_TELEGRAM_CHAT_ID` (or
  `PLASMA_ADMIN_EMAILS` with SMTP) so the team sees requests; operators work the queue.
- Local leftovers: database `plasma_s05b4b_p2_demo` (disposable copy, 284 MB) and the P2 worktree's own
  `node_modules` copy. The Loom database `plasma_s05b4b_s1int_local` was only read (as a template).
