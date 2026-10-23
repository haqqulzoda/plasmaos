'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, Gauge } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/Button';
import { api } from '@/lib/api';
import { PLAN_STATUS_EVENT, type PlanStatus } from '@/lib/plans';

type Props = {
  headers?: Record<string, string | undefined>;
  /** Called with the plan once loaded (the pursuit page uses it for its tabs). */
  onPlan?: (plan: PlanStatus) => void;
};

/** P3: the in-app notice at 80% and 100% of the plan's pursuits, with "upgrade or add pursuits". */
export function PlanNotice({ headers, onPlan }: Props) {
  const t = useTranslations('dashboard.plan');
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

  if (!plan || plan.pursuits.notice === 'none' || plan.pursuits.limit === null) return null;
  const reached = plan.pursuits.notice === 'limit_reached';
  const explore = plan.plan === 'explore';
  const values = {
    used: plan.pursuits.used, limit: plan.pursuits.limit, plan: t(`names.${plan.plan}`),
    period: t(`periods.${plan.period_kind}`),
  };
  const ask = async () => {
    setBusy(true);
    try {
      await api.post('/explore/requests', { request: explore ? 'pilot' : 'upgrade', message: null });
      setRequested(true);
    } catch { /* the notice stays; the team can still be reached from the explore page */ }
    finally { setBusy(false); }
  };
  return <div className={`plan-notice ${reached ? 'plan-notice-reached' : 'plan-notice-near'}`} role={reached ? 'alert' : 'status'}
    data-plan-notice={plan.pursuits.notice}>
    {reached ? <AlertTriangle aria-hidden /> : <Gauge aria-hidden />}
    <div>
      <strong>{explore ? t(reached ? 'exploreReachedTitle' : 'nearTitle', values) : t(reached ? 'reachedTitle' : 'nearTitle', values)}</strong>
      <p>{explore ? t('exploreReachedHelp') : t(reached ? 'reachedHelp' : 'nearHelp', values)}</p>
    </div>
    {requested
      ? <span className="plan-notice-sent">{t('requested')}</span>
      : <Button size="sm" variant={reached ? 'primary' : 'secondary'} loading={busy} onClick={() => void ask()}>
        {explore ? t('startPilot') : t('upgrade')}
      </Button>}
  </div>;
}
