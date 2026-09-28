# W7 to W8 Proposal Handoff

## Exact input

W8 may request only one exact `TeamScenarioRevision`. The W7 handoff includes:

- exact `APPROVED_FOR_PROPOSAL` decision;
- AnalysisRun and AnalysisPack identities;
- immutable Gap assessments;
- unique participants and all exact contributions;
- CandidateMatch and CandidateParticipationRecord identities;
- exact availability, interest, and participation fact identities and snapshots;
- ProjectReference and CVVersion evidence identities;
- later stage obligation and source/private provenance counts;
- current viability and staleness result.

## Entry gate

W8 must obtain the handoff immediately before sealing its artifact. W7 rejects the handoff when approval is missing, the revision is stale, or current assessment is not `VIABLE`.

W8 must bind the revision and approval IDs, revalidate the returned current state, and preserve every evidence identity. It must never resolve a mutable “current scenario,” substitute a later revision, infer missing evidence, or carry an old approval to new facts.

W7 creates no Proposal Evidence Pack or proposal content.

