# W5 Candidate-Gap Contract

W5 may begin candidate retrieval only from a reviewed W4 Gap. Its stable handoff is:

- Gap UUID and immutable AnalysisRun UUID;
- Requirement UUID or Position UUID, exactly one;
- source AnalysisPackItem and exact evidence;
- effective reviewed coverage state;
- reviewed resolution category;
- missing contribution and rationale;
- latest assertion/reviewer context;
- explicit contribution rule where present.

W5 must reject stale or unresolved interpretation as an automatic eligibility decision. PARTNER_FIRM authorizes firm candidate retrieval only when the issued document or a reviewer explicitly permits that contribution. EXPERT authorizes expert candidate retrieval for Position gaps. COMPANY_EVIDENCE, CLARIFICATION, and HUMAN_INTERPRETATION do not authorize partner/expert matching by themselves.

W5 should preserve tenant isolation, sealed source provenance, model/version metadata, and append-only decisions. It should add availability and commitment only as separate reviewed authorities. It must not rewrite W4 Requirements, Positions, Gaps, or assertions.
