# P1 deploy note: pilot readiness on production

For the owner. Deploys `pilot/p1-pilot-readiness` (= `pilot/s1-release` + P1) **as Deploy 4**: run
[DEPLOY_4_RUNBOOK.md](DEPLOY_4_RUNBOOK.md) exactly as written, with the changes in section 3 below. Do
the DNS and SMTP work (sections 1–2) a day before the window: DNS records take hours to propagate,
and the test command (section 4) proves them.

| | |
| --- | --- |
| Checkout | `pilot/p1-pilot-readiness` @ its newest commit (on `pilot/s1-release`; contains no `pilot/s1-int` history). Never push or deploy `pilot/s1-int` |
| Images | build from that commit (`scripts/compose-release.sh export`), as runbook step 6 |
| Migrations | four, in order: the two S1 ones, then `20261016_0001_p1_email_sign_in`, `20261016_0002_p1_organization_access` |
| New tables | `email_sign_in_challenges`, `auth_refresh_tokens`, `admin_alerts` |
| Data changes | every `pending` user → `approved` (one `USER_APPROVED` audit event each, actor SYSTEM, source `P1_MIGRATION`); `organizations.access_state` backfilled from the company approval (approved → pilot, pending → explore, rejected/disabled → disabled) |
| New variables | `SMTP_*` (now required for e-mail sign-in), `PUBLIC_APP_URL`, `ADMIN_ALERT_TELEGRAM_CHAT_ID` (optional), `ADMIN_ALERT_TELEGRAM_BOT_TOKEN` (optional), `PUBLIC_BOOK_CALL_URL` (optional) |
| Sessions | users stay signed in about 30 days (rotating refresh tokens, 90-day cap). Existing sessions keep working; they get a refresh token at their next sign-in |

## 1. E-mail: transactional provider and DNS for plasmaos.uz

Sign-in codes, invitations and admin alerts go out over SMTP from **`no-reply@plasmaos.uz`**. Any
transactional provider works; two that need no extra code:

| | Postmark (recommended: transactional only, fast delivery) | Amazon SES (eu-central-1) |
| --- | --- | --- |
| `SMTP_HOST` | `smtp.postmarkapp.com` | `email-smtp.eu-central-1.amazonaws.com` |
| `SMTP_PORT` / `SMTP_TLS` | `587` / `starttls` | `587` / `starttls` |
| `SMTP_USER` / `SMTP_PASSWORD` | the Server API token (both fields) | the SES SMTP credentials (IAM, not the AWS keys) |
| Before going live | approve the account (Postmark reviews new accounts) | leave the SES sandbox (request production access) |

DNS records to add in the plasmaos.uz zone (the provider's domain page shows the exact values; copy
them from there, do not retype):

| Purpose | Name | Type | Value |
| --- | --- | --- | --- |
| **SPF** (root) | `plasmaos.uz` | TXT | `v=spf1 include:spf.mtasv.net ~all` (Postmark) **or** `v=spf1 include:amazonses.com ~all` (SES). **Only one SPF record may exist**: if the root already has `v=spf1 …` (for example for Google Workspace: `include:_spf.google.com`), add the `include:` to that record instead of creating a second one |
| **DKIM** | Postmark: `<date>pm._domainkey.plasmaos.uz` · SES: three records `<token>._domainkey.plasmaos.uz` | Postmark: TXT · SES: CNAME | Postmark: the `k=rsa; p=…` public key from the Sender Signature / Domain page · SES: `<token>.dkim.amazonses.com` for each of the three tokens (Easy DKIM) |
| **Return-Path / MAIL FROM** (SPF alignment) | Postmark: `pm-bounces.plasmaos.uz` · SES: `bounce.plasmaos.uz` | Postmark: CNAME `pm.mtasv.net` · SES: MX `10 feedback-smtp.eu-central-1.amazonses.com` and TXT `v=spf1 include:amazonses.com ~all` | as on the provider page |
| **DMARC** | `_dmarc.plasmaos.uz` | TXT | start with `v=DMARC1; p=none; rua=mailto:dmarc@plasmaos.uz; fo=1; adkim=r; aspf=r` (reports only). After two weeks of clean reports: `p=quarantine`, later `p=reject` |

