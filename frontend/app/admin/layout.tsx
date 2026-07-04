'use client';

import { ReactNode, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { CheckCircle2, LayoutDashboard, Loader2, LogOut, ShieldCheck, Sparkles } from 'lucide-react';
import { clsx } from 'clsx';
import { signOut, useSession } from 'next-auth/react';
import { api } from '@/lib/api';

interface AdminNavItem {
    name: string;
    href: string;
    icon: ReactNode;
}

const adminNavItems: AdminNavItem[] = [
    { name: 'Overview', href: '/admin', icon: <LayoutDashboard className="w-5 h-5" /> },
    { name: 'Approvals', href: '/admin/approvals', icon: <CheckCircle2 className="w-5 h-5" /> },
];

const isAdminActive = (pathname: string, href: string) =>
    pathname === href || (href !== '/admin' && pathname.startsWith(`${href}/`));

const isBlockedStatus = (status?: string | null) =>
    status === 'rejected' || status === 'disabled';

export default function AdminLayout({ children }: { children: ReactNode }) {
    const pathname = usePathname();
    const router = useRouter();
    const { data: session, status } = useSession();
    const role = session?.platform_role;
    const isOperatorOrAdmin =
        session?.is_admin === true ||
        role === 'admin' ||
        role === 'operator';
    const canAccessAdmin =
        status === 'authenticated' &&
        isOperatorOrAdmin &&
        session?.approval_status === 'approved';

    const handleLogout = async () => {
        await api.post('/auth/logout').catch(() => undefined);
        await signOut({ callbackUrl: '/' });
        router.push('/');
    };

    useEffect(() => {
        if (status === 'loading') {
            return;
        }

        if (status === 'unauthenticated') {
            router.replace('/');
            return;
        }

        if (canAccessAdmin) {
            return;
        }

        if (isBlockedStatus(session?.approval_status)) {
            router.replace('/dashboard/access-blocked');
            return;
        }

        if (session?.approval_status !== 'approved') {
            router.replace('/dashboard/pending-approval');
            return;
        }

        router.replace('/dashboard');
    }, [
        pathname,
        router,
        canAccessAdmin,
        session?.approval_status,
        status,
    ]);

    if (status === 'loading' || !canAccessAdmin) {
        return (
            <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
                <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
            </div>
        );
    }

    return (
        <div className="flex h-screen bg-gray-900 text-white">
            <aside className="w-64 bg-gray-950 border-r border-cyan-500/20 flex flex-col">
                <div className="p-6 border-b border-gray-800">
                    <Link href="/admin" className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-cyan-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                            <ShieldCheck className="w-5 h-5 text-white" />
                        </div>
                        <div>
                            <span className="block text-lg font-bold text-white tracking-tight">Admin Console</span>
                            <span className="block text-xs text-gray-500">Plasma AI</span>
                        </div>
                    </Link>
                </div>

                <nav className="flex-1 p-4 space-y-1">
                    {adminNavItems.map((item) => {
                        const isActive = isAdminActive(pathname, item.href);
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={clsx(
                                    'flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200',
                                    isActive
                                        ? 'bg-cyan-500/10 text-cyan-300 border-l-2 border-cyan-400'
                                        : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
                                )}
                            >
                                {item.icon}
                                <span className="font-medium">{item.name}</span>
                            </Link>
                        );
                    })}
                </nav>

                <div className="p-4 border-t border-gray-800 space-y-2">
                    <Link
                        href="/dashboard"
                        className="flex items-center gap-3 px-4 py-3 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-all duration-200"
                    >
                        <Sparkles className="w-5 h-5" />
                        <span className="font-medium">User dashboard</span>
                    </Link>
                    <button
                        onClick={handleLogout}
                        className="flex items-center gap-3 px-4 py-3 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800/50 transition-all duration-200 w-full"
                    >
                        <LogOut className="w-5 h-5" />
                        <span className="font-medium">Logout</span>
                    </button>
                </div>
            </aside>

            <div className="flex-1 flex flex-col overflow-hidden">
                <header className="h-16 border-b border-gray-800 bg-gray-950/50 backdrop-blur-sm flex items-center justify-between px-8 shrink-0">
                    <div>
                        <h2 className="text-sm font-medium text-gray-400 tracking-wide uppercase">Admin Console</h2>
                        <p className="text-xs text-gray-600">Operator workspace</p>
                    </div>
                    <Link
                        href="/dashboard"
                        className="inline-flex items-center justify-center rounded-lg border border-gray-700 px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white transition-colors"
                    >
                        User dashboard
                    </Link>
                </header>

                <main className="flex-1 overflow-auto">
                    <div className="p-8">
                        {children}
                    </div>
                </main>
            </div>
        </div>
    );
}
