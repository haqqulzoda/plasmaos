# W6 Participation Authority

`CandidateParticipationRecord` binds one Organization and Pursuit to one exact immutable W5 CandidateMatch and shortlist decision. Its unique CandidateMatch constraint prevents parallel roots for the same match. The proposed contribution is snapshotted when the root starts and is never rebound.

Availability, interest, and participation decisions live in three separate append only tables. No current state column exists on the root. PostgreSQL triggers reject update and delete for the root and every child stream. A correction appends a new fact and references a predecessor in the same trail.

W6 never updates the candidate authority, W5 search or review authority, or W4 analysis authority. A newer W4/W5 chain requires a new CandidateMatch and therefore a new root.
