# W2 Membership and owner rules

## Durable lifecycle

The unique `(organization_id, user_id)` constraint gives each Organization/User pair one durable Membership identity. OWNER can invite an existing platform User as MEMBER. The initial state is INVITED; only the invited User can activate it. Revocation records `revoked_at`; reinvitation resets lifecycle timestamps and reuses the same Membership UUID.

MEMBER cannot invite, promote, demote, revoke, or list the full membership roster. OWNER may promote or demote active memberships and revoke active or invited memberships, subject to the final owner rule.

## Concurrent final owner rule

Role and revocation commands first acquire a transaction scoped PostgreSQL advisory lock derived from the Organization UUID. They then validate the actor, lock the target and active owner rows, and recheck the number of ACTIVE OWNER memberships.

The permanent PostgreSQL test starts with two active owners and concurrently asks each owner to demote the other. Exactly one command commits; the second sees the serialized state and fails. The database retains exactly one ACTIVE OWNER. A direct attempt by that final owner to revoke itself also fails with `LastOwnerError`.

## Pursuit ownership during revocation

`owner_membership_id` is nullable and is protected by the composite `(membership_id, organization_id)` foreign key.

Within the same revocation transaction, all pursuits owned by the target Membership are updated before the Membership becomes REVOKED:

- without a destination, ownership becomes null;
- with a destination, the destination must be another ACTIVE Membership in the same Organization;
- a cross Organization destination is rejected.

The permanent test covers both unassignment and explicit transfer. It also confirms that revoking a User in one Organization does not alter the User's Membership in another Organization.

No membership or user cascade can delete Organization owned pursuit history, and W2 adds no Organization hard delete API.
