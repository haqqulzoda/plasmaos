'use client';

import { useEffect } from 'react';

import { sentryOptions, type ErrorTrackingConfig } from '@/lib/errorTracking';

// Browser error tracking (R3). The root layout passes the runtime configuration (null when
// SENTRY_DSN_FRONTEND is unset: nothing is loaded); the SDK is fetched only when enabled.
export function ErrorReporting({ config }: { config: ErrorTrackingConfig | null }) {
  const dsn = config?.dsn;
  const release = config?.release;
  const environment = config?.environment;
  useEffect(() => {
    if (!dsn || !environment) return;
    let cancelled = false;
    void import('@sentry/nextjs').then((Sentry) => {
      if (cancelled || Sentry.getClient()) return;
      Sentry.init({
        ...sentryOptions({ dsn, release, environment }),
        integrations: (defaults: Array<{ name: string }>) =>
          defaults.filter((integration) => integration.name !== 'Replay' && integration.name !== 'Feedback'),
      } as Parameters<typeof Sentry.init>[0]);
      Sentry.setTag('component', 'frontend-browser');
    });
    return () => {
      cancelled = true;
    };
  }, [dsn, release, environment]);
  return null;
}
