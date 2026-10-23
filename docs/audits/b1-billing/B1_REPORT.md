# B1 report: billing and the instant pilot

Branch `pilot/b1-billing` on `pilot/p3-plans-limits` (worktree `D:\projects\plasmaos-b1`). Local only: nothing
pushed or deployed. One additive migration (`20261025_0001_b1_billing`). Deploy note:
[`docs/ops/DEPLOY_5_B1_BILLING_NOTE.md`](../../ops/DEPLOY_5_B1_BILLING_NOTE.md).

**Not yet tested against the Polar sandbox.** No Polar sandbox credentials exist on this machine, and creating a
Polar account was not mine to do. Everything Polar-facing is built to Polar's API and Standard Webhooks
documentation and tested with a fake Polar in the tests and a local stand-in for the demo; the sandbox run is one
command once the owner has the sandbox keys (§9). No live key exists anywhere: the app refuses
`POLAR_ENV=production` outside a production environment.

## 1. The flow

A firm on Explore clicks **Start a pilot** (Explore page, the plan notice, or `/billing/start?plan=pilot`):

1. **Company details**: legal name, TIN (9 digits, required for residents), country, legal address, billing
   e-mail, "registered in Uzbekistan" (→ UZS invoice).
2. **Pilot Terms**: `docs/legal/PILOT_TERMS_v1.md` rendered in the app (as text, never HTML) with an accept box.
   The acceptance stores the version, the SHA-256 of the exact text shown, the user, the time and the IP; a
   changed text refuses the old hash (409 `terms_changed`).
3. **Payment**:
   - **Card (Polar)**: the app creates a Polar checkout (product per plan, metadata `organization_id`,
     `order_id`, `product`; the buyer's e-mail, name, country and TIN; discount codes off) and sends the browser
     there. The **`order.paid` webhook** activates the plan; the success page waits for it.
   - **Bank transfer**: the app issues invoice **PL-YYYY-NNN** (gapless per year), in **UZS at the CBU rate of
     the day** for residents (USD otherwise), e-mails it as a PDF, and **activates the plan at once** with billing
     status `awaiting_payment`. Reminders on **days 3 and 6**; on **day 10** unpaid the organization returns to
     **Explore** with an in-app notice (and an e-mail); an admin **marks it paid** with the bank reference (a
     suspended plan comes back with its original dates).

Activation (both methods): Pilot from today to **+3 months** with P3's quotas (6 pursuits, 1 introduction);
Pursuit Desk **+12 months**; a **welcome e-mail** with the kickoff booking link, a **team alert**
(Telegram/e-mail, existing P1 delivery), an **onboarding task** in the admin queue. Card refunds
(`order.refunded`, full) return the organization to Explore; `subscription.canceled` keeps the plan to the period
end, `subscription.revoked` ends it, renewals (`order.paid` on the subscription) extend it by a year.

## 2. One catalogue

`backend/app/core/plans.py` holds the plans (limits, features: P3) **and** now the prices and the checkout
products (B1): Pilot $900 one-time ($300 × 3), Pursuit Desk $6,000 a year, Agent $18,000 and Enterprise from
$36,000 ("talk to us"), per-tender $400 (team-invoiced), extra pursuit $200 (+1 pursuit), the $900 pilot credit,
the 30-day guarantee, day 75, days 3/6/10. The P3 gates read it; the billing service, the invoice, the e-mails and
the app's billing pages (`GET /billing/catalog`, `/billing/quote`, the plan status' `extra_pursuit_cents`) read it
too: no price is written in the frontend.

## 3. Data (all audited)

| Table | What |
| --- | --- |
| `billing_customers` | organization (unique), legal name, TIN, country, address, billing e-mail, resident |
| `terms_acceptances` | organization, user, terms version, text SHA-256, IP, user agent, time |
| `billing_orders` | product, plan, method, status (`pending`, `awaiting_payment`, `paid`, `lapsed`, `refunded`, `canceled`), list price, credit, amount, the terms acceptance, Polar checkout/discount/subscription ids, plan dates, renewals |
| `billing_invoice_counters`, `billing_invoices` | PL-YYYY-NNN (counter row locked in the issuing transaction), the buyer as invoiced (a copy), UZS/USD, CBU rate and date, total, due date, status, reminders sent |
| `billing_payments` | card (Polar order id, unique) or bank transfer (reference required), amounts, refunds |
| `billing_events` | the webhook inbox: provider event id **unique**, `signature_verified` (always true: a forged delivery is refused and never stored, so it cannot claim an event id), the raw payload, outcome, error, attempts, `processed_at` |
| `billing_pilot_credits` | the pilot credit used, **unique per organization** |
| `billing_fx_rates` | CBU rates by date (cache) |
| `billing_onboarding_tasks` | one per activated plan order |
| `organizations.billing_status` | `paid`, `awaiting_payment`, `suspended`, `refunded`, `canceled`, or NULL (not bought in the app) |

