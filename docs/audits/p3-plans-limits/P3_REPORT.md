# P3 report: plans and limits

Branch `pilot/p3-plans-limits` on `pilot/p2-partner-finder` (worktree `D:\projects\plasmaos-p3`). Local only:
nothing pushed or deployed. One additive migration (`20261024_0001_p3_plans_limits`). Limits and features follow
the pricing table and the owner decisions of 23 Oct 2026 (`plasma-landing/docs/r2/WEBSITE_PLAN_R2.md`).

## 1. Plans

| | Explore | Pilot | Pursuit Desk | Agent | Enterprise | Per-tender review |
| --- | --- | --- | --- | --- | --- | --- |
| Pursuits | 1 a calendar month | 6 in the pilot term | 24 a plan year | 60 a plan year | from the agreement (150 until set) | 1 per purchase (limit = purchases) |
| Introductions (P2 requests) | 0 | 1 | 2 a year | 12 a year | unlimited | 0 |
| Users | 2 | unlimited | unlimited | unlimited | unlimited | unlimited |
| Tender check (requirements, gaps) | yes, requirements only | yes | yes | yes | yes | yes |
| EOI | — | yes | yes | yes | yes | yes |
| Own evidence (company records, library, team, scenarios) | — | yes | yes | yes | yes | yes |
| Partner search (finder, expert suggestions, introductions) | — | yes | yes | yes | yes | — |
| Competitor intelligence (`/tenders/{id}/competitors`) | — | — | — (sector figures) | yes | yes | — |

The catalogue is `backend/app/core/plans.py`; the rules and counting `backend/app/services/plans.py`.

- **Plan → access.** `organizations.plan` (new) sets the P1 access state: explore → explore, pilot → pilot, the
  paid plans → paid; "disabled" stays a separate switch that keeps the plan. Legacy paths that set only a state
  (company approve, pilot setup) keep the plan in step. Migration backfill: explore → explore, pilot → pilot,
  paid → Pursuit Desk, disabled → explore. On the Loom preview copy: 210 approved organizations → Pilot.
- **Periods.** Explore: the calendar month (UTC). Pilot: from `plan_started_on` to `plan_ends_on` (3 months by
  default); every pursuit since the start counts, also after the end date. Paid plans: the plan year from
  `plan_started_on` (anniversaries; 29 Feb → 28 Feb). Per-tender: everything since the start. No start date:
  the organization's creation date.
- **Overrides and grants.** `pursuit_limit_override` / `introduction_limit_override` replace the plan's number
  and persist (Enterprise agreement, per-tender purchases). A grant adds pursuits or introductions to the current
  period only (`organization_plan_grants`, with a reason; audited as `ORGANIZATION_PLAN_GRANTED`).

## 2. Counting rules

- A pursuit counts **once, when its first analysis starts** (`create_analysis_run`): saving or opening a tender
  counts nothing; a second run on the same pursuit (re-analysis after an amendment, another document set, an
  admin retry) never counts again. `organization_pursuit_usage` has one row per (organization, pursuit).
- The check and the count run in the analysis-start transaction under a per-organization advisory lock, so two
  analyses started at the same time cannot both take the last pursuit.
- At the limit a **new** pursuit is refused with HTTP 402 `PLAN_PURSUIT_LIMIT` ("upgrade or add pursuits"; on
  Explore "this month's free tender check is used"); an already counted pursuit still re-analyses.
