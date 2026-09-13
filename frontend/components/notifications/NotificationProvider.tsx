'use client';

import Link from 'next/link';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { Bell } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { api } from '@/lib/api';

type NotificationContextValue = {
  unreadCount: number | null;
  refreshUnreadCount: () => Promise<void>;
  adjustUnreadCount: (delta: number) => void;
};

const NotificationContext = createContext<NotificationContextValue | null>(null);
const REFRESH_INTERVAL_MS = 60_000;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [unreadCount, setUnreadCount] = useState<number | null>(null);

  const refreshUnreadCount = useCallback(async () => {
    try {
      const response = await api.get<{ unread_count: number }>('/notifications/unread-count');
      setUnreadCount(Math.max(0, response.data.unread_count));
    } catch {
      // Retain the last confirmed count; the inbox owns visible failure feedback.
    }
  }, []);

  const adjustUnreadCount = useCallback((delta: number) => {
    setUnreadCount((current) => (current === null ? null : Math.max(0, current + delta)));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void refreshUnreadCount(), 0);
    return () => window.clearTimeout(timer);
  }, [pathname, refreshUnreadCount]);

  useEffect(() => {
    const onFocus = () => void refreshUnreadCount();
    window.addEventListener('focus', onFocus);
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshUnreadCount();
    }, REFRESH_INTERVAL_MS);
    return () => {
      window.removeEventListener('focus', onFocus);
      window.clearInterval(timer);
    };
  }, [refreshUnreadCount]);

  const value = useMemo(
    () => ({ unreadCount, refreshUnreadCount, adjustUnreadCount }),
    [adjustUnreadCount, refreshUnreadCount, unreadCount],
  );
  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
}

export function useNotifications() {
  const value = useContext(NotificationContext);
  if (!value) throw new Error('useNotifications must be used within NotificationProvider');
  return value;
}

export function NotificationBell() {
  const t = useTranslations('notifications');
  const { unreadCount } = useNotifications();
  const label = unreadCount && unreadCount > 0
    ? t('bellWithCount', { count: unreadCount })
    : t('bell');
  return (
    <Link className="notification-bell ds-button ds-button-icon" href="/dashboard/notifications" prefetch={false} aria-label={label}>
      <Bell aria-hidden />
      {unreadCount !== null && unreadCount > 0 && (
        <span className="notification-bell-count ds-numeric" aria-hidden>
          {unreadCount > 99 ? '99+' : unreadCount}
        </span>
      )}
    </Link>
  );
}
