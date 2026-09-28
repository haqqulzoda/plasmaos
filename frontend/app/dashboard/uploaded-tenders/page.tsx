'use client';

import { useCallback, useEffect, useState } from 'react';
import { CalendarDays, FileStack, Plus, RefreshCw } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';

import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, PageHeader, PageSkeleton, StatusBadge, Surface } from '@/components/ui/Display';
import { BidiText } from '@/components/i18n/BidiText';
import { formatDate, formatDateTime } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';
import type { PursuitListResponse } from '@/types/pursuit';
import { customerProcessingState } from '@/types/pursuit';

export default function UploadedTendersPage() {
  const t = useTranslations('pursuits');
  const locale = useLocale() as CustomerSelectableLocale;
  const [organizationId, setOrganizationId] = useState('');
  const [data, setData] = useState<PursuitListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [version, setVersion] = useState(0);
  const chooseOrganization = useCallback((value: string) => {
    setLoading(Boolean(value));
    setError(false);
    setData(null);
    setOrganizationId(value);
  }, []);

  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    api.get<PursuitListResponse>('/pursuits', {
      params: { origin: 'UPLOAD', limit: 100 },
      headers: { 'X-Organization-ID': organizationId },
    }).then((response) => { if (!cancelled) setData(response.data); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [organizationId, version]);

  return <main className="customer-page pursuits-page ds-container-content">
    <PageHeader
      eyebrow={t('uploaded.eyebrow')}
      title={t('uploaded.title')}
      description={t('uploaded.description')}
      primaryAction={<ButtonLink href="/dashboard/uploaded-tenders/upload">
        <Plus aria-hidden />{t('actions.uploadTender')}
      </ButtonLink>}
    />
    <Surface className="pursuit-org-context">
      <OrganizationContextPicker value={organizationId} onChange={chooseOrganization} />
    </Surface>
    {loading && !data ? <PageSkeleton label={t('uploaded.loading')} /> : error ? <EmptyState
      icon={<FileStack aria-hidden />}
      title={t('uploaded.failed')}
      description={t('uploaded.failedHelp')}
      action={<Button variant="secondary" onClick={() => { setLoading(true); setError(false); setVersion((current) => current + 1); }} leadingIcon={<RefreshCw aria-hidden />}>{t('actions.retry')}</Button>}
    /> : data?.items.length ? <div className="pursuit-list" aria-label={t('uploaded.listLabel')}>
      {data.items.map((pursuit) => {
        const processing = customerProcessingState(pursuit.processing_state);
        return <Surface className="pursuit-card" key={pursuit.pursuit_id}>
          <div className="pursuit-card-heading">
            <div>
              <span className="ds-eyebrow">{pursuit.reference || t('values.referenceUnknown')}</span>
              <h2><BidiText>{pursuit.title || t('values.untitled')}</BidiText></h2>
            </div>
            <StatusBadge tone={processing === 'FAILED' ? 'danger' : processing === 'PARTIAL' ? 'warning' : processing === 'READY' ? 'success' : 'info'}>
              {processing ? t(`processing.${processing}`) : t('processing.CHECKING')}
            </StatusBadge>
          </div>
          <dl className="pursuit-facts">
            <div><dt>{t('fields.buyer')}</dt><dd><BidiText>{pursuit.buyer || pursuit.declared_funder || t('values.unknown')}</BidiText></dd></div>
            <div><dt><CalendarDays aria-hidden />{t('fields.deadline')}</dt><dd>{pursuit.external_deadline ? formatDate(pursuit.external_deadline, locale) : t('values.unknown')}</dd></div>
            <div><dt>{t('fields.documents')}</dt><dd>{t('values.processed', { processed: pursuit.processed_count, total: pursuit.file_count })}</dd></div>
            <div><dt>{t('fields.stage')}</dt><dd>{t(`stages.${pursuit.stage}`)}</dd></div>
            <div><dt>{t('fields.owner')}</dt><dd><BidiText>{pursuit.owner_name || t('values.unassigned')}</BidiText></dd></div>
            <div><dt>{t('fields.updated')}</dt><dd>{formatDateTime(pursuit.updated_at, locale)}</dd></div>
          </dl>
          <ButtonLink variant="secondary" href={`/dashboard/pursuits/${pursuit.pursuit_id}?organization_id=${encodeURIComponent(organizationId)}`}>
            {t('actions.openWorkspace')}
          </ButtonLink>
        </Surface>;
      })}
    </div> : organizationId && <EmptyState
      icon={<FileStack aria-hidden />}
      title={t('uploaded.empty')}
      description={t('uploaded.emptyHelp')}
      action={<ButtonLink href="/dashboard/uploaded-tenders/upload">{t('actions.uploadTender')}</ButtonLink>}
    />}
  </main>;
}
