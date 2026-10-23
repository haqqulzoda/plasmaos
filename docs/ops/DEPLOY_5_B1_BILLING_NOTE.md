# Deploy 5 note: B1 billing and the instant pilot

To be merged into the Deploy 5 runbook (as the P1 note was merged into Deploy 4). Branch `pilot/b1-billing`
(on `pilot/p3-plans-limits` → `pilot/p2-partner-finder` → `pilot/p1-pilot-readiness`). Local only until the owner
pushes it. **Sandbox only: no live Polar keys anywhere in this deploy.** Card payments switch to production in a
later, separate step (end of this note).

## What changes

| | |
| --- | --- |
| Migrations | Deploy 4 ends at `20261016_0002_p1_organization_access`. Deploy 5 runs, in order: `20261023_0001_p2_partner_finder` → `20261024_0001_p3_plans_limits` → **`20261025_0001_b1_billing`**. All additive. B1 alone: ten new tables, one column, three widened check constraints, no data change |
| New tables (B1) | `billing_customers`, `terms_acceptances`, `billing_orders`, `billing_invoice_counters`, `billing_invoices`, `billing_payments`, `billing_events` (webhook inbox), `billing_pilot_credits`, `billing_fx_rates`, `billing_onboarding_tasks`; column `organizations.billing_status` |
| Widened constraints | `admin_alerts.kind` + `BILLING`; `email_deliveries.kind` + `BILLING_INVOICE`, `BILLING_REMINDER`, `BILLING_WELCOME`, `BILLING_SUSPENDED`; `email_deliveries.category` + `BILLING` |
| New Beat task | `run-billing-schedule`, hourly at :15 (bank transfer reminders on days 3 and 6, Explore on day 10). Idempotent |
| New routes | app: `/billing/start?plan=pilot\|pursuit_desk\|extra_pursuit` (→ `/dashboard/billing/start`), `/dashboard/billing`, `/dashboard/billing/success`, `/admin/billing`. API: `/api/v1/billing/*`, `/api/v1/admin/billing/*`, **`POST /api/v1/billing/webhooks/polar`** (no session; the Standard Webhooks signature is the authentication) |
| Outbound calls | `sandbox-api.polar.sh` (checkout and discount creation), `cbu.uz` (the USD rate of the day, cached per day, only for invoices to Uzbek residents) |

## Before the window

1. **Pilot Terms.** `docs/legal/PILOT_TERMS_v1.md` (and its copy `backend/app/legal/PILOT_TERMS_v1.md`, kept identical
   by `test_b1_billing.py`) is a **draft written from the 23 Oct decisions**: replace it with the text of the pilot
   agreement template before Deploy 5. Every acceptance stores the SHA-256 of the exact text shown, so changing the
   text later is safe (old acceptances keep their hash); a materially new text should get a new version
   (`PILOT_TERMS_v2.md` and `TERMS_VERSION` in `app/services/billing.py`).
