# W4 Coverage and Gap Semantics

| State | Meaning |
|---|---|
| SUPPORTED | Reviewed evidence supports the requirement. |
| PARTIAL | Some recorded support exists, but it is incomplete or not proven sufficient. |
| GAP | Recorded facts positively show a present failure. |
| EVIDENCE_MISSING | Records do not prove or disprove the requirement. |
| NEEDS_INTERPRETATION | A human must resolve a complex or ambiguous rule. |
| NOT_APPLICABLE | A reviewer determines the item does not apply. |
| LATER_STAGE_OBLIGATION | The obligation is outside the current decision stage. |

These states are constrained independently on Requirements, Positions, Gaps, and assertions. They are not mapped to legacy Compliance FAILED/SATISFIED values.

Company/readiness snapshots retain legacy record IDs and label each record as metadata-only or file-backed. A file reference alone stays PARTIAL; missing data is EVIDENCE_MISSING; an explicit matching missing/expired record may be GAP. Shared partner contribution requires explicit issued-document language. Lead-only stays COMPANY_EVIDENCE; unclear member allocation becomes NEEDS_INTERPRETATION/HUMAN_INTERPRETATION.
