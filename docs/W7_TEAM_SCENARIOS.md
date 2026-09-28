# W7 — Evidence-Backed Team Scenarios

## Status

Implemented on the accepted W6 baseline with Alembic head `20260930_0001_w7_team_scenarios`.

W7 lets an Organization create several named team alternatives for one Pursuit and assess an exact immutable composition against its reviewed W4 Gap set. `VIABLE` is a deterministic operational assessment. It is not a claim of compliance, eligibility, award likelihood, or legal sufficiency.

## Durable identity and immutable revisions

`TeamScenario` contains only Organization, Pursuit, title, creator, timestamps, and optional archival time. It has no mutable composition.

Every create or revise command appends a `TeamScenarioRevision` with a monotonic version number, exact W4 AnalysisRun and AnalysisPack, canonical selection hash, assessment schema version, assessment state, and sealed summary counts. PostgreSQL triggers reject update or delete of revisions and every revision child. Old revisions remain readable.

## Participants and contributions

A revision has one `TeamScenarioParticipant` per distinct Firm or Expert identity. A Firm or Expert reused for several Gaps has several contributions under one participant. The customer's Organization is returned separately as `lead_organization_id`; W7 never creates it as a candidate Firm.

Each `TeamScenarioContribution` seals:

- the exact CandidateMatch, CandidateParticipationRecord, W4 Gap, and Requirement or Position;
- the exact effective W5 review decision ID and `SHORTLISTED` state snapshot;
- proposed contribution and reviewed contribution rule;
- qualification and candidate evidence states;
- ProjectReference or CVVersion evidence identities and strongest evidence;
- availability, interest, and participation fact IDs and effective snapshots;
- availability window, effort or capacity, validity time, confirmation provenance, reconfirmation time, assignment comparison, and upstream stale state.

W7 never updates a W4 Gap, W5 match or decision, or W6 participation trail.

## Gap assessment

Every exact W4 Gap receives an immutable `ScenarioGapAssessment`. The row retains the latest W4 review assertion ID and effective W4 coverage, review, and resolution category used by the revision.

Scenario states are `COVERED`, `PARTIAL`, `UNRESOLVED`, `BLOCKED`, and `NEEDS_REVIEW`. Later stage obligations are disclosed and counted without blocking current viability. `NOT_APPLICABLE` and already supported W4 items need no candidate contribution. `COMPANY_EVIDENCE`, `CLARIFICATION`, and `HUMAN_INTERPRETATION` remain unresolved until W4 resolves them.

A candidate fully covers a Gap only when the exact W5 decision is shortlisted, qualification is `SUPPORTED_BY_EVIDENCE`, the reviewed contribution authority permits the use, W6 availability and participation are current, the assignment window is acceptable, and the upstream chain is current. Partial candidates are never combined into inferred full coverage.

## Deterministic viability

Assessment has four results:

- `DRAFT`: no selected contribution; unresolved inputs remain visible.
- `NEEDS_REVIEW`: an input is incomplete, partial, unknown, conflicting, or requires human resolution.
- `BLOCKED`: an explicit incompatibility exists, including no overlap, unavailable or expired participation, reconfirmation failure, excessive overlapping Expert effort, or concurrent full-time assignments.
- `VIABLE`: every current-stage Gap is covered and no review or blocking issue remains.

For an Expert used in overlapping assignments, known efforts above 100 percent are blocked. Concurrent full-time assignments are blocked. Missing dates or effort require review. The same Firm may serve several corporate Gaps; each contribution keeps its own W5 and W6 lineage.

Conflicting availability, interest, participation, or confirmation conditions across records for one candidate create `CONFLICTING_PARTICIPATION_FACTS` and prevent viability. W7 does not choose one record silently.

## Decisions and approval

`TeamScenarioDecision` is append only and binds one exact revision. Members may append `PREFERRED`, `REJECTED`, or `APPROVED_FOR_PROPOSAL` with a reason.

