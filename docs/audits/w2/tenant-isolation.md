# W2 tenant isolation audit

## Authorization chain

Private Organization and Pursuit access requires all of:

1. authenticated User;
2. approved and enabled platform account;
3. ACTIVE Membership;
4. exact resource Organization match.

The Organization resolver treats a client supplied ID only as a requested context. It joins that ID to the authenticated User's ACTIVE Membership. Zero matches are denied. More than one active membership without an explicit context returns a conflict requiring `X-Organization-ID`.

## Enumeration and mutation controls

The permanent tests use two Organizations whose legacy profiles have the same display name, tax text, and email domain. They prove:

- a Pursuit UUID from Organization A is not returned in Organization B;
- a compatibility Engagement UUID from Organization A is not returned in Organization B;
- Organization B Membership cannot be assigned as owner of Organization A Pursuit;
- a forged Organization context is denied;
- Membership listing requires an ACTIVE OWNER in the requested Organization;
- a revoked Membership loses private pursuit and analysis access;
- a shared source Tender does not expose another Organization's pursuit overlay;
- passive reads do not create, reopen, or transition a Pursuit.

The release read proof also calls foreign Proposal, Pursuit, Membership, legacy Engagement, analysis history, and readiness URLs and requires not found responses.

## Multi Organization behavior

A fixture User is explicitly invited and activated in two Organizations. Context resolution without an Organization ID raises `OrganizationContextRequiredError`. Supplying either Organization resolves only its own Membership and resources. After revocation in Organization A, the Organization B Membership remains ACTIVE and becomes the single automatically resolved context.

No UI switcher is added in W2.

## Platform account state

Platform disable is enforced before role bypass. Disabling an active member returns forbidden at the platform gate while leaving the Membership ACTIVE. Restoring the User leaves that Membership ACTIVE. A separately revoked Membership remains REVOKED through platform disable and restore because no account lifecycle command updates Membership rows.
