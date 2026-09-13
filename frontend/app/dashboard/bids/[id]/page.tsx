'use client';

import { use, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { api } from '@/lib/api';
import { Alert } from '@/components/ui/Feedback';

export default function LegacyBidDetailRedirect({ params }: { params: Promise<{ id: string }> }) {
    const t = useTranslations('bidPreparation');
    const { id } = use(params);
    const router = useRouter();
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;
        api.get(`/proposals/${id}`)
            .then(() => {
                if (active) router.replace(`/dashboard/bid-preparation/${id}`);
            })
            .catch(() => {
                if (active) setError(t('legacyInvalid'));
            });
        return () => { active = false; };
    }, [id, router, t]);

    if (!error) {
        return <div role="status" className="customer-page proposal-state"><Loader2 className="ds-spin" aria-hidden />{t('legacyOpening')}</div>;
    }
    return (
        <div className="customer-page ds-container-content ds-stack">
            <Alert tone="warning" title={error} />
            <Link href="/dashboard/bid-preparation" className="ds-button ds-button-secondary">{t('legacyList')}</Link>
        </div>
    );
}
