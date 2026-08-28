'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Building2, CheckCircle2, Clock3, Loader2, LogOut, RefreshCw } from 'lucide-react';
import { signOut, useSession } from 'next-auth/react';
import { api, setApiAccessToken } from '@/lib/api';

type AccessStatus = {
    user_approval_status: string;
    company_approval_status: string | null;
    onboarding_completed: boolean;
    access_allowed: boolean;
    state: string;
    company_name: string | null;
};

const statusLabel = (status: string | null) => {
    if (!status) return 'Not submitted';
    return status.charAt(0).toUpperCase() + status.slice(1);
};

export default function PendingApprovalPage() {
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
            setError('Approval status could not be refreshed. Please try again.');
        } finally {
            setChecking(false);
        }
    }, [router, update]);

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
        <div className="min-h-[60vh] flex items-center justify-center">
            <section className="w-full max-w-xl border border-gray-800 bg-gray-950 rounded-lg p-8 space-y-6">
                {approved ? (
                    <div className="text-center space-y-4">
                        <div className="mx-auto w-12 h-12 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                            <CheckCircle2 className="w-6 h-6 text-emerald-300" />
                        </div>
                        <div>
                            <h1 className="text-2xl font-semibold text-white">Access approved</h1>
                            <p className="mt-2 text-gray-300">Your workspace is ready. Redirecting to dashboard...</p>
                        </div>
                    </div>
                ) : (
                    <>
                        <div className="text-center space-y-4">
                            <div className="mx-auto w-12 h-12 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                                <Clock3 className="w-6 h-6 text-amber-300" />
                            </div>
                            <div className="space-y-2">
                                <h1 className="text-2xl font-semibold text-white">Access pending</h1>
                                <p className="text-gray-300 leading-6">
                                    Your company profile has been submitted and is waiting for review.
                                    You do not need to submit the form again.
                                </p>
                            </div>
                        </div>

                        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3">
                            <div className="flex items-center gap-2 text-emerald-200 font-medium">
                                <Building2 className="w-4 h-4" />
                                Company profile submitted
                            </div>
                            <p className="mt-1 text-sm text-emerald-100/70">
                                Once approved, you will get access to Tender Explorer, compliance analysis, and reports.
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-3 text-sm">
                            <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
                                <p className="text-gray-500">User approval</p>
                                <p className="mt-1 font-medium text-gray-200">
                                    {statusLabel(access?.user_approval_status ?? 'pending')}
                                </p>
                            </div>
                            <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
                                <p className="text-gray-500">Company approval</p>
                                <p className="mt-1 font-medium text-gray-200">
                                    {statusLabel(access?.company_approval_status ?? 'pending')}
                                </p>
                            </div>
                        </div>

                        <div className="text-sm text-gray-400 space-y-1">
                            <p>What happens next: Plasma reviews your user and company profile.</p>
                            <p>If your access changes, sign in again so your browser receives current authority.</p>
                            <p>Need help? Contact Plasma support through your pilot coordinator.</p>
                        </div>

                        {error && (
                            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                                {error}
                            </div>
                        )}

                        <div className="flex flex-wrap justify-center gap-3">
                            <button
                                type="button"
                                onClick={() => void refreshStatus()}
                                disabled={checking}
                                className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500 disabled:opacity-60"
                            >
                                {checking ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                    <RefreshCw className="w-4 h-4" />
                                )}
                                Refresh approval status
                            </button>
                            <button
                                type="button"
                                onClick={handleLogout}
                                className="inline-flex items-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white transition-colors"
                            >
                                <LogOut className="w-4 h-4" />
                                Logout
                            </button>
                        </div>
                    </>
                )}
            </section>
        </div>
    );
}
