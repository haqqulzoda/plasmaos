# S1-8 report: clean release branch, Deploy 4 additions, cost per use, replay mode for Loom previews

Local only: nothing pushed or deployed, the shared `plasmaos` stack was not stopped, Docker was not pruned; every
test and seed run had a memory watchdog (it kills my one-off containers if the shared backend fails two health
checks in a row; it never fired in S1-8). Since 2026-10-13 Docker Desktop cannot bind-mount host folders ("mkdir
/run/desktop/mnt/host/d: file exists"; running containers are unaffected). Fixing it means restarting Docker
Desktop, which stops the shared stack, so I left it: code and the release tree were streamed into Docker volumes
(`git archive … | docker cp`) instead.

## 1. Release branch `pilot/s1-release`

From `a83d575` (Deploy 3), built with `git checkout pilot/s1-int -- <files>` per group, no rebase:

| Commit | Content |
| --- | --- |
| `a5a1f5a` | S1 award ledger: World Bank contract awards, firm normalization, notice validation, market data (17 files) |
| `1c6f0ba` | S1 product analytics: product events, AI cost ledger, official AI prices, admin metrics (24 files) |
| `ecee350` | S1 outreach: ledger-backed prospect previews (best of N, replay), coverage strip, legacy redirects (118 files) |
| `4f8c019` | S1 docs: Deploy 4 runbook, market sizing, name QA, cost per use, sprint reports (25 files) |
| (last) | S1-8 report and gate evidence (docs only; this file and the runbook's evidence and checkout lines) |

- **Tree**: identical to `pilot/s1-int` (`git diff pilot/s1-int pilot/s1-release` is empty).
- **Names**: the natural-person names that appeared in earlier market-sizing tables (found by matching every
  ledger bidder name against every historical version of the S1 audit documents, then reviewed by hand: three
  names; the v1 tables are aggregates and name nobody; "INDIVIDUAL CONSULTANT" is a placeholder, not a name; the
  committed screenshots show companies only). `git log -p a83d575..pilot/s1-release | grep -c "<name>"`:

  | Name | `pilot/s1-release` | control: `pilot/s1-int` history |
  | --- | --- | --- |
  | #1 | **0** | 2 |
  | #2 | **0** | 3 |
  | #3 | **0** | 2 |

  A case-insensitive count over the same patch is also 0 for each. The control shows the check finds them where
  they are.
- **Intermediate commits** are grouped by feature and are not individually gated (the migration-chain tests, for
  example, are updated in the outreach commit); the gate ran on the final tree.
- Not pushed. `pilot/s1-int` keeps the full history (with the names in its older commits) and must not be pushed.

## 2. Deploy 4 runbook changes

- **Step 4**: when `/etc/plasma/ops.env` exists with `BACKUP_REMOTE` set, also `sudo systemctl start
  plasma-backup-daily.service` and require a fresh `BACKUP_RESULT … tier=daily` line before step 9; otherwise the
  laptop copy as written.
- **Step 8b (new, before step 9)**: read-only SQL counting proposals not linked to any pursuit (no pursuit on the
  proposal's tender in any organization where the proposal's user is an active member), total and per
  organization. **STOP if > 0**; the owner decides. Local data: **116 of 122 proposals unlinked across 4
  organizations**, so expect the STOP unless production differs.
- **Step 17**: as a non-admin member, every award-ledger and metrics endpoint (`summary`, `outcomes`,
  `outcomes.csv`, `firms.csv`, `market-sizing.csv`, `market-sizing.md`, `metrics`) returns **403**: verified
  locally with a non-admin pilot user's token (seven `403`). The pages `/admin/award-ledger` and `/admin/metrics`
  are client routes: the admin layout redirects a non-admin to `/dashboard` and never renders them; the runbook
  says so instead of promising a 403 page.
- **Owner section**: replay mode (pools, the short-notice rule, labels, `--replay-days 0`, pinning a closed
  tender, what to say in the recording), plus the existing list/archive warning.

## 3. Cost per use

[COST_PER_USE.md](COST_PER_USE.md): local AI cost ledger, 2026-10-11 14:18 to 2026-10-13 07:06 UTC, 130 calls, all
`gemini-3.8-flash`, re-priced with the official table (USD 0.75 / 3.75 per million).

| Unit | n | Median USD | p90 USD | Median from 2027-01-01 |
| --- | --- | --- | --- | --- |
| Analysis run (SHORT route) | 33 | 0.0338 | 0.0758 | 0.0676 |
| EOI (relevance notes) | 17 | 0.0146 | 0.0198 | 0.0292 |
| Preview pursuit (analysis + EOI) | 33 | 0.0405 | 0.0782 | 0.0811 |
| Best-of-3 preview command | 6 | 0.176 | 0.212 | 0.35 |

The Flash price doubles on 2027-01-01 (1.50 / 7.50), so every figure doubles. No LONG-route (pro model) run
happened locally: its cost is not measured.

## 4. Replay mode

`seed_demo.py --from-ledger … --replay-days N` (default 120). Pools in order: open Central Asian REOIs (notice ≥
2,500 characters), closed Central Asian REOIs published within N days (replay), then, with `--allow-global`, open
REOIs elsewhere (≥ 5,000). A run on a notice under 5,000 characters is kept only if its analysis extracts ≥ 4
requirements; otherwise it is archived and, when no run of a pool is acceptable, the next pool is tried. A replay
says **"Replay on a closed notice (closed <date>) — for illustration"** in the preview's name, under the pursuit's
title (en/ru/uz/ar) and on the EOI cover (DOCX and PDF, en/ru), above "Draft — not reviewed by your team". A
closed tender's official notice is stored when it is replayed (as a refresh would); a closed tender can be pinned
only while replay is on.

**Central Asian firm-level consulting REOIs by notice length** (local data 2026-10-13; notice as stored, else as a
refresh would derive it):

| | < 2,500 | 2,500–5,000 | ≥ 5,000 |
| --- | --- | --- | --- |
| Open (closing ≥ 7 days ahead) | 0 | **1** (OP00473838, regional CQS, 3,766) | 0 |
| Closed within 120 days | 0 | **5** | **16** |

**Runs** (`--candidates 3 --replay-days 120 --inline-analysis`; firms: KRESTON TASHKENT, TSIAR-FINANS, ENCOMPASS
CONSULTING and the next two local Uzbek firms by consulting bids not already covered, AYKAN INVEST (4 bids, 4
awards) and KPMG VALUATION CONSULTING (4 / 2); the top one, Ernst & Young, was covered in S1-7):

| Firm | Tender | Country | Open / closed | Criteria matched / total | Requirements | Run time | AI cost USD | Kept |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KRESTON TASHKENT | OP00473838 | Central Asia | open | 0 / 3 | 3 (refused: < 4) | 20 s | 0.0190 | |
| | OP00452374 | Uzbekistan | closed 2026-07-03 | 0 / 2 | 4 | 24 s | 0.0255 | |
| | OP00454073 | Uzbekistan | closed 2026-07-21 | 1 / 5 | 16 | 52 s | 0.0744 | |
| | OP00470797 | Uzbekistan | closed 2026-10-02 | **7 / 16** | 24 | 81 s | 0.0926 | **yes (replay)** |
| TSIAR-FINANS | OP00473838 | Central Asia | open | 0 / 4 | 4 | 32 s | 0.0307 | yes |
| ENCOMPASS CONSULTING | OP00473838 | Central Asia | open | 0 / 4 | 4 | 29 s | 0.0311 | yes |
| AYKAN INVEST | OP00473838 | Central Asia | open | 0 / 4 | 4 | 19 s | 0.0245 | yes |
| KPMG VALUATION CONSULTING | OP00473838 | Central Asia | open | 0 / 4 | 4 | 21 s | 0.0238 | yes |

Wall time per command: Kreston 201 s, the others 26–40 s.

**What this shows.** The one open Central Asian REOI (infection-prevention SOPs for a health workforce) passes the
≥ 4-requirement rule in four runs and fails it in one (3 requirements): the extraction varies by one requirement
between runs. Where it passes, the rule keeps it, and it matches **0 criteria** for audit and advisory firms: a
preview no one should record. Kreston's run fell through to replay and got the strongest preview of S1 after Ernst
& Young (7 of 16 criteria on an ESG report-verification REOI that closed 2026-10-02).

What replay gives the other four (their top-ranked replay candidate, pinned, one analysis each):

| Firm | Tender | Country | Closed | Criteria matched / total | Requirements | Run time | AI cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TSIAR-FINANS | OP00468339 | Uzbekistan | 2026-09-25 | 2 / 6 | 7 | 59 s | 0.0669 |
| ENCOMPASS CONSULTING | OP00452535 | Uzbekistan | 2026-07-16 | 1 / 8 | 9 | 192 s | 0.0223 |
| AYKAN INVEST | OP00468339 | Uzbekistan | 2026-09-25 | 2 / 5 | 6 | 40 s | 0.0488 |
| KPMG VALUATION CONSULTING | OP00452374 | Uzbekistan | 2026-07-03 | 1 / 2 | 4 | 38 s | 0.0399 |

Each of these shows the replay line on the pursuit (API `replay_closed_on`, checked live for KPMG: 2026-07-03) and
on the EOI version (`replay_closed_on` next to `NOT_REVIEWED_BY_TEAM`).

**Recommendation** (not implemented; your call): make "at least one criterion matched" part of acceptability, so a
0-match open notice falls through to replay like a short one. Today's data would then give all five firms a replay
preview.

## 5. Gate

On `pilot/s1-release` **4f8c019** (the final S1 tree, identical to `pilot/s1-int` 1f294ce), LF `git archive` export;
backend groups in a 700 MB one-off container on `plasma_db`'s loopback with a disposable database and Redis
(streamed into a Docker volume); frontend and browser groups on Windows:

| Group | Result |
| --- | --- |
| backend | **1,193 passed**, 1 skipped, 0 failed (12 batches of test files, a fresh process each: 119 + 148 + 87 + 79 + 192 + 108 + 73 + 76 + 74 + 88 + 85 + 64), incl. the migration-hash test on LF bytes |
| security | **118 passed**, including the 20 MB upload case (413) |
| analysis | **50 passed** (+12 subtests) |
| connectors | **198 passed**, 1 skipped (+6 subtests) |
| migrations | current, check, schema preflight: **PASS** |
| performance | **PASS** (10,000 and 100,000-row scale checks) |
| config-dependencies | **24 passed**, `pip check` clean; `npm audit --omit=dev` **0**; full audit report-only (dev-only highs under the active exception, until 2026-11-08) |
| frontend | npm ci, typecheck, lint, **406/406** node tests, RTL audit, production build: **PASS** |
| browser | **214 passed, 0 failed** |

**The 20 MB case** had failed twice before (OOM in S1-7; on Windows "environment variable longer than 32,767
characters"). Cause: its pytest id was the 20 MB payload itself, which pytest copies into `PYTEST_CURRENT_TEST`
and its reports. The cases now have short ids (1f294ce); the payload and the expected 413 are unchanged. It
passes in 20 s within 700 MB.

The last commit adds only this report and the runbook's evidence and checkout lines (docs); the gated tree is
otherwise the same.

## 6. Risks

- **Docker Desktop bind mounts are broken** until Docker Desktop restarts (which stops the shared stack: your
  approval). The scripts work around it with volumes; production is unaffected.
- **Open notices with 0 matches are accepted** by the rule as specified (section 4).
- **Extraction varies** by about one requirement between runs on the same short notice, so the ≥ 4 rule can flip.
- **The replay label rides on a marker** in the preview organization's profile notes. Only the seed writes it; if
  someone edits a preview's profile notes and removes it, the pursuit stops showing the line (the preview name and
  the EOI cover keep it).
- **Step 8b will likely STOP the deploy** (116 unlinked proposals locally): decide before the window.
- The pages under `/admin` redirect rather than answer 403 (the data endpoints answer 403).
- LONG-route analysis cost is unmeasured; the Flash price doubles on 2027-01-01.
- The release images are not built yet (the runbook's SHA and bundle values are placeholders).
- `pilot/s1-int` must not be pushed (its older commits contain the names); push only `pilot/s1-release`.
