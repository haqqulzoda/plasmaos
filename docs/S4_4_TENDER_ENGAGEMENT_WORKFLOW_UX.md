# Sprint 4.4 — Tender Engagement Workflow UX

## 1. Workflow Objective

Sprint 4.4 makes the canonical TenderEngagement lifecycle operable through explicit customer commands. My Tenders is the pursuit surface, Bid Preparation remains a Proposal artifact surface, and Tender Details receives only a compact pursuit summary. No command claims that Plasma transmits a bid or verifies an award.

## 2. Canonical State Machine

The authoritative states remain `SAVED`, `EVALUATING`, `PREPARING`, `SUBMITTED`, `WON`, `LOST`, and `DISMISSED`. The identity remains `(user_id, company_profile_id, tender_id)`. The service locks the owned row, validates the transition, updates `status`, `status_changed_at`, and `updated_at`, and leaves `origin` unchanged.

There is no event ledger or milestone timestamp schema. `status_changed_at` truthfully means the time the current status was explicitly recorded; it is not an external portal timestamp.

## 3. Transition Matrix

Normal Sprint 4.1 transitions:

| From | Allowed normal targets |
|---|---|
| SAVED | EVALUATING, PREPARING, DISMISSED |
| EVALUATING | SAVED, PREPARING, DISMISSED |
| PREPARING | SAVED, EVALUATING, SUBMITTED, DISMISSED |
| SUBMITTED | WON, LOST |
| WON | none |
| LOST | none |
| DISMISSED | SAVED, EVALUATING, PREPARING |

Explicit corrections:

| From | Allowed correction targets |
|---|---|
| SUBMITTED | PREPARING |
| WON | SUBMITTED, LOST |
| LOST | SUBMITTED, WON |

The customer action contract deliberately does not turn every technical edge into a primary button. In particular, the existing Save command remains non-downgrading, while Prepare retains the Sprint 4.3 higher-state preservation rule.

## 4. Action Commands

Audit and resulting command surface:

| Action | Canonical service command | API | UI | Allowed source states | Result |
|---|---|---|---|---|---|
| Save | `save_tender_to_my_tenders` | `POST /tenders/{tender_id}/engagement` | Explorer/Details/Resume | none, DISMISSED; higher states preserved | SAVED or unchanged |
| Evaluate | `evaluate` | `POST /my-tenders/{engagement_id}/actions/evaluate` | shared workflow controls | SAVED, DISMISSED | EVALUATING |
| Prepare Bid | `prepare_bid` + canonical status service | `POST /proposals/prepare` | shared workflow controls | none, SAVED, EVALUATING, DISMISSED; PREPARING reused | PREPARING + one Proposal; higher states preserved |
| Mark Submitted | `mark_submitted` | `POST .../actions/mark-submitted` | shared workflow controls | PREPARING | SUBMITTED |
| Record Won | `mark_won` | `POST .../actions/mark-won` | shared workflow controls | SUBMITTED | WON |
| Record Lost | `mark_lost` | `POST .../actions/mark-lost` | shared workflow controls | SUBMITTED | LOST |
| Dismiss | `dismiss` | `POST .../actions/dismiss` | secondary action | SAVED, EVALUATING, PREPARING | DISMISSED |
| Correct submission | `correct_tender_engagement_status` | `POST .../actions/correct-to-preparing` | secondary confirmed action | SUBMITTED | PREPARING |
| Correct outcome | same correction service | `POST .../actions/correct-to-submitted`, `correct-to-won`, `correct-to-lost` | secondary confirmed action | WON/LOST according to matrix | corrected status |

Every action request includes `expected_status`. A locked-row mismatch or invalid transition returns `409`; foreign or missing engagement identity returns `404`. Responses include the safe engagement summary and backend-derived `allowed_actions`.

## 5. Save

Save creates `SAVED`, re-engages `DISMISSED` as `SAVED`, and does not downgrade EVALUATING, PREPARING, SUBMITTED, WON, or LOST. Concurrent creation still uses the canonical unique key and PostgreSQL conflict handling.

