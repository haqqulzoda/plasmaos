import type { Instrumentation } from 'next';

import { errorTrackingConfig, sentryOptions } from '@/lib/errorTracking';

// Error tracking (R3) for the Next.js server: a no-op unless SENTRY_DSN_FRONTEND is set; the SDK
// is only loaded when it is. Events are scrubbed by lib/errorTracking.ts before they leave.
let enabled = false;

export async function register() {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  const config = errorTrackingConfig();
  if (!config) return;
  const Sentry = await import('@sentry/nextjs');
  Sentry.init(sentryOptions(config) as Parameters<typeof Sentry.init>[0]);
  Sentry.setTag('component', 'frontend');
  enabled = true;
}

export const onRequestError: Instrumentation.onRequestError = async (...args) => {
  if (!enabled) return;
  const Sentry = await import('@sentry/nextjs');
  Sentry.captureRequestError(...args);
};
