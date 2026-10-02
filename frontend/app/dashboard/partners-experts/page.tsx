'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';

import { ExpertsTab, OwnExperienceTab, PartnerFirmsTab } from '@/components/library/LibraryTabs';
import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { Button } from '@/components/ui/Button';
import { EmptyState, PageHeader, PageSkeleton, Surface } from '@/components/ui/Display';
import { Tabs } from '@/components/ui/Navigation';
import { libraryTab, type LibraryTab } from '@/lib/library';
import { getLibrary, getSelfFirm } from '@/lib/libraryApi';
import type { CandidateFirm, CandidateLibrary, OrganizationSummary } from '@/types/pursuit';

type Loaded = { library: CandidateLibrary; selfFirm: CandidateFirm | null };

function LibraryPage() {
  const t = useTranslations('pursuits.library');
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tab = libraryTab(searchParams.get('tab'));
  const [organizationId, setOrganizationId] = useState('');
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [data, setData] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const chooseOrganization = useCallback((value: string) => {
    setOrganizationId(value); setData(null); setFailed(false); setLoading(Boolean(value));
  }, []);
  const reload = useCallback(() => setVersion((current) => current + 1), []);
  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    // Two passive reads. Before D2-01 the self-firm read answers 404: "not set up yet".
    Promise.all([getLibrary(organizationId), getSelfFirm(organizationId)])
      .then(([library, selfFirm]) => { if (!cancelled) setData({ library, selfFirm: library.self_firm ?? selfFirm }); })
      .catch(() => { if (!cancelled) setFailed(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [organizationId, version]);
  const selectTab = (value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set('tab', libraryTab(value));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const organizationName = organizations.find((item) => item.organization_id === organizationId)?.display_name ?? '';
  const common = { organizationId, reload };
  const firms = (data?.library.firms ?? []).filter((firm) => !firm.is_self_firm);
  const content = (value: LibraryTab) => !data ? null : value === 'own'
    ? <OwnExperienceTab {...common} selfFirm={data.selfFirm} organizationName={organizationName} />
    : value === 'partners' ? <PartnerFirmsTab {...common} firms={firms} />
      : <ExpertsTab {...common} experts={data.library.experts} />;
  return <main className="customer-page candidate-library-page ds-container-content" data-library-page>
    <PageHeader eyebrow={t('eyebrow')} title={t('title')} description={t('description')} />
    <Surface className="pursuit-org-context">
      <OrganizationContextPicker value={organizationId} onChange={chooseOrganization} onOrganizations={setOrganizations} />
    </Surface>
    {loading && !data ? <PageSkeleton label={t('loading')} /> : failed ? <EmptyState
      icon={<RefreshCw aria-hidden />} title={t('failed')} description={t('failedHelp')}
      action={<Button variant="secondary" onClick={() => { setFailed(false); setLoading(true); reload(); }}>{t('retry')}</Button>}
    /> : data && <Tabs label={t('tabs.label')} value={tab} onChange={selectTab} items={[
      { value: 'own', label: t('tabs.own'), content: tab === 'own' ? content('own') : null },
      { value: 'partners', label: t('tabs.partners'), content: tab === 'partners' ? content('partners') : null },
      { value: 'experts', label: t('tabs.experts'), content: tab === 'experts' ? content('experts') : null },
    ]} />}
  </main>;
}

export default function PartnersExpertsPage() {
  return <Suspense fallback={<PageSkeleton label="" />}><LibraryPage /></Suspense>;
}
