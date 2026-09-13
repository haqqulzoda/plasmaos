'use client';

import { ReactNode, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { PlasmaLogo } from '@/components/brand/PlasmaLogo';
import { AdminShell } from '@/components/shell/AdminShell';
import { signOut, useSession } from 'next-auth/react';
import { api } from '@/lib/api';

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
    const isEffectiveAdmin =
        canAccessAdmin &&
        (session?.is_admin === true || role === 'admin');

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
            <div lang="en" dir="ltr" className="ds-theme ds-admin shell-state" role="status">
                <PlasmaLogo admin /><Loader2 className="ds-spin" aria-hidden /><span>Loading…</span>
            </div>
        );
    }

    return <div lang="en" dir="ltr" data-admin-ltr-island><AdminShell isEffectiveAdmin={isEffectiveAdmin} name={session?.user?.name}
        email={session?.user?.email} onLogout={handleLogout}>{children}</AdminShell></div>;
}