Eleven new audit actions (`BILLING_CUSTOMER_UPDATED`, `…_TERMS_ACCEPTED`, `…_ORDER_CREATED`, `…_INVOICE_ISSUED`,
`…_PAYMENT_RECORDED`, `…_PLAN_ACTIVATED`, `…_REFUND_RECORDED`, `…_PLAN_SUSPENDED`, `…_STATUS_CHANGED`,
`…_CREDIT_APPLIED`, `…_ONBOARDING_COMPLETED`), plus P1's `ORGANIZATION_ACCESS_CHANGED` and P3's
`ORGANIZATION_PLAN_GRANTED` for every plan change and extra pursuit (actor SYSTEM `billing:polar-webhook`,
`billing:checkout`, `billing:schedule`, or the admin).

## 4. Webhooks: signature and idempotency

- Standard Webhooks: `webhook-id`, `webhook-timestamp` (±5 min), `webhook-signature` (`v1,<HMAC-SHA256>` over
  `id.timestamp.body`). Both Polar key forms are accepted (the base64 part of `whsec_…`, and older secrets keyed
  by the whole string, as Polar's SDKs do). Body ≤ 256 KB. Anything else: **403, nothing stored**.
- **Once per event**: the event row is inserted (`ON CONFLICT DO NOTHING`) and locked in the processing
  transaction; a repeat after success answers `duplicate`. A processing error rolls back, stores the delivery
  unprocessed with the error code and answers 500, so Polar retries and the retry processes it.
- **Once per payment**: a Polar order id is unique on `billing_payments`; the same order under a new event id
  answers `duplicate_payment`. An order activates once (`activated_at`).

## 5. Pilot → annual, extra pursuit, isolation

- **Day 75** of a pilot: the dashboard (and every plan notice) offers Pursuit Desk with the $900 credit when the
  pilot was paid. Pursuit Desk checkout applies a **one-time $900** off: on card, a Polar discount created for that
  checkout (fixed, once, one redemption, that product only); on bank transfer, a credit line on the invoice. The
  credit is recorded once per organization; a refund of the annual order gives it back. Agent and Enterprise:
  "Talk to us" (a request to the team).
- **Extra pursuit** ($200, Pilot and paid plans): paid → +1 pursuit in the current period (a P3 grant with a
  SYSTEM actor). At P3's 100% notice the primary action is now **Add a pursuit ($200)**; Explore's is **Start a
  pilot** (checkout).
- **Organizations**: every customer route resolves the organization from the membership (Explore included, for
  the purchase); orders, invoices, PDFs and the checkout lookup are filtered by it (404 otherwise). Buying and
  changing billing details: owners only.

## 6. Admin billing console (`/admin/billing`)

Onboarding queue (mark done), customers (plan, billing status, last order, open invoices), and per organization:
invoices (PDF, **mark paid** with a reference), orders (**record refund** with a note, optionally back to
Explore), payments, terms acceptances (version, hash, user, IP), Polar webhook events, the audit trail, and a
**manual override** of plan and billing status with a reason. Operators read and close onboarding tasks; mark
paid, refunds and overrides need an admin.

## 7. Tests

`backend/test_b1_billing.py` (7, all pass):

- catalogue: prices, products, credit, month arithmetic (24 Oct + 3 → 24 Jan; 30 Nov + 3 → 28 Feb);
- **webhook signature**: both key forms, several signatures in one header, tampered body, other id, other
  secret, stale timestamp, missing headers, no secret configured;
- settings: `POLAR_ENV=production` refused outside production; unknown `POLAR_ENV` refused;
- terms: the backend copy equals `docs/legal`, hashed with LF line ends;
- invoice PDF renders (UZS and USD; Cyrillic buyer);
- migration: additive, reversible, `alembic check` clean;
- one Postgres scenario through the real endpoints:
  - **terms stored**: refused without acceptance and with another hash (nothing stored); stored with version,
    hash, user, IP; linked to the order;
  - **card activation**: Explore → Pilot (dates, quotas, access state, overrides cleared), welcome e-mail with
    the kickoff link, one team alert, one onboarding task, the audit events;
  - **forged delivery** 403 and nothing stored; **processing failure** kept unprocessed, the retry processes it;
    **same delivery again** → `duplicate`; **same Polar order, new event id** → `duplicate_payment`; one payment;
  - **credit applied once**: Pursuit Desk quote 600,000 − 90,000; the Polar discount (amount, product); the
    redemption; a later quote has no credit; `subscription.canceled`/`uncanceled`; a **renewal** extends the year;
    **full refund** → Explore, billing status refunded, credit returned; a repeated refund → `duplicate_refund`;
  - **bank transfer grace and suspension**: resident → UZS invoice PL-YYYY-001 at the (stubbed) CBU rate, PDF
    attached to the e-mail, active at once with `awaiting_payment`; reminders on days 3 and 6 once each, nothing
    on days 2, 4, 9; **day 10 → Explore, `suspended`**, invoice overdue, order lapsed, suspension e-mail, the
    in-app summary; admin **mark paid** (blank reference refused, twice refused) brings the pilot back with its
    dates; an **extra pursuit** by bank transfer → invoice 002, limit 7;
  - **day-75 offer** with the credit (and none on day 74);
  - **organization isolation**: another organization's order, invoice PDF, overview and checkout lookup are 404;
  - admin console: customers, detail (terms, events, audit), onboarding done, manual override (audited).

Frontend: `tests/b1-billing.test.mjs` (5: products, error codes, the terms renderer, string parity in four
locales, wiring) and the P3 test updated for the new notice actions. **Whole static suite: 419 of 419** on the final
code; `tsc` clean; ESLint clean on every changed file; design-token and RTL audits clean;
`next build` passes.

Backend runs: B1 + P3 + P2 + P1-01/02 + R3-04/05 + drift + release config: 71 passed, 4 failed, all four in the
base Windows set (R3-04's fake SMTP and the historical-migration CRLF hash fail identically on the P3 commit;
the constraints test is the local `1.18.4` vs `1.19.2` package; P1-01 is the known flaky one and passed on
re-run). **Full suite** (Windows host, everything): 1,188 passed,
37 failed, 10 errors. 34 failures and the 10 errors are exactly P3's Windows-environment set; the other three were
checked one by one: R3-04 (fake SMTP) and P1-01 fail identically on the P3 commit with this worktree's `.env`;
P1-02 failed because the Docker VM's clock ran about a second ahead of the host (alerts stamped by Postgres were
not yet due) and passes on re-run. No B1-caused failure.

