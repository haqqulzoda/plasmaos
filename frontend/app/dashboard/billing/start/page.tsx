'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Building2, CreditCard, Download, FileSignature, Landmark, ShieldCheck } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { TermsText, useMoney } from '@/components/billing/BillingParts';
import { Button } from '@/components/ui/Button';
import { Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox, Input, Radio, Select } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import { PLAN_STATUS_EVENT } from '@/lib/plans';
import {
  billingErrorCode, billingErrorKey, productFrom, type BillingCustomer, type BillingOverview, type BillingQuote, type BillingTerms,
  type PaymentMethod, type ProductCode,
} from '@/lib/billing';

const COUNTRIES = ['UZ', 'KZ', 'KG', 'TJ', 'TM', 'AF', 'AZ', 'GE', 'AM', 'MN', 'TR', 'PK', 'IN', 'AE', 'SA', 'QA', 'EG',
  'RU', 'UA', 'GB', 'DE', 'FR', 'NL', 'IT', 'ES', 'CH', 'US', 'CA', 'KR', 'JP', 'CN', 'SG'];
const EMPTY: BillingCustomer = { legal_name: '', tin: '', country: 'UZ', address: '', billing_email: '', resident: true };
type Step = 'details' | 'terms' | 'payment';
type Issued = { order_id: string; invoice_id: string; invoice_number: string };

export default function BillingStartPage() {
  return <Suspense fallback={null}><BillingStart /></Suspense>;
}

/** B1: /billing/start?plan=pilot|pursuit_desk|extra_pursuit. Company details, the Pilot Terms accepted, then card
 *  (Polar checkout; the webhook activates) or bank transfer (invoice e-mailed, plan active now). */
