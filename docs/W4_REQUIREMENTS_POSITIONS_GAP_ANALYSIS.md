# W4 — Exact-Version Requirement, Position, and Reviewed Gap Analysis

- **Status:** implemented and release-gate verified
- **Baseline:** accepted W3
- **Alembic head:** '20260927_0001_w4_pursuit_analysis'
- **Production access or deployment:** none

## Scope

W4 turns an explicitly reviewed document selection into a sealed, replayable analysis for either a SOURCE or UPLOAD pursuit. It extracts source-linked corporate Requirements and required Positions, compares corporate Requirements with an immutable snapshot of recorded company/readiness claims, persists unresolved Gaps, and records human review without changing machine output or source evidence.

W4 does not add firm or expert retrieval, availability, commitment, team scenarios, proposal evidence packs, source expansion, model/provider switching, or AI pricing.

## Explicit pack review and sealing

'GET /api/v1/pursuits/{pursuit_id}/analysis-pack-candidate' is a passive read. It displays official/source documents and organization-private exact versions with role, provenance, readiness, page-count truth, content and processing identities, and duplicate/revision warnings. Ready documents may be recommended by default, but the checkboxes submitted to 'POST /api/v1/pursuits/{pursuit_id}/analysis-runs' are authoritative.

The POST re-reads the candidate and requires the submitted candidate SHA to match. It verifies the active Membership, exact pursuit organization, current exact private version, processing-result identity/hash, clean malware result, READY full extraction, source text snapshot hash, and analysis limits. It then commits an immutable AnalysisPack, its replayable items, company snapshot, and queued AnalysisRun before dispatch.

Private items bind PrivateDocument, exact immutable DocumentVersion, version number, content SHA, role, processing-result ID/hash, analyzed-text SHA, and private provenance. Source items bind TenderDocument, source identity and content hashes, copied analyzed text, analyzed-text SHA, source URL, observed time, role/file type, and shared-source provenance. A later private revision or source refresh cannot change either sealed item.

PostgreSQL triggers reject update or delete of packs, pack items, company snapshots, Requirements, Positions, Gaps, review assertions, and lineage records.

## Admission and limits

- Known PDF pages are summed exactly. A total above 500 is rejected. No input is truncated.
- An input with unknown rendered pages retains 'page_count_known=false'. FULL analysis is admitted only while the whole selected pack is at or below the documented conservative 1,500,000 extracted-character alternate limit. The result discloses that rendered-page measurement was unavailable.
- PARTIAL, failed, infected, unscanned, empty, inaccessible, mismatched, or race-changed inputs are rejected for FULL analysis with a remedy-bearing conflict response.
- W4 implements no partial-analysis mode, so it cannot label partial parser/OCR content complete.
- Customer-selectable analysis languages are English, Uzbek, and Russian. UI locale remains independent. Arabic analysis selection remains gated by the existing product policy.

## Durable analysis execution

AnalysisRun is the pursuit-scoped execution authority and references one sealed pack. It records organization, pursuit, requesting Membership, analysis language, state, model/provider, prompt/schema/pipeline versions, attempt and dispatch counters, lease and heartbeat, timestamps, failure stage/reason, and result completeness.

The dedicated 'pursuit_analysis' Celery queue uses late acknowledgement, bounded concurrency, a five-minute renewable lease, at most three database-authoritative attempts, and a ten-second recovery sweep. A committed queued job remains discoverable if broker publication fails. An expired running lease is recoverable. Completed and failed runs are terminally idempotent. Analysis reads only copied pack text and makes no source HTTP request.

## Requirements and Positions

Each Requirement has a stable UUID and exact AnalysisPackItem, verbatim quote, optional verbatim heading/table/list context, character span, truthful page or paragraph locator, normalized statement, category/type/stage, mandatory/scored/informational distinction, structured predicate, explicit contribution rule, coverage state, confidence, provisional review state, and visibly generated interpretation.

The structured predicate retains operator, numeric threshold, unit, condition, and exception. The extraction prompt requires preference, scoring, shared preambles, table context, lead firm, JV/member, and subconsultant distinctions to remain explicit. A quote and optional source context are verified locally against sealed text before persistence. Complex or unclear rules use NEEDS_INTERPRETATION.

Positions are stored separately with title, quantity, mandatory/scored distinction, education, general and specific experience, relevant assignments, languages, certifications, location/travel, effort, dates, and the same exact evidence contract. Corporate experience is never written as personal experience, and company records never become CV evidence. Expert matching is deferred to W5.

## Coverage and Gaps

W4 uses new pursuit coverage semantics and does not translate them through legacy Compliance verdicts:

- SUPPORTED: reviewed evidence supports the requirement.
- PARTIAL: recorded support addresses only part of the rule or attached material has not been proven sufficient.
- GAP: recorded facts positively establish a current-stage failure, such as a matching item explicitly marked missing or expired.
- EVIDENCE_MISSING: current records neither prove nor disprove the requirement.
- NEEDS_INTERPRETATION: a complex, ambiguous, or contribution-dependent rule needs a human decision.
- NOT_APPLICABLE: a reviewer determines that the item does not apply.
- LATER_STAGE_OBLIGATION: the duty applies after the current decision and does not block it.

