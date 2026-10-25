'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Building2, CreditCard, Download, ExternalLink, FileText, MessageSquare, Receipt, RefreshCw } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { BillingNotice, checkoutHref, useMoney } from '@/components/billing/BillingParts';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { StatusBadge, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { api } from '@/lib/api';
import type { BillingInvoice, BillingOverview, ProductCode } from '@/lib/billing';
import type { PlanCode } from '@/lib/plans';

type CatalogPlan = { code: string; price_cents: number; monthly_cents: number | null; billing: string; from_price: boolean };
type CatalogProduct = { code: ProductCode; amount_cents: number };
type Catalog = { plans: CatalogPlan[]; products: CatalogProduct[]; pilot_credit_cents: number };

const INVOICE_TONE = { issued: 'warning', paid: 'success', overdue: 'danger', void: 'neutral' } as const;
const STATUS_TONE = { paid: 'success', awaiting_payment: 'warning', suspended: 'danger', refunded: 'neutral', canceled: 'neutral' } as const;

/** B1: the organization's plan, what it can buy, its invoices and orders. Explore organizations come here to start a pilot. */
export default function BillingPage() {
  const t = useTranslations('dashboard.billing');
  const plans = useTranslations('dashboard.plan');
  const money = useMoney();
  const [overview, setOverview] = useState<BillingOverview | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [downloadFailed, setDownloadFailed] = useState(false);
  const [talk, setTalk] = useState<'idle' | 'sending' | 'sent'>('idle');
  const [renewalBusy, setRenewalBusy] = useState(false);
  const [renewalError, setRenewalError] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([api.get<BillingOverview>('/billing'), api.get<Catalog>('/billing/catalog')]).then(([billing, products]) => {
      if (!active) return;
      setOverview(billing.data);
      setCatalog(products.data);
    }, () => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  const download = useCallback(async (invoice: BillingInvoice) => {
    setDownloadFailed(false);
    try {
      const response = await api.get(`/billing/invoices/${encodeURIComponent(invoice.id)}/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${invoice.number}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch {
      setDownloadFailed(true);
    }
  }, []);

  // Card customers: Polar's customer portal. Bank transfer: ask not to renew (the team confirms).
  const openPortal = async () => {
    setRenewalBusy(true);
    setRenewalError(false);
    try {
      window.location.assign((await api.post<{ url: string }>('/billing/portal')).data.url);
    } catch {
      setRenewalError(true);
      setRenewalBusy(false);
    }
  };
  const cancelRenewal = async () => {
    setRenewalBusy(true);
    setRenewalError(false);
    try {
      setOverview((await api.post<BillingOverview>('/billing/cancel-renewal')).data);
    } catch {
      setRenewalError(true);
    } finally {
      setRenewalBusy(false);
    }
  };

  const talkToUs = async () => {
    setTalk('sending');
    try {
      await api.post('/explore/requests', { request: 'upgrade', message: null });
      setTalk('sent');
    } catch {
      setTalk('idle');
    }
  };

  if (failed) return <div className="customer-page"><Alert tone="danger" title={t('loadFailed')} /></div>;
  if (!overview || !catalog) return <div className="customer-page"><p className="ds-muted" role="status">{t('loading')}</p></div>;

  const price = (code: string) => catalog.plans.find((plan) => plan.code === code);
  const product = (code: ProductCode) => catalog.products.find((item) => item.code === code)?.amount_cents ?? 0;
  const pilot = price('pilot');
  const offers: { code: ProductCode; price: string; show: boolean }[] = [
    { code: 'pilot', price: t('products.pilot.price', { price: money.usd(product('pilot')), monthly: money.usd(pilot?.monthly_cents ?? 0) }),
      show: overview.plan === 'explore' && !overview.orders.some((order) => order.product === 'pilot' && order.status !== 'pending') },
    { code: 'pursuit_desk', price: t('products.pursuit_desk.price', { price: money.usd(product('pursuit_desk')) }),
      show: ['explore', 'pilot'].includes(overview.plan) || (overview.plan === 'pursuit_desk' && overview.summary.status !== 'paid') },
    { code: 'extra_pursuit', price: t('products.extra_pursuit.price', { price: money.usd(product('extra_pursuit')) }),
      show: overview.plan !== 'explore' },
  ];
  const status = overview.summary.status;

  return <div className="customer-page billing-page ds-stack" data-billing-page>
    <header className="billing-header">
      <span className="ds-eyebrow"><CreditCard aria-hidden /> {t('statusLabel')}</span>
      <h1>{t('title')}</h1>
      <p className="ds-muted">{t('lead')}</p>
    </header>

    <BillingNotice summary={overview.summary} />
    {downloadFailed && <Alert tone="danger" title={t('downloadFailed')} />}

    <Surface className="billing-current" aria-labelledby="billing-current-title" data-billing-current>
      <div>
        <span className="ds-eyebrow" id="billing-current-title">{t('currentPlan')}</span>
        <strong className="billing-plan-name">{plans(`names.${overview.plan as PlanCode}`)}</strong>
        <span className="ds-muted">{overview.plan_started_on && overview.plan_ends_on
          ? t('planTerm', { start: money.date(overview.plan_started_on), end: money.date(overview.plan_ends_on) })
          : overview.plan_started_on ? t('planSince', { start: money.date(overview.plan_started_on) }) : ''}</span>
      </div>
      <StatusBadge tone={status ? STATUS_TONE[status] : 'neutral'}>{t(`status.${status ?? 'none'}`)}</StatusBadge>
    </Surface>

    <section className="billing-products" aria-label={t('buy')}>
      {offers.filter((offer) => offer.show).map((offer) => <Surface key={offer.code} className="billing-product" data-billing-product={offer.code}>
        <h2>{t(`products.${offer.code}.name`)}</h2>
        <strong className="billing-price">{offer.price}</strong>
        <p className="ds-muted">{t(`products.${offer.code}.points`)}</p>
        {offer.code === 'pursuit_desk' && overview.pilot_credit_available
          && <p className="billing-credit">{t('creditNote', { credit: money.usd(catalog.pilot_credit_cents) })}</p>}
        <Link className="ds-button ds-button-primary" href={checkoutHref(offer.code)} prefetch={false}>{t('buy')}</Link>
      </Surface>)}
      <Surface className="billing-product billing-product-talk" data-billing-product="talk">
        <h2>{t('talkTitle')}</h2>
        <p className="ds-muted">{t('talkHelp', { agent: money.usd(price('agent')?.price_cents ?? 0),
          enterprise: money.usd(price('enterprise')?.price_cents ?? 0) })}</p>
        {talk === 'sent' ? <p className="plan-notice-sent">{t('talkSent')}</p>
          : <Button variant="secondary" loading={talk === 'sending'} leadingIcon={<MessageSquare aria-hidden />}
            onClick={() => void talkToUs()}>{t('talkToUs')}</Button>}
      </Surface>
    </section>

    {(overview.summary.renewal || overview.summary.card_customer) && <Surface className="billing-renewal" data-billing-renewal
      aria-labelledby="billing-renewal-title">
      <div>
        <h2 id="billing-renewal-title"><RefreshCw aria-hidden /> {t('renewal.title')}</h2>
        {overview.summary.renewal && <p>{overview.summary.renewal.canceled
          ? t('renewal.endsOn', { date: money.date(overview.summary.renewal.renews_on) })
          : t('renewal.renewsOn', { date: money.date(overview.summary.renewal.renews_on) })}</p>}
        {overview.summary.renewal?.method === 'bank_transfer' && overview.summary.renewal.cancel_requested_at
          && !overview.summary.renewal.canceled
          && <p className="ds-muted" data-billing-cancel-requested>{t('renewal.requested', { date: money.date(overview.summary.renewal.cancel_requested_at) })}</p>}
        <p className="ds-muted ds-text-small">{overview.summary.renewal?.method === 'bank_transfer' ? t('renewal.cancelHelp') : t('renewal.manageHelp')}</p>
        {renewalError && <p className="pursuit-upload-error" role="alert">{t('renewal.failed')}</p>}
      </div>
      {overview.summary.renewal?.method === 'bank_transfer'
        ? (!overview.summary.renewal.cancel_requested_at && !overview.summary.renewal.canceled
          && <Button variant="secondary" loading={renewalBusy} onClick={() => void cancelRenewal()} data-billing-cancel>{t('renewal.cancel')}</Button>)
        : overview.summary.card_customer
          && <Button variant="secondary" loading={renewalBusy} leadingIcon={<ExternalLink aria-hidden />}
            onClick={() => void openPortal()} data-billing-portal>{t('renewal.manage')}</Button>}
    </Surface>}

    <section className="billing-section" aria-labelledby="billing-details-title">
      <h2 id="billing-details-title"><Building2 aria-hidden /> {t('detailsTitle')}</h2>
      {overview.customer ? <dl className="billing-details">
        <div><dt>{t('start.legalName')}</dt><dd><BidiText>{overview.customer.legal_name}</BidiText></dd></div>
        {overview.customer.tin && <div><dt>{t('start.tin')}</dt><dd><TechnicalText>{overview.customer.tin}</TechnicalText></dd></div>}
        <div><dt>{t('start.address')}</dt><dd><BidiText>{overview.customer.address}</BidiText> · <TechnicalText>{overview.customer.country}</TechnicalText></dd></div>
        <div><dt>{t('start.billingEmail')}</dt><dd><TechnicalText>{overview.customer.billing_email}</TechnicalText></dd></div>
        <div><dt>{t('invoicesTitle')}</dt><dd>{overview.customer.resident ? t('residentYes') : t('residentNo')}</dd></div>
      </dl> : <p className="ds-muted">{t('noDetails')}</p>}
    </section>

    <section className="billing-section" aria-labelledby="billing-invoices-title">
      <h2 id="billing-invoices-title"><Receipt aria-hidden /> {t('invoicesTitle')}</h2>
      {overview.invoices.length === 0 ? <p className="ds-muted">{t('noInvoices')}</p>
        : <div className="billing-table-wrap"><table className="billing-table">
          <thead><tr><th>{t('invoiceNumber')}</th><th>{t('issued')}</th><th>{t('due')}</th><th>{t('amount')}</th><th>{t('state')}</th><th /></tr></thead>
          <tbody>{overview.invoices.map((invoice) => <tr key={invoice.id} data-billing-invoice={invoice.number}>
            <td><TechnicalText>{invoice.number}</TechnicalText></td>
            <td>{money.date(invoice.issued_on)}</td>
            <td>{money.date(invoice.due_on)}</td>
            <td>{invoice.currency === 'UZS' && invoice.total_uzs ? <>{money.uzs(invoice.total_uzs)}<span className="ds-muted ds-text-small"> · {money.usd(invoice.total_usd_cents)}</span></> : money.usd(invoice.total_usd_cents)}</td>
            <td><StatusBadge tone={INVOICE_TONE[invoice.status]}>{t(`invoiceStatus.${invoice.status}`)}</StatusBadge></td>
            <td><Button size="sm" variant="ghost" leadingIcon={<Download aria-hidden />} onClick={() => void download(invoice)}>{t('download')}</Button></td>
          </tr>)}</tbody>
        </table></div>}
    </section>

    <section className="billing-section" aria-labelledby="billing-orders-title">
      <h2 id="billing-orders-title"><FileText aria-hidden /> {t('ordersTitle')}</h2>
      {overview.orders.length === 0 ? <p className="ds-muted">{t('noOrders')}</p>
        : <div className="billing-table-wrap"><table className="billing-table">
          <thead><tr><th>{t('date')}</th><th>{t('product')}</th><th>{t('paymentMethod')}</th><th>{t('amount')}</th><th>{t('state')}</th></tr></thead>
          <tbody>{overview.orders.map((order) => <tr key={order.id}>
            <td>{money.date(order.created_at)}</td>
            <td>{t(`products.${order.product}.name`)}</td>
            <td>{t(`method.${order.method}`)}</td>
            <td>{money.usd(order.amount_cents)}{order.credit_cents > 0
              && <span className="ds-muted ds-text-small"> · {t('creditApplied', { credit: money.usd(order.credit_cents) })}</span>}</td>
            <td>{t(`orderStatus.${order.status}`)}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </div>;
}
