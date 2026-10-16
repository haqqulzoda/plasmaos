'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** P1: waiting for approval is gone; an organization without a pilot explores (old links land there). */
export default function PendingApprovalPage() {
    const router = useRouter();
    useEffect(() => {
        router.replace('/dashboard/explore');
    }, [router]);
    return null;
}
