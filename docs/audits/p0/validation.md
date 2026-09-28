# P0 validation ledger

## Definitive release wrapper

The final guarded `scripts/run_release_gate.sh all` invocation exited 0. It used only a disposable loopback PostgreSQL target and controlled local browser/API fixtures.

| Gate | Result |
| --- | --- |
| Full backend | 846 passed, 1 skipped, 100 subtests passed |
| Security | 118 passed |
| Analysis | 50 passed, 12 subtests passed |
| Connectors | 198 passed, 1 skipped, 6 subtests passed |
| Migrations | heads, current, check, and schema preflight passed |
| Performance | Passed at 1k, 10k, and 100k rows; at 100k, at most 5 queries and 25 files |
| TypeScript | Passed |
| ESLint | Passed |
| Frontend | 297 of 297 passed |
| RTL audit | Passed with no physical, icon, or authority violations |
| Production build | Passed; 29 routes generated/validated |
| Chromium | 203 passed, 0 failed, 0 external requests |
| Configuration | 24 passed |
| Python dependency check | No broken requirements |
| npm audit | 0 vulnerabilities |

The retained Chromium JSON is `docs/audits/p0/browser-all/results.json`, SHA-256 `f89e5a5c6ce23fd641497bc14a8c2d8e8712a7a25562a9a548954211f0c59539`.

## Focused acceptance coverage

- Six P0 backend tests cover complete eight-page input, source context, golden W4 semantics, the Communications Consultant role, mandatory/preferred/desired distinctions, customer-provided hourly rate, later-stage obligations, missing artifacts, quality states, provenance conflicts, passivity, and migration reversibility.
- Five P0 frontend tests cover processing-versus-quality display, false no-gap prevention, authoritative Next Action, conflict/historical-deadline display, and qualification distinctions.
- The real Chromium P0 case proves the attention state, absence of a false no-gaps claim, visible source conflict, and state-derived Next Action.
- 39 targeted World Bank/project tests passed; Project Context and Project Leadership remain distinct from Contacts and Experts.
- 10 database-backed communications tests passed.
- W4, W5, W6, W7, and W8 workflow browser cases all passed in the final Chromium run.

## Safety boundaries

No production service was accessed, mutated, or deployed. Browser fixtures rejected external requests. Page reads remained passive and did not trigger parsing, AI, source fetching, reruns, or mutations.