- **80% and 100%**: the in-app notice (dashboard and pursuit workspace; red at 100% with "Upgrade or add
  pursuits", which sends an "upgrade" request to the team, or "Start a pilot" on Explore), and one `PLAN_USAGE`
  team alert per period and threshold (Telegram, else e-mail; existing P1 delivery). Notices: 24 → from 20;
  6 → from 5; Explore's 1 → reached only.
- **Introductions**: P2 requests made in the period that were not declined (a declined introduction gives the
  quota back); a repeat of the same request is free. Over the quota: HTTP 402 `PLAN_INTRODUCTION_LIMIT`.
  Both introductions and "ask Plasma to source an expert" count (both are introductions by our team).
- Backfill: one usage row per pursuit that already had an analysis run, counted at its first run (215 rows =
  215 pursuits with runs on the Loom preview copy).

## 3. Gates and Explore

- Explore was fully outside the organization workspace in P1 (company pending). P3 opens **only** what the
  monthly check needs: list and open pursuits, open a pursuit from a tender, its documents list, pack candidate,
  start and read the analysis and its context (`allow_explore` on 9 routes in `pursuits.py`), plus team
  management (members, invitations) with the 2-user cap. Every other organization route keeps P1's strict gate,
  so Explore still has no company records, EOI, team, scenarios or partner search (404 as before).
- In the app, Explore sees "Check this tender" on its Explore page (and the month's status), then the pursuit
  with only Overview and Requirements tabs; the rest of the shell stays Explore-only.
- Plan feature gates (403 `PLAN_FEATURE`) on the EOI router (`eoi`), the library, candidate search,
  participation, team scenarios and proposal evidence (`own_evidence`), the partner finder (`partner_search`;
  prospective JV members are `own_evidence`), and competitor intelligence (Agent, Enterprise; operators bypass).
  The UI hides the tabs a plan lacks and says "not part of your plan" in the partner finder.
- Competitor intelligence has no screen in the customer app today (API only), so the gate changes no screen;
  Pilot and Pursuit Desk lose API access to it, as the pricing table says. "Sector figures" / "sector headline
  figures" do not exist yet (the pricing page marks them Coming).

## 4. Admin

`/admin/organizations`: per organization the plan (badge), period, pursuits used/limit (amber at 80%, red at
100%), introductions, users, last activity. **Plan** (admins): plan, disable switch, start/end dates, pursuit and
introduction limit overrides, success criteria, reason; audited as `ORGANIZATION_ACCESS_CHANGED` with the plan
and overrides in the before/after state. **Usage** (operators read, admins write): this period's usage, grant
extra pursuits or introductions with a reason, the grants, and the plan's audit events. `/admin/audit` lists the
new action.

## 5. Tests

`backend/test_p3_plans_limits.py` (5): the catalogue equals the pricing table (limits, introductions, users,
features, intelligence) and the state↔plan mapping; periods (month, leap February, pilot term and default end,
plan-year anniversaries, 29 Feb anchor, no start date, lifetime); notices at 80/100% (24, 6, 1, unlimited, 0);
the migration (backfill from access states, constraints, reversible, `alembic check` clean); and one Postgres
scenario through the real analysis-start path:

- counting: opening seven pursuits counts nothing; the first analysis counts 1; a second run on the same pursuit
  still 1; six pursuits → 6/6 "limit_reached";
- alerts: exactly one 80% and one 100% `PLAN_USAGE` alert; the alert text;
- limit: the seventh pursuit is refused in the service and at HTTP (402 `PLAN_PURSUIT_LIMIT`), nothing counted;
  a counted pursuit still re-analyses at the limit; a grant of +2 opens it (7 of 8, near limit);
- Explore: strict context refused, `allow_explore` admitted; one check a month, the second refused with the
  Explore message; next month used 0; no EOI, own evidence, partner search or intelligence (EOI route 404);
  2 users: one invitation accepted, the third seat refused (402 `PLAN_USER_LIMIT`); the plan endpoint;
- introductions: Pilot's one introduction, a repeat free, the second firm refused (402), a declined request gives
  it back;
- gates: per-tender has no partner search (403 with code, feature, plan); Pilot and Pursuit Desk get 403 on
  competitor intelligence;
- admin: plan → Agent with an introduction override (60 / 15), a grant (+3 → 18), audit events (grant, plan
  change with before/after plan and override), disabling keeps the plan.

Updated for P3: the P2 test runs on Enterprise (it tests requests, not the quota); head constants and chain
assertions moved to the P3 migration (as P1/P2 did).

Frontend: `tests/p3-plans.test.mjs` (4: plan tabs, plan error codes, string parity in 4 locales, wiring) and the
whole static suite passes. **P2 regression fixed here:** P2 broke three existing frontend tests I had not run in
P2 (`w6-participation`, `w7-team-scenarios`: the team UI used `api.delete` where the team UI is append-only, and a
`note:` field in `types/pursuit.ts`; `p1-customer-pursuit-workspace`: the scenario-workspace condition). Fixed:
removing a prospective member is now `POST …/remove`, the partner-finder types moved to `types/partnerFinder.ts`,
and the P1 test accepts P2's widened condition. `tsc` clean, ESLint clean on changed files, RTL and design-token
audits clean, `next build` passes.

Backend runs: P3 + P2 + P1-02 tests 23 passed. Full backend suite (Windows host, everything including
`test_release_security.py`): 1,184 passed, 34 failed, 10 errors; every failure and error is in the base commit's
Windows-environment set (bash ops scripts, process groups, CRLF hashes, cp1251 reads, the disposable-database
guard); no P3-only failure.

## 6. Screenshots (`screens/`, local copy of the Loom preview database with P1–P3)

| File | Shows |
| --- | --- |
| `01-admin-organizations-plans.png` | admin: plan, period, pursuits, introductions and users per organization |
| `02-admin-plan-editor.png` | admin: the plan editor (plan with its limits, disable, dates, overrides, reason) |
| `03-explore-check-available.png` | Explore: "check one tender free each month" and "Check this tender" |
| `04-explore-requirements-only.png` | Explore after its check: only Overview and Requirements; "This month's free tender check is used" + Start a pilot |
| `05-explore-check-used.png` | Explore page: the notice and "the next one opens on 1 Nov 2026" |
| `06-pilot-near-limit-dashboard.png` | Pilot at 5 of 6 (counted through real analysis starts): the 80% notice |
| `07-pilot-limit-reached-blocked.png` | Pilot at 6 of 6: the 100% notice and "Analyze selected" refused on a new tender |
| `08-introduction-quota-reached.png` | Pilot's one introduction used: a second request refused with the plan message |
| `09-introductions-used.png`, `09b-team-tab-allowance.png` | the requests list and "Introductions by our team: 1 of 1 used" |
| `10-admin-usage-grant-audit.png` | admin usage dialog: 6 / 8 incl. +2 granted, the grant and its audit event |

Demo evidence (demo database): 3 `PLAN_USAGE` alerts (Global Advisors 80% at 5/6 and 100% at 6/6, the Explore
organization 100% at 1/1), 1 `ORGANIZATION_PLAN_GRANTED` audit event, 0 e-mail deliveries (no worker ran).
Two Explore organizations were created for the demo as self sign-ups: "Samarkand Survey LLC (local demo)" (used
its check: 04, 05) and "Bukhara Water Advisory LLC (local demo)" (unused: 03).

## 7. Risks and open points

- **Pilot P1 organizations become limited.** Every approved organization is now a Pilot with 6 pursuits counted
  since its start (backfilled), 1 introduction and no competitor intelligence. Real pilots past 6 pursuits are
  blocked from new tenders at deploy: set their plan or grant pursuits before deploying (the admin page shows who
  is near or over).
- **Competitor intelligence** disappears for Pilot and Pursuit Desk at the API (as priced); no screen uses it.
- **Explore opens routes that were closed.** Only the 9 pursuit routes and team management, each still bound to
  the organization's membership; Explore can open (save) any number of pursuits, analyse one a month, and invite
  one colleague. A security review of the `allow_explore` routes before deploy is advisable.
- **Counting by UTC date**: a plan that starts today includes pursuits counted earlier today; an organization in
  Tashkent sees a new Explore month at 05:00 local time.
- **Pilot after its end date** keeps counting from its start (no reset); moving it to a paid plan starts a plan
  year.
- **The post-commit Celery kick** (alerts) still blocks a request when the broker is down (from P1/P2).
- Plan names (Explore, Pursuit Desk, Agent, Enterprise) are translated in Arabic (the Arabic release test forbids
  English leaves); Russian and Uzbek keep the product names.

## 8. Not done / notes

- Not run: the WSL/Linux gate (WSL hung); a browser run in Russian, Uzbek or Arabic.
- No billing: plans are set by admins (invoices stay manual, in USD).
- Local leftovers: database `plasma_s05b4b_p3_demo` (disposable copy), the worktree's `node_modules` copy.