`dmarc@plasmaos.uz` must be a mailbox that exists (or use the provider's DMARC reporting address).
Wait until the provider shows SPF, DKIM and Return-Path as **verified** before the window.

## 2. `.env` additions on the production host

Add before runbook step 9 (after step 7's `.env` copy), then `chmod 600 .env`:
```
prod$ cat >> .env <<'EOF'
# P1: e-mail sign-in codes, invitations and admin alerts
SMTP_HOST=<from section 1>
SMTP_PORT=587
SMTP_TLS=starttls
SMTP_USER=<token or SMTP user>
SMTP_PASSWORD=<token or SMTP password>
SMTP_FROM=Plasma <no-reply@plasmaos.uz>
PUBLIC_APP_URL=https://<APP_DOMAIN>
# P1: new sign-up and pilot-request alerts: Telegram if set, else e-mail to PLASMA_ADMIN_EMAILS
ADMIN_ALERT_TELEGRAM_CHAT_ID=<chat id, e.g. -100…; optional>
# ADMIN_ALERT_TELEGRAM_BOT_TOKEN=<only if the alert bot differs from TELEGRAM_BOT_TOKEN>
# P1: Explore view "Book a call" (https scheduling link; optional, else the button sends a request)
PUBLIC_BOOK_CALL_URL=<https://cal.example/plasma; optional>
EOF
```
- `PLASMA_ADMIN_EMAILS` must list the people who receive e-mail alerts (already set since Deploy 1).
- Telegram chat id: add the bot to the team group, send one message, then
  `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":-[0-9]*'`.
- The frontend needs nothing new (`AUTH_SECRET`, `AUTH_BRIDGE_SECRET` and `BACKEND_INTERNAL_URL` as before).

## 3. Changes to the Deploy 4 runbook

| Step | Change |
| --- | --- |
| 0 | `COMMIT=<newest commit of pilot/p1-pilot-readiness>`; `SHA` = the image tag built from it |
| 2 | check out `pilot/p1-pilot-readiness` instead of `pilot/s1-release` |
| 7 | after saving `.env.pre-deploy4`, append section 2's block |
| **8b** | **no longer a STOP.** P1 lists every proposal without a pursuit under My Tenders → "Earlier bid drafts (N)", each opening its bid page, so the redirect hides nothing. Run the SQL anyway and keep the counts: the TOTAL row is the number of drafts that list shows across organizations |
| 10 | expect four upgrades; the last two lines are `… -> 20261016_0001_p1_email_sign_in, P1: e-mail one-time-code sign-in, rotating refresh tokens, no manual user approval.` and `… -> 20261016_0002_p1_organization_access, P1: organization access state …`; `alembic current` prints `20261016_0002_p1_organization_access (head)`. Before step 10, note the counts for the after-check: `select approval_status, count(*) from users group by 1;` and `select approval_status, count(*) from company_profiles group by 1;` |
| 12 (new check) | `prod$ docker exec -i plasma_db psql -U plasma -d plasma_ai -c "select access_state, count(*) from organizations group by 1"` → explore = the pending companies, pilot = the approved ones, disabled = rejected + disabled; `select count(*) from users where approval_status='pending'` → **0** |
| 17 (additions) | see section 5 |
| Rollback A | safe: the Deploy 3 code ignores the new columns and tables. Accounts approved by the migration stay approved (by design). E-mail sign-in and Explore disappear with the old images. A2 (exact return) restores `.env.pre-deploy4` |

## 4. Test command: send a code to a real mailbox

After step 11 (the release is up), from the host:
```
prod$ $RUN python scripts/send_test_sign_in_code.py --to <a non-admin mailbox you can read> --confirm SEND_TEST_CODE
```
Expect `delivery=STAGED` then `this delivery: state=SENT`. Open the message: subject "Your Plasma sign-in code",
the 6-digit code in the body, and in the headers (Gmail: ⋮ → Show original) **`spf=pass`, `dkim=pass`,
`dmarc=pass`**. Admin and operator addresses never get a code (they sign in with Google): for them use
`--direct` (a sample with a code that does not work). `NOT SENT: SMTP_HOST / SMTP_FROM are not configured`
means section 2 is missing; `state=PENDING error=SMTP_AUTH` means wrong credentials.

## 5. Production checks after the deploy (owner, browser, https://<APP_DOMAIN>)

1. **Sign-in page** shows "Continue with Google" and "Work e-mail → E-mail me a code".
2. **E-mail code, new address** (a personal mailbox, not an admin): code arrives within a minute; signing in
   opens onboarding; after the company form the **Explore** view opens (feed, coverage, guided demo,
   "Start a pilot", "Book a call"). The team receives a **new sign-up alert** (Telegram, else e-mail).
   "Start a pilot" sends a second alert.
3. **Same address with Google** (if it is a Google account) reaches the **same** user (admin → Accounts:
   one row).
4. **Wrong code** five times → "This code has expired or was used up"; a new code works.
5. **Admin → Organizations**: the test organization shows `explore`; "Access" → `pilot` with dates →
   the user's next page load opens the full workspace. Set it back to `disabled` (or archive it) afterwards.
6. **Pilot setup** for a real firm (section 6), then the invited owner signs in with an e-mail code and lands
   in the firm's workspace (no onboarding).
7. **My Tenders** of a user from the step 8b counts: "Earlier bid drafts (N)" lists their drafts.
8. **Import** (Partners & Experts → Import from template): preview a filled template, import, check the library.
9. **Live analysis smoke** (runbook step 13) must pass: locally the Gemini key returned **HTTP 402**
   (billing/credits) on 2026-10-16. If production's key is on the same Google account, fix billing first:
   every analysis fails until then.

## 6. Pilot setup for the two paying firms

One-off container, as the runbook's other one-off commands:
```
prod$ $RUN python scripts/pilot_setup.py --target production --firm "<Firm exact name>" \
        --owner <owner@firm> [--owner <second owner>] --member <user@firm> [--member …] \
        --start <YYYY-MM-DD> [--months 3 | --end <YYYY-MM-DD>] --country Uzbekistan \
        --success-criteria "<what success means for this pilot>" --dry-run
prod$ $RUN python scripts/pilot_setup.py … (same arguments) --confirm PILOT_SETUP --send-invitations
prod$ $RUN python scripts/pilot_setup.py --target production --firm "<Firm exact name>" --list
```
It refuses preview/demo names and any existing organization it did not create. The invitation links are
printed (and e-mailed with `--send-invitations`); each binds at that address's first sign-in, by Google or by
e-mail code. Re-running adds new addresses only; `--resend` renews open invitations. Plan, dates and
success criteria are on `/admin/organizations` and editable there.

**Done-for-you onboarding**: fill `docs/ops/p1/plasma-library-import-template.xlsx` with the firm's
references and experts (see `plasma-library-import-sample.xlsx`), then in the firm's workspace (signed in as
its owner, or an admin added as a member) Partners & Experts → Import from template.
