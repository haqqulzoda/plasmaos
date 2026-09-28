# W6 — Availability, Interest, and Participation

## Status

Implemented on the accepted W5 baseline. The repository has one linear Alembic head:

`20260929_0001_w6_participation`

W6 records what an authorized Organization member learned about one shortlisted candidate in one Pursuit. It keeps W5 capability evidence, contextual availability, willingness, and participation confirmation as four separate authorities. It does not decide whether a final team is adequate.

## Exact W5 entry gate

`CandidateParticipationRecord` is an immutable Organization private root with one unique `candidate_match_id`, the exact effective `shortlist_decision_id`, Organization, Pursuit, proposed contribution snapshot, creating Membership, and timestamp.

Creation revalidates the exact CandidateMatch and CandidateSearchRun, Organization and Pursuit ownership, latest effective W5 decision, current W4 analysis identity and pack hash, and active Membership. An unreviewed, rejected, irrelevant, evidence request only, or stale match cannot start a trail. Repeating the command for the same current match returns the existing root.

The root never stores mutable availability, interest, or participation state. Those values are read projections over immutable child rows.

## Availability authority

`CandidateAvailabilityFact` appends status, optional date window, Expert effort percentage or truthful textual capacity, location and travel constraints, confirmation source, observed time, validity boundary, actor, optional same Pursuit W3 DocumentVersion, optional bounded private note, and an optional corrected fact reference.

Positive `TENTATIVE`, `AVAILABLE`, and `PARTIALLY_AVAILABLE` facts require `valid_until`. Where the bound W4 Position has parseable assignment dates, an explicit availability window is required. Unknown assignment dates stay unknown. Read projection derives `EXPIRED` without updating the fact.

## Interest authority

`CandidateInterestFact` independently appends `UNKNOWN`, `INTERESTED`, `CONDITIONAL`, or `DECLINED`. Conditional interest requires recorded conditions. Interest never implies availability or participation. Optional validity expiry is derived on read.

## Participation decisions

`CandidateParticipationDecision` independently appends `UNCONFIRMED`, `TENTATIVE`, `CONFIRMED`, `DECLINED`, or `WITHDRAWN` with source, observation time, actor, terms or reason, optional W3 evidence, and predecessor identity.

`TENTATIVE` and `CONFIRMED` require `reconfirm_by`. A passed boundary projects `NEEDS_RECONFIRMATION` and leaves the historical row unchanged. `CONFIRMED` additionally requires current W4/W5 validity, current unexpired `AVAILABLE` or `PARTIALLY_AVAILABLE` status, interest other than `DECLINED`, and explicit confirmation provenance. Partial availability also requires explicit confirmation conditions. `WITHDRAWN` requires the preceding effective decision to be tentative or confirmed.

Confirmation means an authorized member recorded a particular source. It does not claim independent verification, a signed contract, legal commitment, closed Gap, or compliant final team.

## Current and historical writes

Positive availability, positive interest, tentative participation, and confirmed participation revalidate active Membership and the current exact W4/W5 chain on every command. Historical `UNAVAILABLE`, `DECLINED`, and valid withdrawal events can still append after upstream staleness. All commands require an active Membership, including negative facts.

PostgreSQL triggers reject update and delete on the root and all three event tables. Corrections append a row and bind it to a predecessor within the same participation trail. GET projections return the latest recorded fact, derived effective state, expiry and reconfirmation disclosure, upstream staleness, and chronological safe history. Raw notes are not returned.

## Privacy and evidence links

Every W6 row carries Organization ownership and a composite Membership foreign key. A network shared Firm or Expert identity does not share participation data. List and detail reads filter by Organization and Pursuit before projecting any facts. There is no cross Organization capacity reconciliation or busy signal.

An optional confirmation evidence ID must resolve to a W3 DocumentVersion owned by the same Organization and Pursuit. W6 stores only the version identity and never exposes file bytes or private document metadata through participation responses.

## Team workspace

