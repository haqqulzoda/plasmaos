# Sprint 1.2 — World Bank Project Enrichment and Leadership Foundation

## 1. Official Source Contract

The runtime source is the official public World Bank Projects API:

```text
GET https://search.worldbank.org/api/v2/projects?format=json&id={project_id}&rows=1
```

The World Bank identifies the Projects API as its public interface for active,
pipeline, and closed operations data in its
[official developer overview](https://datahelpdesk.worldbank.org/knowledgebase/articles/889386-developer-information-overview).
The canonical human-facing URL is the official
[Projects & Operations project page](https://projects.worldbank.org/en/projects-operations/project-detail/P179267).

The implementation queries only a known canonical World Bank Project ID. It
does not enumerate or crawl the global corpus and uses no login-required or
non-World-Bank source.

### Observed source fields

The inventory below was verified against the official public Projects API for
`P179267` on 2026-08-26.

| Field | Source field | Type / example shape | Authoritative | Current / historical | Nullable | Provenance |
|---|---|---|---|---|---|---|
| Project ID | `id` | string, `P179267` | Yes | Stable identity | No for accepted record | Full raw record |
| Title | `project_name` | string | Yes | Current title | Yes | Full raw record |
| Country/economy | `countryshortname`, `countryname` | string or string list | Yes | Current classification | Yes | Full raw record |
| Region | `regionname` | string | Yes | Current classification | Yes | Full raw record |
| Status | `projectstatusdisplay`, fallback `status` | string, `Active` | Yes | Current and changeable | Yes | Full raw record |
| Approval date | `boardapprovaldate` | ISO timestamp | Yes | Historical event | Yes | Full raw record |
| Closing date | `closingdate` | formatted timestamp | Yes | Current and changeable | Yes | Full raw record |
| Borrower | `borrower` | string | Yes | Current record | Yes | Full raw record |
| Implementing agency | `impagency` | string or list | Yes | Current record | Yes | Full raw record |
| Financing | `totalcommamt`, `curr_total_commitment`, related fields | formatted strings | Yes as raw source | Current financial snapshot | Yes | Raw provenance only in Sprint 1.2 |
| Sectors | `sector`, `sector_namecode` | object lists | Yes | Current classification | Yes | Raw provenance only |
| Themes | `theme_list`, `mjtheme_namecode` | nested object lists | Yes | Current classification | Yes | Raw provenance only |
| Product line | `prodline`, `prodlinetext` | code/string | Yes | Current classification | Yes | Raw provenance only |
| Project team names | `teamleadname` | comma-delimited string or list | Yes as the API's current team-lead field | Current snapshot; no history supplied | Yes | Role provenance plus full raw record |
| Canonical URL | `url` | official HTTPS URL | Yes | Stable project page | Yes; deterministic official fallback | Project and role provenance |
| Source update time | `p2a_updated_date` | timestamp string | Yes | Source-record update time | Yes | Project and role provenance |

Commitment is not promoted to first-class columns because the audited record
does not supply an explicit currency alongside every formatted commitment
field and its alternative numeric fields use different display scales.

## 2. Project Enrichment Fields

Sprint 1.2 adds stable, high-value fields to `Project`: `region`,
`project_status`, `approval_date`, `closing_date`, `borrower`, and
`implementing_agencies`.

It also adds `enrichment_status`, `enrichment_last_attempted_at`,
`last_enriched_at`, `enrichment_failure_class`,
`enrichment_source_updated_at`, `enrichment_fields_obtained`, and
`enrichment_fields_missing`.

Authoritative non-empty values update current Project metadata. Null or empty
values do not erase established values. Status and non-empty dates may change
when the official record changes. The exact official record is retained under
`raw_provenance.world_bank_project_enrichment`.

## 3. Leadership Domain Contract

`ProjectRoleAssignment` is Project-level leadership context. It is not a
procurement contact, tender submission contact, or implementing-agency
contact. It is never presented as a contact for a Tender by backend schemas.

The internal schema labels every assignment with
`role_type = PROJECT_LEADERSHIP`.

## 4. Native vs Canonical Role Mapping

| Native authoritative label | Canonical role | Mapping evidence | Confidence |
|---|---|---|---|
| `Task Team Leader` | `TASK_TEAM_LEADER` | Exact native phrase | High |
| `Co-Task Team Leader` | `CO_TASK_TEAM_LEADER` | Exact native phrase | High |
| `Task Manager` | `PROJECT_TASK_MANAGER` | Exact phrase; deliberately not TTL | High |
| `teamleadname` | `OTHER_PROJECT_ROLE` | Exact Projects API field does not establish TTL equivalence | High that no stronger claim is warranted |
| Any other exact label | `OTHER_PROJECT_ROLE` | Preserved but not semantically guessed | High that no stronger claim is warranted |

The native role string is retained exactly after outer whitespace cleanup.

## 5. ProjectRoleAssignment Schema

The model stores Project, source namespace, deterministic assignment key,
optional source person ID, display name, native and canonical roles, directly
published email/phone if any, source URL/document evidence, structured
provenance, currentness/history timestamps, and creation/update timestamps.

Uniqueness is:

```text
(project_id, source_system, assignment_key)
```

The assignment key is SHA-256 over exact source system, Project external ID,
native role, and either authoritative source person ID or exact display name.
Case is not folded and names are not fuzzily normalized.

## 6. Person Identity Policy

There is no global Person model. The audited Projects API does not publish a
person identifier for `teamleadname`, so `source_person_id` is null. The exact
display name is retained as source evidence. Identical names on separate
Projects remain separate assignments.

No LinkedIn lookup, email derivation, organization matching, title similarity,
or cross-project human deduplication exists.

## 7. Provenance Contract

Every persisted role must contain source system, endpoint, Project ID, source
field, exact source/person value, retrieval time, and available source update
time/record identifier. A role lacking the required evidence is rejected.

The full official Project record is retained at Project level. Role rows retain
the relevant `teamleadname` value and individual observed name, not a vague
`World Bank` label.

## 8. Current/Historical Role Semantics

A repeated observation reuses the assignment and advances
`last_observed_at`. A new complete roster creates new assignments and marks
previously current absent assignments non-current with `ended_at`, preserving
their rows.

Only a successfully normalized record that explicitly contains a valid
`teamleadname` field is considered complete enough to end absent assignments.
A missing/malformed leadership field, identity mismatch, network failure, or
partial response never ends current roles.

## 9. Enrichment Execution Model

World Bank tender persistence commits first. A second, failure-isolated phase
claims a bounded batch of linked new/stale Projects and publishes Celery tasks.
Each task fetches exactly one known Project record, validates identity, and
atomically merges metadata and roles.

Normal tender refresh does not wait for project-detail HTTP requests.
Enrichment dispatch failure is logged and recorded on Project without rolling
back Tender or TenderProject data.

## 10. Retry/Freshness Policy

Successful enrichment is fresh for seven days. Older successful data is
reported as `stale` and becomes eligible for another bounded claim. Queue and
running claims have a 30-minute lease.

Each batch contains at most 50 distinct linked Projects. The Celery task is
rate-limited to 30 requests per minute, has 60/90-second soft/hard limits, and
uses at most three retries with exponential backoff capped at five minutes.

Timeouts, network failures, HTTP 429, and HTTP 5xx are retryable. HTTP 4xx,
identity mismatch, malformed response, empty authoritative response, and
invalid Project ID are not retryable.

## 11. World Bank Integration

Many Tenders may link to one Project, but the queue claimant operates on
distinct Project rows using row locks and an active status lease. Twenty
Tenders linked to one Project therefore produce one enrichment unit.

Existing linked World Bank Projects have `never_attempted` status after the
migration and become eligible in the next bounded World Bank refresh. The
migration itself never performs HTTP calls.

## 12. Procurement-Contact Separation

`CanonicalContact`, tender contact extraction, notice emails, and
`contact_submission` remain unchanged. None are inputs to Project role
normalization or reconciliation.

Likewise, ProjectRoleAssignment is not consumed by tender contact/submission
logic. Fixture coverage uses the same display name in both domains and proves
the procurement email is not copied into the role row.

## 13. Migration

Revision `20260826_0002_s1_2_wb_project_enrichment` directly follows
`20260826_0001_s1_1_project_foundation`. It adds Project enrichment columns,
status constraints/indexes, and `project_role_assignments` with its PK, FK,
unique/check constraints, and current-role index.

The upgrade is additive, performs no source calls, does not modify historical
migrations or the immutable Sprint 0 baseline, and creates no leadership rows.

## 14. Test Results

- Source/role/model contract tests: 15 passed.
- Combined focused Sprint 1.2, Sprint 1.1, migration, World Bank, source, and
  contact-separation contracts: 83 passed.
- Disposable fresh bootstrap: passed; zero fabricated role rows; clean check.
- Disposable Sprint 1.1 upgrade: passed; Projects, links, Tenders, Proposal,
  TenderAnalysis, TenderRecommendation, and document rows preserved.
- Enrichment fixture matrix: passed for metadata, idempotency, leadership
  change/history, partial response safety, identity mismatch, null email,
  cross-Project same-name isolation, contact separation, and Project-level
  queue coalescing.
- Sprint 1.1 disposable regression: passed through the Sprint 1.2 head.
- World Bank connector under `TZ=UTC`, `TZ=Asia/Tashkent`, and
  `TZ=America/New_York`: 18 passed in each timezone.
- Connector regression gate: 195 passed, 1 skipped, 4 subtests passed, zero
  failures. The sole skip remains the known optional local fixture:
  `test_storage_path_resolver.py:33` (`Known 481480 local storage fixture is
  not present`).
- Disabled-authorization and UNKNOWN actionability focus: 49 passed and 8
  subtests passed.

## 15. Production Considerations

No production system was accessed or modified and nothing was deployed.
Deployment must apply the migration before enabling workers that import the
new task. Operators should monitor aggregate enrichment statuses, failure
classes, queue age, source freshness, and unexpected identity mismatches.

The Projects API is public but its undocumented field shapes may evolve. Raw
provenance, strict identity validation, conservative parsing, and partial-
response behavior limit that risk. Runtime failures retain existing Project
metadata and role history.

## 16. Deferred UI Work

Sprint 1.3 retains Project Leadership UI, TTL cards, Tender Details leadership,
Project navigation, provenance tooltips, contact calls to action, and email
actions. Sprint 1.2 adds no frontend code.

ADB leadership and source recovery remain deferred. Hunter, compliance
ownership, My Tenders, Tender Details consolidation, i18n, and analysis
language behavior remain unchanged.