## 8. Screenshots (`screens/`, local copy of the Loom preview database with P1–P3, through the real app)

| File | Shows |
| --- | --- |
| `01-explore-start-pilot.png` | Explore: "Start a pilot" now opens the checkout |
| `02-checkout-company-details.png` | step 1: company details (resident, TIN, address, billing e-mail) |
| `03-checkout-pilot-terms.png` | step 2: the Pilot Terms in the app, accept box |
| `04-checkout-payment-method.png` | step 3: card or bank transfer, order summary |
| `05-bank-transfer-invoice-issued.png` | invoice issued, plan active now, PDF download |
| `06-invoice-pdf-page1.png` | the invoice PDF: PL-2026-001, UZS 10,655,028.00 at the **real** CBU rate of 24.10.2026 (11,838.92), bank details (demo values), "credited to the first annual invoice" |
| `07-dashboard-awaiting-payment.png` | the workspace open, with "Invoice PL-2026-001 is waiting for payment" |
| `08-billing-page.png` | plan and billing: plan, status, Pursuit Desk / extra pursuit / talk to us, details, invoices, orders |
| `09-checkout-card-sandbox.png` | card selected, "Test mode (Polar sandbox)" |
| `10-card-payment-confirmed.png` | after the (stand-in) payment and the signed webhook: "Pilot is active" |
| `11-day-75-annual-offer.png` | day 75: "Continue after the pilot with Pursuit Desk", $900 credited |
| `12-pursuit-desk-checkout-pilot-credit.png` | Pursuit Desk checkout: $6,000 − $900 = $5,100 |
| `13-day-10-unpaid-back-to-explore.png` | day 10 unpaid: back on Explore, "Your plan is paused" |
| `14-admin-billing-console.png` | admin: onboarding queue and customers |
| `15-admin-customer-detail.png` | admin: invoices (overdue), orders (lapsed), terms (version, hash, user, IP), audit |
| `16-admin-mark-paid.png`, `17-admin-after-mark-paid.png` | mark paid with the bank reference; the pilot back, paid |
| `18-near-limit-add-a-pursuit.png` | P3's 100% notice with "Add a pursuit ($200)" |

