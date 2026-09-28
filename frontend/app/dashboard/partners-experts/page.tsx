'use client';

import { useCallback, useEffect, useState } from 'react';
import { Building2, RefreshCw, UserRound } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { Button } from '@/components/ui/Button';
import { EmptyState, PageHeader, PageSkeleton, StatusBadge, Surface } from '@/components/ui/Display';
import { api } from '@/lib/api';
import type { CandidateLibrary } from '@/types/pursuit';

export default function PartnersExpertsPage() {
  const t = useTranslations('pursuits.library');
  const [organizationId, setOrganizationId] = useState('');
  const [data, setData] = useState<CandidateLibrary | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const chooseOrganization = useCallback((value: string) => {
    setOrganizationId(value); setData(null); setFailed(false); setLoading(Boolean(value));
  }, []);
  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    api.get<CandidateLibrary>('/candidates', { headers: { 'X-Organization-ID': organizationId } })
      .then((response) => { if (!cancelled) setData(response.data); })
      .catch(() => { if (!cancelled) setFailed(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [organizationId, version]);
  return <main className="customer-page candidate-library-page ds-container-content">
    <PageHeader eyebrow={t('eyebrow')} title={t('title')} description={t('description')} />
    <Surface className="pursuit-org-context"><OrganizationContextPicker value={organizationId} onChange={chooseOrganization} /></Surface>
    {loading && !data ? <PageSkeleton label={t('loading')} /> : failed ? <EmptyState
      icon={<RefreshCw aria-hidden />} title={t('failed')} description={t('failedHelp')}
      action={<Button variant="secondary" onClick={() => { setFailed(false); setLoading(true); setVersion((current) => current + 1); }}>{t('retry')}</Button>}
    /> : data && !data.firms.length && !data.experts.length ? <EmptyState
      icon={<Building2 aria-hidden />} title={t('empty')} description={t('emptyHelp')}
    /> : data && <>
      <section className="candidate-library-group" aria-labelledby="candidate-library-firms"><header><Building2 aria-hidden /><div><h2 id="candidate-library-firms">{t('firms')}</h2><p>{t('firmsHelp')}</p></div></header>
        <div className="candidate-library-grid">{data.firms.map((firm) => <Surface className="candidate-library-card" key={firm.firm_id} variant="raised">
          <header><div><h3><BidiText>{firm.display_name}</BidiText></h3>{firm.legal_name && <p className="ds-muted"><BidiText>{firm.legal_name}</BidiText></p>}</div><StatusBadge tone={firm.evidence_state === 'VERIFIED' || firm.evidence_state === 'REVIEWED' ? 'success' : 'warning'}>{t(`evidence.${firm.evidence_state}`)}</StatusBadge></header>
          <p>{[firm.country, ...firm.services.map(String), ...firm.sectors.map(String)].filter(Boolean).join(' · ') || t('notRecorded')}</p>
          <h4>{t('referenceHistory')}</h4>
          {firm.project_references.length ? <ul>{firm.project_references.map((reference) => <li key={reference.reference_id}><BidiText>{reference.project_name}</BidiText> · {reference.role} · {reference.completion_state}</li>)}</ul> : <p className="ds-muted">{t('noReferences')}</p>}
          <small>{t(`scopes.${firm.scope}`)}</small>
        </Surface>)}</div>
      </section>
      <section className="candidate-library-group" aria-labelledby="candidate-library-experts"><header><UserRound aria-hidden /><div><h2 id="candidate-library-experts">{t('experts')}</h2><p>{t('expertsHelp')}</p></div></header>
        <div className="candidate-library-grid">{data.experts.map((expert) => <Surface className="candidate-library-card" key={expert.expert_id} variant="raised">
          <header><div><h3><BidiText>{expert.display_name}</BidiText></h3><p className="ds-muted">{expert.specializations.map(String).join(' · ') || t('notRecorded')}</p></div><StatusBadge tone={expert.evidence_state === 'VERIFIED' || expert.evidence_state === 'REVIEWED' ? 'success' : 'warning'}>{t(`evidence.${expert.evidence_state}`)}</StatusBadge></header>
          <p>{expert.languages.map(String).join(' · ') || t('notRecorded')}</p>
          <h4>{t('cvVersions')}</h4>
          {expert.cv_versions.length ? <ul>{expert.cv_versions.map((cv) => <li key={cv.cv_version_id}>{t('cvVersion', { version: cv.version_number })} · {t(`evidence.${cv.evidence_state}`)} · <TechnicalText>{cv.structured_sha256.slice(0, 12)}</TechnicalText></li>)}</ul> : <p className="ds-muted">{t('noCvVersions')}</p>}
          <small>{t(`scopes.${expert.scope}`)}</small>
        </Surface>)}</div>
      </section>
    </>}
  </main>;
}

