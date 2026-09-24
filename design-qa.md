# Sprint 10.1 visual QA

Result: **passed** for the authorized design-system and shell foundation scope.

Reviewed the supplied twelve PNG references and the supplied SVG, then paired the customer Tender Explorer and Admin Accounts references with authenticated implementation captures. The reference images were normalized to 1440px width for comparison; this is a shell assessment, not a full-page pixel-match claim. The written brief controls typography, brand, color normalization and deferred page scope.

| Area | Evidence and result |
| --- | --- |
| Customer shell | [Paired full view](docs/audits/s10_1/comparisons/customer-full.png): single light sidebar, clear active navigation, thin header and account control. 224px desktop sidebar and tokenized gutters provide consistent alignment. |
| Admin shell | [Paired full view](docs/audits/s10_1/comparisons/admin-full.png): separate dark navigation/header, blue active state, real Admin destinations and canonical red mark. The mockup shield is intentionally replaced by the supplied brand. |
| Typography | Shared system sans-serif, consistent weight/size hierarchy and tabular numeric treatment. Mockup serif headings are intentionally overridden by the written brief. No downloaded font or new font license is needed. |
| Color and surfaces | Customer light neutrals and blue actions; separate dark Admin tokens; restrained borders, radii and shadows. Logo red remains a brand asset color. Legacy page palettes are deferred. |
| Asset fidelity | Supplied vector retains all 187 colored paths and their coordinates/fills. Only white background and metadata removed; tightened viewBox contains the measured artwork bounds. Light/dark screenshots show the same mark without distortion. |
| Responsive and RTL | Fixture captures cover 320/390/768/1440; authenticated active-refresh captures cover EN/AR at all four widths. [Arabic at 320px](docs/audits/s10_1/runtime/active-refresh-ar-320.png) shows right-side navigation/brand, contained header controls and readable wrapping. No Arabic reference was supplied; RTL is assessed against the shared contract and bidi behavior. |
| Copy and content | Shell labels use the four existing locale catalogs. Account values come from existing session/access data. Screenshot synthetic data belongs only to test fixtures. No mockup notification counts or Broadcast content is implemented. |
| Interaction | Keyboard navigation, account menu, tabs, forms, search clear, modal focus containment/restoration, dismissal and reduced motion pass the deterministic browser checks. Coarse-pointer navigation meets 44px targets. |
| Accessibility | Both foundation themes have zero serious/critical axe findings. Contrast assertions and keyboard tests pass. This does not certify all legacy pages or every screen reader. |

Visual/interaction corrections verified during iteration: visible mobile canonical mark; removal of duplicate legacy padding; tablet refresh-dropdown alignment; wrapping of Bid Preparation metadata at 320px; explicit modal Tab containment. Final foundation suite: 192/192. Authenticated runtime suite: 60/60. Permanent release browser suite: 145/145.

No outstanding blocking findings were observed within the shell/foundation scope. Page interiors intentionally retain their current dark presentation and existing data/actions. Full Dashboard, Explorer and Tender Details redesign belongs to the next separately authorized sprint. Native datalist rendering varies by platform; browser evidence here is Chromium.

# Sprint 10.2 visual QA

The three-page scope passes after the corrections and renewed paired review recorded in [the Sprint 10.2 visual review](docs/audits/s10_2/visual-review.md). Prior Sprint 10.1 evidence above is preserved.

Reviewed combined reference/implementation inputs for [operational Dashboard](docs/audits/s10_2/comparisons/dashboard-full.png), [setup Dashboard](docs/audits/s10_2/comparisons/dashboard-setup-full.png), [Explorer](docs/audits/s10_2/comparisons/explorer-full.png), [selected preview](docs/audits/s10_2/comparisons/explorer-preview-full.png) and [Tender Details](docs/audits/s10_2/comparisons/tender-details-full.png). EN/AR mobile captures verify wrapping and bidi behavior; no mobile mockup was supplied. Source/example content and viewport heights differ, so this is not a pixel-identical data comparison.

