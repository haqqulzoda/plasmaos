# W1 product truth and AI pricing removal

Baseline: `main` at `122e50b05760e3740845a744057cb6f2b4a11816` plus pre-existing W0 documentation and `.gitignore` work. Sole Alembic head: `20260912_0001_s10_5_communications`.

W1 removes active model-estimated costs, AI Proposal bid suggestions, 75%/85% budget heuristics, generated line prices, export price regeneration and unsupported fixed commercial terms. Tender budget remains a source fact. Manual price entry and explicit-input margin/VAT arithmetic remain customer authored. Existing commercial JSON, analyses, identifiers and exported files are preserved without migration.

Historical unmarked `our_price` has unknown origin and is hidden from current-price UI. New PDF/DOCX exports require a positive price explicitly supplied by the customer; they do not use historical prices or infer line prices. The legacy upload-preview filename defect remains for W3.

Company readiness and profile records are described as recorded information, not verified proof. Compliance verdict logic, World Bank Project/Leadership, source refresh, routes/navigation and deployment are outside W1 and unchanged.

Detailed evidence: [pricing-removal-proof](audits/w1/pricing-removal-proof.md), [evidence-language-audit](audits/w1/evidence-language-audit.md), [W2 ownership and ID contract](audits/w1/w2-ownership-id-contract.md).

## Validation (2026-09-25)

**PASS.** The permanent `scripts/run_release_gate.sh all` wrapper exited 0 against a disposable loopback PostgreSQL database and Redis container. Its final run reported:

| Gate | Result |
|---|---|
| Focused W1 pricing and upload regressions | 20 passed |
| Full backend, including Proposal, AnalysisVersion, Readiness/Compliance and communications | 810 passed, 1 skipped, 100 subtests passed |
| Security / analysis / connectors | 118 passed / 50 passed plus 12 subtests / 198 passed, 1 skipped plus 6 subtests |
| Maintained frontend tests | 247 passed, 0 failed; typecheck, lint, RTL audit and production build passed |
| Maintained Chromium | 145 passed, including locale, responsive, production passivity, authentication and upload cases |
| Alembic | sole head, current, check and schema preflight passed |
| Synthetic scale | 1,000, 10,000 and 100,000 row checks passed |
| Dependency gate | 24 passed, `pip check` clean, npm audit found 0 vulnerabilities |

The communications tests were also run directly against disposable loopback PostgreSQL: 10 passed. No production service or deployment was used.

## Exact W1 file set

- `.gitignore` (W1 documentation exceptions; pre-existing W0 exceptions retained).
- `backend/app/core/ai.py`, `backend/app/api/endpoints/proposals.py`, `backend/test_release_uploads.py`, `backend/test_w1_product_truth.py`.
- `frontend/app/dashboard/bid-preparation/page.tsx`, `frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx`, `frontend/types/bid-preparation.ts`.
- `frontend/messages/en/bidPreparation.json`, `frontend/messages/en/compliance.json`, `frontend/messages/uz/bidPreparation.json`, `frontend/messages/uz/compliance.json`, `frontend/messages/ru/bidPreparation.json`, `frontend/messages/ru/compliance.json`, `frontend/messages/ar/bidPreparation.json`, `frontend/messages/ar/compliance.json`.
- `frontend/tests/bid-preparation.test.mjs`, `frontend/tests/s8-3-arabic-rtl.test.mjs`, `frontend/tests/release-hardening-browser.py`.
- `docs/W1_PRODUCT_TRUTH_AI_PRICING_REMOVAL.md`, `docs/audits/w1/pricing-removal-proof.md`, `docs/audits/w1/evidence-language-audit.md`, `docs/audits/w1/w2-ownership-id-contract.md`.

The W0 documentation files were present before W1 and remain unstaged. W1 introduced no model, migration, route, navigation, source refresh or World Bank Project/Leadership change. The W2 contract is documentation only; the founder decisions in that document are required before W2 migration design is finalized.
