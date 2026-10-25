/**
 * B1: billing as the app reads it (GET /billing, /billing/quote, /billing/terms, /organizations/plan.billing).
 * Import-free for the node test runner.
 */

export type ProductCode = 'pilot' | 'pursuit_desk' | 'extra_pursuit' | 'per_tender';
export type PaymentMethod = 'card' | 'bank_transfer';
export type BillingStatus = 'paid' | 'awaiting_payment' | 'suspended' | 'refunded' | 'canceled';

export const PRODUCT_CODES: ProductCode[] = ['pilot', 'pursuit_desk', 'extra_pursuit', 'per_tender'];
/** Sold only through a one-use link from the team (an offer). */
export const OFFER_PRODUCTS: ProductCode[] = ['per_tender'];

export type BillingCustomer = {
  legal_name: string;
  tin: string | null;
  country: string;
  address: string;
  billing_email: string;
  resident: boolean;
  updated_at?: string | null;
};

export type BillingQuote = {
  product: ProductCode;
  plan: string | null;
  list_amount_cents: number;
  credit_cents: number;
  amount_cents: number;
  billing: string;
  term_months: number | null;
  blocker: string | null;
  methods: { card: boolean; bank_transfer: boolean };
  invoice_currency: 'UZS' | 'USD';
};

export type BillingTerms = { version: string; sha256: string; markdown: string };

export type BillingOrder = {
  id: string;
  product: ProductCode;
  plan: string | null;
  method: PaymentMethod;
  status: 'pending' | 'awaiting_payment' | 'paid' | 'lapsed' | 'refunded' | 'canceled';
  list_amount_cents: number;
  credit_cents: number;
  amount_cents: number;
  created_at: string;
  paid_at: string | null;
  activated_at: string | null;
  refunded_at: string | null;
  refund_note: string | null;
  plan_started_on: string | null;
  plan_ends_on: string | null;
  renewal: boolean;
  /** Terms §6: Pilot refundable on request within 30 days of activation; annual fees not after 14 days. */
  refund_window_ends_on?: string | null;
  attribution?: Record<string, string> | null;
  cancel_requested_at?: string | null;
  cancel_confirmed_at?: string | null;
};

export type BillingInvoice = {
  id: string;
  number: string;
  order_id: string;
  currency: 'UZS' | 'USD';
  list_amount_cents: number;
  credit_cents: number;
  total_usd_cents: number;
  total_uzs: string | null;
  fx_rate: string | null;
  fx_rate_date: string | null;
  issued_on: string;
  due_on: string;
  status: 'issued' | 'paid' | 'overdue' | 'void';
  paid_at: string | null;
  reminders_sent: number;
};

export type BillingPayment = {
  id: string;
  order_id: string;
  invoice_id: string | null;
  method: PaymentMethod;
  provider_payment_id: string | null;
  reference: string | null;
  amount_cents: number;
  currency: string;
  status: string;
  refunded_amount_cents: number;
  paid_at: string;
  note: string | null;
};

export type BillingSummary = {
  status: BillingStatus | null;
  /** Pursuit Desk: how it renews (card: Polar's subscription; bank transfer: an invoice), and a cancellation. */
  renewal?: {
    method: PaymentMethod; order_id: string; renews_on: string | null; canceled: boolean; cancel_requested_at: string | null;
  } | null;
  /** Polar knows the organization (a card payment): the customer portal can be opened. */
  card_customer?: boolean;
  open_invoice: {
    id: string; number: string; due_on: string; days_left: number; currency: string;
    total_usd_cents: number; total_uzs: string | null; status: string;
  } | null;
  annual_offer: {
    product: 'pursuit_desk'; list_amount_cents: number; credit_cents: number; pilot_ends_on: string | null; day: number;
  } | null;
  extra_pursuit_cents?: number | null;
};

export type BillingOverview = {
  organization_id: string;
  plan: string;
  plan_started_on: string | null;
  plan_ends_on: string | null;
  summary: BillingSummary;
  customer: BillingCustomer | null;
  orders: BillingOrder[];
  invoices: BillingInvoice[];
  payments: BillingPayment[];
  pilot_credit_available: boolean;
};

/** /billing/start?plan=… accepts the products sold in the app; per-tender only with the team's offer link. */
export function productFrom(value: string | null | undefined, offer?: string | null): ProductCode | null {
  const product = PRODUCT_CODES.includes(value as ProductCode) ? (value as ProductCode) : null;
  return product && OFFER_PRODUCTS.includes(product) && !offer ? null : product;
}

