'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';

import { Select } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import { pageOrganization, readSelectedOrganization, writeSelectedOrganization } from '@/lib/organizationSelection';
import type { OrganizationSummary } from '@/types/pursuit';

export function OrganizationContextPicker({
  value,
  onChange,
  onOrganizations,
}: {
  value: string;
  onChange: (organizationId: string) => void;
  onOrganizations?: (organizations: OrganizationSummary[]) => void;
}) {
  const t = useTranslations('pursuits');
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get<OrganizationSummary[]>('/organizations')
      .then((response) => {
        if (cancelled) return;
        setOrganizations(response.data);
        onOrganizations?.(response.data);
        // The workspace-wide choice (R3 Task 6), else the only organization.
        const initial = pageOrganization(response.data, readSelectedOrganization());
        if (initial) onChange(initial);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [onChange, onOrganizations]);

  if (failed) return <p role="alert" className="ds-field-error">{t('organizations.failed')}</p>;
  if (organizations.length <= 1) {
    return organizations.length === 1
      ? <p className="ds-muted ds-text-small">{t('organizations.using', { name: organizations[0].display_name || t('organizations.unnamed') })}</p>
      : <p role="status" className="ds-muted ds-text-small">{t('organizations.loading')}</p>;
  }
  return (
    <Select
      label={t('organizations.label')}
      helper={t('organizations.help')}
      required
      value={value}
      onChange={(event) => { writeSelectedOrganization(event.target.value || null); onChange(event.target.value); }}
    >
      <option value="">{t('organizations.choose')}</option>
      {organizations.map((organization) => (
        <option key={organization.organization_id} value={organization.organization_id}>
          {organization.display_name || t('organizations.unnamed')}
        </option>
      ))}
    </Select>
  );
}
