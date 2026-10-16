# P1 report: pilot readiness

Branch `pilot/p1-pilot-readiness` on `pilot/s1-release` (the Deploy 4 release; no `pilot/s1-int` history).
Local only: nothing pushed or deployed. Deploy steps: [P1_DEPLOY_NOTE.md](../../ops/P1_DEPLOY_NOTE.md).

## 1. Audit: what existed

| Area | Before P1 |
| --- | --- |
| Sign-in | Google only (Auth.js → signed bridge assertion → backend JWT, 8 h; session 8 h, re-validated on every callback) |
| E-mail | SMTP outbox from R3 (STARTTLS/SSL, retries, sealed secrets) used for invitations, analysis/EOI mails and the digest; never configured on production |
| Approval | every new user `pending` until an admin approved the user **and** the company; pending page with "refresh status" |
| Organization gate | company approval, enforced by `require_approved_pilot_access` on tender/explorer routes, **not** on organization-scoped routes (pursuits, uploads, analyses, library, EOI): a pending-company owner could call them directly |
| Pilot state | `company_profiles.pilot_status` (CRM label, no plan dates, no criteria); demo seed and prospect previews only |
| Library import | D2-02: per-tab CSV import in the browser, row by row (not atomic), no XLSX, no assignments, no duplicate check |
| Own-TOR path | upload (PDF/DOCX, ClamAV, parse) → analysis → review → team search → EOI: all present (W3–W8, D2) |
| Deploy 4 blocker (S1-8) | runbook step 8b: the Bid Preparation redirect hides proposals without a pursuit (116 of 122 locally) → STOP |

## 2. What I built

**1a. E-mail one-time code** (`app/services/email_sign_in.py`, `auth.py`, `frontend/auth.ts`, `SignInPanel.tsx`)
- `POST /auth/email/request-code`: 202 with the same body for every address (new, existing, disabled,
  admin, malformed-but-valid). 6 digits from `secrets`, stored only as HMAC-SHA256(key from SECRET_KEY,
  challenge id + code); one open challenge per address (new request supersedes; partial unique index +
  advisory lock); 10-minute expiry; single use; 5 wrong attempts close it.
- Limits (Redis, **fail closed**): 1 request/min and 5/h per address, 30/h per client address; verify 10 per
  10 min per address, 30 per 10 min per client. Rate-limit keys hold a hash of the address, never the address.
- `POST /auth/email/verify-code` accepts only a signed, single-use, 60-second bridge assertion from the
  Auth.js server (`purpose: email_code`; a Google assertion is never accepted here); the client address
  travels in it for the per-address limit.
- Blocked (disabled/rejected) and privileged accounts (admin/operator or on an allowlist) get a challenge but
  **no e-mail**: privileged accounts sign in with Google only (their Google accounts carry 2FA; an SMTP code
  would be the weakest path into admin).
- Audit events: `EMAIL_SIGN_IN_CODE_REQUESTED` (with delivery: staged / no channel / blocked / privileged),
  `EMAIL_SIGN_IN_SUCCEEDED`, `EMAIL_SIGN_IN_FAILED` (reason code), `EMAIL_SIGN_IN_CODE_LOCKED`; codes and
  hashes never appear in events, logs or outbox payloads.
- Same user as Google: a code-only account is a pre-provisioned row (`plasma-preprovisioned:<email>`) that the
  first Google sign-in binds; Google first, code later reaches the same row. Invitations accept on code sign-in
  through the same function (`actor_label=auth/email-code`).
- Sessions ~30 days: rotating refresh tokens (`auth_refresh_tokens`, SHA-256 only), 30-day idle, 90-day cap;
  a rotated token reused after a 60 s grace (two tabs) revokes the family (`REFRESH_REUSE_DETECTED`); any
  `auth_version` change (disable, role, approval) or logout ends it. The refresh token lives only in the
  encrypted Auth.js cookie, never in browser JS. Access token stays 8 h.
- Codes leave through the outbox, sealed until sent, and a code past its 10 minutes is never sent (FAILED).

**1b. Delivery**: SMTP settings and DNS (SPF/DKIM/Return-Path/DMARC for plasmaos.uz, Postmark or SES) in the
deploy note; `scripts/send_test_sign_in_code.py --to … --confirm SEND_TEST_CODE` (real path, or `--direct`).

**1c. No manual user approval**: a verified e-mail approves at sign-up (Google or code); migration 0001
approves every pending user (one audit event each) and a disabled user's restore target; the organization gate
stays and is now **enforced on every organization-scoped route** (`resolve_organization_context` requires an
approved company). Source-refresh POSTs moved from user approval to the organization gate so the change
widens nothing. Admin disable/restore unchanged.

