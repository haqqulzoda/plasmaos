# Sprint 3.3 — Privileged Account Survivability Safeguards

## 1. Previous Risk

Sprint 3.1 allowed an administrator to disable or reject their own account. With two administrators, concurrent cross-removal requests could also both authorize before either commit and leave zero usable administrators. Request-start authorization and frontend buttons alone could not protect this invariant across API instances.

## 2. Effective Admin Definition

`is_effective_admin(user)` is the repository-native predicate. It requires canonical `approval_status == "approved"` and either `platform_role == "admin"` or the compatibility `is_admin` flag. Pending, rejected, disabled, operator, ordinary, allowlist-only, and stale-session identities do not count. `is_admin_user` delegates to this predicate so API authorization and survivability use identical semantics.

| Privilege | Grant path | Revoke path | Runtime endpoint | Authority source | Version effect | Risk |
|---|---|---|---|---|---|---|
| Admin | Google admin allowlist; verified repair command | Direct DBA/manual code only | No role endpoint | Approved row plus `platform_role=admin` or `is_admin=true` | Supported grants increment | Runtime lifecycle removal is protected |
| Operator | Google operator allowlist | Direct DBA/manual code only | No role endpoint | Approved row plus operator role, or effective admin | Supported grant increments | Zero operators is allowed |
| Lifecycle access | Admin approve/restore | Admin reject/disable | Yes | Canonical approval state | Every successful transition increments | Protected by locked service |

## 3. Survivability Invariant

After every committed user lifecycle mutation that can remove current admin access:

```text
COUNT(users WHERE approval_status = 'approved'
      AND (is_admin IS TRUE OR platform_role = 'admin')) >= 1
```

The count is evaluated from the database while holding the dedicated transaction lock. The verified repair command is not used as justification for permitting zero administrators.

## 4. Self-Action Policy

An effective administrator cannot disable or reject their own account through the ordinary admin API, regardless of how many other administrators exist. These are separate explicit 409 denials, not side effects of the last-admin count. No runtime role-revocation endpoint exists, so no self-demotion path was added.

## 5. Last-Admin Policy

Disable or reject checks that affect an effective admin are performed under the database lock. A mutation that would leave fewer than one effective admin is rejected with 409 before lifecycle state or `auth_version` changes. Disabled, rejected, pending, and allowlist-only accounts are never counted as backups.

## 6. PostgreSQL Concurrency Mechanism

`admin_survivability.py` uses `pg_advisory_xact_lock(namespace, key)` with a stable, Sprint 3.3-specific two-int32 key. The transaction-scoped lock is shared by all FastAPI processes and releases on commit or rollback. It serializes only user lifecycle mutations governed by admin survivability and does not reuse Sprint 2 analysis lock keys.

After acquiring the advisory lock, actor and target rows are selected in deterministic UUID order with `FOR UPDATE` and `populate_existing=True`.

## 7. Actor Revalidation

The request-start `require_admin` dependency remains the first gate. Inside the survivability lock, the actor row is loaded again and must still satisfy `is_effective_admin`. An actor disabled or rejected while waiting receives 403 and performs no mutation.

## 8. Target Revalidation

The target is loaded from the database under the same lock. A second request against an already-mutated target encounters the Sprint 3.1 strict transition rule and returns 409. It cannot increment `auth_version` twice or overwrite disable provenance.

## 9. Two-Admin Race

The real PostgreSQL test concurrently ran A→disable B and B→reject A in separate sessions. One transaction committed; the second actor was revalidated after waiting and denied because its authority was no longer current. Final effective-admin count was exactly one.

## 10. Three-Admin Race

Three concurrent cyclic removal requests were serialized without deadlock. Two committed, one stale actor was denied, and exactly one effective admin remained. The required invariant is at least one, independent of which transaction acquires the lock first.

## 11. Same-Target Race

Two administrators concurrently disabled the same third administrator. One committed; the second received an invalid-transition denial. The target's `auth_version` increased exactly once and `pre_disabled_approval_status` remained `approved`.

## 12. Lifecycle Interaction

Sprint 3.1 transition semantics are unchanged. Approve and restore also pass through the locked, freshly loaded actor/target path but are not blocked by last-admin checks because they preserve or increase survivability. Known-provenance restore returns to the recorded state. Unknown-provenance restore remains conservatively pending and therefore does not create an effective administrator.

## 13. `auth_version` Interaction

The existing lifecycle service still performs the single monotonic version increment. The survivability service checks policy first and invokes that service only for an allowed transition. Self-action, last-admin, stale-actor, missing-user, and invalid-transition denials do not advance the version. Sprint 3.2 exact-version revocation remains unchanged.

## 14. Admin Repair / Recovery

The repair command requires server/database access, configured admin allowlist membership, an existing user, exact Google ID verification, and a migrated schema. It refuses disabled accounts until restore, promotes eligible pending/rejected users, increments `auth_version`, records `admin_promoted`, and commits once. It can recover a zero-admin database out of band but does not weaken normal runtime protection. Google allowlist bootstrap remains a separate verified grant path and cannot override rejected/disabled lifecycle.

## 15. Operator Policy

Zero operators is operationally valid because effective administrators satisfy operator-level dependencies and source operations have admin coverage. No last-operator rule or new role-management endpoint was added.

## 16. Frontend Guard

The approval queue disables self-reject and self-disable buttons by matching the authenticated session email to the row email and supplies a clear tooltip. This is convenience only; the backend remains authoritative and applies the same denial to direct API calls.

## 17. Preflight

The read-only preflight now reports total users, effective admins, approved/disabled/rejected/pending admin-role-or-legacy-flag rows, and an explicit `zero_effective_admins` Boolean. It performs no repair and reveals no identities, lock details, credentials, or security versions.

## 18. Test Results

`test_s3_3_privileged_account_survivability.py` covers the exact effective-admin matrix, self-action denial, last-admin policy, inactive admin-like rows, actor/target revalidation, non-last removal, unknown-provenance restore, dedicated PostgreSQL lock use, runtime-path audit, preflight, and frontend guards. The companion real PostgreSQL script covers two-admin, three-admin, same-target, rollback/retry, restore, self-action, business-row preservation, current head, and `alembic check`.

Static mutation classification:

| Mutation path | Classification |
|---|---|
| Admin user approve/reject/disable/restore endpoints | Safe through locked lifecycle service |
| Company approval/reject/disable endpoints | Safe; company state does not remove effective admin authority, and owner credentials are revoked |
| Google allowlist reconciliation | Safe privilege grant; atomic version increment |
| Verified admin repair command | Out-of-band admin repair; atomic version increment and activity event |
| User onboarding/company profile changes | Not an admin-role mutation |
| Admin/operator removal by direct SQL | Direct SQL/DBA only; outside application enforcement |

## 19. Deferred Audit Trail

Existing `admin_activity` events remain in use for successful lifecycle changes and receive actor, target, action, previous state, new state, before/after snapshots, and reason. Sprint 3.3 does not create a second audit system. Complete append-only administrative audit and denial-event design remain Sprint 3.4.

## 20. Production Considerations

No production access or deployment occurred. PostgreSQL is authoritative; direct DBA SQL cannot be constrained by application locks and remains an out-of-band operational risk. The advisory-lock key must remain stable across instances. Monitoring should alert when preflight reports zero effective admins, but automated repair is intentionally absent.
