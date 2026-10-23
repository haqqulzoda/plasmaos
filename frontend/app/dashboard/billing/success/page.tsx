'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { useMoney } from '@/components/billing/BillingParts';
import { Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { api } from '@/lib/api';
import type { BillingOrder } from '@/lib/billing';

type OrderStatus = { order: BillingOrder; plan: string; billing_status: string | null };
const POLL_MS = 2500;
const MAX_POLLS = 48;

export default function BillingSuccessPage() {
  return <Suspense fallback={null}><BillingSuccess /></Suspense>;
}

/** B1: Polar returns here (?checkout_id=…). The webhook activates the plan; this page waits for it. */
function BillingSuccess() {
  const t = useTranslations('dashboard.billing.success');
  const billing = useTranslations('dashboard.billing');
  const money = useMoney();
  const checkoutId = useSearchParams().get('checkout_id');
  const [status, setStatus] = useState<OrderStatus | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!checkoutId) return;
    let active = true;
    let polls = 0;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const response = await api.get<OrderStatus>('/billing/orders', { params: { checkout_id: checkoutId } });
        if (!active) return;
        setStatus(response.data);
        if (response.data.order.activated_at) return;  // access is read per request: no session refresh
      } catch {
        if (!active) return;
        if (polls > 3) { setMissing(true); return; }
      }
      polls += 1;
      if (polls < MAX_POLLS) timer = window.setTimeout(() => void poll(), POLL_MS);
    };
    void poll();
    return () => { active = false; window.clearTimeout(timer); };
  }, [checkoutId]);

  if (missing || !checkoutId) return <div className="customer-page"><Alert tone="warning" title={t('notFound')}>
    <Link href="/dashboard/billing" prefetch={false}>{billing('notice.openBilling')}</Link></Alert></div>;
  const order = status?.order;
  const active = Boolean(order?.activated_at);
  const product = order ? billing(`products.${order.product}.name`) : '';
  return <div className="customer-page billing-page ds-stack" data-billing-success={active ? 'active' : 'waiting'}>
    <Surface className="billing-success">
      {active ? <CheckCircle2 aria-hidden className="billing-success-icon" /> : <Loader2 aria-hidden className="ds-spin billing-success-icon" />}
      <div role="status">
        <h1>{active ? t('activeTitle', { product }) : t('waitingTitle')}</h1>
        <p className="ds-muted">{active
          ? (order?.plan ? t('activeHelp', { date: money.date(order.plan_ends_on) }) : t('addonHelp'))
          : t('waitingHelp')}</p>
      </div>
      {active && <Link className="ds-button ds-button-primary" href="/dashboard" prefetch={false}>{t('openDashboard')}</Link>}
    </Surface>
  </div>;
}
