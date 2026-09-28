# W6 Participation Contract

## Stable W5 input

W6 may start only from:

- immutable `CandidateMatch.id`;
- immutable `CandidateSearchRun.analysis_run_id` and `gap_id`;
- exactly one Firm or Expert identity;
- proposed contribution, including the latest append only reviewer correction;
- candidate evidence state and qualification state;
- an effective `SHORTLISTED` review decision.

## W6 additions

W6 owns separate append only participation facts for availability window, proposed effort or capacity, interest, confirmation source and date, tentative or confirmed participation, unavailability, and withdrawal.

## Forbidden rebinding

W6 must not mutate CandidateSearchRun, CandidateMatch, the candidate authority, W4 analysis, or W4 Gap. A new or changed W4 analysis requires a new W5 search and a new W6 participation trail. W6 must preserve the distinction between capability evidence, availability, agreement, and final team compliance.

## Entry recommendation

Begin W6 with a `CandidateParticipationRecord` authority keyed to CandidateMatch and Organization, an append only event history, explicit confirmation provenance, expiry rules, and revocation/withdrawal semantics. Add no outbound invitation until identity, consent, delivery, and audit controls are separately accepted.

