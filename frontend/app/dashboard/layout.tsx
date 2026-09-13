'use client';

import { ReactNode, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { PlasmaLogo } from '@/components/brand/PlasmaLogo';
import { CustomerShell } from '@/components/shell/CustomerShell';
import { signOut, useSession } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { api, setApiAccessToken } from '@/lib/api';
import {
    clearSourceRefreshSession,
    GlobalRefreshIndicator,
    SourceRefreshProvider,
} from '@/components/source-refresh/SourceRefreshProvider';
import { NotificationBell, NotificationProvider } from '@/components/notifications/NotificationProvider';

export type AccessStatus = {
    company_profile_id?: string | null;
    company_name?: string | null;
    onboarding_required?: boolean;
    onboarding_completed: boolean;
    user_approval_status: string;
    company_approval_status?: string | null;
    platform_role: string;
    access_allowed: boolean;
    state: string;
    rejection_or_disabled_reason?: string | null;
};

const CONTROL_PATHS = new Set([
    '/dashboard/onboarding',
    '/dashboard/pending-approval',
    '/dashboard/access-blocked',
]);

export default function DashboardLayout({ children }: { children: ReactNode }) {
    const common = useTranslations('common');
    const [companyName, setCompanyName] = useState<string | null>(null);
    const [accessError, setAccessError] = useState(false);
    const [retryVersion, setRetryVersion] = useState(0);
    const pathname = usePathname();
    const router = useRouter();
    const { data: session, status, update } = useSession();
    const [accessReadyPath, setAccessReadyPath] = useState<string | null>(null);
    const [workspaceAccessAllowed, setWorkspaceAccessAllowed] = useState<boolean | null>(null);

    const handleLogout = async () => {
        clearSourceRefreshSession();
        await api.post('/auth/logout').catch(() => undefined);
        await signOut({ callbackUrl: '/' });
        router.push('/');
    };

    useEffect(() => {
        let cancelled = false;

        const evaluateAccess = async () => {
            if (status === 'loading') {
                return;
            }

            if (status === 'unauthenticated') {
                router.replace('/');
                return;
            }

            try {
                const response = await api.get<AccessStatus>('/users/me/access-status');
                const access = response.data;
                if (!cancelled) setCompanyName(access.company_name ?? null);
                if (!cancelled) setAccessError(false);

                if (access.state === 'rejected' || access.state === 'disabled') {
                    if (!cancelled) setWorkspaceAccessAllowed(false);
                    if (pathname !== '/dashboard/access-blocked') {
                        router.replace('/dashboard/access-blocked');
                        return;
                    }
                    if (!cancelled) setAccessReadyPath(pathname);
                    return;
                }

                if (!access.onboarding_completed || access.onboarding_required) {
                    if (!cancelled) setWorkspaceAccessAllowed(false);
                    if (pathname !== '/dashboard/onboarding') {
                        router.replace('/dashboard/onboarding');
                        return;
                    }
                    if (!cancelled) setAccessReadyPath(pathname);
                    return;
                }

                if (access.access_allowed) {
                    if (!cancelled) setWorkspaceAccessAllowed(true);
                    if (CONTROL_PATHS.has(pathname)) {
                        const refreshedSession = await update();
                        setApiAccessToken(refreshedSession?.accessToken ?? null);
                        router.replace('/dashboard');
                        return;
                    }
                    if (!cancelled) setAccessReadyPath(pathname);
                    return;
                }

                if (pathname !== '/dashboard/pending-approval') {
                    if (!cancelled) setWorkspaceAccessAllowed(false);
                    router.replace('/dashboard/pending-approval');
                    return;
                }
                if (!cancelled) setWorkspaceAccessAllowed(false);
                if (!cancelled) setAccessReadyPath(pathname);
            } catch {
                if (!cancelled) setAccessError(true);
            }
        };

        evaluateAccess();

        return () => {
            cancelled = true;
        };
    }, [
        pathname,
        retryVersion,
        router,
        status,
        update,
    ]);

    if (accessError) {
        return <div role="alert" className="ds-theme shell-state">
            <p>{common('states.unavailable')}</p>
            <Button variant="secondary" onClick={() => {setAccessError(false); setRetryVersion(value => value + 1);}}>{common('actions.retry')}</Button>
        </div>;
    }

    if (status === 'loading' || (accessReadyPath !== pathname && workspaceAccessAllowed !== true)) {
        return (
            <div className="ds-theme shell-state" role="status">
                <PlasmaLogo /><Loader2 className="ds-spin" aria-hidden /><span>{common('states.loading')}</span>
            </div>
        );
    }

    const role = session?.platform_role;
    const isOperatorOrAdmin =
        session?.is_admin === true ||
        role === 'admin' ||
        role === 'operator';


    const dashboardShell = workspaceAccessAllowed ? (
        <NotificationProvider>
            <CustomerShell name={session?.user?.name} email={session?.user?.email}
                company={companyName} canAdmin={isOperatorOrAdmin} onLogout={handleLogout}
                refresh={<GlobalRefreshIndicator />} notifications={<NotificationBell />}>
                {children}
            </CustomerShell>
        </NotificationProvider>
    ) : (
        <CustomerShell name={session?.user?.name} email={session?.user?.email}
            company={companyName} canAdmin={isOperatorOrAdmin} onLogout={handleLogout}>
            {children}
        </CustomerShell>
    );

    return workspaceAccessAllowed
        ? <SourceRefreshProvider enabled>{dashboardShell}</SourceRefreshProvider>
        : dashboardShell;
}