Verified fixes: duplicate card padding and row density, Details inner columns, requirement contrast, readable localized errors, translated tab wrapping, tablet popover bounds and readiness definition-list semantics. The supplied mark, system sans, blue actions and purple text-only selected navigation follow the approved foundation. Unsupported images, percentages and domains are intentionally omitted per the mapping ledger.

Final evidence: 359/359 Sprint Chromium checks, 145/145 maintained browser checks, and twelve axe runs with zero serious/critical findings. Keyboard, preview dismissal/focus, explicit actions, locale continuity and passive request budgets pass. This is scoped QA, not formal WCAG certification. No outstanding P0/P1/P2 finding remains within this scope.

final result: passed

# Sprint 10.3 visual QA

My Tenders and the Bid Preparation list pass the scoped review recorded in [the visual review](docs/audits/s10_3/visual-review.md). Earlier Sprint evidence above is preserved.

Reopened the final paired [My Tenders](docs/audits/s10_3/comparisons/my-tenders-full.png) and [Bid Preparation](docs/audits/s10_3/comparisons/bid-preparation-full.png) reference/implementation images after correcting summary spacing and placing actions under desktop facts. Reviewed [English and Arabic at 320px](docs/audits/s10_3/comparisons/mobile.png); narrow layouts wrap within their viewport and preserve original Tender content. Mobile menus pass bounds and focus checks at 320/390/768.

The supplied red mark, system sans, blue actions and purple icon/text-only sidebar selection follow the accepted foundation. Unsupported mockup domains and source-logo assets remain explicit omissions in the pre-implementation ledger. Proposal price/confidence reflect stored fields; pursuit, artifact and source statuses remain separate. No outstanding P0/P1/P2 finding was observed within these lists.

Final evidence: 229/229 Sprint Chromium checks, 145/145 maintained browser checks, eight page axe scans with zero serious/critical findings. This is scoped review, not pixel-identical example-data reproduction or formal WCAG certification.

final result: passed


# Sprint 10.4 visual QA

Company Profile, Readiness Vault and Compliance Analysis pass the scoped [visual review](docs/audits/s10_4/visual-review.md). Earlier sprint evidence above is preserved.

The combined [Profile](docs/audits/s10_4/comparisons/profile-paired-final.png), [Readiness Add record](docs/audits/s10_4/comparisons/readiness-paired-final.png) and [Compliance override](docs/audits/s10_4/comparisons/compliance-paired-final.png) inputs pair the supplied 1536 × 1024 references with browser captures at the same CSS viewport and scale 1. The review records full and focused crops, state/data differences, and all five fidelity surfaces.

Post-fix mobile captures confirm wrapped hashes, separate assessment headings/badges and readable full-row Selects in English and Arabic. Prior insufficient heading wrapping is documented in the iteration history. The existing foundation and canonical data boundaries explain intentional differences from mockup examples, including separate Settings locale controls and omitted unsupported metrics/upload/search.

366/366 Sprint Chromium cases and 145/145 maintained browser cases pass. Page and overlay axe checks have zero serious/critical findings. No actionable P0/P1/P2 issue remains within this scope.

final result: passed

# Sprint 14.2 design QA — Tender Explorer

## Evidence and comparison

- Approved source: `/mnt/d/Downloads/redesign/explorer/ChatGPT Image Sep 16, 2026, 08_23_58 PM.png` (1122 × 1402).
- Implemented render: [English desktop](docs/audits/s14_2/browser/explorer-en-1440.png) (1440 × 1716); [Arabic mobile](docs/audits/s14_2/browser/explorer-ar-390.png).
- Normalized side-by-side: [full page](docs/audits/s14_2/design-comparison.png); [first-result detail](docs/audits/s14_2/design-comparison-first-row.png). The desktop render is scaled to the source width for comparison, so text size should be judged from the original render too.
- Browser evidence: [85-case results](docs/audits/s14_2/browser/results.json), including four locales at 320/390/768/1440 and EN/AR axe at 390/1440.

