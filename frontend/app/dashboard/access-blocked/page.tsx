'use client';

import { useEffect, useState } from 'react';
import { Ban, LogOut } from 'lucide-react';
import { signOut } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/Button';

export default function AccessBlockedPage() {
    const t = useTranslations('auth');
    const [state, setState] = useState<'rejected' | 'disabled'>('rejected');
    const [reason, setReason] = useState<string | null>(null);
    const title = state === 'disabled' ? t('disabledTitle') : t('blockedTitle');
    const message = state === 'disabled'
        ? t('disabledHelp')
        : t('blockedHelp');

    useEffect(() => {
        api.get<{
            state: string;
            rejection_or_disabled_reason: string | null;
        }>('/users/me/access-status')
            .then(({ data }) => {
                setState(data.state === 'disabled' ? 'disabled' : 'rejected');
                setReason(data.rejection_or_disabled_reason);
            })
            .catch(() => undefined);
    }, []);

    const handleLogout = async () => {
        await api.post('/auth/logout').catch(() => undefined);
        await signOut({ callbackUrl: '/' });
    };

    return (
        <div className="customer-page customer-state-page">
            <section className="ds-surface customer-state-card customer-state-copy">
                <div className="customer-state-icon ds-tone-danger">
                    <Ban aria-hidden />
                </div>
                <div>
                    <h1>{title}</h1>
                    <p className="ds-muted">{message}</p>
                    {reason && <p className="ds-muted bidi-auto">{t('reason', {reason})}</p>}
                </div>
                <Button
                    variant="secondary"
                    onClick={handleLogout}
                    leadingIcon={<LogOut aria-hidden />}
                >
                    {t('logout')}
                </Button>
            </section>
        </div>
    );
}