**1d. Explore | pilot | paid | disabled** (`organizations.access_state` + plan dates + success criteria,
migration 0002; `app/services/organization_access.py` keeps the company gate in step):
- Explore: opportunities feed (top open by deadline), coverage strip, one guided demo analysis (fixed JSON of a
  real public notice analysed for the fictional demo firm, `scripts/export_explore_demo.py`), "Start a pilot"
  and "Book a call" (link if `PUBLIC_BOOK_CALL_URL`, else a request). It replaces the pending page; the shell
  shows only "Explore". No uploads, analyses, library or award ledger (backend-enforced, 404/403).
- Admin: `/admin/organizations` shows state, plan and criteria; admins change them (audited
  `ORGANIZATION_ACCESS_CHANGED`); admin company approve/reject/disable move the state too.
- Alerts (`admin_alerts`, Beat + kick): Telegram if `ADMIN_ALERT_TELEGRAM_CHAT_ID`, else e-mail to
  `PLASMA_ADMIN_EMAILS`: every new self sign-up (not invitees), every pilot/call request, and (found in item 4)
  the AI provider rejecting the key/billing, once an hour while it lasts.

**2. Pilot setup** `scripts/pilot_setup.py`: `--firm`, `--owner`/`--member`, `--start`, `--months 3`/`--end`,
`--success-criteria`, `--dry-run`/`--confirm PILOT_SETUP`, `--send-invitations`, `--resend`, `--list`. Real
organization (refuses preview/demo names and organizations it did not make), state pilot, plan and criteria,
invitations that bind at the first sign-in by Google or code; re-runs add only new addresses.

**3. Library import** (`app/services/library_import.py`, `/candidates/library-import/{template,preview,commit}`,
`WorkbookImport.tsx`): one XLSX (Instructions, References, Experts, Expert assignments; drop-downs; frozen
header) or one CSV per sheet, also the D2-02 CSV headers. Standard-library reader (no new dependency): 2 MB,
1,000 rows/sheet, zip and XML part limits, DOCTYPE/ENTITY refused. Preview marks every row new / already there /
error with the reason; commit re-reads the file, refuses a different one (SHA-256), writes all new rows in **one
transaction**; records are UNVERIFIED like typed ones. Files: `docs/ops/p1/plasma-library-import-template.xlsx`
(+ three CSVs) and a filled `plasma-library-import-sample.xlsx` (fictional demo firm: 40 references, 12 experts,
13 assignments). Explore organizations cannot import.

