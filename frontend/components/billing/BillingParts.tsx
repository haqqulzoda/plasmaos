'use client';

import Link from 'next/link';
import { AlertTriangle, CalendarClock, CreditCard, Sparkles } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';

import { formatCurrency, formatDate } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { parseMarkdown, type BillingSummary, type MarkdownInline } from '@/lib/billing';

export function useMoney() {
  const locale = useLocale() as CustomerSelectableLocale;
  return {
    locale,
    usd: (cents: number) => formatCurrency(cents / 100, 'USD', locale,
      cents % 100 === 0 ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    uzs: (value: string | null | undefined) => formatCurrency(Number(value ?? 0), 'UZS', locale, { maximumFractionDigits: 0 }),
    // Billing runs on the Tashkent business date (invoices, the CBU rate, plan terms).
    date: (value: string | null | undefined) => (value ? formatDate(value, locale, { timeZone: 'Asia/Tashkent' }) : '—'),
  };
}

export const checkoutHref = (product: string) => `/dashboard/billing/start?plan=${encodeURIComponent(product)}`;

/** B1: the billing notices next to the plan: an invoice awaiting payment, a paused plan, a refund or
 *  cancellation, and the Pursuit Desk offer from the pilot's 75th day. */
export function BillingNotice({ summary }: { summary: BillingSummary | null | undefined }) {
  const t = useTranslations('dashboard.billing.notice');
  const money = useMoney();
  if (!summary) return null;
  const invoice = summary.open_invoice;
  const amount = invoice
    ? (invoice.currency === 'UZS' && invoice.total_uzs ? money.uzs(invoice.total_uzs) : money.usd(invoice.total_usd_cents))
    : '';
  const notices = [];
  if (summary.status === 'suspended' && invoice) {
    notices.push(<div key="suspended" className="plan-notice plan-notice-reached" role="alert" data-billing-notice="suspended">
      <AlertTriangle aria-hidden />
      <div><strong>{t('suspendedTitle', { number: invoice.number })}</strong><p>{t('suspendedHelp')}</p></div>
      <Link className="ds-button ds-button-primary ds-button-sm" href="/dashboard/billing" prefetch={false}>{t('openBilling')}</Link>
    </div>);
  } else if (summary.status === 'awaiting_payment' && invoice) {
    notices.push(<div key="awaiting" className="plan-notice plan-notice-near" role="status" data-billing-notice="awaiting_payment">
      <CalendarClock aria-hidden />
      <div><strong>{t('awaitingTitle', { number: invoice.number })}</strong>
        <p>{t('awaitingHelp', { amount, date: money.date(invoice.due_on), number: invoice.number })}</p></div>
      <Link className="ds-button ds-button-secondary ds-button-sm" href="/dashboard/billing" prefetch={false}>{t('openBilling')}</Link>
    </div>);
  } else if (summary.status === 'refunded' || summary.status === 'canceled') {
    notices.push(<div key="closed" className="plan-notice" role="status" data-billing-notice={summary.status}>
      <CreditCard aria-hidden />
      <div><strong>{t(`${summary.status}Title`)}</strong><p>{t(`${summary.status}Help`)}</p></div>
    </div>);
  }
  const offer = summary.annual_offer;
  if (offer) {
    const values = { date: money.date(offer.pilot_ends_on), price: money.usd(offer.list_amount_cents), credit: money.usd(offer.credit_cents) };
    notices.push(<div key="offer" className="plan-notice plan-notice-offer" role="status" data-billing-notice="annual_offer">
      <Sparkles aria-hidden />
      <div><strong>{t('offerTitle')}</strong><p>{offer.credit_cents ? t('offerHelp', values) : t('offerHelpNoCredit', values)}</p></div>
      <Link className="ds-button ds-button-primary ds-button-sm" href={checkoutHref('pursuit_desk')} prefetch={false}>{t('continueDesk')}</Link>
    </div>);
  }
  return notices.length ? <>{notices}</> : null;
}

function Inline({ parts }: { parts: MarkdownInline[] }) {
  return <>{parts.map((part, index) => part.strong ? <strong key={index}>{part.text}</strong>
    : part.em ? <em key={index}>{part.text}</em> : <span key={index}>{part.text}</span>)}</>;
}

/** The Pilot Terms (Markdown from the API), rendered as React text: never as HTML. */
export function TermsText({ markdown }: { markdown: string }) {
  return <div className="billing-terms-text" data-billing-terms>
    {parseMarkdown(markdown).map((block, index) => {
      if (block.kind === 'ul') return <ul key={index}>{block.items.map((item, key) => <li key={key}><Inline parts={item} /></li>)}</ul>;
      if (block.kind === 'h1') return <h3 key={index}><Inline parts={block.inline} /></h3>;
      if (block.kind === 'h2' || block.kind === 'h3') return <h4 key={index}><Inline parts={block.inline} /></h4>;
      return <p key={index}><Inline parts={block.inline} /></p>;
    })}
  </div>;
}