/** ref and utm_* carried from /billing/start to the order (marketing attribution). */
export const ATTRIBUTION_KEYS = ['ref', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'] as const;
export const ATTRIBUTION_COOKIE = 'plasma_billing_attribution';

export function attributionFrom(params: URLSearchParams): Record<string, string> | null {
  const values: Record<string, string> = {};
  for (const key of ATTRIBUTION_KEYS) {
    const value = params.get(key)?.trim();
    if (value) values[key] = value.slice(0, 200);
  }
  return Object.keys(values).length ? values : null;
}

/** The attribution from the URL, else from the cookie /billing/start set (it survives the sign-in). */
export function resolveAttribution(params: URLSearchParams, cookieHeader: string): Record<string, string> | null {
  const fromUrl = attributionFrom(params);
  if (fromUrl) return fromUrl;
  const raw = cookieHeader.split(';').map((part) => part.trim()).find((part) => part.startsWith(`${ATTRIBUTION_COOKIE}=`));
  if (!raw) return null;
  try {
    return attributionFrom(new URLSearchParams(decodeURIComponent(raw.slice(ATTRIBUTION_COOKIE.length + 1))));
  } catch {
    return null;
  }
}

/** The checkout errors the app explains (dashboard.billing.start.errors.*); anything else is "generic". */
export const BILLING_ERROR_CODES = [
  'customer_invalid', 'customer_required', 'terms_not_accepted', 'terms_changed', 'method_unavailable', 'card_unavailable',
  'fx_unavailable', 'owner_required', 'pilot_used', 'already_paid_plan', 'already_on_plan', 'already_higher_plan',
  'awaiting_payment', 'plan_required', 'organization_disabled', 'unknown_product', 'offer_required', 'per_tender_on_plan',
  'not_cancellable', 'cancel_requested', 'not_card_customer', 'portal_unavailable',
] as const;
export type BillingErrorKey = (typeof BILLING_ERROR_CODES)[number] | 'generic';

export function billingErrorKey(code: string | null | undefined): BillingErrorKey {
  return (BILLING_ERROR_CODES as readonly string[]).includes(code ?? '') ? (code as BillingErrorKey) : 'generic';
}

/** A billing error from the API ({code, message}): its code, else null. */
export function billingErrorCode(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === 'string' ? code : null;
  }
  return null;
}

export type MarkdownInline = { text: string; strong?: boolean; em?: boolean };
export type MarkdownBlock =
  | { kind: 'h1' | 'h2' | 'h3' | 'p'; inline: MarkdownInline[] }
  | { kind: 'ul'; items: MarkdownInline[][] }
  | { kind: 'table'; header: MarkdownInline[][]; rows: MarkdownInline[][][] }
  | { kind: 'hr' };

/** **bold** and *italic* only; everything else is text (rendered as React text, never as HTML). */
export function parseInline(text: string): MarkdownInline[] {
  const parts: MarkdownInline[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    parts.push(match[1] !== undefined ? { text: match[1], strong: true } : { text: match[2], em: true });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

const cells = (line: string) => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => parseInline(cell.trim()));
const isTableRule = (line: string) => /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/.test(line);

/** The Markdown the terms use: #/##/### headings, paragraphs, "- " lists, pipe tables, "---" rules. */
export function parseMarkdown(markdown: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  let table: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'p', inline: parseInline(paragraph.join(' ')) });
    if (list.length) blocks.push({ kind: 'ul', items: list.map(parseInline) });
    if (table.length) {
      const [head, ...rest] = table;
      const body = rest[0] !== undefined && isTableRule(rest[0]) ? rest.slice(1) : rest;
      blocks.push({ kind: 'table', header: cells(head), rows: body.map(cells) });
    }
    paragraph = [];
    list = [];
    table = [];
  };
  for (const raw of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trim();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (!line) { flush(); continue; }
    if (line.startsWith('|')) {
      if (!table.length) flush();
      table.push(line);
      continue;
    }
    if (table.length) flush();
    if (/^(-{3,}|\*{3,})$/.test(line)) {
      flush();
      blocks.push({ kind: 'hr' });
      continue;
    }
    if (heading) {
      flush();
      blocks.push({ kind: (`h${heading[1].length}`) as 'h1' | 'h2' | 'h3', inline: parseInline(heading[2]) });
      continue;
    }
    if (line.startsWith('- ')) {
      if (paragraph.length) { blocks.push({ kind: 'p', inline: parseInline(paragraph.join(' ')) }); paragraph = []; }
      list.push(line.slice(2));
      continue;
    }
    if (list.length) { blocks.push({ kind: 'ul', items: list.map(parseInline) }); list = []; }
    paragraph.push(line);
  }
  flush();
  return blocks;
}
