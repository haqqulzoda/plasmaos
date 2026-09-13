'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Building2, CheckCircle2, Clock3, LogOut, RefreshCw } from 'lucide-react';
import { signOut, useSession } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { api, setApiAccessToken } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Feedback';

type AccessStatus = {
    user_approval_status: string;
    company_approval_status: string | null;
    onboarding_completed: boolean;
    access_allowed: boolean;
    state: string;
    company_name: string | null;
};

export default function PendingApprovalPage() {
    const t = useTranslations('auth');
    const router = useRouter();
    const { update } = useSession();
    const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [access, setAccess] = useState<AccessStatus | null>(null);
    const [checking, setChecking] = useState(false);
    const [approved, setApproved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const refreshStatus = useCallback(async () => {
        setChecking(true);
        setError(null);
        try {
            const response = await api.get<AccessStatus>('/users/me/access-status');
            setAccess(response.data);

            if (response.data.state === 'rejected' || response.data.state === 'disabled') {
                router.replace('/dashboard/access-blocked');
                return;
            }
            if (!response.data.onboarding_completed) {
                router.replace('/dashboard/onboarding');
                return;
            }
            if (response.data.access_allowed) {
                setApproved(true);
                const refreshedSession = await update();
                setApiAccessToken(refreshedSession?.accessToken ?? null);
                redirectTimer.current = setTimeout(() => {
                    router.replace('/dashboard');
                }, 900);
            }
        } catch {
            setError(t('refreshFailed'));
        } finally {
            setChecking(false);
        }
    }, [router, t, update]);

    const statusLabel = (value: string | null) => {
        if (value === 'approved') return t('approved');
        if (value === 'pending') return t('pending');
        if (value === 'rejected') return t('rejected');
        if (value === 'disabled') return t('disabled');
        return t('notSubmitted');
    };

    useEffect(() => {
        void refreshStatus();
        return () => {
            if (redirectTimer.current) clearTimeout(redirectTimer.current);
        };
    }, [refreshStatus]);

    const handleLogout = async () => {
        await api.post('/auth/logout').catch(() => undefined);
        await signOut({ callbackUrl: '/' });
    };

    return (
        <div className="customer-page customer-state-page">
            <section className="ds-surface customer-state-card">
                {approved ? (
                    <div className="customer-state-copy" role="status" aria-live="polite">
                        <div className="customer-state-icon ds-tone-success">
                            <CheckCircle2 aria-hidden />
                        </div>
                        <div>
                            <h1>{t('accessApproved')}</h1>
                            <p className="ds-muted">{t('redirecting')}</p>
                        </div>
                    </div>
                ) : (
                    <>
                        <div className="customer-state-copy">
                            <div className="customer-state-icon ds-tone-warning">
                                <Clock3 aria-hidden />
                            </div>
                            <div>
                                <span className="ds-eyebrow">{t('pending')}</span>
                                <h1>{t('accessPending')}</h1>
                                <p className="ds-muted">{t('pendingHelp')}</p>
                            </div>
                        </div>

                        <Alert tone="success" title={t('profileSubmitted')}><Building2 aria-hidden />{t('approvedHelp')}</Alert>

                        <dl className="customer-state-facts">
                            <div className="ds-surface-subtle">
                                <dt className="ds-muted">{t('userApproval')}</dt>
                                <dd>
                                    {statusLabel(access?.user_approval_status ?? 'pending')}
                                </dd>
                            </div>
                            <div className="ds-surface-subtle">
                                <dt className="ds-muted">{t('companyApproval')}</dt>
                                <dd>
                                    {statusLabel(access?.company_approval_status ?? 'pending')}
                                </dd>
                            </div>
                        </dl>

                        <div className="customer-state-guidance ds-muted">
                            <p>{t('nextReview')}</p>
                            <p>{t('nextSignin')}</p>
                            <p>{t('help')}</p>
                        </div>

                        {error && <Alert tone="danger" title={error} />}

                        <div className="ds-row customer-state-actions">
                            <Button
                                onClick={() => void refreshStatus()}
                                loading={checking}
                                leadingIcon={<RefreshCw aria-hidden />}
                            >
                                {t('refreshStatus')}
                            </Button>
                            <Button
                                variant="secondary"
                                onClick={handleLogout}
                                leadingIcon={<LogOut aria-hidden />}
                            >
                                {t('logout')}
                            </Button>
                        </div>
                    </>
                )}
            </section>
        </div>
    );
}
