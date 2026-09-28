# Real-RFP golden benchmark

The permanent benchmark uses a repository-safe deterministic text fixture derived from the unmodified parsed output of the supplied eight-page PDF: `backend/tests/fixtures/communications_consultant_rfp.txt`. The source PDF itself remains outside the repository.

## Input coverage

The fixture asserts ordered page markers 1 through 8 and source text from the beginning, middle, and end of the document. It proves the analyzer input contains Town of University Park, contract UP-2012-01, the historical deadline, submission requirements, scope, Qualifications, Bachelor's degree, Required Materials, three professional references, and the five-page limit. The check is not satisfied by page count alone.

## Semantic coverage

The benchmark sends schema-valid facts through the real quote/source-context validator and asserts materially non-empty verified output. It covers:

- Communications Consultant as a role, with individual/firm applicability preserved as `NEEDS_INTERPRETATION` and `HUMAN_INTERPRETATION`.
- Mandatory minimum five years of marketing communications experience.
- Mandatory minimum two years of web-based marketing campaign experience.
- Mandatory bachelor's degree, journalism/interviewing/media experience, and graphic-design/layout experience.
- Preferred video shooting/editing knowledge and preferred non-profit knowledge.
- Marketing automation/social-media experience as desired, not mandatory.
- Resume or corporate profile, communication/media samples, monthly hours and availability, administrative expenses, legal/financial disclosure, insurance acknowledgement, at least three references, five-page maximum, and printed plus electronic delivery.
- Hourly rate as bidder/customer-provided commercial input. The fixture explicitly rejects generated, recommended, suggested, or budget-derived pricing.
- Contract execution after award and work after Notice to Proceed as `LATER_STAGE_OBLIGATION`.
- Required referenced bid artifacts as `EVIDENCE_MISSING` when the pack contains no matching artifact; nothing is invented and extraction continues.

The test intentionally avoids one exact row count. Correct clause splitting or combination may evolve while all required semantics remain enforced.

## Provenance result

The cross-page qualification block and layout-wrapped proposal clauses pass deterministic normalized matching while retaining offsets and page locators into the original sealed text. Hallucinated or reordered evidence still fails because normalized matching remains an exact ordered substring test.

## Live-provider qualification

The provider and model were deliberately unchanged. Two post-fix live rerun attempts exceeded a 600-second local timeout before returning a new model response. The permanent gate therefore relies on the captured real parser output and deterministic schema/provenance/persistence path, not on a nondeterministic external call. A responsive-provider staging canary remains recommended before production rollout.