2. **Polar sandbox** (https://sandbox.polar.sh, a separate account from production):
   - create three products, USD: **Pilot** one-time **$900**; **Pursuit Desk** recurring **yearly $6,000**;
     **Extra pursuit** one-time **$200**. Copy the three product ids;
   - create an **organization access token** with scopes `checkouts:write`, `discounts:write`, `products:read`;
   - add a **webhook endpoint** `https://<API_DOMAIN>/api/v1/billing/webhooks/polar`, format **Raw**, events
     `order.paid`, `order.refunded`, `subscription.active`, `subscription.canceled`, `subscription.uncanceled`,
     `subscription.revoked`, `subscription.updated`; copy its secret (`whsec_…`).
3. **Bank details** for the invoice: the UZS account (bank, account, MFO, beneficiary) and the USD account
   (bank, SWIFT, account, intermediary bank if any). One line each, lines separated by ` | `.
4. **Resend**: already the SMTP provider since Deploy 4 (`SMTP_HOST=smtp.resend.com`). Invoices go out from
   `SMTP_FROM` with the PDF attached; nothing new to configure. Billing e-mails are transactional (no
   preference switch).

## `.env` additions (production host)

```
POLAR_ENV=sandbox
POLAR_ACCESS_TOKEN=<sandbox organization access token>
POLAR_WEBHOOK_SECRET=<sandbox webhook secret, whsec_…>
POLAR_PRODUCT_IDS={"pilot":"<id>","pursuit_desk":"<id>","extra_pursuit":"<id>"}
INVOICE_SELLER_NAME=Plasma AI Solutions
INVOICE_SELLER_ADDRESS=<legal address>, Tashkent, Uzbekistan
INVOICE_SELLER_TIN=<STIR>
INVOICE_SELLER_EMAIL=hq@plasmaos.uz
INVOICE_SELLER_PHONE=+998 94 877 87 83
INVOICE_BANK_DETAILS_UZS=Bank: <…> | Account: <…> | MFO: <…> | Beneficiary: Plasma AI Solutions
INVOICE_BANK_DETAILS_USD=Bank: <…> | SWIFT: <…> | Account: <…> | Beneficiary: Plasma AI Solutions
BILLING_KICKOFF_URL=https://cal.com/plasmahq/30min
```

`PUBLIC_APP_URL` (Deploy 4) is required for card checkout (Polar's success URL). Without the Polar values the
app offers bank transfer only; without bank details for the buyer's currency it offers card only.
**`POLAR_ENV=production` is refused at start-up unless `ENVIRONMENT` is production or release**, and Deploy 5 keeps
`sandbox`. Check before the window (laptop, backend directory, a `.env` with the sandbox values):

```
python scripts/polar_sandbox_check.py --webhook-selftest     # three products OK, problems: 0
```

## After the migrations (add to the runbook's checks)

1. `alembic current` = `20261025_0001_b1_billing (head)`; `SELECT count(*) FROM billing_orders` = 0.
2. **Card, sandbox**: as a fresh self sign-up (Explore), open `https://<APP_DOMAIN>/billing/start?plan=pilot`, enter
   company details, accept the terms, pay with **4242 4242 4242 4242** (any future date, any CVC). Must see:
   the success page turns to "Pilot is active" within seconds; the organization is Pilot with dates today → +3
   months and 6 pursuits; `/admin/billing` shows the order paid, a `billing_events` row `order.paid` →
   `activated`, an open onboarding task; the team alert (Telegram or e-mail) "bought Pilot (card)"; the welcome
   e-mail with the kickoff link. **STOP** if the webhook shows 403 (`webhook_signature_invalid`: the secret) or no
   row at all (the endpoint URL / Caddy route).
3. **Terms**: in that organization's detail on `/admin/billing`, the acceptance shows `PILOT_TERMS_v1`, the hash,
   the user and an IP. **Check the IP is the browser's public address, not a Docker address (172.x)**; if it is
   172.x, the Next.js rewrite does not forward `X-Forwarded-For` and the IP must come from the forwarded header.
4. **Bank transfer**: a second test organization, resident, buys a pilot by bank transfer. Must see: invoice
   `PL-2026-001` (or the next number), UZS at today's CBU rate, the e-mail with the PDF, the plan active with
   "awaiting payment" on the dashboard. Mark it paid on `/admin/billing` with a test reference.
5. **Refund** the sandbox card order in the Polar dashboard: the organization returns to Explore
   (`order.refunded` → `refunded`).
6. Delete or disable the two test organizations (or keep them as internal) and record their ids in the log.

## Rollback

The schema stays (additive); the Deploy 4 images run on it unchanged (the old build never reads the new tables).
If billing misbehaves after the window, set `POLAR_ACCESS_TOKEN=` and `INVOICE_BANK_DETAILS_*=` (empty): the
checkout then offers no payment method, and plans are set by admins as in P3. Webhooks already received stay in
`billing_events`; deliveries that failed are retried by Polar for a while (check its webhook log).

## Later: switching card payments to production (not in Deploy 5)

A separate, owner-approved step after the sandbox has worked end to end: create the same three products and a
webhook in the **production** Polar organization, set `POLAR_ENV=production` with the production token, secret and
product ids, restart `backend`, `celery_beat`, `celery_worker`. One real $900 pilot payment and its refund prove it.

## Risks to watch

- **Unpaid bank transfers get ten days of a full pilot.** By design ("use it immediately"); the day-10 job returns
  them to Explore and the team sees each suspension.
- **Pilot credit**: applied once per organization (`billing_pilot_credits` is unique per organization). Two
  Pursuit Desk checkouts opened at the same time could both carry the Polar discount; the second payment raises a
  `credit_already_used` team alert to settle by hand.
- **Pilots paid before B1** (invoiced by hand) have no paid pilot order, so the app does not offer them the $900
  credit: record it by hand on their first annual invoice.
- **CBU rate**: fetched once per invoice date; if cbu.uz is down, a resident's bank transfer checkout answers "try
  again shortly" (card still works).
