# W2 organization, membership and pursuit ID contract (proposal only)

This is the W2 migration input, not a W1 schema change. Existing `User`, `CompanyProfile`, `TenderEngagement`, `Tender`, `Proposal`, `TenderAnalysis`, `AnalysisVersion` and source Project IDs remain stable.

## Identity and ownership

| Concept | Proposed stable key and relationship | Compatibility rule |
|---|---|---|
| Organization | New UUID primary key; exactly one initial Organization for each existing CompanyProfile | Unique immutable `legacy_company_profile_id` mapping. Never merge profiles by name, domain, tax text or owner email. An exception report handles profiles without valid owners. |
| Membership | New UUID; unique `(organization_id, user_id)` active relationship; role and state explicit | Backfill the existing profile owner as active owner member. Platform user approval/disable remains a separate gate. Disable blocks access without deleting membership; membership revoke blocks only that organization's access. |
| OrganizationPursuit | New UUID owned by Organization; origin enum `SOURCE` or `UPLOAD`; source Tender FK nullable; owner Membership FK; internal deadline separate from source deadline | One canonical lifecycle. A source pursuit must have a source Tender and a unique `(organization_id, tender_id)` active identity; an upload pursuit has no source Tender and receives its own UUID. No uniqueness by filename, title, hash or external URL. |
| Legacy CompanyProfile | Preserve UUID and one-to-one mapping to initial Organization | Keep legacy reads while organization data is backfilled. Claims remain unverified until later evidence migration. |
| Legacy TenderEngagement | Preserve UUID, status history and `(user, profile, tender)` authority during transition | Unique nullable `legacy_engagement_id` on pursuit or a unique mapping table. One existing Engagement maps to exactly one source pursuit; compatibility endpoints resolve its old UUID and never reinterpret it as a pursuit UUID. |

## Required constraints and semantics

1. Source pursuit identity: organization plus shared Tender, with explicit origin and database uniqueness for the source case. No source Tender row is duplicated per organization. Historical duplicate or orphan rows are reported before a unique constraint is enforced.
2. Upload pursuit identity: generated UUID and organization ownership, with `source_tender_id=NULL`. Creation and private document intake must be transactional. Upload metadata never populates shared Tender or TenderDocument.
3. Owner: an active membership in the pursuit's organization; require reassignment or an explicit unassigned state before revocation. Owner is an assignment, not the only authorization rule.
4. Deadlines: source Tender deadline is a read-only source fact; internal deadline is organization-controlled, nullable and may differ. Record author/time for edits. Do not write internal dates back to Tender.
5. Platform disable versus membership revoke: both are checked on every private read/write and worker action. Re-enable does not silently restore a revoked membership.
6. Proposal/Analysis links: add pursuit FK and immutable mapping in later slices; preserve Proposal UUID, TenderAnalysis and AnalysisVersion IDs/hashes, historical JSON and export bytes. Ambiguous records enter a quarantine report, not a guessed join.
7. Backfill: checkpointed idempotent batches, explicit legacy keys, count parity, cross-tenant authorization tests, and reversible routing. No destructive replacement of Engagement rows during the compatibility period.

## Founder decisions required before W2 migration

- Confirm **one initial organization per CompanyProfile**, including sole-person profiles, and no automatic company-name merging.
- Confirm existing profile owner becomes **owner membership**, and choose who can invite or transfer ownership and whether a last-owner removal is blocked.
- Confirm one active source pursuit per organization/Tender and whether archived pursuits can be reopened or require a new lifecycle record.
- Confirm upload pursuits are unique only by UUID, with duplicate detection as a warning rather than an identity rule.
- Confirm whether legacy Engagement UUIDs remain accepted indefinitely in compatibility endpoints or receive a sunset date. They must never be reused as pursuit IDs.
- Define ownership transfer and internal deadline edit permissions; source deadline is always source controlled.
- Define account disable and membership revoke policy for pending tasks, invitations and notifications.
- Decide legal retention and deletion rules for organizations, private documents, experts and historical artifacts. W2 must not infer a deletion policy from current user cascades.

Recommended W2 entry: approve these decisions, then implement additive Organization/Membership and pursuit mapping with parity and tenant-isolation tests before any private upload path.