## Fidelity audit

| Surface | Finding | Disposition |
| --- | --- | --- |
| Product shell/header | Existing Plasma shell preserved; DISCOVERY, title, subtitle and secondary Refresh follow the approved hierarchy. | Pass |
| Discovery workspace | Search first, compact structured filters, active chips and a separate results toolbar. Full-width filters replace the unsupported Saved searches module. | Pass; deliberate product-boundary deviation |
| Results | Four consistent zones: approved source identity, concise tender data, factual status/deadline, canonical match/actions. Neutral tags, light borders and restrained blue/green treatment match the accepted visual language. | Pass |
| Content | Fixture titles/counts/dates differ from the illustrative mockup; production values come exclusively from the Explorer read model. Match percentages appear only for Recommendation rows. | Pass; data-authority deviation |
| Responsive/RTL | No page-level horizontal overflow in 16 locale-width combinations. Mobile ordering is source/status, title/metadata, summary, deadline, match/actions; directional icons mirror in Arabic. | Pass |
| Accessibility | Four representative axe runs have zero serious/critical findings; controls and bookmark states are labeled, keyboardable and focus-visible. | Pass |

## Iterations and residuals

1. Moved mobile status into the leading source/status area, matching the required mobile reading order.
2. Allowed the action header to wrap so the Russian match label and bookmark no longer overflow.
3. Moved Preview to the title line so the action zone stays compact and the primary/secondary actions align with the mockup.
4. The approved World Bank local asset is a cached raster inside an SVG and is softer than the illustrative mark at large zoom. Replacing it requires a newly approved official asset; no invented or remote brand image was introduced. This is a low-priority asset-quality residual, not an actionable Sprint 14.2 layout defect.

No unresolved P0/P1/P2 design findings. Saved searches, match-quality filtering and Compact mode are intentionally omitted because no canonical product contract exists for them.

final result: passed

# Sprint 14.2 follow-up design QA — World Bank logo and budget

The supplied transparent World Bank PNG is 3000 × 2000, and the new Tender Explorer mockup is 1312 × 1199. The final implementation was captured at a 1440px CSS desktop viewport and at 320/390/768/1440px in each of EN/UZ/RU/AR. Compare the [paired full view](docs/audits/s14_2/budget-logo-comparison.png), [paired first-result crop](docs/audits/s14_2/budget-logo-first-row.png), [desktop render](docs/audits/s14_2/browser/explorer-en-1440.png), and [English mobile render](docs/audits/s14_2/browser/explorer-en-390.png). The mockup’s illustrative tender content is not a runtime fixture; compare hierarchy and layout, not example titles or dates.

| Fidelity surface | Finding |
| --- | --- |
| Shell and layout | Existing Plasma shell and Explorer workspace remain unchanged. Four result zones stay aligned; the new Budget fact sits beside Deadline on desktop. |
| Typography, color and assets | Supplied high-resolution WB art is displayed at 48 × 48px within the established source identity; at this review the World Bank text label was still retained. The later logo-only follow-up below removes that visible caption. |
| Content and data | Budget comes from each canonical Explorer row and its own currency. Missing/zero/invalid values render the localized undisclosed-value fallback; no mockup amount is hardcoded. |
| Responsive and RTL | At narrow widths Deadline precedes Budget and both precede actions. Sixteen locale-width combinations have no horizontal overflow; monetary text is bidi-isolated for Arabic. |
| Interaction and accessibility | Existing search, chips, tabs, pagination, bookmark, preview and source actions still pass. Four EN/AR axe scans at 390/1440 report zero serious/critical findings. |

Iterations: the first render showed an Open status pill stretching across its grid track, corrected with start alignment; the next paired crop showed the globe larger than the mockup, corrected to a 48px desktop crop. The final paired crop and browser screenshots were recaptured after both changes. Focused Explorer browser acceptance: **87/87 pass**, including supplied-art loading and canonical/missing budget cases, with zero external requests; [maintained release browser acceptance](docs/audits/s14_2/release_browser/results.json): **145/145 pass**. Frontend static tests: **231/231 pass**. No unresolved P0/P1/P2 findings in this follow-up. The existing Docker app was not rebuilt or deployed.

