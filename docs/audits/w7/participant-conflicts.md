# W7 Participant Conflict Audit

Participant uniqueness is enforced per revision and Firm or Expert identity. The same Firm or Expert can retain several exact contributions without duplicate participant cards.

For one identity, W7 compares availability, interest, participation, and recorded conditions across all selected W6 records. Differences create `CONFLICTING_PARTICIPATION_FACTS` and prevent `VIABLE`.

For overlapping Expert assignments, known effort above 100 percent creates blocking `EXPERT_DOUBLE_COUNT`. Concurrent full-time capacity creates blocking `CONCURRENT_FULL_TIME_CONFLICT`. Missing dates or effort creates review issue `UNKNOWN_EFFORT`. Partial windows require review and no overlap blocks the scenario.

Firm contributions without meaningful Position assignment dates are evaluated through current corporate capacity and confirmation facts; W7 does not invent an Expert-style date requirement for them.

