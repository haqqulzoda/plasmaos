# W7 Scenario Staleness Audit

On read, W7 compares the sealed revision with:

- current W4 AnalysisRun identity, pack input state, exact Gap set, review assertions, and effective Gap facts;
- current W5 effective review decision ID and state;
- current W6 availability, interest, participation decision IDs, derived effective states, freshness, and assignment-window result.

A difference returns `scenario_current=false` with explicit reasons and never updates the revision. A historical approval remains attached to its exact revision but cannot pass the proposal handoff gate. Consuming new facts requires a new revision.