Proposal approval requires an active Membership, explicit confirmation, a current revision, and a current `VIABLE` projection. The approval means only that the Organization approved that exact team for proposal preparation. A historical approval remains readable after staleness but cannot authorize a new handoff.

## Staleness

GET projections compare the sealed revision with the current W4 run and pack state, the exact reviewed Gap set and assertions, the current W5 decision, and current W6 fact identities and effective states. Any relevant change sets `scenario_current=false` and returns explicit reasons. The historical revision is not changed. A new revision is required to consume new facts.

## Routes and passive reads

- `POST /api/v1/pursuits/{pursuit_id}/team-scenarios`
- `GET /api/v1/pursuits/{pursuit_id}/team-scenarios`
- `GET /api/v1/pursuits/{pursuit_id}/team-scenarios/{scenario_id}`
- `POST /api/v1/pursuits/{pursuit_id}/team-scenarios/{scenario_id}/revisions`
- `POST /api/v1/pursuits/{pursuit_id}/team-scenarios/{scenario_id}/revisions/{revision_id}/decisions`
- `GET /api/v1/pursuits/{pursuit_id}/team-scenarios/{scenario_id}/revisions/{revision_id}/proposal-handoff`

Scenario lists are capped at 50 roots and 1,000 revisions. Participants, contributions, assessments, issues, and decisions load set wise. The populated permanent proof enforces a fixed 40-query ceiling independent of participant count. GETs perform database reads only: no AI, source HTTP, search, outreach, notifications, or W6 writes.

## Team UI

Pursuit → Team retains the W5 candidate and W6 participation cards and adds **SCENARIOS**. Members can create alternatives, select W6 records, append revisions, inspect partner and Expert contributions, inspect Gap outcomes and structured issues, record decisions, and approve an eligible exact revision.

The comparison shows assessment, unresolved Gaps, partner count, Expert count, confirmed participant count, stale state, and blocking issue count. It provides no score, percentage, ranking, winner, or automated recommendation. The lead Organization is shown separately.

## Privacy and World Bank boundary

Every root, revision, child, issue, and decision is Organization private. Composite foreign keys and tenant filtered reads prevent cross customer access. Use of a network shared candidate does not expose another Organization's scenario or capacity facts.

World Bank Project Context, Project Leadership, procurement contacts, and source participant records are unchanged. None becomes a scenario participant without the full explicit W5 CandidateMatch and W6 participation authority.

## W8 handoff

The handoff returns the exact approved revision and approval decision, AnalysisRun and AnalysisPack, Gap assessments, participants and contributions, CandidateMatch and CandidateParticipationRecord identities, exact W6 fact IDs, evidence identities, current viability, later stage count, and source/private provenance counts.

W8 must revalidate this handoff immediately before sealing a Proposal Evidence Pack. A stale or nonviable revision is rejected.

## Validation authority

Permanent W7 coverage is in `backend/test_w7_team_scenarios.py`, `frontend/tests/w7-team-scenarios.test.mjs`, and the `w7/team-scenarios` Chromium case in `frontend/tests/release-hardening-browser.py`. It covers W6→W7 migration, multiple alternatives, immutable revisions, Firm and Expert deduplication, multi-gap use, strict viability, scheduling and effort conflicts, W6 fact conflicts and freshness, decisions, approval and handoff gates, SOURCE and UPLOAD pursuits, tenant privacy, World Bank fingerprints, passive bounded reads, and UI semantics.

The completed cumulative release evidence is: 835 backend tests passed, 1 skipped, and 100 nested subtests passed; 284 frontend static tests passed; TypeScript, ESLint, RTL audit, and the production Next.js build passed; 201 Chromium cases passed with zero external requests; security, analysis, connector, migration drift, schema preflight, and 100,000-row performance gates passed; Python dependencies were consistent and npm reported zero vulnerabilities. `scripts/run_release_gate.sh all` exited successfully against a guarded disposable local PostgreSQL database.

