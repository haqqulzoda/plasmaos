'use client';

import { use, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';

import { api } from '@/lib/api';

export default function LegacyBidDetailRedirect({ params }: { params: Promise<{ id: string }> }) {
    const { id } = use(params);
    const router = useRouter();
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;
        api.get(`/proposals/${id}`)
            .then(() => {
                if (active) router.replace(`/dashboard/bid-preparation/${id}`);
            })
            .catch(() => {
                if (active) setError('This legacy bookmark is not an owned Bid Preparation artifact.');
            });
        return () => { active = false; };
    }, [id, router]);

    if (!error) {
        return <div role="status" className="flex items-center gap-2 p-8 text-zinc-300"><Loader2 className="h-4 w-4 animate-spin" />Opening Bid Preparation…</div>;
    }
    return (
        <div className="space-y-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-6 text-amber-100">
            <p role="alert">{error}</p>
            <Link href="/dashboard/bid-preparation" className="text-sm font-semibold underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300">Open Bid Preparation list</Link>
        </div>
    );
}