final result: passed

# Sprint 14.2 follow-up design QA — EBRD and logo-only cards

The user-supplied 1140 × 1141 transparent EBRD image was checked against its exact copied asset. The [final desktop render](docs/audits/s14_2/browser/explorer-en-1440.png) and [390px mobile render](docs/audits/s14_2/browser/explorer-en-390.png) show it on the card's light background with no duplicate source captions. Other known sources are likewise logo-only; the unknown-source fallback retains a visible name. No new layout mockup accompanied this asset request.

Desktop source identity remains within its 90px card column. The EBRD square is 84px on desktop and 72px on mobile, preserving the supplied image's full aspect ratio. Removing captions does not alter the card's title, deadline, budget, actions or source filter. Each logo supplies its source name as alternative text; when a logo is absent or fails, the fallback name remains visible. EN/UZ/RU/AR at 320/390/768/1440 have no horizontal overflow. The four representative EN/AR axe scans report zero serious/critical findings.

Focused Explorer browser acceptance: **89/89 pass**, including source-art loading, caption absence and fallback identity; [maintained release browser gate](docs/audits/s14_2/release_browser/results.json): **145/145 pass**. Frontend tests: **232/232 pass**. Production build passes. No P0/P1/P2 design finding remains within this change. Existing Docker deployment was not altered.

final result: passed

# Sprint 14.2 follow-up design QA — concise result cards

The [desktop](docs/audits/s14_2/browser/explorer-en-1440.png) and [mobile](docs/audits/s14_2/browser/explorer-en-390.png) captures show the result cards without description snippets. The source logo, title, location/reference, tags, deadline, budget and actions retain their reading order and alignment. The full description remains available on Tender Details; the unchanged Preview drawer continues to show key facts only. No new reference image was supplied for this text-removal request.

All 16 EN/UZ/RU/AR × 320/390/768/1440 browser combinations have no horizontal overflow. The explicit card-description absence check passes, as do four EN/AR axe scans with zero serious/critical findings. Focused browser acceptance: **90/90 pass**. Frontend tests: **233/233 pass**; TypeScript, ESLint and production build pass. No P0/P1/P2 issue observed within this small change. The existing deployment was not modified.

final result: passed

# Sprint 14.3 design QA — Tender Details

The approved 874 × 1799 mockup at `/mnt/d/Downloads/redesign/tenderdetails/ChatGPT Image Sep 17, 2026, 04_29_45 AM.png` was paired with the real Chromium [English desktop render](docs/audits/s14_3/browser/tender-details-en-1440.png) (1425 × 1521 raster from a 1440px CSS viewport) in one [normalized comparison](docs/audits/s14_3/design-comparison.png). The [Arabic mobile render](docs/audits/s14_3/browser/tender-details-ar-390.png) records RTL and stacked tables. Source values in the mockup are illustrative; browser values come from a deterministic canonical Details fixture.

| Fidelity surface | Paired-review finding |
| --- | --- |
| Hierarchy and spacing | Back/utility, identity, three decision cards, two project cards, documents, competitor table, contacts and final bid strip follow the reference order. The render is shorter because its fixture has one leadership/document/competitor row rather than four/five/four mockup rows. |
| Typography | The existing Plasma type scale keeps the prominent tender title, compact fact labels, section headings and tabular metadata readable. No long source description or redundant tab strip remains. |
| Color and surfaces | Existing institutional light tokens, thin rules, restrained blue actions and green only for true OPEN state match the mockup. No decorative gradient or dark/customer styling was added. |
| Images and icons | Global Plasma mark is unchanged; outline icons use the established app library. No fabricated logo or bitmap asset was introduced. |
| Copy and authority | Unsupported Project objective/sector, percentages, critical-record claim and collaboration promise are omitted; source-backed names, stored Recommendation, historical competitor evidence and explicit document states remain truthful. |

