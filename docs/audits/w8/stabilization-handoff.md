# W8 Stabilization Handoff

## Stable contracts

- Alembic head: `20261001_0001_w8_proposal_evidence_pack`.
- Pack schema: `w8-proposal-evidence-pack-v1`.
- Generator version is recorded on every artifact.
- Existing W1 commercial Proposal and W7 handoff contracts remain separate.

## Operational checks

Monitor seal duration because the explicit seal transaction uses broad authority-table locks to close append races. Monitor private artifact storage growth and hash/size verification failures. Keep PostgreSQL migration checks, W8 permanent tests, frontend static tests, production build, browser acceptance, and the release wrapper as stabilization gates.

## Accepted results

- Backend: 838 passed, 1 skipped, 100 subtests passed.
- Security group: 118 passed.
- Analysis group: 50 passed, 12 subtests passed.
- Connector group: 198 passed, 1 skipped, 6 subtests passed.
- Frontend: 292/292; typecheck, lint, RTL audit, and production build passed.
- Chromium: 202/202, including the explicit W8 seal case.
- Alembic heads/current/check and schema preflight: passed.
- Scale: bounded query budgets passed through 100,000 records.
- Dependencies: `pip check` clean; npm audit reported zero vulnerabilities.
- `scripts/run_release_gate.sh all`: PASS.

## Deferred work

Submission, messaging, generated narrative, source CV ingestion/linkage, commercial pricing, task management, team recommendations, connectors, and legacy Bid Preparation retirement are outside W8. No production deployment or production access was performed.

## Rollback

Downgrade from W8 to W7 removes only W8 workspaces, packs, items, artifacts, triggers, and the W8 decision uniqueness constraint. It preserves W0 through W7 and all legacy Proposal data.
