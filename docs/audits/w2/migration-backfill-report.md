# W2 migration and backfill report

## Revision chain

| Revision | Purpose |
|---|---|
| `20260912_0001_s10_5_communications` | Accepted W1 head |
| `20260925_0001_w2_organization_membership` | Organization, Membership, durable states, exception report, exact profile backfill |
| `20260925_0002_w2_organization_pursuit` | OrganizationPursuit, append only lifecycle events, exact Engagement backfill, Proposal/analysis resolution report |

The migrations add tables, enums, constraints, indexes, rows, and one audit trigger. They do not drop or rewrite CompanyProfile, TenderEngagement, Tender, Project, Proposal, TenderAnalysis, or AnalysisVersion.

## Deterministic mapping

- Organization ID: MD5 UUID of `plasma:w2:organization:{company_profile_id}`.
- Initial Membership ID: MD5 UUID of `plasma:w2:membership:{organization_id}:{user_id}`.
- Backfilled Pursuit ID: MD5 UUID of `plasma:w2:pursuit:{legacy_engagement_id}`.
- Legacy Engagement UUID: copied exactly into `legacy_engagement_id`; never used as the Pursuit primary key.

Organization insert conflicts resolve on the unique legacy profile. Membership insert conflicts resolve on the durable Organization/User identity. Pursuit backfill conflicts resolve on the permanent legacy compatibility ID. Lifecycle backfill inserts only when the corresponding `LEGACY_BACKFILL` event does not exist.

## Reconciliation and quarantine

Revision A compares valid Company Profiles with Organization and ACTIVE OWNER counts. Revision B compares exactly valid Engagement rows with mapped compatibility rows. A mismatch aborts the migration.

`tenancy_backfill_exceptions` records:

- Company Profile with a missing owner User;
- Engagement with an invalid User/Profile/Organization tuple;
- Engagement with a missing Tender;
- Proposal without an exact User -> Company Profile -> Organization + Tender pursuit;
- owned analysis without an exact profile Organization + Tender pursuit.

The migration never maps by company name, email, domain, INN, title, or similarity. Two seeded profiles with identical display and tax text produced two Organizations in the permanent test.

## Disposable PostgreSQL evidence

The permanent W2 test starts from the repository structural baseline, upgrades to the exact W1 head, seeds Company Profiles, a World Bank source chain, Engagement, Proposal, TenderAnalysis, and AnalysisVersion, then upgrades to W2. It proves:

- two profiles produce two Organizations and two ACTIVE OWNER memberships;
- the Engagement creates one SOURCE pursuit with a distinct deterministic UUID;
- lifecycle stage and safe timestamps are copied exactly;
- one `LEGACY_BACKFILL` event is created;
- the valid fixture produces zero exceptions;
- source, Project, Leadership, Engagement, Proposal, TenderAnalysis, and AnalysisVersion fingerprints are unchanged;
- downgrade to W1 and reupgrade produce the same Organization and Pursuit identities;
- `alembic check` reports no new operations.

Fresh bootstrap, `alembic heads`, `current`, `check`, and the aggregate schema/data preflight are part of the release migration gate. All test databases use the loopback disposable target guard and are removed afterward.

## Validation result

The permanent release migration gate passed on 2026-09-26. It verified the single W2 head, upgraded a clean disposable database, ran `alembic current`, `alembic check`, and the aggregate schema/data preflight, then removed the test database. The seeded valid W1 upgrade produced zero quarantine rows. Production was neither queried nor changed.