## 6. Evaluate

Evaluate is an explicit action from SAVED or DISMISSED. It creates no Proposal, Compliance Analysis, Project, or source-side mutation.

## 7. Prepare Bid

The Sprint 4.3 transactional Prepare/Continue path is unchanged. It creates or reuses exactly one owned Proposal and one engagement, advances eligible lower states to PREPARING, and preserves SUBMITTED/WON/LOST.

## 8. Mark Submitted

Only an explicit command from PREPARING records SUBMITTED. A Proposal is not required. Proposal completion, export, Compliance, Tender status, and deadlines never call this command.

## 9. Won / Lost

WON and LOST are explicit outcomes recorded from SUBMITTED. The UI states that this records the outcome in Plasma and does not imply authoritative source verification, revenue creation, or CRM behavior.

## 10. Dismiss

Dismiss means the company is not currently pursuing the Tender. It changes only the engagement state and does not delete the Tender, engagement, Proposal, Bid Preparation content, Compliance Analysis, Project, or audit data.

## 11. Resume

DISMISSED exposes Save again, Evaluate, and Prepare Bid according to the established matrix. All paths reuse the same canonical engagement row.

## 12. Corrections

Submission and outcome corrections are secondary actions with explicit confirmation. They use only the Sprint 4.1 correction matrix and cannot silently rewrite a non-existent history ledger.

## 13. Proposal Independence

Proposal `COMPLETED`, legacy Proposal `SUBMITTED`, PDF generation, and DOCX export do not mutate engagement status. A Proposal-only legacy record remains outside My Tenders until explicit Continue. SUBMITTED/WON/LOST are representable without a Proposal.

## 14. Compliance Independence

Compliance reads and analysis commands remain independent and contain no TenderEngagement writer.

## 15. Source Status Independence

Tender OPEN/CLOSED/CANCELLED and deadline state remain source facts. They do not infer dismissal, submission, win, or loss. Mixed source/engagement combinations remain representable.

## 16. My Tenders UX

Rows retain separate engagement and Tender badges, Tender, buyer, deadline, source, optional Project context, filters, counts, search, sorting, and pagination. Primary actions are state-aware; dismissal and corrections are secondary. Successful mutations refetch list rows and counts. Background mutation refresh preserves the row long enough to show a stale-state explanation.

`ACTIVE` remains every engagement except DISMISSED, including WON and LOST. This preserves Sprint 4.2 semantics.

## 17. Tender Details Integration

Tender Details now has one compact Tender pursuit panel with current status, concise explanation, relevant workflow controls, My Tenders link, and Bid Preparation link when an owned Proposal exists. Existing source, Compliance, Project, and other detail sections are unchanged.

## 18. Bid Preparation Context

Bid Preparation displays the same canonical pursuit panel, but all mutations call the engagement or Prepare APIs. Proposal-only legacy detail remains passive and offers explicit Continue Bid Preparation.

## 19. Concurrency

Real PostgreSQL 16 results:

- PREPARING → SUBMITTED versus DISMISSED: one commit, one conflict;
- SUBMITTED → WON versus LOST: one commit, one conflict;
- duplicate Mark Submitted: one commit, one conflict;
- DISMISSED → SAVED versus PREPARING: one commit, one conflict;
- zero duplicate logical keys and zero missing status timestamps;
- no partial mutation and no unexplained server error.

## 20. Tenant Security

All commands first resolve an engagement through the current user and owned CompanyProfile, then lock it through the full canonical identity. Same-name foreign tenant mutation returns not found. Approved-access dependencies continue to deny pending, rejected, disabled, and stale credentials. Platform admin status does not grant customer engagement access or impersonation.

## 21. Browser Acceptance