**4. Own-TOR path**: see section 4. **5. Deploy 4**: My Tenders lists proposals without a pursuit ("Earlier bid
drafts (N)", each opening its bid page), so step 8b is informational; runbook updated.

## 3. Tests

New: `test_p1_01_email_sign_in.py` (7), `test_p1_02_organization_access.py` (4),
`test_p1_03_library_import.py` (5). The Postgres scenarios cover: identical answers for new/existing/disabled/
admin/allowlisted addresses; no e-mail for blocked and privileged; fail-closed limits; four wrong codes then lock;
expiry; single use; supersede; Google ↔ code reach one row; a pre-P1 pending user approved at Google sign-in;
invitation accepted by code; rotation, sibling in grace, reuse → family revoked, `auth_version` and logout end a
family; the outbox sends once and wipes the secret; migration up/down/check with data; explore refused by the
organization context and allowed the feed; Explore endpoints and request limits; sign-up alerts only for self
sign-ups; Telegram retry/failed, e-mail fallback, NO_CHANNEL; admin editor (validation, audit, company gate,
paid/disabled); admin company approve → pilot; pilot setup dry run, write, re-run, refusals, invited owner lands
in the firm; import counts, duplicates (file, library, CV), SHA guard, one-transaction commit, re-import no-op.

Updated (behaviour changed on purpose): new users are approved (R3 invitations, release security login policy,
S1 access foundation, onboarding), the migration head pins (63 files), refresh/logout signatures, the R3
admin-panel contract (one PUT), the onboarding/Explore contract.

**Gate** on `b3b75f3` (LF export, WSL, disposable databases on the shared Postgres, Redis DB 8):

| Group | Result |
| --- | --- |
| backend (131 files, 12 batches, a fresh process each; includes the security group and the migration-hash test on LF bytes) | **1,207 passed**, 1 skipped, **2 failed** → both were contract tests pinning pre-P1 behaviour (proxy public paths; explorer refusing a pending company), updated in the next commit and green on re-run: **1,209 passed** |
| migrations | heads, current, check, schema preflight: **PASS** |
| frontend | typecheck, lint, **406/406** node tests (after fixing two raw colour fallbacks, one unmirrored arrow and the R3 admin-panel contract), RTL audit **ok**, production build **OK** |
| browser group (`release-hardening-browser.py`) | **not run** (memory); the E2E screenshots above exercise the changed screens |
| connectors, performance, config-dependencies | not re-run: no connector, scale or dependency change (no new package) |

## 4. Own-TOR demo path (item 4): two real TORs

TOR A: GIZ 10032993, *Digital platform for Jordan's National Water Master Plan process*, ToR, PDF, 25 pages.
TOR B: World Bank OP00454427, *Consultancy services for the provision of a Regional Fund Manager* (R-DARES),
TOR, DOCX, 13 pages. Firm: Northwind Engineering Consultants LLC (pilot via `pilot_setup.py`), library from the
sample workbook. Local stack: this branch's backend and one worker on a disposable database, shared ClamAV.

| Step | TOR A (PDF) | TOR B (DOCX) |
| --- | --- | --- |
| Upload request | 1.9 s (wall, UI) | 1.9 s |
| Malware scan + parse | 6.9 s (worker) | 6.1 s (wall) |
| Analysis | **FAILED after 4.6 s**: provider HTTP 402 | **FAILED after 4.4 s**: provider HTTP 402 |
| Review / team shortlist / EOI | not reachable (no completed analysis) | not reachable |

**Blocker: the Gemini key in the local `.env` is rejected with HTTP 402** (billing or prepaid credits). The last
successful local analyses date from 2026-10-10. You chose to skip live analyses, so the review, shortlist and EOI
steps and their run times are **not measured** in P1; the S1-8 report has the last measured figures (analysis
20–192 s on short notices). Rerun when the key works: `p1_e2e.py tor A|B` (scratch script; the steps are the
UI's own API calls). If production's key is on the same Google account, every production analysis fails today.

Fixed during the run:
- "Plasma has been notified" on a provider failure was not true: it now alerts the team (above).
- Code-sent step broke the address at its hyphen; it now sits on its own line.
- Code-only accounts were named by the raw local part; `first.last@` now shows "First Last".
- The invite page said "This invitation link is not valid" right after a successful sign-in accepted it; it now
  says the user has joined and opens the workspace (Google had the same flaw).
- Explore showed every workspace link and "Upload Tender" (all bouncing back) and "Command Center"; the shell now
  shows only Explore.
- The admin "pilot" badge carried a warning icon; pilot/paid are success-toned.
- Import preview counted assignments already on an expert's CV as new (Import then skipped them); they are
  duplicates now, so the button promises only what it adds.
- Import requires a value basis with a contract value (the library's own rule) and says so per row.
- A transient 401 on one code verification did not recur in three probes and a retry (logged, not explained).

Still reads imperfectly (not changed): the failed-analysis box gives no reason (the reason text is English-only
from the backend); an uploaded pursuit's Documents tab says "This tender has no official/source documents"
(true, but odd for an upload); the guided demo is the only completed local run (Rogun HPP LTA, 0 of 8 met),
an honest but unflattering example with no team step (the view now hides empty steps): re-export from a better run once analyses work
(`scripts/export_explore_demo.py --run-id …`).

## 5. Screenshots (`screens/`)

| File | Step |
| --- | --- |
| 01-1 / 01-2 / 01-3 | sign-in page (Google + e-mail code) · code sent · invited owner lands in the pilot workspace |
| 02-1 … 02-4 | import dialog · preview (40 + 12 + 13 new) · import finished (re-import over existing experts) · library |
| 03-1 | onboarding after a self sign-up by code |
| 03-2 (+ -390) | Explore view, desktop and mobile |
| 03-3 | guided demo: gaps and EOI steps (the exported run has no team shortlist; that step is now hidden) |
| 03-4 | "Start a pilot" sent |
| 04-1 / 04-2 / 04-3 | admin Organizations · access editor (explore → pilot, 3-month default) · after save |
| 05-1 / 05-2 | invite page with both sign-in methods · after sign-in (before the wording fix) |
| 06-1 | My Tenders: earlier bid drafts |
| 1A-1, 1A-2 / 1B-1, 1B-2, 1B-3 | upload with role and context · documents ready · analysis failed (402) |

## 6. Security choices (summary)

Fail-closed limits on the 6-digit path; HMAC (keyed) code hashes; codes only in the mailbox (sealed in the
outbox until sent, wiped after, never sent stale); identical responses; no e-mail path into admin/operator
accounts; verify reachable only through Auth.js (signed, single-use, 60 s); refresh tokens hashed, rotated,
reuse-detected, bound to `auth_version`; organization gate now enforced on all organization-scoped routes;
no new runtime dependency (XLSX via the standard library with hard limits).

## 7. Risks and open items

- **Gemini 402** (above): fix billing before the pilots; the smoke in runbook step 13 catches it.
- DNS records must be verified before the window, or codes land in spam / are rejected (DMARC).
- Telegram alerts need a chat id; otherwise they go to `PLASMA_ADMIN_EMAILS` by e-mail.
- Existing sessions have no refresh token until their next sign-in (they keep today's behaviour until then).
- The Explore feed and coverage are empty on a fresh database (fine on production).
- The staging stack was stopped for this work (your approval) and restarted afterwards (section 8).

## 8. Environment

Staging stack stopped (stop only) during the E2E and the gate, then started again; the shared `plasmaos`
stack was never stopped. Disposable databases `plasma_s05b4b_p1*` on the shared Postgres; Redis DB 7/8 for the
E2E and gate so the shared workers never saw those tasks.
