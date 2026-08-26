# Sprint 1.1 — Canonical Project Foundation

## 1. Domain Contract

`Project` is a source-scoped canonical domain object. It is not a Tender and
does not contain procurement-contact, task-team-leader, leadership, or role
assignment data. A Project can be linked to many Tenders through the explicit
`TenderProject` association model.

## 2. Project Identity

The only canonical identity is:

```text
(source_system, external_project_id)
```

`external_project_id` is a source-native string and is not globally unique.
It is never converted to an integer. The model uses the existing canonical
source strings: `uzex`, `world_bank`, `adb`, `giz`, and `ebrd`.

## 3. TenderProject Contract

`TenderProject` records the Tender, Project, deterministic linkage method,
exact source value, and structured provenance. `tender_id` is unique for the
current zero-or-one Project-per-Tender contract. The association model leaves
room for a future cardinality change without embedding Project identity into
Tender.

Allowed linkage methods are `SOURCE_PROJECT_ID` and `SOURCE_NATIVE_LINK`.
Fuzzy, title, email, organization, LinkedIn, and LLM-derived linkage methods
are intentionally absent.

Both foreign keys use `ON DELETE CASCADE` into the association row only.
Deleting a Tender deletes its link. Deleting a Project deletes its links but
cannot delete a Tender. Deleting one linked Tender cannot delete the Project
or other Tender links.

## 4. Source-Scope Rule

The database uniqueness constraint is
`UNIQUE(source_system, external_project_id)`. The disposable PostgreSQL test
proves that `("world_bank", "P123456")` and `("adb", "P123456")` are separate
Projects.

### Identifier inventory

| Source | Current field | Example shape | Authoritative? | Normalization | Current usage |
|---|---|---|---|---|---|
| CanonicalTender | `project_id` | nullable source-native string | Adapter-dependent | shared persistence trims outer whitespace | carried into `Tender.project_id` |
| Tender ORM/API/frontend | `project_id` | `P179267`, `59001-001`, `55400` | compatibility/source evidence | stored and returned as a string | search, list/detail display, response compatibility |
| World Bank | payload `project_id` | `P179267` | yes for project identity | connector cleans whitespace; Sprint 1.1 validates strict `P######` | canonical backfill and ongoing linkage |
| ADB | `project_id` / category `project_number` | `59001-001` | coverage not approved for this sprint | whitespace cleanup only | compatibility field only; no canonical backfill |
| EBRD | detail `project_id` / `EBRD Project ID` | `55400` | source-derived but not approved for this sprint | source parser cleanup | compatibility field only |
| GIZ | e-procurement page ID and `eproc_project_id` metadata | portal-specific token | not an approved canonical Project contract | URL/parser extraction | tender identity/evidence only |
| UzEx | no authoritative Project field contract | normally null | no | none | no Project creation |

No `project_number`, `project_code`, `project_reference`, `source_project`, or
`external_project` canonical field currently exists outside source payload
metadata and ADB's `project_number` category field. GIZ's `project_url` values
are procurement portal pages, not canonical Project URLs.

## 5. World Bank Backfill

The migration reads only persisted Tenders where
`source_system = 'world_bank'` and `project_id` matches strict deterministic
source evidence. It upserts Project by the source-scoped identity and inserts
one TenderProject per eligible Tender. Both operations use conflict handling,
so the equivalent backfill is idempotent.

The migration emits deterministic counts for Tenders with IDs, valid and
skipped IDs, distinct Projects, created/reused Projects, created/existing
links, normalization changes, and errors. It logs counts only and does not log
quarantined identifiers.

Disposable seeded result:

| Metric | First migration | Equivalent rerun |
|---|---:|---:|
| World Bank Tenders with non-null Project ID | 5 | 5 |
| Valid IDs | 3 | 3 |
| Invalid/skipped IDs | 2 | 2 |
| Distinct Project IDs | 2 | 2 |
| Projects created | 2 | 0 |
| Projects reused | 1 | 3 |
| TenderProject links created | 3 | 0 |
| Links already present | 0 | 3 |
| Errors | 0 | 0 |

These are disposable fixture results, not production counts. No production
system was accessed.

## 6. Normalization Rules

Normalization is conservative: convert to string, trim outer whitespace,
reject empty values, preserve casing and punctuation, and never guess a new
format. World Bank IDs must match uppercase `P` followed by exactly six
digits.