function BillingStart() {
  const t = useTranslations('dashboard.billing');
  const s = useTranslations('dashboard.billing.start');
  const money = useMoney();
  const params = useSearchParams();
  const product = productFrom(params.get('plan'));
  const [step, setStep] = useState<Step>('details');
  const [customer, setCustomer] = useState<BillingCustomer>(EMPTY);
  const [terms, setTerms] = useState<BillingTerms | null>(null);
  const [quote, setQuote] = useState<BillingQuote | null>(null);
  const [sandbox, setSandbox] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [method, setMethod] = useState<PaymentMethod | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [loaded, setLoaded] = useState(false);

  const countryName = useMemo(() => {
    try {
      const names = new Intl.DisplayNames([money.locale], { type: 'region' });
      return (code: string) => names.of(code) ?? code;
    } catch {
      return (code: string) => code;
    }
  }, [money.locale]);

  const loadQuote = useCallback(async (code: ProductCode) => {
    const response = await api.get<BillingQuote>('/billing/quote', { params: { product: code } });
    setQuote(response.data);
    setMethod((current) => current && response.data.methods[current] ? current
      : response.data.methods.card ? 'card' : response.data.methods.bank_transfer ? 'bank_transfer' : null);
    return response.data;
  }, []);

  useEffect(() => {
    if (!product) return;
    let active = true;
    Promise.all([
      api.get<BillingOverview>('/billing'), api.get<BillingTerms>('/billing/terms'),
      api.get<{ polar_env: string }>('/billing/catalog'), loadQuote(product),
    ]).then(([overview, text, catalog]) => {
      if (!active) return;
      if (overview.data.customer) setCustomer({ ...overview.data.customer, tin: overview.data.customer.tin ?? '' });
      setTerms(text.data);
      setSandbox(catalog.data.polar_env === 'sandbox');
      setLoaded(true);
    }, () => { if (active) { setError(s('errors.generic')); setLoaded(true); } });
    return () => { active = false; };
  }, [loadQuote, product, s]);

  const fail = (failure: unknown) => {
    setError(s(`errors.${billingErrorKey(billingErrorCode(failure))}`));
  };

  const saveDetails = async () => {
    if (!product) return;
    setBusy(true);
    setError(null);
    try {
      await api.put('/billing/customer', { ...customer, tin: customer.tin?.trim() || null });
      await loadQuote(product);
      setStep('terms');
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy(false);
    }
  };

  const pay = async () => {
    if (!product || !terms || !method) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.post<{ checkout_url: string | null; order_id: string; invoice_id: string | null; invoice_number: string | null }>(
        '/billing/checkout', { product, method, terms_version: terms.version, terms_sha256: terms.sha256, accept_terms: accepted });
      if (response.data.checkout_url) {
        window.location.assign(response.data.checkout_url);
        return;
      }
      // The plan is active now. Access is checked per request from the database, so no session refresh
      // here (a refresh re-renders the dashboard layout and would unmount this confirmation).
      setIssued({ order_id: response.data.order_id, invoice_id: response.data.invoice_id ?? '', invoice_number: response.data.invoice_number ?? '' });
      window.dispatchEvent(new Event(PLAN_STATUS_EVENT));
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy(false);
    }
  };

  const downloadInvoice = async () => {
    if (!issued) return;
    const response = await api.get(`/billing/invoices/${encodeURIComponent(issued.invoice_id)}/pdf`, { responseType: 'blob' });
    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${issued.invoice_number}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  if (!product) return <div className="customer-page"><Alert tone="info" title={s('unknownProduct')}>
    <Link href="/dashboard/billing" prefetch={false}>{t('notice.openBilling')}</Link></Alert></div>;
  const name = t(`products.${product}.name`);
  if (!loaded) return <div className="customer-page"><p className="ds-muted" role="status">{t('loading')}</p></div>;

  if (issued) return <div className="customer-page billing-page ds-stack" data-billing-issued>
    <Alert tone="success" title={s('invoiceIssuedTitle', { number: issued.invoice_number })}>
      {s('invoiceIssuedHelp', { product: name, email: customer.billing_email, number: issued.invoice_number })}
    </Alert>
    <div className="ds-row">
      <Button variant="secondary" leadingIcon={<Download aria-hidden />} onClick={() => void downloadInvoice()}>{s('downloadInvoice')}</Button>
      <Link className="ds-button ds-button-primary" href="/dashboard" prefetch={false}>{s('openPlasma')}</Link>
    </div>
  </div>;

  const steps: Step[] = ['details', 'terms', 'payment'];
  const blocker = quote?.blocker;
  const residentCurrency = quote?.invoice_currency ?? (customer.resident ? 'UZS' : 'USD');

  return <div className="customer-page billing-page billing-start ds-stack" data-billing-start={product}>
    <header className="billing-header">
      <span className="ds-eyebrow">{s('stepOf', { step: steps.indexOf(step) + 1 })}</span>
      <h1>{s('title', { product: name })}</h1>
      <ol className="billing-steps">{steps.map((item, index) => <li key={item} aria-current={item === step ? 'step' : undefined}
        data-done={steps.indexOf(step) > index || undefined}>{s(`steps.${item}`)}</li>)}</ol>
    </header>
    {blocker && <Alert tone="warning" title={s(`errors.${billingErrorKey(blocker)}`)}>
      <Link href="/dashboard/billing" prefetch={false}>{t('notice.openBilling')}</Link></Alert>}
    {error && <Alert tone="danger" title={error} />}

    <div className="billing-start-grid">
      <Surface className="billing-start-main">
        {step === 'details' && <form className="ds-stack" data-billing-step="details"
          onSubmit={(event) => { event.preventDefault(); void saveDetails(); }}>
          <h2><Building2 aria-hidden /> {s('steps.details')}</h2>
          <Input label={s('legalName')} required maxLength={300} value={customer.legal_name}
            onChange={(event) => setCustomer({ ...customer, legal_name: event.target.value })} />
          <Checkbox label={s('resident')} checked={customer.resident}
            onChange={(event) => setCustomer({ ...customer, resident: event.target.checked, country: event.target.checked ? 'UZ' : customer.country })} />
          <Input label={s('tin')} helper={s('tinHelp')} required={customer.resident} maxLength={40} inputMode="numeric"
            value={customer.tin ?? ''} onChange={(event) => setCustomer({ ...customer, tin: event.target.value })} />
          <Select label={s('country')} value={customer.country} disabled={customer.resident}
            onChange={(event) => setCustomer({ ...customer, country: event.target.value })}>
            {COUNTRIES.map((code) => <option key={code} value={code}>{countryName(code)}</option>)}
          </Select>
          <Input label={s('address')} required maxLength={500} value={customer.address}
            onChange={(event) => setCustomer({ ...customer, address: event.target.value })} />
          <Input label={s('billingEmail')} helper={s('billingEmailHelp')} required type="email" maxLength={255}
            value={customer.billing_email} onChange={(event) => setCustomer({ ...customer, billing_email: event.target.value })} />
          <div className="ds-row"><Button type="submit" loading={busy} disabled={Boolean(blocker)}>{s('next')}</Button></div>
        </form>}

        {step === 'terms' && terms && <div className="ds-stack" data-billing-step="terms">
          <h2><FileSignature aria-hidden /> {s('steps.terms')}</h2>
          <p className="ds-muted">{s('termsHelp', { version: terms.version })}</p>
          <div className="billing-terms" tabIndex={0}><TermsText markdown={terms.markdown} /></div>
          <Checkbox label={s('accept', { company: customer.legal_name })} checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)} data-billing-accept />
          <div className="ds-row">
            <Button variant="secondary" onClick={() => setStep('details')}>{s('back')}</Button>
            <Button disabled={!accepted} onClick={() => setStep('payment')}>{s('next')}</Button>
          </div>
        </div>}

        {step === 'payment' && quote && <div className="ds-stack" data-billing-step="payment">
          <h2><CreditCard aria-hidden /> {s('steps.payment')}</h2>
          <fieldset className="billing-methods" aria-label={s('steps.payment')}>
            <div className="billing-method" data-disabled={!quote.methods.card || undefined}>
              <Radio name="method" label={<span><CreditCard aria-hidden /> <strong>{s('card')}</strong></span>} value="card"
                checked={method === 'card'} disabled={!quote.methods.card} onChange={() => setMethod('card')} />
              <p className="ds-muted ds-text-small">{quote.methods.card ? s('cardHelp') : s('unavailable')}</p>
            </div>
            <div className="billing-method" data-disabled={!quote.methods.bank_transfer || undefined}>
              <Radio name="method" label={<span><Landmark aria-hidden /> <strong>{s('bank')}</strong></span>} value="bank_transfer"
                checked={method === 'bank_transfer'} disabled={!quote.methods.bank_transfer} onChange={() => setMethod('bank_transfer')} />
              <p className="ds-muted ds-text-small">{quote.methods.bank_transfer ? s('bankHelp', { currency: residentCurrency }) : s('unavailable')}</p>
            </div>
          </fieldset>
          {sandbox && method === 'card' && <p className="billing-sandbox"><ShieldCheck aria-hidden /> {s('sandbox')}</p>}
          <div className="ds-row">
            <Button variant="secondary" onClick={() => setStep('terms')}>{s('back')}</Button>
            <Button loading={busy} disabled={!method || !accepted || Boolean(blocker)} onClick={() => void pay()}>
              {method === 'bank_transfer' ? s('issueInvoice') : s('payCard')}</Button>
          </div>
        </div>}
      </Surface>

      {quote && <Surface className="billing-summary" aria-labelledby="billing-summary-title" data-billing-summary>
        <h2 id="billing-summary-title">{s('summary')}</h2>
        <strong>{name}</strong>
        <p className="ds-muted ds-text-small">{t(`products.${product}.points`)}</p>
        <dl>
          <div><dt>{s('listPrice')}</dt><dd>{money.usd(quote.list_amount_cents)}</dd></div>
          {quote.credit_cents > 0 && <div className="billing-credit"><dt>{s('credit')}</dt><dd>−{money.usd(quote.credit_cents)}</dd></div>}
          <div className="billing-total"><dt>{s('total')}</dt><dd>{money.usd(quote.amount_cents)}</dd></div>
        </dl>
      </Surface>}
    </div>
  </div>;
}
