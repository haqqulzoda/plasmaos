'use client';

import { useEffect, useState } from 'react';
import { ClipboardCheck } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';

import { OpenWorkspaceButton } from '@/components/pursuits/OpenWorkspaceButton';
import { formatDate, formatNumber } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';
import { analysisCardState, sourcePursuitFor, type AnalysisCardState } from '@/lib/analysisCard';
import { activeOrganizations } from '@/lib/openWorkspace';
import type { OrganizationSummary, PursuitAnalysis, PursuitListResponse } from '@/types/pursuit';

/**
 * Replaces the legacy Compliance & Company Readiness card. Reads only: the
 * organization, its SOURCE pursuit for this tender, and that pursuit's latest
 * analysis run. Nothing is created on render; the action is "Open workspace".
 */
export function PursuitAnalysisCard({ tenderId, canStartNew }: { tenderId: string; canStartNew: boolean }) {
  const t = useTranslations('tenderDetails.analysisCard');
  const locale = useLocale() as CustomerSelectableLocale;
  const [state, setState] = useState<AnalysisCardState | 'loading' | 'unavailable'>('loading');
  const [hasPursuit, setHasPursuit] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const organizations = activeOrganizations((await api.get<OrganizationSummary[]>('/organizations')).data ?? []);
      if (organizations.length !== 1) return { pursuit: false, state: { kind: 'none' } as AnalysisCardState };
      const headers = { 'X-Organization-ID': organizations[0].organization_id };
      const pursuits = await api.get<PursuitListResponse>('/pursuits', { params: { origin: 'SOURCE', limit: 100, offset: 0 }, headers });
      const pursuit = sourcePursuitFor(pursuits.data.items ?? [], tenderId);
      if (!pursuit) return { pursuit: false, state: { kind: 'none' } as AnalysisCardState };
      const latest = await api.get<PursuitAnalysis | null>(`/pursuits/${encodeURIComponent(pursuit.pursuit_id)}/analysis-runs/latest`, { headers });
      return { pursuit: true, state: analysisCardState(latest.data) };
    })()
      .then((result) => { if (!cancelled) { setHasPursuit(result.pursuit); setState(result.state); } })
      .catch(() => { if (!cancelled) setState('unavailable'); });
    return () => { cancelled = true; };
  }, [tenderId]);

  return <section className="s143-decision-card" aria-labelledby="s143-analysis-title" data-analysis-card>
    <h2 id="s143-analysis-title"><ClipboardCheck aria-hidden="true" />{t('title')}</h2>
    {state === 'loading' ? <p className="s143-decision-copy" role="status">{t('loading')}</p>
      : state === 'unavailable' ? <p className="s143-decision-copy">{t('unavailable')}</p>
        : state.kind === 'none' ? <p className="s143-decision-copy" data-analysis-state="none">{t('none')}</p>
          : state.kind === 'running' ? <p className="s143-decision-copy" data-analysis-state="running">{t('running')}</p>
            : state.kind === 'failed' ? <p className="s143-decision-copy" data-analysis-state="failed">{t('failed')}</p>
              : <>
                <p className="s143-decision-copy" data-analysis-state="ready">
                  {state.completedAt ? t('readyOn', { date: formatDate(state.completedAt, locale) }) : t('ready')}
                </p>
                <dl className="s143-decision-list">
                  <div><dt>{t('requirements')}</dt><dd>{formatNumber(state.requirements, locale)}</dd></div>
                  <div><dt>{t('evidenceMissing')}</dt><dd>{formatNumber(state.evidenceMissing, locale)}</dd></div>
                  <div><dt>{t('gaps')}</dt><dd>{formatNumber(state.gaps, locale)}</dd></div>
                  {state.positions > 0 && <div><dt>{t('positions')}</dt><dd>{formatNumber(state.positions, locale)}</dd></div>}
                  {state.notes > 0 && <div><dt>{t('notes')}</dt><dd>{formatNumber(state.notes, locale)}</dd></div>}
                </dl>
              </>}
    <div className="s143-decision-links">
      <OpenWorkspaceButton tenderId={tenderId} variant="secondary" disabled={!hasPursuit && !canStartNew} />
    </div>
  </section>;
}
