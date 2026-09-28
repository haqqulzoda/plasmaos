# W3 private document ownership contract

W2 reserves `PursuitOrigin.UPLOAD` structurally but does not implement Upload Tender, private document persistence, upload APIs, parsing, duplicate enforcement, or UI.

W3 private files must use this ownership chain:

`Organization -> OrganizationPursuit -> PrivateDocument -> DocumentVersion`

## Required ownership rules

- PrivateDocument belongs to exactly one OrganizationPursuit.
- DocumentVersion belongs to exactly one PrivateDocument and is immutable after persistence.
- Authorization derives from ACTIVE Membership in the Pursuit Organization.
- Client supplied Organization, Pursuit, Document, and Version IDs must be joined back to that active Membership.
- Membership revocation removes access without deleting document history.
- Pursuit owner assignment does not define document authorization by itself.
- Organization and Pursuit hard deletion remain unavailable until an explicit retention design exists.

## Source separation

PrivateDocument and DocumentVersion must not use TenderDocument. TenderDocument remains source owned and follows source refresh and provenance rules. Upload pursuit files must not mutate Tender, TenderDocument, Project, TenderProject, or ProjectRoleAssignment.

UPLOAD pursuits have `source_tender_id = NULL`. Their UUID is canonical; title, reference, and content hash may support advisory duplicate warnings but must not become identity or uniqueness constraints.

## Compatibility constraints carried forward

- preserve W1 manual commercial price input;
- preserve source deadline separately from internal target dates;
- preserve legacy Engagement mappings indefinitely for SOURCE pursuits;
- do not reuse legacy Engagement UUIDs for uploaded pursuits;
- keep Proposal and future analysis/evidence relations explicit and UUID based;
- retain the legacy upload timezone preview defect as a separately scoped issue unless W3 replaces that path directly.
