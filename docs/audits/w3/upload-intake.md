# W3 Upload Intake Audit

## Upload-origin flow

1. The user opens the persistent **Upload Tender** action.
2. The workflow loads active organizations. One is automatic; multiple require an explicit selection.
3. The user selects one or more PDF/DOCX files and a controlled role for each.
4. Optional tender context is submitted with the same command. At least one accepted file is required; budget is not requested and a missing deadline remains empty.
5. One `UPLOAD` pursuit, private documents, first versions and durable jobs commit. No source Tender is created.
6. The browser opens `/dashboard/pursuits/{id}`. Processing is asynchronous and no W4 analysis starts.

## Source-linked flow

Tender Details provides an explicit **Upload tender documents** action in the Documents area. The action resolves organization context, gets or creates that organization’s source pursuit, and stores only private documents. Passive Tender Details GETs do not create pursuits or documents.

## Context confirmation

Organization-private context supports title, buyer, declared funder/source, country, reference, procurement stage, external deadline, deadline timezone and source URL. User-entered values are confirmed. Extracted suggestions remain provisional, identify the exact source `DocumentVersion`, and include page/span evidence when available. Users can apply, correct and save them.

Declared funder text does not create a connector, shared Tender, World Bank project, or source support claim. Missing values stay unknown.

## Duplicate and revision behavior

Exact hash within the same organization/pursuit creates a warning and still creates a distinct document. Explicit replacement adds the next immutable version. The workspace supports authoritative role correction on the logical private document. W3 performs no automatic merge, supersession or hard deletion.

