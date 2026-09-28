# W3 Source and Private Separation Audit

## Authorities

Shared source authority remains `Tender`, `TenderDocument`, `Project`, `TenderProject`, and `ProjectRoleAssignment`. Organization-private authority is `OrganizationPursuit`, `PrivateDocument`, `DocumentVersion`, processing results and private context.

An upload-origin pursuit has `origin=UPLOAD` and `source_tender_id=NULL`; a database check prevents any other combination. A source-linked upload uses the organization/source Tender uniqueness rule to reuse one `SOURCE` pursuit. It creates no second Tender and never copies bytes or text into `TenderDocument`.

The private service imports shared source documents only for the passive W4 candidate projection. It has no update path for source/project tables. Source refresh services have no relationship or mutation path to private document tables.

## UI separation

Tender Details labels its source-backed list **Official source documents**. A separate **Organization uploads** block appears below it and performs no private read until the user clicks and submits. Private documents are reviewed in the pursuit workspace. This preserves the accepted passive Tender Details request graph and SQL budget.

If an official document resembles a private upload, both authorities remain intact. W3 does not infer supersession from filenames, titles or hashes.

