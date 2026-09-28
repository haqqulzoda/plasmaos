# W4 Staleness and Lineage

A sealed run remains valid for its historical inputs. Passive analysis reads recompute the current candidate SHA and compare it with the sealed candidate SHA. A difference returns 'inputs_changed=true' and the UI displays **INPUTS CHANGED / ANALYSIS MAY BE STALE**. No row from the old run changes.

Every explicit rerun creates a fresh pack, company snapshot, run, Requirement set, Position set, and Gap set. Explicit lineage can connect two Requirements or two Positions from distinct runs in chronological order. The actor Membership and rationale are recorded. There is no automatic lineage from normalized text, quote similarity, embeddings, or LLM output.

Tests change a private role and source analyzed text, prove stale detection, create a new immutable run, prove old row counts remain fixed, and append reviewer-recognized lineage.
