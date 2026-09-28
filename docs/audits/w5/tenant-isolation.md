# W5 Tenant Isolation

All private library reads use the active Organization context. Search runs also carry Organization and Pursuit composite foreign keys plus an actor Membership composite foreign key. Reviewer decisions carry the same Organization and actor binding.

The permanent two-Organization test proves Organization B cannot list Organization A's private Firm, Expert, ProjectReference, or CVVersion and cannot read A's CandidateSearchRun, CandidateMatch, or review history. Cross-tenant identifiers return no resource.

Network shared records are ownerless, require explicit permission, and expose safe schema fields only. Shared Experts require explicit consent or a contractual basis. Private notes never appear in library or match responses.

GET services execute reads only. They do not call source HTTP, AI, scraping, outreach, or mutation paths.