The first paired render exposed raw `world_bank` when the test source catalog was unavailable. A known-source display fallback was added, and the final paired render shows “World Bank” while still preferring catalog names. The top-bar refresh warning in the first render was a fixture omission; the corrected harness provides a successful local catalog/status response. No actionable P0/P1/P2 visual issue remains.

The [35-case Sprint 14.3 browser result](docs/audits/s14_3/browser/results.json) covers explicit actions, absence of passive writes, empty/error states, 16 EN/UZ/RU/AR × 320/390/768/1440 combinations without overflow, and four representative EN/AR axe runs with zero serious/critical findings. The maintained [145-case production browser gate](docs/audits/s14_3/release_browser/results.json) also passes. Full backend release certification is pending the disposable local database/Redis environment, as recorded in the [Sprint report](docs/S14_3_TENDER_DETAILS_UI_UX_REFINEMENT.md); that external gate is not represented as a design defect.

final result: passed

# Sprint 14.3 follow-up design QA — Project Context and Project Leadership

The approved Project Context / Project Leadership mockup supplied in the conversation and `/mnt/c/Users/acer/Desktop/ui-instruction-report.md` were reviewed against the real Chromium [English desktop render](docs/audits/s14_3/browser/tender-details-en-1440.png), [English mobile render](docs/audits/s14_3/browser/tender-details-en-390.png), and [Arabic mobile render](docs/audits/s14_3/browser/tender-details-ar-390.png). The browser fixture uses five source-backed names so the desktop capture exercises the compact two-column state.

| Fidelity surface | Finding |
| --- | --- |
| Project Context | Existing fields and wording are unchanged. The label/value grid is tighter while retaining a compact semantic definition list. No metadata was added. |
| Project Leadership | The exact English helper copy is smaller and muted. Rows contain names only, with compact padding and subtle dividers; current and historical source records share the same names-only presentation rather than creating role treatments. |
| Scaling | 1–3 names use one column; 4–6 use equal columns; 7+ initially show six names and a localized `View all (N)` control. Expanding and collapsing are keyboard-accessible and preserve every returned name. |
| Layout balance | Desktop uses approximately 55/45 Context/Leadership widths, aligns both cards at the top, and allows independent natural heights. Tablet/mobile stack the cards without horizontal overflow. |
| Visual style | Section icons are reduced and baseline-aligned. Thin neutral borders, no added shadows, restrained blue, and typography-led hierarchy preserve the established institutional system. |
| Accessibility and localization | EN/UZ/RU/AR pass at 320/390/768/1440. Four representative EN/AR axe scans report zero serious/critical findings, and RTL stacking/alignment was visually inspected. |

Verification: **38/38 focused static tests**, **36/36 real-browser acceptance cases**, TypeScript, full ESLint, and the optimized production build pass. The browser gate explicitly covers mixed current/historical names in the 7+ expansion case. No P0/P1/P2 design issue remains in this correction scope. Existing Docker deployment was not rebuilt or changed.

final result: passed

# Sprint 14.3 correction QA — concise Context labels and balanced Leadership height

The supplied three-name defect screenshot was compared with the renewed real Chromium [English desktop render](docs/audits/s14_3/browser/tender-details-en-1440.png). The final render keeps the existing 55/45 composition and visual language while correcting only the requested labels and height behavior. [English mobile](docs/audits/s14_3/browser/tender-details-en-390.png) and [Arabic mobile](docs/audits/s14_3/browser/tender-details-ar-390.png) confirm that stacked cards retain compact natural heights and localized labels.

Project Context now renders exactly `Name`, `Country / Region`, `Status`, `Approval date`, and `Closing date` in English. No field, value, or metadata was added or removed. With three names, both desktop cards have equal measured heights and Leadership remains a single-column names-only list. A separate six-name browser case confirms equal heights with the compact two-column list. The eight-name case confirms that equal-height balancing is disabled, only six names render initially, and `View all (8)` exposes the remaining source-backed names.

