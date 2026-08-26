# Sprint 1.3 — Project Context, Leadership, and Provenance UI

## 1. UI Information Architecture

Tender Details now fetches Project intelligence independently and presents a
compact **Project Context** block after the core tender identity, buyer/market,
and procurement-timing facts. It does not change the existing Tender Details
architecture or visually compete with deadlines, compliance, bid preparation,
documents, or procurement contacts.

The block contains optional authoritative metadata, provenance, current
Project Leadership, and an expandable historical-leadership region. Tender
Explorer list rows remain unchanged and do not fetch leadership data.

## 2. Project Context Fields

The presentation allowlist is Project ID, source, title, country, region,
Project status, approval date, closing date, borrower, implementing agencies,
official source URL, enrichment state, last successful enrichment time, and
derived source freshness.

Only meaningful values render. Missing values are omitted instead of producing
repeated `N/A`, `null`, or `undefined` text. Labels distinguish **Project
Approval** and **Project Closing** from the Tender deadline. Implementing agency
and borrower remain Project context and are not relabeled as buyer or
procurement authority. Financing remains deferred because Sprint 1.2 retained
it only as source-specific raw provenance.

## 3. Project Leadership Semantics

The locked heading is **Project Leadership**. Each current assignment is a
separate row containing its published display name, conservative role label,
and institutional source attribution. Multiple leaders and roles are supported.

The UI states that Project leadership is project-level context and may differ
from the Tender's procurement contact. Leadership never changes Tender status,
actionability, deadlines, compliance access, or Proposal behavior.

## 4. Native/Canonical Role Labels

Canonical role controls the normal user-facing label:

| Canonical role | UI label |
|---|---|
| `TASK_TEAM_LEADER` | Task Team Leader |
| `CO_TASK_TEAM_LEADER` | Co-Task Team Leader |
| `PROJECT_TASK_MANAGER` | Task Manager |
| `OTHER_PROJECT_ROLE` | `[Institution] project team` |
| Unknown/null-compatible future value | Project role |

The mapping is centralized in `frontend/types/project.ts` rather than scattered
through component markup.

## 5. `teamleadname` Safety Rule

`native_role = teamleadname` always renders as **World Bank project team** for
World Bank records. It never renders as Task Team Leader, TTL, Co-TTL, or the
raw technical field name. This defense-in-depth check runs before canonical
label mapping, preserving Sprint 1.2's semantic decision even if inconsistent
future payload data reaches the client.

## 6. Procurement Contact Separation

The existing **Contact & Submission** section remains unchanged and separate.
The Project endpoint queries only `TenderProject`, `Project`, and
`ProjectRoleAssignment`; it neither reads nor promotes `CanonicalContact`,
notice contact metadata, submission contact fields, buyer fields, or
implementing-agency contacts.

Leadership email or phone renders as plain professional source data only when
the authoritative assignment supplies it. Null values render nothing. There is
no lookup, inference, placeholder address, mail action, phone action, or CRM
call to action.

## 7. Current/Historical Roles

The endpoint separates `current_roles` and `historical_roles`. Current rows are
visible by default. Historical assignments appear only when present under the
native keyboard-accessible `<details>/<summary>` control **Previous project
leadership**. Historical rows include their observed-until date and cannot be
visually confused with current responsibility.

## 8. Provenance/Freshness

The UI shows the institutional source, official Project URL when present, and
the last successful check date. **Verified from World Bank project data** is
shown only for fresh successful enrichment.

Backend states are translated as follows:

| Source freshness | Presentation |
|---|---|
| Fresh | No warning |
| Stale | Project information may be outdated. |
| Incomplete/partial | Some project information is unavailable. |
| Unavailable/failed | Project details are temporarily unavailable. |
| Pending/not enriched | Project details are being prepared. |

Raw provenance JSON, failure classes, HTTP status, retry count, Celery state,
and lease details are not exposed by the endpoint.

## 9. Loading/Error States

Project Context has an independent restrained loading state and never blocks
core Tender rendering. A successful null response omits the section. A known
World Bank identity can remain visible while enrichment is pending or if the
separate request fails. Project request failures are caught locally and do not
set the Tender page's core error state. There is no polling or repeated fetch
on rerender.

## 10. API Contract

The additive endpoint is:

```text
GET /api/v1/tenders/{tender_id}/project
```

It returns `null` for a visible Tender without a canonical link, otherwise:

```json
{
  "project": {
    "id": "canonical-project-uuid",
    "source_system": "world_bank",
    "external_project_id": "P179267",
    "name": "...",
    "status": "Active",
    "enrichment_status": "successful",
    "source_freshness": "fresh",
    "last_successful_enrichment_at": "..."
  },
  "current_roles": [],
  "historical_roles": []
}
```

The route requires approved pilot access and applies the same customer-visible
Tender condition. It resolves identity through `TenderProject`, not a raw
Tender string. One Project select plus `selectinload` for all role assignments
avoids per-role queries and excludes documents, compliance, and contact data.

## 11. Accessibility

Project and leadership regions use semantic headings. Freshness/error text uses
`role=status`, so it is not conveyed only by color. The official external link
has a descriptive accessible label and safe new-tab semantics. Historical
leadership uses native keyboard-accessible disclosure. Metadata and role grids
collapse to one column at narrow widths and use wrapping/min-width safeguards
to prevent horizontal overflow.

## 12. Test Results

- Sprint 1.3 backend API/presentation contracts: 11 passed.
- Sprint 1.3 frontend deterministic matrix: 17 passed.
- Combined Sprint 1.3, Sprint 1.2, Sprint 1.1, and access focus: 46 passed.
- World Bank connector: 18 passed under each of UTC, Asia/Tashkent, and
  America/New_York.
- Connector gate: 195 passed, 1 skipped, 4 subtests passed, zero failures. The
  existing skip is `test_storage_path_resolver.py:33` because the known 481480
  optional local storage fixture is absent.
- Disabled-authorization and UNKNOWN actionability: 49 passed and 8 subtests
  passed.
- Frontend Project Context test, TypeScript, production build: passed.
- ESLint: zero errors and 15 unchanged pre-existing unused-code warnings.
- Production build retains the pre-existing Next.js middleware-convention
  deprecation warning.
- Repository sole head: `20260826_0002_s1_2_wb_project_enrichment`.
- Disposable PostgreSQL fresh and existing-upgrade `alembic check`: clean; no
  leaked database and zero fabricated leadership rows.
- Immutable baseline and drift contracts: 15 passed. The configured local
  developer database remains intentionally untouched at its older Sprint 0.4C
  revision, so a direct check against that database reports it is not up to
  date rather than generating a schema diff.

## 13. Deferred Work

No standalone Project page/workspace, Project search, Project Explorer,
project recommendations, contact enrichment, people search, outreach, CRM,
ADB leadership, localization, or analysis-language support was added. No new
migration exists, Sprint 2 was not started, and nothing was deployed.
