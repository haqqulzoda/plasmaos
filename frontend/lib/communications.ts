export const NOTIFICATION_CATEGORIES = ['SYSTEM', 'TENDER_ALERT', 'ADMIN'] as const;
export type NotificationCategory = (typeof NOTIFICATION_CATEGORIES)[number];

export type NotificationItem = {
  id: string;
  event_id: string;
  category: NotificationCategory;
  event_type: string;
  template_key: string | null;
  payload: Record<string, unknown>;
  subject: string | null;
  body: string | null;
  message_type: 'ANNOUNCEMENT' | 'SYSTEM_ALERT' | null;
  content_format: 'plain_text';
  is_test: boolean;
  created_at: string;
  read_at: string | null;
  is_read: boolean;
};

export type NotificationPage = {
  items: NotificationItem[];
  next_cursor: string | null;
};

export type NotificationDestination = {
  href: string;
  labelKey: 'openTender' | 'openCompliance' | 'openDashboard';
};

const uuid = (value: unknown): value is string =>
  typeof value === 'string' &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

/** The only authority for notification navigation. Payload URLs are never read. */
export function notificationDestination(item: NotificationItem): NotificationDestination | null {
  if (item.event_type === 'RECOMMENDATION_CREATED' && uuid(item.payload.tender_id)) {
    return {
      href: `/dashboard/tenders/${encodeURIComponent(item.payload.tender_id)}`,
      labelKey: 'openTender',
    };
  }
  if (
    ['DOCUMENTS_READY', 'DOCUMENTS_PARTIAL', 'DOCUMENTS_FAILED'].includes(item.event_type) &&
    uuid(item.payload.tender_id)
  ) {
    return {
      href: `/dashboard/tenders/${encodeURIComponent(item.payload.tender_id)}#requirements-documents`,
      labelKey: 'openTender',
    };
  }
  if (item.event_type === 'ANALYSIS_COMPLETED' && uuid(item.payload.analysis_id)) {
    // The approved backend contract does not carry tender_id for analysis events.
    // Compliance can safely resolve the user's current version context.
    return { href: '/dashboard/my-tenders', labelKey: 'openCompliance' };
  }
  if (item.event_type === 'ACCOUNT_APPROVED') {
    return { href: '/dashboard', labelKey: 'openDashboard' };
  }
  return null;
}

export const SYSTEM_TEMPLATE_KEYS = {
  'notifications.recommendation_created': 'recommendationCreated',
  'notifications.analysis_completed': 'analysisCompleted',
  'notifications.account_approved': 'accountApproved',
  'notifications.documents_ready': 'documentsReady',
  'notifications.documents_partial': 'documentsPartial',
  'notifications.documents_failed': 'documentsFailed',
} as const;

export type SystemTemplateKey = keyof typeof SYSTEM_TEMPLATE_KEYS;

export function knownSystemTemplate(value: string | null): value is SystemTemplateKey {
  return value !== null && Object.hasOwn(SYSTEM_TEMPLATE_KEYS, value);
}

export const notificationQuery = (
  filter: 'ALL' | 'UNREAD' | NotificationCategory,
  cursor?: string | null,
) => ({
  limit: 25,
  cursor: cursor || undefined,
  unread: filter === 'UNREAD' ? true : undefined,
  category: NOTIFICATION_CATEGORIES.includes(filter as NotificationCategory)
    ? filter
    : undefined,
});

export type BroadcastStatus = 'DRAFT' | 'QUEUED' | 'SENDING' | 'SENT' | 'PARTIAL' | 'FAILED';
export type BroadcastMessageType = 'ANNOUNCEMENT' | 'SYSTEM_ALERT';
export type BroadcastAudience = 'ALL_ELIGIBLE_USERS' | 'SELECTED_USERS';

export type BroadcastSummary = {
  id: string;
  subject: string;
  message_type: BroadcastMessageType;
  audience_mode: BroadcastAudience;
  status: BroadcastStatus;
  recipient_count: number;
  delivered_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
};

export type BroadcastDetail = BroadcastSummary & {
  body: string;
  content_format: 'plain_text';
  selected_user_count: number;
  last_error_code: string | null;
  queued_at: string | null;
  completed_at: string | null;
};

export type BroadcastPage = { items: BroadcastSummary[]; next_cursor: string | null };

export const terminalBroadcast = (status: BroadcastStatus) =>
  status === 'SENT' || status === 'PARTIAL' || status === 'FAILED';

export const mutableBroadcast = (status?: BroadcastStatus) => !status || status === 'DRAFT';

type CommunicationsApiError = { response?: { status?: number; data?: { detail?: { code?: string } } } };

export function communicationsError(error: unknown): string {
  const candidate = error as CommunicationsApiError;
  const code = candidate.response?.data?.detail?.code;
  if (candidate.response?.status === 401) return 'Your session is no longer valid. Sign in again.';
  if (candidate.response?.status === 403) return 'Current administrator authority is required.';
  if (code === 'broadcast_immutable') return 'This broadcast is already queued or sent and cannot be edited.';
  if (code === 'broadcast_empty_audience') return 'No eligible recipients are in this audience.';
  if (code === 'broadcast_test_rate_limited') return 'The test-send limit has been reached. Try again later.';
  if (code === 'communications_invalid_audience') return 'Review the selected audience and try again.';
  if (code === 'communications_unavailable') return 'Communications are temporarily unavailable. Try again.';
  return 'The request could not be completed. No unconfirmed change is shown.';
}
