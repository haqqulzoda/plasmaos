# W5 — Firms, Experts, and Evidence Backed Candidate Retrieval

## Status

Implemented on the accepted W4 baseline. The repository has one linear Alembic head:

`20260928_0001_w5_candidate_retrieval`

W5 answers one bounded question: which recorded Firm or Expert appears able to contribute to one exact reviewed W4 Gap, and which evidence supports or weakens that conclusion?

## Authority model

`Firm` and `Expert` are reusable candidate authorities. `Firm` has no identity relationship to tenant `Organization`. `Expert` has no relationship to Project Leadership, procurement contacts, or generic contact records. Records enter these authorities only through explicit candidate data entry.

`ProjectReference` records the Firm's actual role, share, contract or service value and its basis, dates, completion state, relevant scope, and evidence provenance. Unknown values remain null. A value cannot be saved without currency and an explicit `FIRM_SHARE`, `CONSORTIUM_TOTAL`, or `CONTRACT_TOTAL` basis.

`CVVersion` stores immutable structured facts and a canonical SHA-256. It records education, qualifications, certifications, assignments, actual roles and dates inside the assignment facts, languages, provenance, and evidence state. W5 does not store reusable CV bytes in `TenderDocument`. Structured facts without reviewed proof retain `UNVERIFIED` or `EVIDENCE_MISSING`.

## Visibility

Two scopes exist:

- `ORGANIZATION_PRIVATE`: the owning Organization alone may read or use the record.
- `NETWORK_SHARED`: an operator must record an explicit permission basis. Shared Experts also require `EXPLICIT_CONSENT` or `CONTRACTUAL_BASIS`.

Safe responses omit private notes, rates, private CV bytes, relationship history, and all participation state. Shared provenance is reduced to an allowlist of evidence fields.

## Authorized supply

Authenticated active Organization members can create and edit private Firm and Expert descriptors, add ProjectReferences, and append CV versions through `/api/v1/candidates`. Network shared writes require operator authority. `EXPLICIT_IMPORT` is the only import source type and still uses the same reviewed data entry route. Competitor and historical participant data never creates candidates implicitly.

The first release deliberately provides no supplier portal, scraping, automatic outreach, or source connector.

## Reviewed Gap gate

`POST /api/v1/pursuits/{pursuit_id}/candidate-search-runs` is the only search trigger. The service requires:

1. the exact W4 `AnalysisRun` is completed and belongs to the Organization and Pursuit;
2. its sealed `AnalysisPack.candidate_sha256` still equals the current pursuit candidate hash;
3. the requested Gap belongs to that run;
4. the latest append only GAP assertion is `CONFIRMED` or `CORRECTED`;
5. effective coverage is `GAP`, `PARTIAL`, or `EVIDENCE_MISSING`;
6. effective resolution is `PARTNER_FIRM` or `EXPERT`;
7. `PARTNER_FIRM` points to a Requirement and has an explicit issued or reviewer corrected contribution rule;
8. `EXPERT` points to a Position.

`COMPANY_EVIDENCE`, `CLARIFICATION`, `HUMAN_INTERPRETATION`, unresolved `NEEDS_INTERPRETATION`, and all terminal or later stage states are rejected.

## Retrieval and evaluation

Retrieval uses current PostgreSQL records only. It uses structured capability, service, sector, geography, ProjectReference, specialization, language, qualification, and CV fact text. It performs no network request, scraping, AI call, message, or outreach.

Each action reads at most 100 visible authorities and persists at most 20 results. Firms and their references use two set based queries. Experts and their CV versions use two set based queries. Responses bulk load matches, reviews, and candidate identities.

Permanent integration coverage enforces a four-query ceiling for a populated Organization library projection and a ten-query ceiling for a populated historical search projection, including its current-input stale check. The same W4 pack authority is exercised for both SOURCE and UPLOAD pursuits by the permanent W4 integration suite; W5 does not branch retrieval authority by pursuit origin.

Retrieval ranking is internal ordering. The product exposes no match probability or universal percentage. Evaluation then compares each retrieved record with the exact Requirement or Position Gap. The result is one of:

- `SUPPORTED_BY_EVIDENCE`
- `PARTIAL`
- `EVIDENCE_MISSING`
- `NEEDS_REVIEW`
- `NOT_RELEVANT`

Only reviewed or verified records can support a conclusion. Missing proof stays missing. Expert experience periods are not summed, so overlapping periods cannot inflate general experience.

## Immutable search history

Every completed `CandidateSearchRun` binds Organization, Pursuit, exact W4 run, exact Gap, Requirement or Position, latest review assertion, effective states, contribution rule, search version, parameters, actor Membership, limit, and timestamps.

Each immutable `CandidateMatch` binds exactly one Firm or Expert, the Gap, proposed contribution, strongest evidence, relevant evidence, weaknesses, qualification state, rationale, provenance, and rank. Database triggers reject update and delete for CV versions, completed searches, matches, and reviewer decisions.

Reviewer actions append `CandidateReviewDecision` rows. The current decision is a projection of the newest row. Review can shortlist, reject, request evidence, mark irrelevant, or correct the proposed contribution. No W4 row is changed.

Historical searches remain readable. A changed pursuit input or newer W4 analysis marks the old search stale and requires a new search run.

## User experience

The Pursuit workspace has a Team section with separate Partners and Experts groups. Only reviewed eligible gaps appear. Search begins from an explicit button. Result cards show candidate identity, exact Gap ID, proposed contribution, strongest evidence, remaining weakness, evidence review state, scope, rationale, and next reviewer action.

The lightweight Partners & Experts library is linked from Team only when at least one visible record exists. It displays safe structured Firm reference history and Expert CV version history. It is not a marketplace.

## Preserved boundaries

- Competitor Intelligence remains unchanged and is not an automatic candidate source.
- World Bank Project Context, Project Leadership, procurement contacts, and participant records remain separate.
- W4 Requirements, Positions, Gaps, source quotes, and assertions are not rewritten.
- W1 no AI pricing remains intact.
- No availability, effort, capacity, interest, willingness, confirmation, commitment, participation, withdrawal, invitation, TeamScenario, or proposal pack exists in W5.

## Validation authority

Permanent coverage lives in `backend/test_w5_candidate_retrieval.py`, `frontend/tests/w5-candidate-retrieval.test.mjs`, and the `w5/team-candidate-retrieval` Chromium case. The final local gate completed with 828 backend tests plus 100 subtests, 269 frontend tests, and 199 Chromium cases passing; one existing backend test remained intentionally skipped. Migration heads/current/check/preflight, security, analysis, connectors, scale, typecheck, lint, RTL, production build, Python dependency consistency, and the high-severity npm audit also passed.

## W6 boundary

W6 may consume an immutable CandidateMatch plus its exact Gap and AnalysisRun, candidate identity, proposed contribution, evidence state, and effective reviewer shortlist decision. W6 must append separate participation facts; it must not add them to or mutate the W5 search record.