The W5 Team card now shows separate **FIT / EVIDENCE**, **AVAILABILITY**, **INTEREST**, and **PARTICIPATION** areas. A current shortlist has an explicit start action. Members can append availability, interest, participation, correction, decline, and withdrawal facts. The view shows source and observed date, expiry, reconfirmation, assignment window coverage, upstream staleness, same candidate reuse in the Pursuit, and chronological actor/source/supersession history.

The UI contains no invitation, email, SMS, Slack, or automatic external action.

## Assignment comparison and duplicate use

The projection compares the latest availability window with two ISO dates in the bound W4 Position and returns `FULL_WINDOW`, `PARTIAL_WINDOW`, `NO_OVERLAP`, or `UNKNOWN_DATES`. This is a factual comparison and does not rewrite W4/W5 or decide final qualification.

The same Firm or Expert can have independent roots for different CandidateMatches. The projection reports other record IDs for the same candidate inside the same Pursuit. W6 never merges them or resolves double counting.

## Routes and passivity

- `POST /api/v1/pursuits/{pursuit_id}/candidate-matches/{candidate_match_id}/participation-record`
- `GET /api/v1/pursuits/{pursuit_id}/participation-records`
- `GET /api/v1/pursuits/{pursuit_id}/participation-records/{record_id}`
- `POST .../{record_id}/availability-facts`
- `POST .../{record_id}/interest-facts`
- `POST .../{record_id}/decisions`

GET projection loads roots, W5 matches/searches/reviews, three fact streams, candidate identities, positions, and stale state set wise. The bounded list is capped at 100 roots and the permanent populated-list proof enforces a 16-query ceiling. Reads perform no writes, AI work, source HTTP, notification, or outreach.

The service is pursuit origin neutral. SOURCE and UPLOAD paths use the same W3/W4 sealed pack and W5 match authority; W4 permanent coverage proves both pack origins. W6 adds no origin branch.

## Operator limitation

The first release is member recorded. `OPERATOR_RECORDED` is a provenance category, but it does not grant tenant access. An operator can record for an Organization only when that user also has an active Membership selected through the normal Organization context. W6 adds no implicit operator tenant bypass.

## Preserved boundaries

- Firm, ProjectReference, Expert, CVVersion, CandidateSearchRun, CandidateMatch, and CandidateReviewDecision remain unchanged.
- W4 AnalysisRun, Requirement, Position, Gap, source quote, and assertions remain unchanged.
- World Bank Project Context, Project Leadership, procurement contacts, and participant history remain separate and never create participation.
- There is no TeamScenario, Gap closure, proposal evidence pack, candidate scraping, new source integration, model/provider change, AI pricing, or production deployment.

## Validation authority

Permanent coverage lives in `backend/test_w6_participation.py`, `frontend/tests/w6-participation.test.mjs`, and the `w6/participation-history` Chromium case. It covers reversible W5→W6 migration, exact shortlist identity, Firm and network shared Expert records, positive and terminal state guards, windows and derived expiry, reconfirmation, corrections, database immutability, staleness, revoked Membership, privacy, query bounds, World Bank fingerprints, UI separation, and absence of outreach.

The completed release evidence is: 832 backend tests passed, 1 skipped, and 100 nested subtests passed; 276 frontend static tests passed; TypeScript, ESLint, RTL, and the production Next.js build passed; 200 Chromium scenarios passed with no external requests; Alembic head, current, drift, and schema preflight checks passed; the 100,000-row performance proof stayed within 5 queries; dependency checks reported no broken Python requirements and no npm vulnerabilities; and `scripts/run_release_gate.sh all` exited successfully.

## W7 boundary

W7 may consume the contract in `docs/audits/w6/w7-team-scenario-contract.md`. It may create disclosed DRAFT scenarios from unresolved or tentative inputs. It must independently evaluate current Gap coverage, evidence, contribution rules, availability, confirmation freshness, overlapping assignments, duplicate candidate use, and unresolved assumptions before any ready or viable conclusion.