Company/readiness comparison uses an immutable snapshot with original legacy record IDs and an explicit METADATA_ONLY or FILE_BACKED basis. Metadata is never presented as verified proof. A matching file reference remains PARTIAL until its contents are shown to prove the rule. Missing records produce EVIDENCE_MISSING, while explicit missing/expired records may produce GAP.

Persistent Gaps point to exactly one Requirement or Position and retain source pack evidence, the missing contribution, state, rationale, provisional review state, and one resolution category: COMPANY_EVIDENCE, PARTNER_FIRM, EXPERT, CLARIFICATION, or HUMAN_INTERPRETATION. Partner resolution is used only for an explicit shared-contribution rule. Lead-only rules remain company evidence; unclear lead/member eligibility requires human interpretation.

## Human review, reruns, and staleness

Reviewer actions append immutable assertions with actor Membership, exact run, target, prior and new coverage/review states, corrected normalized fields, reason, timestamp, and an optional pointer to the preceding assertion. Machine fields, sealed evidence, and original quotes never change. The read projection applies the latest assertion while returning both machine and effective values.

A rerun always creates a new pack and run. Requirements, Positions, and Gaps from older runs remain unchanged. Explicit lineage can connect reviewer-recognized Requirements or Positions across distinct runs; no text similarity or model output creates lineage automatically.

Latest and exact-run GETs compare the current passive candidate SHA with the sealed candidate SHA. A mismatch displays **INPUTS CHANGED / ANALYSIS MAY BE STALE** and explains that the historical result remains valid only for its sealed inputs.

## UI and compatibility

'/dashboard/pursuits/{id}' now has a real Requirements section. It contains the exact pack review, analysis-language selection, run state and limit disclosure, stale-input banner, current-stage Gaps, grouped coverage states, required Positions, source-first evidence inspector, generated interpretation, and review controls. It contains no compliance/readiness percentage, universal risk score, fake match score, partner search, or expert search.

Historical TenderAnalysis, immutable AnalysisVersion, Compliance routes/deep links, exports, source Tender details, Project Context, Project Leadership, leadership provenance, and procurement-contact separation remain unchanged. W4 neither imports legacy verdicts into Gap semantics nor treats a Project leader as required-personnel evidence.

## API surface

- 'GET /api/v1/pursuits/{id}/analysis-pack-candidate'
- 'POST /api/v1/pursuits/{id}/analysis-runs'
- 'GET /api/v1/pursuits/{id}/analysis-runs/latest'
- 'GET /api/v1/pursuits/{id}/analysis-runs/{run_id}'
- 'POST /api/v1/pursuits/{id}/analysis-runs/{run_id}/reviews'
- 'POST /api/v1/pursuits/{id}/analysis-lineage'

All GETs are passive: zero AI calls, parsing, source HTTP, acquisition, or mutation. Analysis starts only from the explicit POST.

## Verification artifacts

- [Analysis pack sealing](audits/w4/analysis-pack-sealing.md)
- [Requirement provenance](audits/w4/requirement-provenance.md)
- [Position extraction](audits/w4/position-extraction.md)
- [Coverage and Gap semantics](audits/w4/coverage-gap-semantics.md)
- [Reviewer assertions](audits/w4/reviewer-assertions.md)
- [Staleness and lineage](audits/w4/staleness-lineage.md)
- [World Bank preservation](audits/w4/world-bank-preservation.md)
- [W5 candidate-gap contract](audits/w4/w5-candidate-gap-contract.md)

## Final verification

The permanent 'scripts/run_release_gate.sh all' wrapper passed against disposable PostgreSQL/Redis and isolated private storage on 2026-09-26.

- Backend: 825 passed, 1 skipped, 100 subtests passed.
- Focused security: 118 passed.
- Focused analysis: 50 passed, 12 subtests passed.
- Connector regressions: 198 passed, 1 skipped, 6 subtests passed.
- Alembic: heads, current, check, and schema preflight passed at '20260927_0001_w4_pursuit_analysis'. W3 downgrade and W4 re-upgrade also passed in the W4 migration test.
- Scale: passed at 1,000, 10,000, and 100,000 records with bounded query counts.
- Frontend: typecheck, lint, 263 tests, RTL audit, and production build passed.
- Chromium: 198 passed, 0 failed, with zero external requests. This includes the explicit W4 pack-review and review-assertion flow.
- Dependencies: 'pip check' found no broken requirements; 'npm audit --audit-level=high' found zero vulnerabilities.
- Compose: 'docker compose config --quiet' passed with synthetic required secrets.
- Formatting: W4 source and documentation files passed targeted whitespace checks; frontend lint and type checks passed.
- Cleanup: disposable PostgreSQL/Redis containers, anonymous test volume, isolated storage, and browser artifacts were removed after verification.
- Production access or deployment: none.
