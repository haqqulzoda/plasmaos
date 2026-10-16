import { createHmac, randomUUID } from 'node:crypto';
import NextAuth, { CredentialsSignin } from 'next-auth';
import Credentials from 'next-auth/providers/credentials';
import GoogleProvider from 'next-auth/providers/google';

import { resolveBackendApiBase } from '@/lib/backendApiBase';

// Server-side calls (NextAuth callbacks) use BACKEND_INTERNAL_URL to reach
// the backend via Docker's internal network.  Falls back to the public URL.
const backendApiBase = resolveBackendApiBase();

// P1: about 30 days. The backend access token still lives 8 hours; a rotating refresh
// token (kept only in this encrypted session cookie, never sent to the browser's JS)
// renews it. The backend caps a sign-in at 90 days and ends it on logout, disable or
// any change of authority.
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;
const ROTATE_BEFORE_EXPIRY_MS = 5 * 60 * 1000;

type BackendClaims = {
  platform_role?: string;
  approval_status?: string;
  is_admin?: boolean;
  onboarding_required?: boolean;
  company_profile_id?: string | null;
  company_approval_status?: string | null;
  company_pilot_status?: string | null;
  exp?: number;
};

type BackendTokenPayload = {
  access_token?: string;
  token_type?: string;
  refresh_token?: string | null;
} & BackendClaims;

/** The public, account-independent reason an e-mail code sign-in failed (shown by the sign-in page). */
class EmailCodeSignInError extends CredentialsSignin {
  constructor(code: string) {
    super();
    this.code = code;
  }
}

function decodeBackendClaims(accessToken: string): BackendClaims {
  try {
    const parts = accessToken.split('.');
    if (parts.length !== 3) return {};
    return JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf-8')) as BackendClaims;
  } catch {
    return {};
  }
}

function bridgeAssertion(claims: Record<string, unknown>): string {
  const secret = process.env.AUTH_BRIDGE_SECRET;
  if (!secret || secret.length < 32) throw new Error('Authentication unavailable');
  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify({
    ...claims, iss: 'plasma-authjs', aud: 'plasma-backend', iat: now, exp: now + 60, jti: randomUUID(),
  })).toString('base64url');
  const unsigned = `${header}.${body}`;
  return `${unsigned}.${createHmac('sha256', secret).update(unsigned).digest('base64url')}`;
}

function clientAddress(request: Request | undefined): string | undefined {
  // The edge proxy (Caddy) sets X-Forwarded-For to the browser's address.
  const forwarded = request?.headers.get('x-forwarded-for')?.split(',')[0]?.trim();
  const address = forwarded || request?.headers.get('x-real-ip')?.trim() || undefined;
  return address && address.length <= 64 ? address : undefined;
}

function clearBackendAuthority(token: Record<string, unknown>) {
  delete token.accessToken;
  delete token.refreshToken;
  delete token.platform_role;
  delete token.approval_status;
  delete token.is_admin;
  delete token.onboarding_required;
  delete token.company_profile_id;
  delete token.company_approval_status;
  delete token.company_pilot_status;
  token.backendSessionError = 'BackendSessionRevoked';
}

function storeBackendSession(token: Record<string, unknown>, payload: BackendTokenPayload) {
  token.accessToken = payload.access_token;
  if (typeof payload.refresh_token === 'string' && payload.refresh_token) token.refreshToken = payload.refresh_token;
  delete token.backendSessionError;
  applyBackendClaims(token, payload);
}

function isBackendTokenPayload(payload: BackendTokenPayload): boolean {
  return Boolean(payload.access_token) && payload.token_type === 'bearer';
}

