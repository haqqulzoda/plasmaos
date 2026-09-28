# W0 route and interface map

Current route evidence: `frontend/app/dashboard/**/page.tsx`, `frontend/app/admin/**/page.tsx`, `backend/app/main.py`, and endpoint routers. No navigation changes were made.

| Current page/deep link | Current authority/API | Future destination and compatibility |
|---|---|---|
| `/dashboard` | Recommendation shortlist, source refresh activity, engagement counts | Dashboard/Opportunities overview; retain route and passive reads. |
| `/dashboard/tenders` | `/api/v1/explorer/tenders`, source catalog | Opportunities; retain existing source filters and links. |
| `/dashboard/tenders/[tenderId]` | Shared Tender plus Project Context, Leadership, contacts, documents, optional owned engagement | SourceOpportunity details, with explicit “start/open pursuit”; preserve UUID deep link and all World Bank sections. |
| `/dashboard/tenders/[tenderId]/compliance` | Owned TenderAnalysis/AnalysisVersion, Vault and overrides | Pursuit Analysis/Gap tab for source-linked work; preserve old deep link with owned pursuit resolution; no analysis on page load. |
| `/dashboard/my-tenders` | `/api/v1/my-tenders`, Engagement | My Tenders organization pursuits; preserve list URL, adapt query/ID contract in a versioned API or compatibility adapter. |
| `/dashboard/bid-preparation`, `/dashboard/bid-preparation/[proposalId]` | `/api/v1/proposals`, Proposal ID | Pursuit Proposal tab; keep Proposal ID deep link redirect after ownership check. |
| `/dashboard/settings` | User preferences and `/users/me/company` | Company & Evidence, plus account preferences. Keep profile link redirect. |
| `/dashboard/readiness-vault` | `/vault`, `/vault/readiness` | Company & Evidence; preserve legacy entry/IDs during evidence migration. |
| `/dashboard/notifications` | `/api/v1/notifications` | Notifications; reuse route. |
| `/admin`, `/admin/approvals`, `/admin/companies/[companyProfileId]`, `/admin/audit`, `/admin/broadcasts` | Platform approval, account lifecycle, audit and broadcasts | Admin; retain platform role separation and current links. |
| `/dashboard/admin/*` | Legacy admin links | Existing redirects stay until replacement routes are verified. |
| `/dashboard/bids`, `/dashboard/bids/[id]`, `/dashboard/proposals`, `/dashboard/workspace`, `/dashboard/hunter` | Legacy redirects or retired hunter surface | Maintain redirect behavior; never infer a pursuit or create Proposal on GET. |
| No current route | No organization-private upload tender authority | Uploaded Tenders index and persistent Upload Tender action require W2/W3. |
| No current route | No partner or expert authority | Partners & Experts requires W5. |

Target navigation: **Opportunities, Uploaded Tenders, My Tenders, Company & Evidence, Partners & Experts, Notifications**, with a persistent **Upload Tender** action. The source opportunity detail and pursuit workspace are distinct route identities. A source Tender UUID, Engagement UUID, and Proposal UUID must not be interchanged.

Key API compatibility surface: `/api/v1/tenders/{id}` and `/details`, `/project`, `/documents`, `/latest-analysis`, `/compliance`, `/api/v1/my-tenders/{engagement_id}`, `/api/v1/tenders/{id}/engagement`, and `/api/v1/proposals/{proposal_id}`. Add organization pursuit APIs before redirecting these. Existing GETs should remain passive.
