# B1 report: billing and the instant pilot

Branch `pilot/b1-billing` on `pilot/p3-plans-limits` (worktree `D:\projects\plasmaos-b1`). Local only: nothing
pushed or deployed. One additive migration (`20261025_0001_b1_billing`). Deploy note:
[`docs/ops/DEPLOY_5_B1_BILLING_NOTE.md`](../../ops/DEPLOY_5_B1_BILLING_NOTE.md).

**Polar sandbox (25 Oct):** the token, the three products, the checkout request and the pilot-credit discount were
checked against the real sandbox (§9); a webhook from Polar to this app has not been received yet (the endpoint
URL is a placeholder until Deploy 5). No live key exists anywhere: the app refuses `POLAR_ENV=production` outside a
production environment.

**Terms (25 Oct):** the owner-approved **Plasma Pilot and Subscription Terms, version 1 (effective 26 Oct 2026)**
replace the draft; the behaviour was aligned with them and the remaining differences are listed in §12.

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
     status `awaiting_payment`, **payment due in 7 days**. Reminders on **days 3 and 6**; still unpaid on
     **day 10** the organization returns to
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

## 9. Polar sandbox

Done on 25 Oct with the owner's sandbox token (`scripts/polar_sandbox_check.py`):

- the token reads products; **Pilot** 90000 usd one-time, **Pursuit Desk** 600000 usd **yearly**, **Extra pursuit**
  20000 usd one-time: all three match the catalogue (Agent, Enterprise and Per-tender products also exist in the
  sandbox; the app does not sell them, so they are not configured);
- the webhook secret verifies with the app's Standard Webhooks check;
- a **checkout** with the app's exact request (metadata, external customer id, name, billing country, no discount
  codes) is created (201);
- the **pilot credit**: a fixed one-time $900 discount (`amounts: {"usd": 90000}`, one redemption, Pursuit Desk only)
  is created, and a Pursuit Desk checkout carrying it is created.

Two fixes came out of it: **Polar refuses an Uzbek TIN** as `customer_tax_id` (422 "Invalid tax ID"), which would
have broken card checkout for every resident, so the TIN is no longer sent to Polar (it stays on our records and
invoices; Polar is seller of record for cards); and Polar refuses reserved e-mail domains, so the e-mail is
optional in the client.

Still to do once the webhook points at a reachable URL (Deploy 5): pay a sandbox checkout with
4242 4242 4242 4242 and watch `order.paid` arrive; a refund; a Pursuit Desk with the credit. Not yet observed: the
webhook payload fields (`metadata`, `checkout_id`, `subscription_id`, `total_amount`, `refunded_amount`, `status`)
and whether renewal orders carry the checkout's metadata (both cases are handled).

## 10. Risks and open points

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

## 12. The approved terms (v1, effective 26 Oct 2026) against the code

`docs/legal/PILOT_TERMS_v1.md` and `PILOT_TERMS_v1.pdf` are the owner-approved text (from
`paa/legal/PLASMA_PILOT_TERMS_v1.*`; the backend copies are byte-identical, checked by the test). The checkout's
terms step renders it (headings, lists, its three tables, rules) as text, and `terms_acceptances` stores the SHA-256
of exactly that text (`c5f091d6…`). The **PDF is attached to the activation (welcome) e-mail**.

**Made to match:**

| Terms | Before | Now |
| --- | --- | --- |
| §1 Pilot: 3 months, 6 pursuits, 1 introduction, unlimited users | already | unchanged (P3 catalogue) |
| §4 bank transfer: due within 7 days | due on day 10 | due on day **7**; reminders days 3 and 6 |
| §4 Explore if unpaid 10 days after issue | already | unchanged; invoice, e-mails and app say both dates |
| §5 credit only if the annual plan is ordered within 30 days after the Pilot ends | any time | window enforced, judged on the order date (not the payment date) |
| §6 Pilot refund within 30 days of activation; annual not after 14 days | "30 days of payment" | wording fixed; the admin console shows each order's refund window |
| §7 Pilot ends after 3 months, no renewal; "when a plan ends … Explore" | a Pilot ran on past its end | a bought Pilot moves to Explore on its end date |
| §7 Pursuit Desk renews yearly | card only (Polar subscription) | bank transfer too: a renewal order and invoice on the renewal date, plan extended at once, then §4's 7/10-day rules; once only |
| §7 cancel before the renewal date | — | bank transfer: an admin sets "canceled" (e-mail request) → the plan ends on the renewal date, no invoice |

**Still different, for the owner to decide:**

1. **Cancel "in the app"** (§7): there is no cancel button. Card subscriptions can be canceled in Polar's customer
   portal (linked from Polar's receipts); bank-transfer customers must e-mail and an admin records it. An in-app
   "Cancel renewal" (calling Polar for cards) is a small follow-up.
2. **Per-tender review** (§1, "online in the Plasma app"): the app does not sell it (it is "talk to us"); the Polar
   product exists but is not wired. Also P3 gives Per-tender **no partner search**, while §1 says "every paid plan
   includes … partner and expert search".
3. **VAT** (§4 "prices exclude VAT … where they apply"): invoices show no VAT line and no VAT status. Whether Plasma
   charges VAT, and whether resident invoices must also go out as electronic invoices through the tax system,
   needs the accountant's answer before real bank-transfer invoices.
4. **Refund windows are shown, not enforced** (§6): an admin can still record a refund after 30 / 14 days (the law
   or a service failure may require it). The **onboarding guarantee** (7 business days from receiving documents)
   is not tracked: onboarding tasks have no "documents received" date or deadline.
5. **Services** (§2–§3): onboarding loads, specialist reviews (2 per pilot, 1 per quarter) and success criteria are
   delivered by the team; the app does not count reviews (success criteria exist only as P1's admin field).
6. **Plans set by an admin** (P1/P3 pilots, invoiced by hand) are not ended automatically at their end date; only
   plans bought through B1 are. Existing pilots need the owner's decision.
7. **§13 new versions**: renewals keep the accepted version; there is no flow yet to ask for acceptance of a v2 at
   renewal.
8. **Effective date**: the app shows and records v1 as soon as it is deployed; if Deploy 5 happens before
   26 Oct 2026, acceptances will predate the stated effective date.
9. **Seller address**: the terms name "Plasma AI Solutions, Tashkent" (HQ Tashkent, regional office Karshi); invoices
   carry the registered legal entity, PLASMA AI SOLUTIONS MChJ, 21 Mustaqillik Street, Qarshi. Consistent with §15,
   but worth a glance.

Tests for these: `test_b1_billing.py` checks the terms copy and PDF (clauses for 7 days, 10 days, the credit window,
the refund window, renewal, the pilot's 6 pursuits and 1 introduction), the 7-day due date, the PDF on the welcome
e-mail, the credit window (day 30 after the pilot yes, day 31 no), the pilot ending (not the day before, Explore on
the day), a Pursuit Desk by bank transfer with the credit, its renewal (once, invoice due in 7 days, plan extended)
and, after an admin "canceled", its end. All 7 B1 tests pass; P3, P2, R3-04 and the drift tests pass (except the
known Windows CRLF-hash test); frontend 419/419, `tsc`, ESLint and the token audit clean. Screens 01–08 were
re-captured with the approved terms (03: the terms step with its tables; 06: the invoice with the 7-day due date,
the day-10 rule and the credit window), and `emails-sample.md` shows the welcome e-mail with the terms PDF attached.
