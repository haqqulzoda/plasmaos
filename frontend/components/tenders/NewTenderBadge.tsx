'use client';

import type { ServerClockReference } from '@/lib/tenderNewness';
import { shouldShowNewBadge } from '@/lib/tenderNewness';

export function NewTenderBadge({
    isNew,
    newUntil,
    clock,
    monotonicNow,
}: {
    isNew: boolean;
    newUntil: string;
    clock: ServerClockReference | null;
    monotonicNow: number;
}) {
    if (!shouldShowNewBadge(isNew, newUntil, clock, monotonicNow)) return null;
    return <span title="Recently discovered by Plasma" aria-label="New Tender, recently discovered by Plasma" className="inline-flex rounded-md border border-cyan-400/35 bg-cyan-400/10 px-2 py-1 text-[11px] font-semibold text-cyan-200">New</span>;
}