/** Exchange the refresh token. Transport and server failures keep the session for the next try. */
async function rotateWithRefreshToken(token: Record<string, unknown>) {
  if (typeof token.refreshToken !== 'string') {
    clearBackendAuthority(token);
    return;
  }
  try {
    const response = await fetch(`${backendApiBase}/auth/session/rotate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: token.refreshToken }),
      cache: 'no-store',
    });
    if (!response.ok) {
      if (response.status >= 500 || response.status === 429) return;
      clearBackendAuthority(token);
      return;
    }
    const payload = (await response.json()) as BackendTokenPayload;
    if (!isBackendTokenPayload(payload)) {
      clearBackendAuthority(token);
      return;
    }
    storeBackendSession(token, payload);
  } catch {
    return;
  }
}

async function validateAndRotateBackendSession(token: Record<string, unknown>) {
  if (typeof token.accessToken !== 'string') {
    if (typeof token.refreshToken === 'string') await rotateWithRefreshToken(token);
    return;
  }

  const expiresAt = decodeBackendClaims(token.accessToken).exp;
  if (
    typeof token.refreshToken === 'string' &&
    typeof expiresAt === 'number' &&
    expiresAt * 1000 - Date.now() < ROTATE_BEFORE_EXPIRY_MS
  ) {
    await rotateWithRefreshToken(token);
    return;
  }

  try {
    const refreshResponse = await fetch(`${backendApiBase}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token.accessToken}`,
      },
      cache: 'no-store',
    });
    if (!refreshResponse.ok) {
      if (refreshResponse.status >= 500) return;
      if (refreshResponse.status === 401 && typeof token.refreshToken === 'string') {
        // An expired access token: the refresh token decides (it fails too after any change of authority).
        await rotateWithRefreshToken(token);
        return;
      }
      clearBackendAuthority(token);
      return;
    }

    const refreshPayload = (await refreshResponse.json()) as BackendTokenPayload;
    if (!isBackendTokenPayload(refreshPayload)) {
      clearBackendAuthority(token);
      return;
    }

    storeBackendSession(token, refreshPayload);
  } catch {
    // Preserve credentials during transport failure. Every protected backend
    // request still verifies current account authority; no access is granted here.
    return;
  }
}

function applyBackendClaims(
  token: Record<string, unknown>,
  payload: BackendTokenPayload,
) {
  const claims = payload.access_token ? decodeBackendClaims(payload.access_token) : {};
  token.platform_role = payload.platform_role ?? claims.platform_role;
  token.approval_status = payload.approval_status ?? claims.approval_status;
  token.is_admin = payload.is_admin ?? claims.is_admin;
  token.onboarding_required = payload.onboarding_required ?? claims.onboarding_required;
  token.company_profile_id = payload.company_profile_id ?? claims.company_profile_id ?? null;
  token.company_approval_status = payload.company_approval_status ?? claims.company_approval_status ?? null;
  token.company_pilot_status = payload.company_pilot_status ?? claims.company_pilot_status ?? null;
}

export const { handlers, auth } = NextAuth({
  secret: process.env.AUTH_SECRET,
  trustHost: true,
  useSecureCookies:
    (process.env.AUTH_URL ?? process.env.NEXTAUTH_URL)?.startsWith('https://') ??
    process.env.NODE_ENV === 'production',
  session: { strategy: 'jwt', maxAge: SESSION_MAX_AGE_SECONDS },
  pages: {
    signIn: '/',
    // Our own localized page instead of Auth.js's built-in "Server error" screen.
    error: '/auth/error',
  },
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? '',
      authorization: { params: { prompt: 'select_account', access_type: 'offline' } },
    }),
    // P1: a 6-digit code sent by e-mail (requested by the page from /auth/email/request-code).
    Credentials({
      id: 'email-code',
      name: 'E-mail code',
      credentials: { email: {}, code: {} },
      async authorize(credentials, request) {
        const email = typeof credentials?.email === 'string' ? credentials.email.trim().toLowerCase() : '';
        const code = typeof credentials?.code === 'string' ? credentials.code.replace(/\s+/g, '') : '';
        if (!email || !/^\d{6}$/.test(code)) throw new EmailCodeSignInError('invalid_code');

        const response = await fetch(`${backendApiBase}/auth/email/verify-code`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email,
            code,
            bridge_assertion: bridgeAssertion({ purpose: 'email_code', email, client_ip: clientAddress(request) }),
          }),
          cache: 'no-store',
        });
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as { detail?: { code?: string } } | null;
          const reason = body?.detail?.code;
          if (response.status === 429) throw new EmailCodeSignInError('rate_limited');
          if (reason === 'CODE_EXPIRED') throw new EmailCodeSignInError('code_expired');
          if (reason === 'ACCOUNT_UNAVAILABLE') throw new EmailCodeSignInError('account_unavailable');
          if (response.status >= 500) throw new EmailCodeSignInError('unavailable');
          throw new EmailCodeSignInError('invalid_code');
        }
        const payload = (await response.json()) as BackendTokenPayload & { email?: string };
        if (!isBackendTokenPayload(payload)) throw new EmailCodeSignInError('unavailable');
        const claims = decodeBackendClaims(payload.access_token as string) as BackendClaims & {
          sub?: string; name?: string; email?: string;
        };
        return {
          id: claims.sub ?? email,
          email: claims.email ?? email,
          name: claims.name ?? email,
          backend: payload,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile, user }) {
      // ── Initial Google sign-in: exchange for a backend JWT ──
      if (account?.provider === 'google') {
        const googleId =
          typeof profile?.sub === 'string'
            ? profile.sub
            : typeof account.providerAccountId === 'string'
              ? account.providerAccountId
              : undefined;
        const email = typeof profile?.email === 'string' ? profile.email : undefined;

        if (!googleId || !email || profile?.email_verified !== true) {
          throw new Error('Google identity payload incomplete');
        }

        const identity = { google_id: googleId, email, name: user.name ?? email, avatar_url: user.image ?? null };
        const response = await fetch(`${backendApiBase}/auth/google`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...identity,
            bridge_assertion: bridgeAssertion({ ...identity, sub: googleId, email_verified: true }),
          }),
        });

        if (!response.ok) {
          throw new Error('Backend Google bridge failed');
        }

        const payload = (await response.json()) as BackendTokenPayload;

        if (!isBackendTokenPayload(payload)) {
          throw new Error('Invalid backend token payload');
        }

        storeBackendSession(token as Record<string, unknown>, payload);
        return token;
      }

      // ── Initial e-mail code sign-in: authorize() already holds the backend session ──
      if (account?.provider === 'email-code') {
        const payload = (user as { backend?: BackendTokenPayload } | undefined)?.backend;
        if (!payload || !isBackendTokenPayload(payload)) throw new Error('Invalid backend token payload');
        storeBackendSession(token as Record<string, unknown>, payload);
        return token;
      }

      // Every Auth.js callback proves current backend authority. Approval,
      // rejection, disable, restore, and role changes all require sign-in again.
      await validateAndRotateBackendSession(token as Record<string, unknown>);

      return token;
    },
    async session({ session, token }) {
      // The refresh token never leaves the encrypted session cookie.
      (session as { accessToken?: string }).accessToken =
        typeof token.accessToken === 'string' ? token.accessToken : undefined;
      session.backendSessionError =
        token.backendSessionError === 'BackendSessionRevoked'
          ? 'BackendSessionRevoked'
          : undefined;
      session.platform_role = typeof token.platform_role === 'string' ? token.platform_role : undefined;
      session.approval_status = typeof token.approval_status === 'string' ? token.approval_status : undefined;
      session.is_admin = typeof token.is_admin === 'boolean' ? token.is_admin : undefined;
      session.onboarding_required = typeof token.onboarding_required === 'boolean' ? token.onboarding_required : undefined;
      session.company_profile_id = typeof token.company_profile_id === 'string' ? token.company_profile_id : null;
      session.company_approval_status =
        typeof token.company_approval_status === 'string' ? token.company_approval_status : null;
      session.company_pilot_status =
        typeof token.company_pilot_status === 'string' ? token.company_pilot_status : null;
      if (session.user) {
        session.user.platform_role = session.platform_role;
        session.user.approval_status = session.approval_status;
        session.user.is_admin = session.is_admin;
        session.user.onboarding_required = session.onboarding_required;
        session.user.company_profile_id = session.company_profile_id;
        session.user.company_approval_status = session.company_approval_status;
        session.user.company_pilot_status = session.company_pilot_status;
      }
      return session;
    },
  },
});
