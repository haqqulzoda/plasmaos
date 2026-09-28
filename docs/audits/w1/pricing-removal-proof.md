# W1 pricing removal proof

Baseline: `122e50b05760e3740845a744057cb6f2b4a11816`; W0 documentation and `.gitignore` edits were already present. The sole migration head remains `20260912_0001_s10_5_communications`.

| Surface | Prior active behavior | W1 boundary |
|---|---|---|
| Tender text and file analysis | Prompt/schema requested `estimated_cost_breakdown` | Both prompts and response schema request technical scope only. Existing AnalysisVersion snapshots remain untouched. |
| Strategic AI draft | Prompt/schema returned `suggested_price`, unit price and total; budget supplied as input | Prompt and schema omit commercial values and budget. Normal and fallback parsing validate to the price-free schema. |
| Proposal `ai-draft` | Read cached `our_price`; budget × 0.85 fallback; wrote `our_price`, `ai_items`, priced `line_items` | Cache is the new `price_free_draft` key. Response has no price. The route only appends price-free content and preserves legacy JSON keys. |
| Proposal `upload-tz` | Budget × 0.75 cost and × 0.85 bid; distributed unit prices | Writes only price-free scope under `price_free_draft`. Prior root fields remain. The route remains legacy and does not become a new upload authority. |
| Manual Proposal update | Customer supplies `our_price` or `items` plus optional margin/VAT | Manual arithmetic remains explicit-input only. New manual prices receive `commercial_price_origin=USER_ENTERED`; calculated items use `priced_items`. A generic `structured_data` replacement cannot overwrite the price or provenance marker. No source budget enters this arithmetic. |
| Bid Preparation UI | AI response filled a suggested-price input; historical `our_price` displayed as current | AI response cannot set the price input. Only values marked `USER_ENTERED` populate the input or list price. Otherwise the list says “Not set.” Scope rows have no generated prices. |
| PDF and DOCX | Read stored `our_price`, priced AI items and totals; distributed missing prices; inserted fixed payment/VAT/validity terms | A positive explicit request price is required. Exports use it and request delivery days, show source budget as a separate fact, and render scope without prices. New summaries come from `price_free_draft`; unsupported fixed terms were removed. |

## Provenance classes

- **SOURCE FACT:** `Tender.budget`, `Tender.currency`, and quoted source financial clauses. W1 leaves source rows and source refresh untouched.
- **USER ENTERED:** Current export request `price`; manual Proposal `our_price` and `items` submitted through PUT. The marker is assigned only on explicit manual updates.
- **ACTIVE AI GENERATED:** The removed `suggested_price`, cost breakdown, generated line prices and percentage-of-budget paths.
- **HISTORICAL GENERATED:** Existing `structured_data.our_price`, `ai_items`, `line_items`, `subtotal`, `grand_total`, old AnalysisVersion results and saved PDF/DOCX bytes. W1 performs no backfill or cleanup.
- **AMBIGUOUS:** An unmarked historical `our_price` may be AI generated or manually entered. W1 hides it from current-price presentation and does not infer its origin. A new explicit price is required to export.

The old upload preview name mismatch remains: upload writes a generated file name and preview resolves a Proposal-ID name. W3 must replace this with an authorized private document-version reference.

Legacy root-level summaries remain visible with a historical-text warning. Merely saving other edits does not promote that text into the new price-free draft; a new AI draft or an explicit summary edit is required before a fresh export includes it.

Regression guard: `backend/test_w1_product_truth.py` validates schema filtering, prompt shape, active-route absence of budget heuristics, export boundary, direct API provenance spoofing, provenance-gated UI, and locale copy. `backend/test_release_uploads.py` checks the live legacy upload route emits no price and preserves prior historical JSON fields.
