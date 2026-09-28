# W3 Tenant Isolation Audit

## Authorization chain

Every W3 endpoint first requires an authenticated, approved platform user. It then resolves one active `Membership`:

- one active membership may be selected automatically;
- multiple active memberships require an explicit `X-Organization-ID`;
- the requested organization must be one of the user’s active memberships;
- a revoked membership fails on the next request.

All private reads join or filter by organization and pursuit. Composite foreign keys enforce the same organization across pursuit, private document, creator/uploader membership, context and batch. Document/version enumeration returns a generic not-found response across tenant boundaries.

The private download authorization chain validates user, platform approval, active membership, organization, pursuit, document, exact version and clean malware result. A pursuit owner alone grants no access.

## Enumeration and duplicate privacy

Duplicate lookup is limited to the current organization and pursuit. It returns only IDs already visible to the caller and is advisory. Identical bytes in another organization cannot be detected through the API. Hash or title is never an identity and no automatic merge occurs.

The integration proof creates two organizations, attempts cross-tenant pursuit and exact-version reads, revokes an active membership, and verifies multi-organization requests require explicit context.

