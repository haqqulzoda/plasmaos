'use client';

import { ReactNode, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
    Archive,
    Building2,
    LayoutDashboard,
    Radar,
    ScrollText,
    FileText,
    LogOut,
    Sparkles,
    Loader2,
    ShieldCheck,
} from 'lucide-react';
import { clsx } from 'clsx';
import { signOut, useSession } from 'next-auth/react';
import { api } from '@/lib/api';

interface NavItem {
    name: string;
    href: string;
    icon: ReactNode;
}

const baseNavItems: NavItem[] = [
    { name: 'Dashboard', href: '/dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { name: 'Tenders', href: '/dashboard/tenders', icon: <ScrollText className="w-5 h-5" /> },
    { name: 'Hunter Feed', href: '/dashboard/hunter', icon: <Radar className="w-5 h-5" /> },
    { name: 'My Bids', href: '/dashboard/bids', icon: <FileText className="w-5 h-5" /> },
    { name: 'Company Profile', href: '/dashboard/settings', icon: <Building2 className="w-5 h-5" /> },
    { name: 'Readiness Vault', href: '/dashboard/readiness-vault', icon: <Archive className="w-5 h-5" /> },
];

type CompanyProfileStatus = {
    company_profile_id?: string | null;
    onboarding_required?: boolean;
    approval_status?: string | null;
};

const CONTROL_PATHS = new Set([
    '/dashboard/onboarding',
    '/dashboard/pending-approval',
    '/dashboard/access-blocked',
]);

const isBlockedStatus = (status?: string | null) =>
    status === 'rejected' || status === 'disabled';

export default function DashboardLayout({ children }: { children: ReactNode }) {
    const pathname = usePathname();
    const router = useRouter();
    const { data: session, status } = useSession();
    const [accessReadyPath, setAccessReadyPath] = useState<string | null>(null);

    const handleLogout = async () => {
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

            const role = session?.platform_role;
            const approvalStatus = session?.approval_status;
            const isOperatorOrAdmin =
                session?.is_admin === true ||
                role === 'admin' ||
                role === 'operator';

            if (isOperatorOrAdmin) {
                if (CONTROL_PATHS.has(pathname)) {
                    router.replace('/dashboard');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
                return;
            }

            if (isBlockedStatus(approvalStatus)) {
                if (pathname !== '/dashboard/access-blocked') {
                    router.replace('/dashboard/access-blocked');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
                return;
            }

            const sessionCompanyId = session?.company_profile_id;
            const sessionCompanyStatus = session?.company_approval_status;

            if (!sessionCompanyId && approvalStatus !== 'approved') {
                if (pathname !== '/dashboard/onboarding') {
                    router.replace('/dashboard/onboarding');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
                return;
            }

            if (isBlockedStatus(sessionCompanyStatus)) {
                if (pathname !== '/dashboard/access-blocked') {
                    router.replace('/dashboard/access-blocked');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
                return;
            }

            if (sessionCompanyId && (approvalStatus !== 'approved' || sessionCompanyStatus !== 'approved')) {
                if (pathname !== '/dashboard/pending-approval') {
                    router.replace('/dashboard/pending-approval');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
                return;
            }

            try {
                const response = await api.get<CompanyProfileStatus>('/users/me/company');
                const company = response.data;
                const companyStatus = company.approval_status ?? session?.company_approval_status;
                const onboardingRequired =
                    company.onboarding_required === true || !company.company_profile_id;

                if (onboardingRequired) {
                    if (pathname !== '/dashboard/onboarding') {
                        router.replace('/dashboard/onboarding');
                        return;
                    }
                    if (!cancelled) setAccessReadyPath(pathname);
                    return;
                }

                if (isBlockedStatus(companyStatus)) {
                    if (pathname !== '/dashboard/access-blocked') {
                        router.replace('/dashboard/access-blocked');
                        return;
                    }
                    if (!cancelled) setAccessReadyPath(pathname);
                    return;
                }

                const approvedPilot =
                    approvalStatus === 'approved' && companyStatus === 'approved';

                if (approvedPilot) {
                    if (CONTROL_PATHS.has(pathname)) {
                        router.replace('/dashboard');
                        return;
                    }
                    if (!cancelled) setAccessReadyPath(pathname);
                    return;
                }

                if (pathname !== '/dashboard/pending-approval') {
                    router.replace('/dashboard/pending-approval');
                    return;
                }
                if (!cancelled) setAccessReadyPath(pathname);
            } catch (error) {
                console.error('Failed to evaluate company access:', error);
                if (pathname !== '/dashboard/onboarding') {
                    router.replace('/dashboard/onboarding');
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
        session?.approval_status,
        session?.company_profile_id,
        session?.company_approval_status,
        session?.is_admin,
        session?.platform_role,
        status,
    ]);

    if (status === 'loading' || accessReadyPath !== pathname) {
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

    return (
        <div className="flex h-screen bg-gray-900 text-white">
            {/* Sidebar */}
            <aside className="w-64 bg-gray-950 border-r border-gray-800 flex flex-col">
                {/* Logo */}
                <div className="p-6 border-b border-gray-800">
                    <Link href="/dashboard" className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                            <Sparkles className="w-5 h-5 text-white" />
                        </div>
                        <span className="text-xl font-bold text-white tracking-tight">Plasma AI</span>
                    </Link>
                </div>

                {/* Navigation */}
                <nav className="flex-1 p-4 space-y-1">
                    {navItems.map((item) => {
                        const isActive = pathname === item.href;
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={clsx(
                                    'flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200',
                                    isActive
                                        ? 'bg-indigo-900/20 text-indigo-400 border-l-2 border-indigo-500'
                                        : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
                                )}
                            >
                                {item.icon}
                                <span className="font-medium">{item.name}</span>
                            </Link>
                        );
                    })}
                </nav>

                {/* Logout */}
                <div className="p-4 border-t border-gray-800">
                    <button
                        onClick={handleLogout}
                        className="flex items-center gap-3 px-4 py-3 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800/50 transition-all duration-200 w-full"
                    >
                        <LogOut className="w-5 h-5" />
                        <span className="font-medium">Logout</span>
                    </button>
                </div>
            </aside>

            {/* Main Content */}
            <div className="flex-1 flex flex-col overflow-hidden">
                {/* Top Header */}
                <header className="h-16 border-b border-gray-800 bg-gray-950/50 backdrop-blur-sm flex items-center justify-between px-8 shrink-0">
                    <h2 className="text-sm font-medium text-gray-400 tracking-wide uppercase">Command Center</h2>
                    <div className="flex items-center gap-3">
                        {isOperatorOrAdmin && (
                            <Link
                                href="/admin"
                                className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/30 px-3 py-2 text-sm font-medium text-cyan-200 hover:bg-cyan-500/10 hover:text-cyan-100 transition-colors"
                            >
                                <ShieldCheck className="w-4 h-4" />
                                Admin Console
                            </Link>
                        )}
                        <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-3 py-1.5">
                            <div className="w-2 h-2 rounded-full animate-pulse bg-emerald-500" />
                            <span className="text-emerald-400 text-xs font-semibold tracking-wide">Agent Active</span>
                        </div>
                    </div>
                </header>

                {/* Page Content */}
                <main className="flex-1 overflow-auto">
                    <div className="p-8">
                        {children}
                    </div>
                </main>
            </div>
        </div>
    );
}
