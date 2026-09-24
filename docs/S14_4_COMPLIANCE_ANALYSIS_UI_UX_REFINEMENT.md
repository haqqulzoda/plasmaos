# Sprint 14.4 — Compliance Analysis UI/UX Refinement

## 1. Status

Complete. This sprint is a frontend-only refinement of the
existing Compliance workbench. It does not alter the Compliance engine, model
configuration, prompts, classification rules, database schema, or production
state.

## 2. Mockup/report mapping

| Mockup/report element | Canonical authority | Support | Implementation decision |
| --- | --- | --- | --- |
| Tender/header context | `GET /tenders/{id}` | SUPPORTED | Use canonical title, external ID, source system, deadline, and source URL. |
| Beta state | Product contract | SUPPORTED | Restrained badge beside the page title. |
| Current AnalysisVersion | Latest/version-detail Compliance reads | SUPPORTED | Show exact selected immutable version. |
| Analysis language | `AnalysisVersion.analysis_language` and user default | SUPPORTED | Keep per-run selector separate from UI locale; show stored result language. |
| Summary metrics | `hybrid_compliance` and evidence filenames | SUPPORTED | Show verdict, reviewed count, canonical failed dealbreakers, canonical Vault-supported matches, and referenced source-document count. |
| Requirement statuses | `RequirementMatchDetail.verdict` | SUPPORTED | Preserve `FAILED`, `NEEDS_MANUAL_REVIEW`, and `SATISFIED` without reinterpretation. |
| Requirement categories | `RequirementMatchDetail.category` | SUPPORTED | Display and filter the recorded category verbatim. |
| Source document/page/section | Requirement evidence fields | SUPPORTED | Display only non-empty canonical values. |
| Source excerpts | `exact_quote` / `raw_text_snippet` | SUPPORTED | Render verbatim with automatic text direction before generated analysis. |
| Analysis explanation | `RequirementMatchDetail.reason` | SUPPORTED | Render as Plasma analysis in the stored analysis language. |
| Vault/readiness matches | Existing deterministic match fields | SUPPORTED | Show existing credential/evidence metadata as support, never as an invented pass. |
| Overrides/manual review | Existing owned override endpoints | SUPPORTED | Preserve explicit audited override on current versions only. |
| Version history | Owned AnalysisVersion list/detail endpoints | SUPPORTED | Preserve bounded pagination and exact-version selection. |
| Exact-version export/PDF | Existing Compliance export endpoint | SUPPORTED | Preserve `analysis_id` + `version_number` export and Arabic gate. |
| Language selection | Existing analysis run contract | SUPPORTED | Preserve EN/UZ/RU explicit-run selector. |
| Search | Loaded requirement fields | SUPPORTED | Client-side bounded search over title, requirement text, section, and filename. |
| Filters | Loaded verdict/category/source fields | SUPPORTED | Client-side filters with a complete reset. |
| Related requirements | No canonical relationship | UNSUPPORTED | Omitted; no client-side inference. |
| Link readiness record | No explicit linking endpoint/domain action | UNSUPPORTED | Omitted; a contextual route to Readiness Vault is used where canonical match metadata exists. |
| Notes | No Compliance-note model or ownership contract | UNSUPPORTED | Omitted; no local persistence. |
| Open document | Existing safe `/document-preview/{id}` route | SUPPORTED | Explicit user action only; retain filename and page when a PDF page is recorded. |

## 3. Page hierarchy

The page follows the approved sequence: tender context, Compliance heading and
Beta disclosure, canonical tender metadata/source action, compact summary,
search and filters, grouped requirement rows, and an evidence inspector. Existing
language, history, export, analysis-run, document, and override controls remain
discoverable without competing with the review workspace.

## 4. Beta implementation

The Beta badge is placed beside the page title with concise assistive text. No
large warning banner is introduced.

## 5. Summary

The previous decorative metrics/card stack is replaced by a text-led summary.
No compliance percentage, risk score, quality score, or inferred coverage count
is introduced.

## 6. Requirement grouping

- Critical gaps: canonical `failed_dealbreakers` only.
- Manual review: canonical `manual_reviews_required` only.
- Satisfied requirements: canonical `satisfied_requirements` only.
- Recorded obligations: preserved as their own canonical, non-pass group.

Unknown/manual-review results remain distinct from failed and satisfied results.

## 7. Requirement rows

Rows expose a stable review index, title, concise source-backed text, source
metadata, status, and selected state. Full evidence, analysis rationale, and
override actions live in the inspector.

## 8. Evidence inspector

