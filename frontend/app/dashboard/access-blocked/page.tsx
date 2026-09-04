'use client';

import { useEffect, useState } from 'react';
import { Ban, LogOut } from 'lucide-react';
import { signOut } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { api } from '@/lib/api';

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
        <div className="min-h-[60vh] flex items-center justify-center">
            <section className="w-full max-w-xl border border-gray-800 bg-gray-950 rounded-lg p-8 text-center space-y-5">
                <div className="mx-auto w-12 h-12 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                    <Ban className="w-6 h-6 text-red-300" />
                </div>
                <div className="space-y-2">
                    <h1 className="text-2xl font-semibold text-white">{title}</h1>
                    <p className="text-gray-300 leading-6">{message}</p>
                    {reason && <p className="text-sm text-gray-500">{t('reason', {reason})}</p>}
                </div>
                <button
                    type="button"
                    onClick={handleLogout}
                    className="inline-flex items-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white transition-colors"
                >
                    <LogOut className="w-4 h-4" />
                    {t('logout')}
                </button>
            </section>
        </div>
    );
}
