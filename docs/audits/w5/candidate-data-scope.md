# W5 Candidate Data Scope

## Authorities

Candidate data has its own `candidate_firms`, `candidate_project_references`, `candidate_experts`, and `candidate_cv_versions` tables. `candidate_firms` is deliberately separate from `organizations`; matching names have no identity effect.

## Scope rules

`ORGANIZATION_PRIVATE` requires `owner_organization_id`. Every read filters that value against the active Organization context. `NETWORK_SHARED` requires a null owner and a nonempty permission basis. Shared Expert records additionally require `EXPLICIT_CONSENT` or `CONTRACTUAL_BASIS`.

Private notes remain model-only and never enter API response schemas. W5 defines no rate, availability, relationship history, reusable CV byte, or participation field. Shared provenance uses a fixed allowlist.

## Supply boundary

Active members may curate their private records. Operators may curate shared records. The source field accepts `MANUAL` or `EXPLICIT_IMPORT`; no participant, competitor, contact, leader, or public project query automatically inserts an authority row.

