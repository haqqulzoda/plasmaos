# W8 Legacy Proposal Compatibility Audit

The legacy `Proposal` model and Bid Preparation routes remain the authority for historical commercial preparation. W8 adds separate tables, APIs, storage, and UI state. It neither imports `our_price` nor dual-writes legacy Proposal data.

For an exact SOURCE Pursuit, the workspace can return the current user's existing legacy Proposal UUID as a compatibility link. Historical UUIDs, structured data, old artifacts, and deep links retain their meaning. The permanent test fingerprints the legacy Proposal row count across SOURCE and UPLOAD W8 flows.
