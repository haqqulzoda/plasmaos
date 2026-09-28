# W2 World Bank preservation audit

## Preserved authority chain

For a source linked World Bank pursuit, context remains available through:

`OrganizationPursuit -> Tender -> TenderProject -> Project -> ProjectRoleAssignment`

The Pursuit stores only its source Tender UUID. It does not copy Project identity, Project provenance, source metadata, leadership, procurement contacts, deadlines, or refresh state.

## Write boundary

Canonical pursuit and membership services import source models for existence checks and projections only. Their mutation statements target Membership, OrganizationPursuit, and PursuitLifecycleEvent. There is no update path to:

- Tender;
- TenderDocument;
- Project;
- TenderProject;
- ProjectRoleAssignment.

The permanent W2 migration/runtime test fingerprints a World Bank Tender, Project, TenderProject, current leader, and historical leader before migration and after all W2 commands. Every fingerprint remains identical. The fixture preserves the literal native `teamleadname` provenance and a separate procurement contact in Tender source metadata.

## Existing permanent regressions

The maintained World Bank tests continue to cover Project Context, provenance, current and historical Leadership, literal native team lead values, absence of invented TTL titles, distinct procurement contacts, partial refresh preservation, failed refresh preservation, bounded queries, and truncation contracts.

Leadership never creates a Membership, Expert, or CandidateMatch. The W2 seeded project has two role assignments while the membership backfill creates memberships only from CompanyProfile owners; the role rows have no effect on tenancy counts.

Source deadline stays on Tender and is exposed separately from the Organization controlled `internal_target_at` pursuit field.
