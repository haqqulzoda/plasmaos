# W8 Pack Sealing Audit

## Gate

Sealing accepts exact `scenario_id`, `revision_id`, and `approval_decision_id`. The server resolves the active Membership and the authoritative W7 proposal handoff. The latest decision for the exact revision must be `APPROVED_FOR_PROPOSAL`; an older approval cannot authorize a newer decision state or revision.

## Transaction boundary

PostgreSQL locks cover the Membership and W4 through W8 authority tables before the handoff is read. After inserting the immutable snapshot, the service reloads and compares the handoff immediately before commit. A changed revision, decision, current flag, viability state, or upstream identity aborts the transaction.

## Database enforcement

Composite foreign keys retain Organization and Pursuit lineage. Unique constraints assign one workspace per Organization Pursuit and monotonic pack versions. Database triggers reject update/delete on packs, items, and artifacts. The permanent test proves a direct SQL mutation fails.
