# P1 workspace hierarchy audit

## Information architecture

The workspace exposes one tablist and one active tabpanel:

1. Overview — identity, next action, context, source project facts, and analysis-derived tender summary.
2. Requirements — analysis pack control, quality state, gaps, requirements, and positions.
3. Team — partner needs, expert needs, participation, and then team options.
4. Documents & Evidence — official/source documents and organization-private documents as separate groups.
5. Proposal — approved team selection, immutable evidence packs, and exports.

Only the active heavy panel mounts. Overview is therefore not burdened by candidate, participation, proposal-workspace, or export reads. Source tender details load only for a SOURCE pursuit on Overview; the analysis-pack candidate loads in Documents only when that tab is opened.

The header next action derives from authoritative processing, extraction quality, reviewed-gap, participation, scenario viability, and approval projections. It moves the customer to the relevant tab without inventing a new workflow state.
