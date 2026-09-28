# P1 demo-readiness audit

## Classification

P1 is ready for a **precomputed-result customer demo**. The workspace communicates the P0R live-provider classification `LIVE_DEMO_RISKY`: analysis is visibly asynchronous, no completion time is promised, retry is explicit, and the last successful result survives a later failed or running attempt.

For demonstrations, open a pursuit with a precomputed reviewable extraction. Navigate Overview → Requirements → Team → Proposal to show the customer decision sequence. A live provider run may be shown only as a non-guaranteed operation; P1 does not change provider reliability or latency.

## UX acceptance

- Five-tab hierarchy and authoritative next action.
- Compact context with explicit conflicts and historical deadlines.
- Informative analysis-derived Overview.
- Requirement source/assessment/evidence ordering.
- Partner/expert progressive disclosure and Team options.
- Price-free evidence pack preparation.
- Localized EN/UZ/RU/AR and RTL-safe keyboard navigation.
- Narrow proposal matrix cards and bounded passive query behavior.

## Definitive validation

The permanent `scripts/run_release_gate.sh all` wrapper exited 0 using only disposable loopback PostgreSQL/Redis and controlled local fixtures. Backend, security, analysis, connectors, Alembic preflight, 100k-row scale, TypeScript, ESLint, RTL, production build, dependency, and configuration gates all passed. Frontend tests passed 303/303. The final permanent browser-group rerun passed 204/204 with zero external requests, including P0, P1 async running/failed retention, W4–W8 workflows, both SOURCE/UPLOAD behavior, four locales, and 320/390/768/1440 layouts.

Axe ran on the Pursuit workspace for every locale/width combination (16 cases) with zero serious or critical violations. The retained browser artifact is `browser-all/results.json`, SHA-256 `888734d7bfebed538455d648c0c7442439014e7b82ec0d6cadd61e6bd0b7e982`.

No production deployment is part of this result.
