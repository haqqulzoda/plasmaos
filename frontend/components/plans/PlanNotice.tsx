'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Gauge } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { BillingNotice, checkoutHref, useMoney } from '@/components/billing/BillingParts';
import { Button } from '@/components/ui/Button';
import { api } from '@/lib/api';
import { PLAN_STATUS_EVENT, type PlanStatus } from '@/lib/plans';

type Props = {
  headers?: Record<string, string | undefined>;
  /** Called with the plan once loaded (the pursuit page uses it for its tabs). */
  onPlan?: (plan: PlanStatus) => void;
};

/** P3: the in-app notice at 80% and 100% of the plan's pursuits, with "upgrade or add pursuits".
 *  B1: "Start a pilot" and "Add a pursuit" open the checkout; the billing notices come first. */
export function PlanNotice({ headers, onPlan }: Props) {
  const t = useTranslations('dashboard.plan');
  const billing = useTranslations('dashboard.billing');
  const money = useMoney();
  const [plan, setPlan] = useState<PlanStatus | null>(null);
  const [requested, setRequested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const refresh = () => setVersion((value) => value + 1);
    window.addEventListener(PLAN_STATUS_EVENT, refresh);
    return () => window.removeEventListener(PLAN_STATUS_EVENT, refresh);
  }, []);
  useEffect(() => {
    let active = true;
    api.get<PlanStatus>('/organizations/plan', { headers }).then((response) => {
      if (!active) return;
      setPlan(response.data);
      onPlan?.(response.data);
    }, () => undefined);
    return () => { active = false; };
  }, [headers, onPlan, version]);

  if (!plan) return null;
  const billingNotice = <BillingNotice summary={plan.billing} />;
  if (plan.pursuits.notice === 'none' || plan.pursuits.limit === null) return billingNotice;
  const reached = plan.pursuits.notice === 'limit_reached';
  const explore = plan.plan === 'explore';
  const values = {
    used: plan.pursuits.used, limit: plan.pursuits.limit, plan: t(`names.${plan.plan}`),
    period: t(`periods.${plan.period_kind}`),
  };
  const ask = async () => {
    setBusy(true);
    try {
      await api.post('/explore/requests', { request: 'upgrade', message: null });
      setRequested(true);
    } catch { /* the notice stays; the team can still be reached from the explore page */ }
    finally { setBusy(false); }
  };
  return <>{billingNotice}<div className={`plan-notice ${reached ? 'plan-notice-reached' : 'plan-notice-near'}`} role={reached ? 'alert' : 'status'}
    data-plan-notice={plan.pursuits.notice}>
    {reached ? <AlertTriangle aria-hidden /> : <Gauge aria-hidden />}
    <div>
      <strong>{explore ? t(reached ? 'exploreReachedTitle' : 'nearTitle', values) : t(reached ? 'reachedTitle' : 'nearTitle', values)}</strong>
      <p>{explore ? t('exploreReachedHelp') : t(reached ? 'reachedHelp' : 'nearHelp', values)}</p>
    </div>
    <div className="plan-notice-actions">
      {explore
        ? <Link className="ds-button ds-button-primary ds-button-sm" href={checkoutHref('pilot')} prefetch={false}>{t('startPilot')}</Link>
        : <Link className={`ds-button ds-button-sm ${reached ? 'ds-button-primary' : 'ds-button-secondary'}`}
          href={checkoutHref('extra_pursuit')} prefetch={false}>{billing('addPursuit', {
            price: plan.billing?.extra_pursuit_cents ? money.usd(plan.billing.extra_pursuit_cents) : '…' })}</Link>}
      {!explore && (requested
        ? <span className="plan-notice-sent">{t('requested')}</span>
        : <Button size="sm" variant="ghost" loading={busy} onClick={() => void ask()}>{t('upgrade')}</Button>)}
    </div>
  </div></>;
}
