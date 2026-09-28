# W6 Upstream Staleness

Starting a trail and every positive write recompute W5 staleness from the exact CandidateSearchRun, latest W4 AnalysisRun, and current W3/W4 candidate pack hash. They also require the latest W5 review to remain `SHORTLISTED`.

The historical root is never rebound. A newer W4 run, changed pack hash, stale W5 search, or later non shortlist review makes `upstream_stale=true` with a reason. Historical reads remain available. `UNAVAILABLE`, `DECLINED`, and semantically valid withdrawal history can still append, while all commands continue to require an active Organization Membership.
