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

const eventLine = (event: SourceRefreshActivityEvent, translate?: RefreshPresentationTranslator): string => {
    if (translate) {
        const values = {source: event.source_display_name, count: event.created_count};
        if (event.status === 'source_unavailable') return translate('eventUnavailable', values);
        if (event.status === 'failed') return translate('eventFailed', values);
        if (event.status === 'partial') return translate('eventPartial', values);
        if (event.degraded || event.fallback_used) return translate('eventLimited', values);
        return translate('eventComplete', values);
    }
    if (event.status === 'source_unavailable') return `${event.source_display_name}: source unavailable`;
    if (event.status === 'failed') return `${event.source_display_name}: refresh failed`;
    if (event.status === 'partial') return `${event.source_display_name}: ${countCopy(event.created_count)}, with issues`;
    if (event.degraded || event.fallback_used) return `${event.source_display_name}: ${countCopy(event.created_count)}, limited coverage`;
    return `${event.source_display_name}: ${countCopy(event.created_count)}`;
};

export type RefreshPresentationTranslator = (
    key: 'complete' | 'completeFromSource' | 'sourceUnavailable' | 'failed' | 'partial'
        | 'limited' | 'zeroNew' | 'aggregated' | 'sourcesCompleted' | 'someIssues'
        | 'eventUnavailable' | 'eventFailed' | 'eventPartial' | 'eventLimited'
        | 'eventComplete' | 'viewNew',
    values?: Readonly<Record<string, string | number>>,
) => string;

export function notificationForEvents(
    events: SourceRefreshActivityEvent[],
    id: string,
    translate?: RefreshPresentationTranslator,
): RefreshNotice {
    if (events.length === 1) {
        const event = events[0];
        if (event.status === 'source_unavailable') {
            return { id, title: translate ? translate('sourceUnavailable', {source: event.source_display_name}) : `${event.source_display_name} could not be refreshed`, detail: null, tone: 'danger', href: null, action_label: null };
        }
        if (event.status === 'failed') {
            return { id, title: translate ? translate('failed', {source: event.source_display_name}) : `${event.source_display_name} refresh failed`, detail: null, tone: 'danger', href: null, action_label: null };
        }
        if (event.status === 'partial') {
            return { id, title: translate ? translate('partial', {source: event.source_display_name, count: event.created_count}) : `${event.source_display_name} refresh completed with issues — ${countCopy(event.created_count)}`, detail: null, tone: 'warning', href: sourceActivityHref(event), action_label: event.created_count > 0 ? (translate ? translate('viewNew') : 'View new tenders') : null };
        }
        if (event.degraded || event.fallback_used) {
            return { id, title: translate ? translate('limited', {source: event.source_display_name}) : `${event.source_display_name} refresh completed with limited source coverage`, detail: translate ? translate('eventComplete', {source: event.source_display_name, count: event.created_count}) : countCopy(event.created_count), tone: 'warning', href: sourceActivityHref(event), action_label: event.created_count > 0 ? (translate ? translate('viewNew') : 'View new tenders') : null };
        }
        if (translate && event.status === 'completed' && !event.degraded && !event.fallback_used) {
            return {
                id,
                title: translate('completeFromSource', {
                    count: event.created_count,
                    source: event.source_display_name,
                }),
                detail: event.created_count > 0 ? translate('complete') : null,
                tone: 'success',
                href: sourceActivityHref(event),
                action_label: event.created_count > 0 ? translate('viewNew') : null,
            };
        }
        if (event.created_count === 0) {
            return { id, title: translate ? translate('zeroNew', {source: event.source_display_name}) : `${event.source_display_name} refresh complete — no new tenders`, detail: null, tone: 'success', href: null, action_label: null };
        }
        return { id, title: translate ? translate('completeFromSource', {count: event.created_count, source: event.source_display_name}) : `${countCopy(event.created_count)} from ${event.source_display_name}`, detail: translate ? translate('complete') : 'Refresh complete', tone: 'success', href: sourceActivityHref(event), action_label: translate ? translate('viewNew') : 'View new tenders' };
    }

    const total = events.reduce((sum, event) => sum + (event.counts_authoritative ? event.created_count : 0), 0);
    const hasIssues = events.some((event) => event.status !== 'completed' || event.degraded || event.fallback_used);
    return {
        id,
        title: total > 0
            ? (translate ? translate('aggregated', {count: total, sourceCount: events.length}) : `${countCopy(total)} across ${events.length} sources`)
            : (translate ? translate('sourcesCompleted', {sourceCount: events.length}) : `${events.length} source refreshes completed`),
        detail: `${events.map((event) => eventLine(event, translate)).join(' · ')}${hasIssues ? ` · ${translate ? translate('someIssues') : 'Some sources completed with issues.'}` : ''}`,
        tone: hasIssues ? 'warning' : 'success',
        href: total > 0 ? '/dashboard/tenders?view=all&new_only=true' : null,
        action_label: total > 0 ? (translate ? translate('viewNew') : 'View new tenders') : null,
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
