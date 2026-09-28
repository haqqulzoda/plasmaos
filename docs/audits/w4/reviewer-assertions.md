# W4 Reviewer Assertions

Machine Requirements, Positions, Gaps, and their source evidence are immutable. Human review appends 'pursuit_analysis_review_assertions' with:

- actor Membership and organization;
- exact AnalysisRun;
- exactly one Requirement, Position, or Gap target;
- prior and new coverage/review states;
- corrected normalized fields;
- reason and timestamp;
- the preceding assertion when one exists.

The projection returns original machine values and separately calculated effective values from the latest assertion. It never updates source quotes or model output. Database triggers also make assertions append-only.

The API permits confirmation, corrected normalized facts, all seven coverage states including not applicable and later-stage, and recorded interpretation through corrected fields plus rationale. Evidence and identity fields are explicitly rejected from correction payloads.
