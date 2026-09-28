# P0R live semantic and trust coverage

Accepted live run: `01dfa335-b85c-4585-826e-438d40dad9b2`, sealed pack `f317c4cd-e1db-4170-82a8-0a24989fd937`.

## Source context

| Expected context | Live customer projection | Result |
| --- | --- | --- |
| Title | Communications Consultant | Pass |
| Buyer | Town of University Park | Pass |
| Reference | UP-2012-01 | Pass |
| Historical deadline | 2012-02-17 16:00 at `America/New_York` | Pass |

All six context suggestions carried `SOURCE_DETECTED` provenance.

## Required semantic coverage

| Semantic obligation | Live result |
| --- | --- |
| Communications Consultant role | Pass |
| 5+ years marketing communications | Pass |
| 2+ years web campaigns | Pass |
| Bachelor's degree required | Pass |
| Journalism/interview/media | Pass |
| Graphic design/layout | Pass |
| Video capability preferred, not mandatory | Pass |
| Non-profit knowledge preferred | Pass |
| Marketing automation/social media desired | Pass |
| Resume/profile | Pass |
| Work samples | Pass |
| Availability/hours | Pass |
| Hourly rate as customer-provided input | Pass |
| Legal/financial disclosure | Pass |
| Insurance | Pass |
| At least 3 references | Pass |
| 5-page maximum | Pass |
| Printed and electronic submission | Pass |
| Later-stage contract/Notice-to-Proceed obligations | Pass |

Coverage was 19 of 19 materially required meanings. Clauses were allowed to split or combine naturally; no exact row count was imposed.

## Trust acceptance

- State: `COMPLETED` / `FULL` / `READY_FOR_REVIEW`.
- Counts: requirements 15 raw, 15 verified, 15 persisted; position 1/1/1; gaps 12 persisted. The result therefore did not make a false no-gaps claim.
- Validation: schema rejects 0, provenance rejects 0, normalization drops 0, duplicates 0.
- Evidence: supported quotes and source contexts were retained; page locators 2, 4, 6, and 7 were all within the exact eight-page source.
- Qualification strength: mandatory, preferred, and desired distinctions all survived to the customer projection. Video and non-profit experience remained preferred rather than mandatory.
- Pricing boundary: no AI-generated hourly rate and no budget-derived pricing appeared. Hourly rate remained an RFP-requested customer input.
- Source integrity: one sealed item, exact source hash, 8 known pages, 16,594 characters, and no alternate content.
- Read passivity: repeated result/context GETs left every W4 table and run snapshot unchanged and invoked no provider.