`emails-sample.md`: the six billing e-mails the demo staged (welcome ×2, invoice with its PDF, reminders day 3
and day 6, suspension), rendered exactly as the outbox sends them.

**How the card screens were made.** Without sandbox keys, the demo backend pointed its Polar API base at a local
stand-in (a scratch script, not in the repo) that answers the two API calls and, on "Pay", sends an `order.paid`
webhook **signed with the Standard Webhooks scheme** to the real webhook endpoint, then redirects to the success
URL like Polar. The Polar-hosted checkout page itself is therefore not shown. Demo organizations: two Explore
self sign-ups from P3 ("Bukhara Water Advisory LLC (local demo)": bank transfer; "Samarkand Survey LLC (local
demo)": card); the day-75 and day-10 states were produced by moving the pilot start back and running the schedule
for "today + 3, + 6, + 10" against the demo database.

## 9. Polar sandbox: what remains

1. Owner: a Polar **sandbox** organization, three products (Pilot $900 one-time, Pursuit Desk $6,000 yearly,
   Extra pursuit $200 one-time), an access token (`checkouts:write`, `discounts:write`, `products:read`), a webhook
   to `https://<API_DOMAIN>/api/v1/billing/webhooks/polar` with the seven events (deploy note).
2. `python scripts/polar_sandbox_check.py --webhook-selftest` (products match the catalogue; the secret
   verifies), then `--checkout` to pay one sandbox checkout with 4242 4242 4242 4242 and see `order.paid`
   arrive (stored as `unmatched_order`, touching no customer).
3. Then the Deploy 5 checks: a real sandbox pilot purchase end to end, a refund, a Pursuit Desk with the credit.

Assumptions to confirm in that run (from Polar's documentation, not yet observed): the order payload carries
`metadata`, `checkout_id`, `subscription_id`, `total_amount`, `refunded_amount`, `status`; subscription renewal
orders carry the checkout's metadata or the subscription id (both are handled); discounts take
`amounts: {"usd": cents}`; the product read returns `prices[].price_amount` and `recurring_interval`.

## 10. Risks and open points

- **Pilot Terms are a draft.** The pilot agreement template you mentioned lives in a Claude Docs page I could not
  read from here; `PILOT_TERMS_v1.md` is written from the 23 Oct decisions (prices, credit, 30-day refund, 10-day
  bank transfer rule, data, liability capped at the fees, Uzbek law). Replace it before Deploy 5.
- **Bank transfer gives ten days of a full pilot before money arrives** (by design: "use it immediately").
- **IP in the terms acceptance** is the request's client address. Locally it is 127.0.0.1; behind Caddy and the
  Next.js rewrite it may be the frontend container's address unless the forwarded header reaches the backend.
  Checked as step 3 of the deploy note.
- **Credit race**: two Pursuit Desk checkouts opened at once both carry a Polar discount; the second payment
  raises a `credit_already_used` team alert (settled by hand). Pilots paid before B1 (by hand) are not offered the
  credit in the app.
- **Business date is Tashkent** (invoice dates, CBU rate, plan dates, the day count). P3's counting periods stay
  on UTC, so a plan bought between 00:00 and 05:00 Tashkent starts "tomorrow" by P3's clock for those hours.
- **Partial refunds** are recorded and alerted, never downgrade; extra pursuits are never taken back (refund or
  lapse alerts the team).
- **CBU outage**: a resident's bank transfer answers "try again shortly" (card still works); the rate is cached
  per date.
- **Owners only** can buy; members see the billing page and download invoices.
- **`/billing/start` signed out** goes to the sign-in page and does not return to the checkout afterwards.
- The webhook endpoint is public by design (signature-authenticated); it stores nothing that is not signed.

## 11. Not done / notes

- Not run: the Polar sandbox (§9), the WSL/Linux gate, a browser run in Russian, Uzbek or Arabic (strings exist
  and pass parity), a real e-mail send (the outbox rows were rendered, not sent).
- Local leftovers: database `plasma_s05b4b_b1_demo` (disposable copy), a throwaway Redis container
  `b1-demo-redis` (stopped at the end), the worktree's `node_modules` copy.
