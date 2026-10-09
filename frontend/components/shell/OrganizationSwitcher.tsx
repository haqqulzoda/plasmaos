'use client';

import { useEffect, useState } from 'react';
import { Building2 } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { api } from '@/lib/api';
import { readSelectedOrganization, validSelection, writeSelectedOrganization } from '@/lib/organizationSelection';
import type { OrganizationSummary } from '@/types/pursuit';

/**
 * R3 Task 6: for a user in several organizations, which organization's company profile,
 * matches, readiness and pursuits the workspace shows. Hidden for single-organization users.
 */
export function OrganizationSwitcher() {
    const t = useTranslations('navigation');
    const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
    const [selected, setSelected] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        api.get<OrganizationSummary[]>('/organizations')
            .then(({ data }) => {
                if (cancelled) return;
                const active = data.filter((item) => item.membership_state === 'ACTIVE');
                setOrganizations(active);
                const stored = readSelectedOrganization();
                const valid = validSelection(active, stored);
                if (stored && !valid) writeSelectedOrganization(null);  // revoked or left
                setSelected(valid ?? active[0]?.organization_id ?? null);
            })
            .catch(() => { /* the default organization applies */ });
        return () => { cancelled = true; };
    }, []);

    if (organizations.length < 2) return null;
    return <label className="shell-organization-switcher" data-organization-switcher>
        <Building2 aria-hidden />
        <span className="sr-only">{t('organization')}</span>
        <select className="ds-control" value={selected ?? ''} aria-label={t('organization')}
            onChange={(event) => {
                writeSelectedOrganization(event.target.value);
                // Every page re-reads its data for the chosen organization.
                window.location.reload();
            }}>
            {organizations.map((item) => <option key={item.organization_id} value={item.organization_id}>
                {item.display_name || item.organization_id.slice(0, 8)}
            </option>)}
        </select>
    </label>;
}
