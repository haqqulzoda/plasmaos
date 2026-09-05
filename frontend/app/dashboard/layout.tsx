'use client';

import { ReactNode, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
    Archive,
    Bookmark,
    Building2,
    LayoutDashboard,
    ScrollText,
    FileText,
    LogOut,
    Sparkles,
    Loader2,
    ShieldCheck,
} from 'lucide-react';
import { clsx } from 'clsx';
import { signOut, useSession } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { api, setApiAccessToken } from '@/lib/api';
import {
    clearSourceRefreshSession,
    GlobalRefreshIndicator,
    SourceRefreshProvider,
} from '@/components/source-refresh/SourceRefreshProvider';

interface NavItem {
    nameKey: 'dashboard' | 'tenders' | 'myTenders' | 'bidPreparation' | 'companyProfile' | 'readinessVault';
    href: string;
    icon: ReactNode;
}

const baseNavItems: NavItem[] = [
    { nameKey: 'dashboard', href: '/dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { nameKey: 'tenders', href: '/dashboard/tenders', icon: <ScrollText className="w-5 h-5" /> },
    { nameKey: 'myTenders', href: '/dashboard/my-tenders', icon: <Bookmark className="w-5 h-5" /> },
    { nameKey: 'bidPreparation', href: '/dashboard/bid-preparation', icon: <FileText className="w-5 h-5" /> },
    { nameKey: 'companyProfile', href: '/dashboard/settings', icon: <Building2 className="w-5 h-5" /> },
    { nameKey: 'readinessVault', href: '/dashboard/readiness-vault', icon: <Archive className="w-5 h-5" /> },
];

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
    const t = useTranslations('navigation');
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
            } catch (error) {
                console.error('Failed to evaluate workspace access:', error);
                if (!cancelled) setWorkspaceAccessAllowed(false);
                if (!CONTROL_PATHS.has(pathname)) {
                    router.replace('/dashboard/pending-approval');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
            }
        };

        evaluateAccess();

        return () => {
            cancelled = true;
        };
    }, [
        pathname,
        router,
        status,
        update,
    ]);

    if (status === 'loading' || (accessReadyPath !== pathname && workspaceAccessAllowed !== true)) {
        return (
            <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
                <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
            </div>
        );
    }

    const role = session?.platform_role;
    const isOperatorOrAdmin =
        session?.is_admin === true ||
        role === 'admin' ||
        role === 'operator';
    const navItems = baseNavItems;

    const dashboardShell = (
        <div className="flex h-screen bg-gray-900 text-white">
            {/* Sidebar */}
            <aside className="w-16 shrink-0 bg-gray-950 border-e border-gray-800 flex flex-col sm:w-64">
                {/* Logo */}
                <div className="border-b border-gray-800 p-3 sm:p-6">
                    <Link href="/dashboard" aria-label={t('dashboardLabel')} className="flex items-center justify-center gap-3 sm:justify-start">
                        <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                            <Sparkles className="w-5 h-5 text-white" />
                        </div>
                        <span className="hidden text-xl font-bold text-white tracking-tight sm:inline">Plasma AI</span>
                    </Link>
                </div>

                {/* Navigation */}
                <nav aria-label={t('navigationLabel')} className="flex-1 space-y-1 p-2 sm:p-4">
                    {navItems.map((item) => {
                        const isActive = pathname === item.href;
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                aria-label={t(item.nameKey)}
                                className={clsx(
                                    'flex items-center justify-center gap-3 rounded-lg px-2 py-3 transition-all duration-200 sm:justify-start sm:px-4',
                                    isActive
                                        ? 'bg-indigo-900/20 text-indigo-400 border-s-2 border-indigo-500'
                                        : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
                                )}
                            >
                                {item.icon}
                                <span className="hidden font-medium sm:inline">{t(item.nameKey)}</span>
                            </Link>
                        );
                    })}
                </nav>

                {/* Logout */}
                <div className="border-t border-gray-800 p-2 sm:p-4">
                    <button
                        onClick={handleLogout}
                        aria-label={t('logout')}
                        className="flex w-full items-center justify-center gap-3 rounded-lg px-2 py-3 text-gray-400 transition-all duration-200 hover:bg-gray-800/50 hover:text-red-400 sm:justify-start sm:px-4"
                    >
                        <LogOut className="w-5 h-5" />
                        <span className="hidden font-medium sm:inline">{t('logout')}</span>
                    </button>
                </div>
            </aside>

            {/* Main Content */}
            <div className="flex-1 flex flex-col overflow-hidden">
                {/* Top Header */}
                <header className="h-16 border-b border-gray-800 bg-gray-950/50 backdrop-blur-sm flex items-center justify-between px-3 shrink-0 sm:px-8">
                    <h2 className="text-sm font-medium text-gray-400 tracking-wide uppercase">{t('commandCenter')}</h2>
                    <div className="flex items-center gap-3">
                        {workspaceAccessAllowed ? <GlobalRefreshIndicator /> : null}
                        {isOperatorOrAdmin && (
                            <Link
                                href="/admin"
                                className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/30 px-3 py-2 text-sm font-medium text-cyan-200 hover:bg-cyan-500/10 hover:text-cyan-100 transition-colors"
                            >
                                <ShieldCheck className="w-4 h-4" />
                                {t('adminConsole')}
                            </Link>
                        )}
                      
                    </div>
                </header>

                {/* Page Content */}
                <main className="flex-1 overflow-auto">
                    <div className="p-3 sm:p-8">
                        {children}
                    </div>
                </main>
            </div>
        </div>
    );

    return workspaceAccessAllowed
        ? <SourceRefreshProvider enabled>{dashboardShell}</SourceRefreshProvider>
        : dashboardShell;
}