Desktop uses a sticky inspector. Tablet/mobile use the existing accessible
drawer pattern. Selection preserves list position. Source evidence precedes and
is visually separated from Plasma analysis.

## 9. Evidence/source provenance

Document names, pages, sections, and excerpts come only from the immutable
analysis result. Missing values are omitted or labeled unavailable. Selecting a
requirement performs no document fetch; opening a document remains explicit.

## 10. Search/filter behavior

Search and filters operate on the already-loaded, bounded analysis snapshot.
Reset restores all statuses, categories, sources, and the empty query. A
selected requirement remains available in the inspector when filters change.

## 11. Readiness integration

Existing deterministic Vault evidence remains supporting evidence. The UI does
not claim that same-name or partial evidence guarantees compliance. No new link
persistence is added.

## 12. Related requirements/notes decision

Both are omitted because the repository has no canonical relationship model or
Compliance-note ownership contract.

## 13. AnalysisVersion/history/export preservation

Immutable history, exact-version reads, bounded pagination, integrity state,
and exact-version export remain unchanged.

## 14. Analysis-language preservation

The selected run language is captured explicitly. Stored analysis content uses
the immutable version language and is never derived from UI locale.

## 15. Overrides/manual review

Existing explicit overrides remain available for current failed dealbreakers
and continue to write through the audited override endpoint without rewriting
historical AnalysisVersion truth.

## 16. Loading/partial/error states

Summary, list, and inspector use local loading surfaces. Analysis, coverage,
history, document metadata, export, and override errors remain independently
reported. The previous saved result stays visible during a new explicit run.

## 17. Passivity/request/query budgets

Page load retains bounded existing reads and performs no AI, acquisition,
document-preview, or domain write. Search, filtering, selection, collapse, and
drawer actions are local. Source bytes are requested only after explicit open.

## 18. Responsive/locales/RTL/a11y

Validated at 320, 390, 768, and 1440 px for EN/UZ/RU/AR. All 16 combinations
stay within the viewport. Arabic uses the shared RTL contract and bidi islands;
source text remains automatic-direction content. Keyboard row selection,
focus restoration after drawer dismissal, non-color status labels, logical CSS,
and four representative EN/AR axe scans pass with zero serious/critical
findings.

## 19. Frontend/backend/browser/release totals

- Complete frontend static suite: 246/246 passed.
- Focused Sprint 14.4 static contract: 8/8 passed (included above).
- Focused backend Compliance ownership/version/read/language suite: 47/47
  passed; no backend production file was changed.
- Sprint 14.4 production-browser acceptance: 40/40 passed.
- Representative axe runs: 4/4 passed with zero serious/critical findings.
- TypeScript, focused ESLint, design-token, legacy-design, RTL, literal-copy,
  and optimized production-build gates passed.

## 20. Bundle impact

No new runtime dependency or image asset is introduced.

## 21. Exact files changed

Product and contract files:

- `.gitignore`
- `design-qa.md`
- `docs/S14_4_COMPLIANCE_ANALYSIS_UI_UX_REFINEMENT.md`
- `frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx`
- `frontend/components/customer/pages.css`
- `frontend/messages/{en,uz,ru,ar}/compliance.json`
- `frontend/tests/s14-4-compliance.test.mjs`
- `frontend/tests/s14-4-browser-acceptance.py`
- `frontend/tests/s14-4-visual-compare.py`

Selected checked-in QA evidence:

- `docs/audits/s14_4/design-comparison.png`
- `docs/audits/s14_4/browser/results.json`
- `docs/audits/s14_4/browser/compliance-en-{390,1440}.png`
- `docs/audits/s14_4/browser/compliance-ar-390.png`
- `docs/audits/s14_4/browser/compliance-{en,ar}-{390,1440}-axe.json`

## 22. Deliberate mockup deviations

- “Critical gaps” is used only for canonical failed dealbreakers.
- “Partial matches” becomes truthful manual-review wording.
- “Covered by readiness records” counts only canonical deterministic Vault
  support and is not treated as a compliance guarantee.
- Related requirements, readiness linking, and notes are omitted.
- Recorded obligations remain a separate group rather than being presented as
  matched requirements.

## 23. Remaining Compliance UI issues

No unresolved P0, P1, or P2 issue remains in the authorized Sprint 14.4
scope. Related-requirement relationships, Compliance notes, and readiness-link
persistence remain deliberately absent until their owning domain contracts
exist; these are product-boundary omissions, not hidden UI placeholders.

## 24. Sprint 14.5 entry contract

Sprint 14.5 is not started. Any future work must preserve all Sprint 14.4
passivity, provenance, immutability, language, export, ownership, and responsive
contracts.
