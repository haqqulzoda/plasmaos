# W2 legacy compatibility audit

## Permanent identifier mapping

Every valid historical TenderEngagement maps to one SOURCE OrganizationPursuit. The Engagement UUID is stored as unique `legacy_engagement_id`. The Pursuit receives a deterministic, separate UUID. A database check rejects equality between the two identifiers.

New SOURCE pursuits receive both a canonical Pursuit UUID and a separate compatibility UUID. This keeps the current legacy API response shape stable without treating a compatibility identifier as the canonical pursuit identity.

## Runtime authority

After W2, `OrganizationPursuit.stage` is the only lifecycle writer target. The legacy `tender_engagements` table remains preserved as read only history. There is no runtime dual write.

The legacy adapter resolves the authenticated User and Company Profile to an ACTIVE Membership and Organization, then calls the canonical pursuit service. It returns a `LegacyEngagementView` whose `id` is the compatibility Engagement UUID and whose internal `pursuit_id` remains distinct.

## Preserved routes and behavior

- `/api/v1/my-tenders`
- `/api/v1/my-tenders/{engagement_id}`
- `/api/v1/tenders/{tender_id}/engagement`
- existing save and semantic lifecycle action routes
- Bid Preparation and Proposal deep links
- source Tender URLs and identities

My Tenders reads the canonical stage, source Tender, and Project in set based queries. Pagination, status counts, default dismissed behavior, source filters, stable ordering, project projection, allowed actions, and legacy response identifiers remain intact.

Closed WON or LOST pursuits cannot be reopened by an ordinary transition. A legacy explicit save/evaluate/prepare command is adapted to the canonical explicit reopen command and retains the same Pursuit UUID. Stale expected stage checks are evaluated after the row lock with a forced ORM refresh, which prevents two concurrent lifecycle commands from both committing.

## Proposal and analysis

Proposal UUID, status, exports, and W1 price truth are unchanged. Proposal lists resolve the exact source pursuit through the proposal User's active profile Organization. Bid Preparation writes the canonical pursuit and preserves the one Proposal per User/Tender rule.

TenderAnalysis and AnalysisVersion rows remain unchanged. Compatibility reads add active Membership validation to the existing exact User/Profile/Tender ownership rule. Historical snapshots and hashes are never copied into Pursuit or rewritten.
