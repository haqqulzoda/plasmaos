# Extraction-quality gate

Technical run status and extraction quality are separate persisted facts.

| Condition | Technical status | Quality |
| --- | --- | --- |
| Worker finishes and extraction is materially populated | `COMPLETED` | `READY_FOR_REVIEW` |
| Worker finishes but returns zero findings | `COMPLETED` | `NEEDS_ATTENTION` |
| Procurement-rich input returns implausibly few findings | `COMPLETED` | `NEEDS_ATTENTION` |
| Worker exhausts attempts/fails | `FAILED` | `FAILED` |

The deterministic anomaly check measures input characters and bounded occurrences of `QUALIFICATIONS`, `REQUIRED`, `MUST`, `SHALL`, `MINIMUM`, `BIDDER`, `PROPOSAL`, `SUBMIT`, `REFERENCES`, and `DEADLINE`. It creates no requirements and makes no compliance decision.

The persisted diagnostics are count-only: page and character counts, bounded signal counts, raw Requirement and Position counts, schema/provenance/normalization/duplicate counts, persisted Requirement/Position/Gap counts, and the quality result. Raw document text, prompts, and raw model responses are not exposed through the customer response.

For pre-P0 historical completed runs where the new fields are null, the read model safely derives `NEEDS_ATTENTION` when persisted requirements and positions are both zero. GET remains passive: it neither writes the derived state nor triggers parsing, AI, source fetch, or rerun.

A small non-procurement document with no findings also returns `NEEDS_ATTENTION`; importantly, the signal detector does not manufacture requirements. This conservative state avoids claiming successful coverage when no findings exist.
