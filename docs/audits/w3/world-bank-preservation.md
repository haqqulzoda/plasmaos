# W3 World Bank Preservation Audit

For a source World Bank pursuit, the canonical chain remains:

`OrganizationPursuit -> Tender -> Project -> ProjectRoleAssignment`

The W3 integration proof seeds a World Bank Tender, its `TenderProject` linkage, current Project leadership and historical leadership. It records complete row fingerprints, creates a source pursuit, attaches a private clarification document, creates upload-origin private documents, processes them, retries work and runs recovery. The fingerprints of Tender, Project, TenderProject, current leadership and historical leadership remain byte-for-byte unchanged.

The pursuit workspace links source pursuits back to Tender Details, including the existing Project Context and Project Leadership sections. An upload-origin pursuit with declared funder text such as “World Bank” has no `source_tender_id` and therefore cannot fabricate Project Context or leadership.

No W3 parser or context suggestion writes connector identity, project identity, source metadata or leadership.