Real Chromium passed 35/35: complete progression, dismiss/resume, all corrections, exact submission wording, legacy Continue, Proposal/Compliance/export/source independence, stale 409 refresh, counts/filter refresh, tenant isolation, revoked credentials, shared Tender Details/Bid Preparation context, passive reads, and no-Proposal submission/outcome.

Sprint 4.2 browser regression passed 15/15 and Sprint 4.3 browser regression passed 20/20.

## 22. Static Audits

- Status writer: the only runtime assignment is inside `app/services/tender_engagements.py`; list query equality is read-only.
- Submission: the only engagement SUBMITTED target is the canonical `mark_submitted` helper.
- Outcomes: the only WON/LOST targets are canonical explicit helpers/corrections.
- Copy: no customer runtime occurrence of `Submit Bid`, `Submit Tender`, automatic submission/outcome claims, or `My Bids` remains.
- Route identity: Bid Preparation uses Proposal ID; Tender Details and Compliance use Tender ID.

## 23. Regression Results

- Sprint 4.1/4.2/4.3/4.4 focused contracts: 39 passed.
- Sprint 4.1 PostgreSQL: fresh/existing/concurrency passed; Alembic clean.
- Sprint 4.2 PostgreSQL: 150 representative engagements passed; Alembic clean.
- Sprint 4.3 PostgreSQL: 118 Proposal fixture passed; Alembic clean.
- Sprint 4.4 PostgreSQL: full workflow and four concurrency cases passed; Alembic clean.
- Sprint 3: 49 tests plus 54 subtests; all disposable scripts passed.
- Sprint 2: 35 tests; all disposable scripts passed.
- Sprint 1/WB: 51 tests; all disposable scripts passed with one existing Alembic deprecation warning.
- Connector gate: 195 passed, one approved fixture skip, four subtests passed.
- Frontend: TypeScript, production build, and 19 focused tests passed; ESLint zero errors and 15 pre-existing warnings.

The local read-only preflight completed safely. It reports 118 Proposals (110 valid owner/Tender/Profile relationships, eight owners without profiles) and no Proposal duplicates or broken user/Tender references. The configured local development database remains intentionally at `20260828_0002_s3_4_admin_audit_hardening`, so its TenderEngagement table is absent; no repair or upgrade was attempted.

## 24. Deferred Sprint 5 Work

Full Tender Details consolidation, Hunter/Explorer merge, recommendation ML, automatic submission, award synchronization, collaborative workspace, event timeline, and CRM pipeline remain deferred.

## 25. Sprint 4 Release Considerations

Repository migration head remains `20260828_0003_s4_1_tender_engagement_foundation`; no Sprint 4.4 migration was added. Disposable fresh and representative databases reached the head and passed `alembic check`. Before release, the normal controlled deployment process must upgrade non-current environments; this sprint did not deploy or mutate production.

Sprint 4.4 files:

- `backend/app/services/tender_engagements.py`
- `backend/app/services/my_tenders.py`
- `backend/app/schemas/engagement.py`
- `backend/app/api/endpoints/my_tenders.py`
- `backend/app/api/endpoints/proposals.py`
- `backend/test_s4_4_tender_engagement_workflow_ux.py`
- `backend/test_s4_4_workflow_postgresql.py`
- `backend/scripts/test_s4_4_tender_engagement_workflow_ux.py`
- `frontend/types/engagement.ts`
- `frontend/components/tenders/EngagementWorkflowActions.tsx`
- `frontend/components/tenders/TenderEngagementPanel.tsx`
- `frontend/app/dashboard/my-tenders/page.tsx`
- `frontend/app/dashboard/tenders/[tenderId]/page.tsx`
- `frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx`
- `frontend/tests/engagement-workflow.test.mjs`
- `frontend/tests/engagement-workflow-browser-acceptance.py`
- `frontend/tests/my-tenders-browser-acceptance.py`
- `frontend/tests/bid-preparation-browser-acceptance.py`
- `frontend/package.json`
- `docs/S4_4_TENDER_ENGAGEMENT_WORKFLOW_UX.md`
