'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Bell, CheckCheck, ChevronDown, Circle, Inbox, RefreshCw } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { AxiosError } from 'axios';
import { api } from '@/lib/api';
import { Alert } from '@/components/ui/Feedback';
import { Button } from '@/components/ui/Button';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { useNotifications } from '@/components/notifications/NotificationProvider';
import {
  SYSTEM_TEMPLATE_KEYS,
  knownSystemTemplate,
  notificationDestination,
  notificationQuery,
  type NotificationCategory,
  type NotificationItem,
  type NotificationPage,
} from '@/lib/communications';

type Filter = 'ALL' | 'UNREAD' | NotificationCategory;
const FILTERS: Filter[] = ['ALL', 'UNREAD', 'SYSTEM', 'TENDER_ALERT', 'ADMIN'];

export default function NotificationsPage() {
  const t = useTranslations('notifications');
  const locale = useLocale();
  const { unreadCount, refreshUnreadCount, adjustUnreadCount } = useNotifications();
  const [filter, setFilter] = useState<Filter>('ALL');
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [mutating, setMutating] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const load = useCallback(async (append = false, cursor?: string | null) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError(null);
    try {
      const response = await api.get<NotificationPage>('/notifications', {
        params: notificationQuery(filter, cursor),
      });
      setItems((current) => (append ? [...current, ...response.data.items] : response.data.items));
      setNextCursor(response.data.next_cursor);
    } catch {
      setError(t('states.failure'));
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const setRead = async (item: NotificationItem, isRead: boolean) => {
    if (mutating.has(item.id)) return;
    setMutating((current) => new Set(current).add(item.id));
    setError(null);
    setFeedback(null);
    setItems((current) => current.map((candidate) =>
      candidate.id === item.id
        ? { ...candidate, is_read: isRead, read_at: isRead ? new Date().toISOString() : null }
        : candidate,
    ));
    adjustUnreadCount(isRead ? -1 : 1);
    try {
      await api.patch(`/notifications/${encodeURIComponent(item.id)}`, { is_read: isRead });
      setFeedback(isRead ? t('feedback.markedRead') : t('feedback.markedUnread'));
      if (filter === 'UNREAD' && isRead) setItems((current) => current.filter((candidate) => candidate.id !== item.id));
    } catch (caught) {
      // Restore only this row so a concurrent successful mutation on another
      // notification is never undone by this request failing.
      setItems((current) => current.map((candidate) => candidate.id === item.id ? item : candidate));
      adjustUnreadCount(isRead ? 1 : -1);
      setError(notificationMutationError(caught, t('states.mutationFailure')));
    } finally {
      setMutating((current) => {
        const next = new Set(current);
        next.delete(item.id);
        return next;
      });
      await refreshUnreadCount();
    }
  };

  const markAllRead = async () => {
    const priorItems = items;
    const priorUnreadCount = unreadCount;
    setMutating(new Set(items.filter((item) => !item.is_read).map((item) => item.id)));
    setError(null);
    setFeedback(null);
    setItems((current) => current.map((item) => ({ ...item, is_read: true, read_at: item.read_at || new Date().toISOString() })));
    if (priorUnreadCount !== null) adjustUnreadCount(-priorUnreadCount);
    try {
      await api.post('/notifications/mark-all-read');
      setFeedback(t('feedback.allRead'));
      if (filter === 'UNREAD') setItems([]);
    } catch (caught) {
      setItems(priorItems);
      if (priorUnreadCount !== null) adjustUnreadCount(priorUnreadCount);
      setError(notificationMutationError(caught, t('states.mutationFailure')));
    } finally {
      setMutating(new Set());
      await refreshUnreadCount();
    }
  };

  const hasUnread = items.some((item) => !item.is_read);
  return (
    <div className="customer-page notifications-page ds-container-content ds-stack">
      <header className="ds-page-header notification-page-header">
        <div>
          <span className="ds-eyebrow">{t('eyebrow')}</span>
          <h1>{t('title')}</h1>
          <p className="ds-muted">{t('description')}</p>
        </div>
        <Button variant="secondary" onClick={markAllRead} disabled={!hasUnread || mutating.size > 0} leadingIcon={<CheckCheck aria-hidden />}>
          {t('markAllRead')}
        </Button>
      </header>

      <div className="notification-filters" role="group" aria-label={t('filterLabel')}>
        {FILTERS.map((value) => (
          <Button
            key={value}
            size="sm"
            variant={filter === value ? 'primary' : 'ghost'}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {t(`filters.${value}`)}
          </Button>
        ))}
      </div>

      <div className="sr-only" role="status" aria-live="polite">{feedback}</div>
      {error && (
        <Alert tone="danger" title={error} action={<Button size="sm" variant="secondary" onClick={() => load()} leadingIcon={<RefreshCw aria-hidden />}>{t('retry')}</Button>} />
      )}

      <section className="notification-list ds-surface" aria-busy={loading} aria-label={t('listLabel')}>
        {loading ? (
          <NotificationSkeleton label={t('states.loading')} />
        ) : items.length === 0 ? (
          <div className="notification-empty">
            <Inbox aria-hidden />
            <h2>{filter === 'ALL' ? t('states.empty') : t('states.filteredEmpty')}</h2>
            <p className="ds-muted">{filter === 'ALL' ? t('states.emptyHelp') : t('states.filteredEmptyHelp')}</p>
          </div>
        ) : (
          <ol>
            {items.map((item) => (
              <NotificationRow
                key={item.id}
                item={item}
                locale={locale}
                busy={mutating.has(item.id)}
                onReadChange={(isRead) => void setRead(item, isRead)}
              />
            ))}
          </ol>
        )}
      </section>

      {nextCursor && !loading && (
        <Button className="notification-load-more" variant="secondary" loading={loadingMore} onClick={() => load(true, nextCursor)} trailingIcon={<ChevronDown aria-hidden />}>
          {t('loadMore')}
        </Button>
      )}
    </div>
  );
}

function NotificationRow({ item, locale, busy, onReadChange }: {
  item: NotificationItem;
  locale: string;
  busy: boolean;
  onReadChange: (isRead: boolean) => void;
}) {
  const t = useTranslations('notifications');
  const destination = notificationDestination(item);
  const broadcast = item.event_type === 'ADMIN_BROADCAST' || item.event_type === 'ADMIN_BROADCAST_TEST';
  const safeTemplate = knownSystemTemplate(item.template_key) ? SYSTEM_TEMPLATE_KEYS[item.template_key] : null;
  const title = broadcast ? item.subject || t('fallback.title') : safeTemplate ? t(`templates.${safeTemplate}.title`) : t('fallback.title');
  const body = broadcast
    ? item.body || ''
    : safeTemplate
      ? t(`templates.${safeTemplate}.body`, { versionNumber: numericPayload(item.payload.version_number) })
      : t('fallback.body');
  const category = t(`categories.${item.category}`);
  const date = safeDate(item.created_at, locale);
  return (
    <li className="notification-row" data-read={item.is_read} aria-label={`${title}. ${item.is_read ? t('read') : t('unread')}`}>
      <span className="notification-state" aria-hidden>{item.is_read ? <Bell /> : <Circle fill="currentColor" />}</span>
      <div className="notification-content">
        <div className="notification-meta">
          <span className="ds-badge">{category}</span>
          {item.is_test && <span className="ds-badge ds-tone-warning">{t('test')}</span>}
          <time dateTime={item.created_at}>{date}</time>
        </div>
        <h2><BidiText>{title}</BidiText></h2>
        <BidiText className="notification-body">{body}</BidiText>
        {safeTemplate === 'analysisCompleted' && typeof item.payload.version_number === 'number' && (
          <TechnicalText className="notification-technical">{t('version', { versionNumber: item.payload.version_number })}</TechnicalText>
        )}
        <div className="notification-actions">
          {destination && (
            <Link className="ds-button ds-button-ghost ds-button-sm" href={destination.href} prefetch={false}>
              {t(`actions.${destination.labelKey}`)}
            </Link>
          )}
          <Button size="sm" variant="ghost" loading={busy} onClick={() => onReadChange(!item.is_read)}>
            {item.is_read ? t('actions.markUnread') : t('actions.markRead')}
          </Button>
        </div>
      </div>
    </li>
  );
}

function NotificationSkeleton({ label }: { label: string }) {
  return <div className="notification-loading" role="status"><RefreshCw className="ds-spin" aria-hidden /><span>{label}</span></div>;
}

function numericPayload(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 1;
}

function safeDate(value: string, locale: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? '' : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}

function notificationMutationError(error: unknown, fallback: string) {
  return (error as AxiosError)?.response?.status === 404 ? fallback : fallback;
}
