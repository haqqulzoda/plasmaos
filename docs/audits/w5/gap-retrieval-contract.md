# W5 Gap Retrieval Contract

Candidate retrieval starts only through explicit POST and binds the latest effective reviewed GAP assertion.

Firm retrieval requires effective `PARTNER_FIRM`, a Requirement target, eligible effective coverage, and issued or reviewer corrected language that explicitly permits a joint venture, consortium, partner, member, subconsultant, or combined contribution.

Expert retrieval requires effective `EXPERT` and a Position target. Unsupported resolution categories and unresolved interpretation are rejected before a search row is created.

The source AnalysisRun's sealed candidate hash is compared with the current pursuit candidate hash. A mismatch blocks a new search. A newer W4 run or changed hash marks historical results stale without rebinding or deleting them.

Search is PostgreSQL-only, caps the retrieval pool at 100 and persisted matches at 20, and never performs source scraping or an AI call.

