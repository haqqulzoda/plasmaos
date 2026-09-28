# W4 Exact-Version Analysis Pack Contract

## Purpose

W4 must analyze a sealed input, never a moving set of “current” files. W3 exposes a passive candidate at:

`GET /api/v1/pursuits/{pursuit_id}/analysis-pack-candidate`

The endpoint performs no parsing, source fetch, AI call, acquisition or mutation.

## Candidate schema

Top level:

- `schema_version = w4-analysis-pack-candidate-v1`
- `candidate_sha256`, computed from the canonical identities below
- `organization_id`, `pursuit_id`, `pursuit_origin`
- optional `source_tender_id`
- aggregate `parse_ready`
- `page_count_total` only when every included page count is known
- `generated_at`, excluded from the candidate hash

Each shared source document contains:

- exact `tender_document_id`
- `snapshot_sha256` over its W3 source identity snapshot
- content SHA-256 when the source authority has one
- file type, parse readiness, page count/language when known
- `provenance = SHARED_SOURCE`
- source capture timestamp

Each private input contains:

- exact `private_document_id`
- exact immutable `document_version_id` and version number
- exact content SHA-256
- controlled role
- processing state and parse readiness
- page count and explicit known/unknown status
- language when known
- `provenance = ORGANIZATION_PRIVATE_UPLOAD`

No storage key, filesystem path or extracted text is part of the external candidate.

## W4 sealing requirements

Before analysis starts, W4 must persist a new immutable analysis-pack record with:

1. the candidate schema version and candidate SHA-256;
2. organization and pursuit IDs;
3. every exact source snapshot and private version identity;
4. all exact content or snapshot hashes;
5. readiness, page-count and language/provenance facts used for admission;
6. the requesting active membership and time;
7. an analysis-pack limit decision, including the W4 500-page rule.

W4 must fail if a selected item is unready, inaccessible, hash-mismatched, over its analysis limits, or changed between candidate read and sealing. Later private revisions or source refreshes must not alter a sealed pack. A new selection requires a new pack identity.

W4 may then derive Requirements, Positions and Gap analysis from that sealed pack. W3 performs none of those operations.