Verification: **39/39 focused static tests**, **37/37 real-browser acceptance cases**, EN/UZ/RU/AR at 320/390/768/1440 without horizontal overflow, four representative axe scans with zero serious/critical findings, TypeScript, ESLint, and the optimized production build all pass. No P0/P1/P2 issue remains in this correction scope. The Docker deployment was not rebuilt.

final result: passed

# Sprint 14.3 correction QA — empty Leadership height

The supplied empty-Leadership defect screenshot was reviewed against the focused real Chromium [implementation capture](docs/audits/s14_3/project-cards-empty-balanced-en-1440.png). Project Context retains its canonical populated rows while Project Leadership retains the existing helper and truthful empty message. Both desktop cards measure **194.6875px**, a **0px** height difference, with no added content or decorative treatment.

The balancing condition now covers zero through six returned leadership names. Seven or more names still opt out of equal-height stretching and retain the first-six plus `View all (N)` overflow behavior. The dedicated empty-state browser assertion reports no horizontal overflow and zero serious/critical axe findings. **39/39 focused static tests**, TypeScript, ESLint, and the optimized production build pass. The broader CDP-based browser harness could not relaunch its temporary Windows debug port during this follow-up, so the requested state was independently verified through a direct Playwright Chromium launch and captured above.

final result: passed

# Sprint 14.4 design QA — Compliance Analysis

The approved 1215 × 1295 mockup at `/mnt/d/Downloads/redesign/compliance/ChatGPT Image Sep 17, 2026, 04_56_01 AM.png` was reviewed beside the real Chromium [English desktop render](docs/audits/s14_4/browser/compliance-en-1440.png) in the [normalized paired comparison](docs/audits/s14_4/design-comparison.png). The implementation capture uses a 1440px CSS viewport at device scale 1 and is normalized to the mockup width for the comparison. [English mobile](docs/audits/s14_4/browser/compliance-en-390.png) and [Arabic mobile](docs/audits/s14_4/browser/compliance-ar-390.png) provide the narrow and RTL evidence. Fixture titles, dates, counts, and requirement text intentionally differ from the illustrative mockup.

| Fidelity surface | Finding |
| --- | --- |
| Hierarchy and spacing | Tender context and restrained Beta treatment lead into a compact canonical summary, local search/filters, dense grouped rows, and the evidence inspector. Analysis execution, exact-version export, and history remain available below the primary review workspace as secondary controls. |
| Typography | The existing Plasma sans hierarchy clearly separates page identity, result state, section titles, row titles, metadata, source excerpts, and generated analysis. Compact technical values wrap without clipping. |
| Color and surfaces | Light institutional surfaces, thin neutral rules, restrained blue selection/action treatment, and semantic red/amber/green labels follow the mockup without adding gradients or decorative cards. Status is always conveyed in text and icon as well as color. |
| Images and icons | The existing canonical Plasma mark and established outline icon set are retained. No generated, remote, or invented visual asset was added. |
| Copy and data authority | Summary counts and groups use only immutable Compliance result fields. Manual review is not relabeled as failure; recorded obligations remain separate; unsupported related-requirement, note, and readiness-link persistence are omitted. Source evidence appears before Plasma analysis. |
| Responsive, RTL, and accessibility | EN/UZ/RU/AR pass at 320/390/768/1440 with no page overflow. Desktop uses a sticky inspector; narrower layouts use a focus-restoring drawer. Four representative EN/AR axe scans report zero serious/critical findings. |

Iterations during QA corrected warning-label contrast, semantic definition-list order, secondary-control hierarchy, localized matched-section test matching, and resting-state screenshot capture. The final focused browser result is **40/40**, the complete frontend static suite is **246/246**, focused backend Compliance/version/language regression is **47/47**, and TypeScript, design-token, legacy-design, RTL, literal-copy, and optimized production-build gates pass. No unresolved P0/P1/P2 design finding remains within Sprint 14.4 scope. Docker deployment was not changed.

final result: passed
