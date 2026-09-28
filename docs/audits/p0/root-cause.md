# P0 root-cause evidence

## Reproduction identity

- Source: `B4a Communications Consultant RFP.pdf` (the supplied, unmodified PDF)
- Source SHA-256: `88d34d5bce1685088d18e104de0c8a5325924cd23d9c0a1cb1f48b4587cd4a3b`
- DocumentVersion: `19e7d39e-6632-4273-892a-893bc0e6e972`
- Pursuit: `57daeab3-650c-43e5-bdbe-48e5683dd7e4`
- AnalysisPack: `e3c61fee-fa1c-4d2f-aac2-9d695ad8d525`
- AnalysisPackItem: `91ec0dc3-01ee-4f83-adbf-7f42c5e268b2`
- AnalysisRun: `470f76fd-b7d7-4423-ba97-5399c5a9117d`
- ProcessingResult: `0272773d-e88d-4fb9-92b6-21ec8f0035fb`
- Selected-pack SHA-256: `6e3f88d14c66703a3e771a0e9191605a61fe2261f26d4c5a60417e8802d76927`

This is local development evidence only. No production system was accessed.

## Pipeline trace

| Stage | Evidence | Outcome |
| --- | --- | --- |
| PDF | 176,299 bytes; source hash above | Intact |
| Parser | `pymupdf-local-ocr`; 8 known pages | Ready |
| Parsed text | 16,594 characters | Intact |
| Per-page text | 1: 362; 2: 2,598; 3: 2,978; 4: 2,492; 5: 2,339; 6: 2,461; 7: 2,701; 8: 561 characters | All pages present |
| Sealed pack | Text SHA-256 `8b8c971137f64dd972f469a2bd5b91ffc14f5e8bdc27ad23f5de67cf0c034c7b` | Identical to parsed input |
| Model input | All 16,594 sealed characters, including late-page Qualifications and Required Materials | Intact |
| Model | `google-gemini` / `gemini-3.1-pro-preview` | Returned JSON |
| Prompt | `pursuit_analysis_w4_v1`; SHA-256 `e050c19f81210ecb1c3f89da33548ed498e46ea49ce8ce0eeb65ed1425c0194a` | Reproduced |
| Schema/pipeline | `pursuit_analysis_output_w4_v1` / `pursuit_analysis_pipeline_w4_v1` | Reproduced |
| Raw response | 12,310 characters; SHA-256 `b1b1dcb2b7ed85f661c519574c67cca03e7211fb4d1558792e96e9e33cab83b5`; 5 requirement facts and 1 position fact | Materially non-empty |
| Schema validation | All 6 facts accepted | Passed |
| Quote/provenance validation | 6 of 6 rejected | Failed |
| Normalization | 0 facts dropped by semantic normalization | Not the loss point |
| Persistence | 0 requirements, 0 positions, 0 gaps, 0 review assertions | Received empty verified set |
| Terminal state | `COMPLETED` / `FULL` | Misleading without a quality state |

The raw private document text and full model response are deliberately not copied into logs or customer-visible data. The response hash, length, type counts, schema result, and per-stage rejection counts provide reproducible safe diagnostics.

## Exact failure classification

`QUOTE_VALIDATION_REJECTION`

The parser did not lose pages, the sealed pack did not lose text, the model did not return an empty result, and schema validation did not fail. The old verifier used literal substring checks. Two otherwise supported quotes differed only because one crossed a PDF page marker/running header and one crossed a layout line break. Four additional findings had valid source-context text whose spacing around section headings differed from the PyMuPDF layout. Every model fact was consequently removed before persistence.

The defect had a second trust consequence: the worker's technical completion was treated as extraction success even though zero findings survived. That made the customer UI capable of implying there were no gaps.

## Fix rationale

The verifier now performs deterministic evidence normalization for matching only: Unicode compatibility normalization, apostrophe/dash normalization, whitespace folding, and removal of recognized page-marker/running-header decoration. The matched normalized span is mapped back to exact offsets in the immutable sealed text, preserving source traceability. It does not use fuzzy similarity and does not admit text absent from the source.

An independent post-extraction quality state now prevents a technically completed but suspiciously empty result from being treated as ready. Count-only diagnostics record input size, bounded procurement signals, raw/verified/rejected/persisted counts, and the anomaly outcome without storing private source text.
