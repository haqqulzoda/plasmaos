# S1 outreach tooling (plasmaos)

Branch `pilot/s1-outreach` from `origin/pilot/week1` (a83d575). Local only; nothing deployed, no migration.

## 1. Prospect seed: "<Firm> — Plasma preview"

```
python scripts/demo/seed_demo.py --target local --prospect-file prospect.json --dry-run
python scripts/demo/seed_demo.py --target local --prospect-file prospect.json --confirm SEED_DEMO
python scripts/demo/seed_demo.py --target local --prospect-file prospect.json --confirm SEED_DEMO --resume pv20261010-1
python scripts/demo/seed_demo.py --target local --list-previews
python scripts/demo/seed_demo.py --target local --archive-preview <organization-id> --confirm SEED_DEMO
```

Run it where the D3-04 seed runs (backend container, or a one-off container on the stack network). `--target production` works the same once deployed.

**Prospect file** (`backend/scripts/demo/prospect.example.json`): `firm_name`, `country`, `services`, `sectors`, optional `regions`, 3–8 `references` (each with `source_url`; optional client, country, sector, service, role, dates as `YYYY`/`YYYY-MM`/`YYYY-MM-DD`, value + currency, scope) and optional `experts` (name, title, `source_url`, years, languages, specializations). Unknown keys are refused, so contact details cannot be stored.

**What a run creates**
- Organization **"<Firm> — Plasma preview"**. A per-run steward (`demo-steward+pv<date>-<n>@plasma.invalid`, which can never sign in) owns the company profile; **plasmatest0@gmail.com is an OWNER**. Previews coexist: the demo user switches between them with the R3-6 organization switcher, and no other organization is touched.
- The firm, its references, experts and CVs, all `UNVERIFIED`, with provenance `{"demo": true, "seed": "s1-prospect", "origin": "public_records", "verification": "unverified", "note": "From public records, unverified.", "source_url": …}`. Every reference's scope text ends with "From public records, unverified. Source: <url>", so the marking travels with the record wherever its scope is shown. Nothing the file doesn't state (director, address, phone, tax number) is invented.
- One pursuit on the best-matching **open World Bank REOI**: firm-level consulting, closing at least 7 days out, official notice ≥ 2,000 characters, at least one sector keyword. Ranking: sector words in the title (whole words), then the firm's service words in the title, then sector words in the project sectors and notice text, then the firm's country, then region, then latest deadline. You can pin one with `--tender-external world_bank:OP…`.
- The analysis (real provider), the bulk review confirmation (as in D3-04), and **EOI v1** (DOCX + PDF).

**Never contacts anyone.** It creates no account that can sign in and approves none: the demo user must already exist and be approved, otherwise the run is refused. Event staging is suppressed (no inbox items, e-mails or broadcasts), and the source URLs are stored but never fetched.

**Archive** revokes every membership except the steward's, renames the org to "… (archived YYYY-MM-DD)" and stamps the profile notes. Records are kept, since the analysis and EOI tables are append-only. It is idempotent and refuses anything that is not a prospect preview. Once a preview is archived, the same firm can be previewed again.

### Timing (local stack, real Gemini analysis, 2026-10-10)

`pv20261010-1`, "Example Water Engineering LLC — Plasma preview" (the example file). Picked OP00473995, "Feasibility Study and Detailed Design of Irrigation Schemes…" (Ethiopia).

| Step | Seconds |
|---|---|
| plan (tender ranking) | 1.7 |
| organization + records | 1.5 |
| analysis (queued → worker → COMPLETED, READY_FOR_REVIEW) | 27.3 |
| review confirmation + EOI v1 (DOCX 39 KB, PDF 31 KB) | 4.2 |
| **total** | **34.6** (54 s wall clock including container start) |

`notifications_emitted 0`, `broadcasts_emitted 0`. The default analysis wait is 480 s, so a stuck worker fails the run before 10 minutes; `--resume` continues it. Note: the EOI's one shortlisting criterion matched none of the three fictional example references, so real prospect references matter for a convincing preview.

The local `plasmatest0@gmail.com` account did not exist, so it was pre-provisioned once through D3-04's audited `ensure_demo_user`. That staged its own ACCOUNT_APPROVED in-app notification; SMTP is not configured locally, so nothing was sent.

## 2. Coverage strip on Opportunities

`frontend/components/source-refresh/CoverageStrip.tsx`, under the Opportunities header. For each customer-visible source in the registry catalog (UzEx, World Bank, GIZ, EBRD) it shows the notice types (translated), the **last successful refresh** (`last_success_at` from `/tenders/sources/refresh-status`, formatted for the locale) and the partial/stale notes, then **"ADB consulting — Coming"**. No backend change. Messages are in en/ru/uz/ar; layout uses logical properties (RTL-correct) and design tokens. It is hidden while the catalog loads or fails, since the Refresh menu already reports that.

