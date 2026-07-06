const DEFAULT_API_PATH = '/api/v1';

const trimTrailingSlash = (value: string): string => value.replace(/\/$/, '');

export function resolveBackendApiBase(): string {
  const configured = process.env.BACKEND_INTERNAL_URL ?? DEFAULT_API_PATH;

  const normalized = trimTrailingSlash(configured);
  if (/^https?:\/\//i.test(normalized)) {
    return normalized;
  }

  const origin =
    process.env.NEXTAUTH_URL ??
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : undefined);

  if (!origin) {
    return normalized;
  }

  return trimTrailingSlash(new URL(normalized, origin).toString());
}
