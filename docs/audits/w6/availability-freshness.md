# W6 Availability Freshness

Positive availability has an explicit observation, provenance source, and `valid_until`. If W4 provides two ISO assignment dates, a positive Expert fact also requires an explicit availability window. Unknown dates remain unknown.

The read projection compares the latest window with the W4 Position and returns `FULL_WINDOW`, `PARTIAL_WINDOW`, `NO_OVERLAP`, or `UNKNOWN_DATES`. When `valid_until` has passed it returns effective `EXPIRED` while retaining the recorded status and row.

Tentative and confirmed participation use `reconfirm_by`. A passed boundary returns effective `NEEDS_RECONFIRMATION`; it never withdraws or rewrites a decision.