## 3. Legacy URLs

| URL | Lands on |
|---|---|
| `/dashboard/bids`, `/dashboard/proposals`, `/dashboard/bid-preparation`, `/dashboard/workspace` | `/dashboard/my-tenders` (Pursuits) |
| `/dashboard/readiness-vault` | `/dashboard/settings/readiness` (Company & Experience) |
| `/bids`, `/proposals`, `/bid-preparation`, `/workspace` | `/dashboard/my-tenders` |
| `/readiness-vault` | `/dashboard/settings/readiness` |

The Readiness Vault page moved under Company & Experience (`app/dashboard/settings/readiness/page.tsx`, unchanged content), because it is the only place that feature lives. A bare redirect would have removed it. Links from Company & Experience and Compliance point there. Proposal pages (`/dashboard/bid-preparation/<id>`, `/dashboard/bids/<id>`) still open, because Pursuits links to legacy proposals, and their back links now go to Pursuits.

## Files

- Backend: `scripts/demo/prospect.py` (new), `scripts/demo/prospect.example.json` (new), `scripts/demo/seed_demo.py` (CLI flags; ranking takes keywords, home country, notice type, whole words, title-first and services; D3-04 defaults unchanged), `test_s1_prospect_seed.py` (new).
- Frontend: `components/source-refresh/CoverageStrip.tsx` (new), `app/dashboard/tenders/page.tsx`, `components/customer/pages.css`, `messages/{en,ru,uz,ar}/explorer.json`, the five redirect pages, `app/dashboard/settings/readiness/page.tsx` (moved), `app/dashboard/settings/page.tsx`, `app/dashboard/tenders/[tenderId]/compliance/page.tsx`, `app/dashboard/bid-preparation/[proposalId]/page.tsx`, `app/dashboard/bids/[id]/page.tsx`, `next.config.ts`, `tests/s1-outreach.test.mjs` (new), `tests/s1-outreach-browser.py` (new), and route expectations in 8 existing static tests.

## Tests

- `test_s1_prospect_seed.py` + `test_d3_04_demo_seed.py`: **20 passed** on disposable PostgreSQL. WSL was unavailable (Wsl/Service/0x8007274c), so they ran in a one-off capped container sharing `plasma_db`'s loopback, with a `plasma_s05b4b_*` database. The prospect end-to-end test covers: refusal without an approved demo user, ranking (including Ports/Waterways and IFB exclusion), the pin, a sector mismatch, seeding, zero rows in every notification/broadcast table, membership and ownership, provenance on every record, EOI v1, the duplicate-name refusal, resume idempotency, coexisting previews, listing, archive (confirm, non-preview refusal, idempotency, records kept) and re-preview after archive.
- Frontend: `node --test tests/*.test.mjs` **402 passed, 0 failed**; `tsc --noEmit`, eslint on changed files, `audit-customer-literals` and `audit-rtl` clean.
- Browser (`tests/s1-outreach-browser.py`, production build, mocked API): strip shows 4 sources + ADB, 3 refresh times, no overflow, in en/ru/ar at 1440 and 390; all 10 legacy URLs land correctly. **PASS.**

Screenshots: `docs/audits/s1/screens/` (`opportunities-coverage-{en,ru,ar}-{1440,390}.png`, `coverage-strip-…`).

## Risks

- **Prospect data is public and unverified.** A preview shows a real firm's name inside our product. Keep previews private to the demo account, show them only to that firm, and archive after the conversation. The scope text and the org name say "Plasma preview" and "From public records, unverified".
- **Match quality depends on the sectors written in the file** and on open World Bank REOIs at the time. If nothing matches, the run refuses; pin a notice with `--tender-external`.
- **EOI substance depends on the references.** Thin references produce an EOI with criteria left uncovered, as in the timing run.
- **The bulk review confirmation** (inherited from D3-04) marks AI-extracted requirements as confirmed by the demo user. That is acceptable for a preview, but it is not a human review.
- **Readiness Vault URL change:** old bookmarks redirect, but browser acceptance scripts that open `/dashboard/readiness-vault` directly now follow a redirect (not run here; the static tests were updated).
- **The Bid Preparation list is gone** (redirects to Pursuits). Legacy proposals stay reachable from their pursuit and by direct link, but there is no list of proposals that have no pursuit.
- The preview organization from the timing run is still active in the local database (`de425a60-…`). Archive it with the command above when no longer needed.
