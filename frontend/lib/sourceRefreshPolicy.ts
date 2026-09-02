import type {
    RefreshNotice,
    SourceRefreshActivityEvent,
} from '@/types/source-refresh';

export const ACTIVE_REFRESH_POLL_MS = 2_500;
export const INACTIVE_REFRESH_POLL_MS = 60_000;
export const ACTIVITY_DRAIN_PAGE_LIMIT = 10;
export const ACTIVITY_PAGE_SIZE = 25;
export const COMPLETION_GRACE_POLLS = 2;
export const NOTIFICATION_GROUP_MS = 500;
export const MAX_VISIBLE_NOTICES = 4;
export const MAX_SESSION_JOB_IDS = 256;
export const MAX_POLL_BACKOFF_MS = 30_000;

export const nextPollDelay = (activeCount: number, gracePolls: number, failureCount: number): number => {
    const base = activeCount > 0 || gracePolls > 0
        ? ACTIVE_REFRESH_POLL_MS
        : INACTIVE_REFRESH_POLL_MS;
    if (failureCount === 0) return base;
    return Math.min(MAX_POLL_BACKOFF_MS, base * (2 ** Math.min(failureCount, 4)));
};

export const sourceActivityHref = (event: SourceRefreshActivityEvent): string | null =>
    event.counts_authoritative && event.created_count > 0
        ? `/dashboard/tenders?view=all&source=${encodeURIComponent(event.source_system)}&new_only=true`
        : null;

const countCopy = (count: number): string => `${count} new tender${count === 1 ? '' : 's'}`;

const eventLine = (event: SourceRefreshActivityEvent): string => {
    if (event.status === 'source_unavailable') return `${event.source_display_name}: source unavailable`;
    if (event.status === 'failed') return `${event.source_display_name}: refresh failed`;
    if (event.status === 'partial') return `${event.source_display_name}: ${countCopy(event.created_count)}, with issues`;
    if (event.degraded || event.fallback_used) return `${event.source_display_name}: ${countCopy(event.created_count)}, limited coverage`;
    return `${event.source_display_name}: ${countCopy(event.created_count)}`;
};

export function notificationForEvents(events: SourceRefreshActivityEvent[], id: string): RefreshNotice {
    if (events.length === 1) {
        const event = events[0];
        if (event.status === 'source_unavailable') {
            return { id, title: `${event.source_display_name} could not be refreshed`, detail: event.terminal_reason || null, tone: 'danger', href: null, action_label: null };
        }
        if (event.status === 'failed') {
            return { id, title: `${event.source_display_name} refresh failed`, detail: event.terminal_reason || null, tone: 'danger', href: null, action_label: null };
        }
        if (event.status === 'partial') {
            return { id, title: `${event.source_display_name} refresh completed with issues — ${countCopy(event.created_count)}`, detail: event.terminal_reason || null, tone: 'warning', href: sourceActivityHref(event), action_label: event.created_count > 0 ? 'View new tenders' : null };
        }
        if (event.degraded || event.fallback_used) {
            return { id, title: `${event.source_display_name} refresh completed with limited source coverage`, detail: countCopy(event.created_count), tone: 'warning', href: sourceActivityHref(event), action_label: event.created_count > 0 ? 'View new tenders' : null };
        }
        if (event.created_count === 0) {
            return { id, title: `${event.source_display_name} refresh complete — no new tenders`, detail: null, tone: 'success', href: null, action_label: null };
        }
        return { id, title: `${countCopy(event.created_count)} from ${event.source_display_name}`, detail: 'Refresh complete', tone: 'success', href: sourceActivityHref(event), action_label: 'View new tenders' };
    }

    const total = events.reduce((sum, event) => sum + (event.counts_authoritative ? event.created_count : 0), 0);
    const hasIssues = events.some((event) => event.status !== 'completed' || event.degraded || event.fallback_used);
    return {
        id,
        title: total > 0
            ? `${countCopy(total)} across ${events.length} sources`
            : `${events.length} source refreshes completed`,
        detail: `${events.map(eventLine).join(' · ')}${hasIssues ? ' · Some sources completed with issues.' : ''}`,
        tone: hasIssues ? 'warning' : 'success',
        href: total > 0 ? '/dashboard/tenders?view=all&new_only=true' : null,
        action_label: total > 0 ? 'View new tenders' : null,
    };
}

export const activityEventsWithoutDuplicates = (
    events: SourceRefreshActivityEvent[],
    seenJobIds: Set<string>,
): SourceRefreshActivityEvent[] => events.filter((event) => {
    if (seenJobIds.has(event.job_id)) return false;
    seenJobIds.add(event.job_id);
    return true;
});
