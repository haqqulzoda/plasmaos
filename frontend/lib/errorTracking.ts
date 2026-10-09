// Error tracking (R3): Sentry for the Next.js server and the browser.
//
// Off unless SENTRY_DSN_FRONTEND is set in the frontend container (read at request time, so
// one image serves with or without it). release = PLASMA_BUILD_SHA, environment = ENVIRONMENT.
// Every event and breadcrumb is scrubbed before it leaves: no request bodies, cookies or auth
// headers, no user, no query strings, and e-mail addresses, tokens, quoted strings and prose
// (where document content shows up) redacted. Mirrors backend/app/core/observability.py.

export type ErrorTrackingConfig = { dsn: string; release?: string; environment: string };

type Json = unknown;
type SentryLikeEvent = Record<string, Json>;

const MAX_TEXT_LENGTH = 300;
const FILTERED = '[Filtered]';
const SAFE_HEADERS = new Set([
  'accept', 'accept-language', 'content-length', 'content-type', 'host', 'user-agent', 'x-request-id',
]);
const SENSITIVE_KEY =
  /pass|secret|token|auth|cookie|session|csrf|api[_-]?key|access[_-]?key|dsn|credential|private|signature|email|e_mail|phone|text|content|body|document|notice|prompt|payload|file|excerpt|quote|snippet|answer|response/i;

const RULES: Array<[RegExp, string]> = [
  [/(\b[a-z][a-z0-9+.-]*:\/\/)[^/\s:@]+:[^/\s@]+@/gi, '$1[redacted]@'],
  [/\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}/gi, '$1 [redacted]'],
  [/\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}/g, '[redacted token]'],
  [/\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|dsn|signature|sig|key)(\s*[=:]\s*)("[^"]*"|'[^']*'|[^\s&,;)]+)/gi, '$1$2[redacted]'],
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '[email]'],
  [/'(?:[^'\\]|\\.){40,}'|"(?:[^"\\]|\\.){40,}"|“[^”]{40,}”/g, "'[redacted text]'"],
  // Prose: ten or more words in a row is document content, not a diagnostic.
  [/(?:\p{L}{2,}[\s,;:.()'"“”-]+){9,}\p{L}{2,}[.,;:]?/gu, '[redacted text]'],
  [/(?<![A-Za-z0-9_+])[A-Za-z0-9_+]{32,}={0,2}/g, '[redacted token]'],
];

export function scrubText(value: Json, limit = MAX_TEXT_LENGTH): Json {
  if (typeof value !== 'string') return value;
  let text = value;
  for (const [pattern, replacement] of RULES) text = text.replace(pattern, replacement);
  return text.length > limit ? `${text.slice(0, limit)}…[truncated]` : text;
}

export function scrubData(value: Json, depth = 0): Json {
  if (depth > 6) return FILTERED;
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => scrubData(item, depth + 1));
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, Json>).map(([key, item]) => [
        key,
        SENSITIVE_KEY.test(key) ? FILTERED : scrubData(item, depth + 1),
      ]),
    );
  }
  return scrubText(value);
}

export function scrubUrl(url: Json): Json {
  if (typeof url !== 'string') return url;
  try {
    const parsed = new URL(url, 'http://relative.invalid');
    const base = url.startsWith('/') ? '' : `${parsed.protocol}//${parsed.host}`;
    return scrubText(`${base}${parsed.pathname}`);
  } catch {
    return scrubText(url.split('?')[0]);
  }
}

function scrubFrames(stacktrace: Json): void {
  const frames = (stacktrace as { frames?: Array<Record<string, Json>> } | undefined)?.frames;
  for (const frame of frames ?? []) delete frame.vars;
}

export function scrubBreadcrumb<T extends Record<string, Json>>(crumb: T): T | null {
  if (!crumb || typeof crumb !== 'object') return null;
  const next: Record<string, Json> = { ...crumb };
  if ('message' in next) next.message = scrubText(next.message);
  if (next.data && typeof next.data === 'object') {
    const { url, to, from, ...rest } = next.data as Record<string, Json>;
    const data = scrubData(rest) as Record<string, Json>;
    if (url !== undefined) data.url = scrubUrl(url);
    if (to !== undefined) data.to = scrubUrl(to);
    if (from !== undefined) data.from = scrubUrl(from);
    next.data = data;
  }
  return next as T;
}

export function scrubEvent<T extends SentryLikeEvent>(event: T): T {
  const next: SentryLikeEvent = { ...event };
  const request = next.request as Record<string, Json> | undefined;
  if (request && typeof request === 'object') {
    const headers = Object.fromEntries(
      Object.entries((request.headers as Record<string, Json>) ?? {})
        .filter(([key]) => SAFE_HEADERS.has(key.toLowerCase()))
        .map(([key, value]) => [key, scrubText(value)]),
    );
    next.request = { method: request.method, url: scrubUrl(request.url), headers };
  }
  delete next.user;
  const exceptions = (next.exception as { values?: Array<Record<string, Json>> } | undefined)?.values ?? [];
  for (const exception of exceptions) {
    exception.value = scrubText(exception.value);
    scrubFrames(exception.stacktrace);
  }
  if ('message' in next) next.message = scrubText(next.message);
  const breadcrumbs = next.breadcrumbs;
  if (Array.isArray(breadcrumbs)) {
    next.breadcrumbs = breadcrumbs
      .map((crumb) => scrubBreadcrumb(crumb as Record<string, Json>))
      .filter(Boolean);
  }
  for (const key of ['extra', 'contexts', 'tags'] as const) {
    if (next[key] && typeof next[key] === 'object') next[key] = scrubData(next[key]);
  }
  return next as T;
}

/** Server-side configuration, or null when error tracking is off. */
export function errorTrackingConfig(env: Record<string, string | undefined> = process.env): ErrorTrackingConfig | null {
  const dsn = env.SENTRY_DSN_FRONTEND?.trim();
  if (!dsn) return null;
  const sha = env.PLASMA_BUILD_SHA?.trim();
  return {
    dsn,
    release: sha && sha !== 'unknown' ? sha : undefined,
    environment: env.ENVIRONMENT?.trim() || 'production',
  };
}

/** Options shared by the server and browser SDKs (no tracing, no PII, scrubbed). */
export function sentryOptions(config: ErrorTrackingConfig) {
  return {
    dsn: config.dsn,
    release: config.release,
    environment: config.environment,
    sendDefaultPii: false,
    tracesSampleRate: 0,
    maxBreadcrumbs: 30,
    maxValueLength: MAX_TEXT_LENGTH,
    beforeSend: <T extends SentryLikeEvent>(event: T) => scrubEvent(event),
    beforeSendTransaction: () => null,
    beforeBreadcrumb: <T extends Record<string, Json>>(crumb: T) => scrubBreadcrumb(crumb),
  };
}