The exact raw source value remains in `TenderProject.source_value` and both raw
and normalized values are recorded in structured provenance. The disposable
normalization fixture recorded:

| Raw value | Normalized value |
|---|---|
| `"  P654321  "` | `"P654321"` |

## 7. Invalid-ID Policy

Identifiers are classified as `VALID`, `EMPTY`, `MALFORMED`, or `SUSPICIOUS`.
Empty strings, over-length/control-character values, and nonconforming World
Bank shapes are skipped. They do not create Project or TenderProject rows.
The disposable migration fixture quarantined two values: one empty and one
suspicious. Values are not printed in migration counts.

## 8. ADB Deferred Policy

There is no ADB discovery, recovery, enrichment, leadership ingestion, or data
backfill in Sprint 1.1. A synthetic schema/service fixture only proves that an
ADB namespace does not collide with World Bank. No ADB completeness claim is
made.

## 9. Connector Integration

Every World Bank connector upsert now performs:

```text
Tender upsert -> deterministic Project resolution -> TenderProject linkage
```

The raw payload's `project_id` is retained as `source_value`, even when the
existing normalized Tender compatibility field is trimmed. Repeated refreshes
reuse the Project and association. Current source payload data supplies only
authoritative country metadata; a Tender notice URL is not misrepresented as
a Project URL and a Tender title is not treated as a Project name.

Metadata merge semantics fill only missing Project fields. Null or empty
refresh values cannot overwrite existing name, country, source URL, or raw
provenance.

## 10. Migration

Revision `20260826_0001_s1_1_project_foundation` has the sole parent
`20260825_0001_s0_5b3`. It creates only `projects`, `tender_projects`, their
primary/foreign/unique/check constraints, and the Project lookup index on
`tender_projects.project_id`. The unique indexes optimize Project source/ID
lookup and Tender linkage lookup without redundant indexes.

No historical migration or immutable 0.4c baseline artifact was changed. The
bootstrap helper now validates that the current sole head is a descendant of
the manifest-approved first post-baseline migration, allowing the immutable
baseline to advance through later forward migrations.

## 11. Data Preservation

The existing `Tender.project_id` column remains in the ORM, schema, API, and
frontend. The migration does not delete or update Tenders and does not touch
Tender lifecycle, TenderDocuments, Proposals, TenderAnalysis, or
TenderRecommendation.

The disposable existing-database scenario compared exact representative rows
before and after migration, including Tender statuses and artifact row
versions. All were unchanged. Only Project and TenderProject rows were added.

## 12. Test Results

- Focused Project/World Bank/foundation/migration contracts: 43 passed.
- Disposable PostgreSQL fresh bootstrap: passed; new head reached; zero rows.
- Disposable Sprint 0-head upgrade: passed; business rows unchanged.
- Backfill sharing: passed; two Tenders reused one Project.
- Equivalent backfill rerun: passed; zero new Projects or links.
- Cross-source collision: passed; World Bank and ADB identities stayed separate.
- Invalid/empty quarantine: passed; no fabricated Projects.
- Connector refresh and sparse-metadata merge: passed.
- Project deletion isolation: passed; Tender retained.
- `alembic check`: `No new upgrade operations detected` in both disposable cases.

- World Bank suite under `TZ=UTC`: 18 passed.
- World Bank suite under `TZ=Asia/Tashkent`: 18 passed.
- Full connector regression gate: 195 passed, 1 environment-dependent local
  storage fixture skipped, 4 subtests passed, 0 failures. The passed-plus-
  skipped test inventory remains 196.
- Disabled-account security and UNKNOWN actionability focus: 42 passed.

## 13. Production Migration Considerations

The migration is additive and transaction-bound. It emits aggregate backfill
observability without sensitive row values. Strict validation makes skip-and-
report the failure mode for suspicious IDs. Existing compatibility fields are
retained for rollback confidence and later cleanup.

Before human-controlled production deployment, operators should review the
aggregate counts, investigate any unexpected skipped-ID volume outside this
migration, and confirm the single Alembic head. This work does not deploy and
does not access or mutate production.

## 14. Deferred Work

Sprint 1.2 retains World Bank Project enrichment, TTL/project leadership,
project-team contacts, role assignments, and Project UI. ADB recovery,
leadership, and production backfill also remain deferred. This sprint does not
change Tender Explorer, Hunter, compliance ownership, My Tenders, Tender
Details consolidation, i18n, analysis language, or connector architecture.
