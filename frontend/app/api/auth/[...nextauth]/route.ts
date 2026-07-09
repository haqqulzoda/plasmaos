import NextAuth from 'next-auth';
import GoogleProvider from 'next-auth/providers/google';

import { resolveBackendApiBase } from '@/lib/backendApiBase';

// Server-side calls (NextAuth callbacks) use BACKEND_INTERNAL_URL to reach
// the backend via Docker's internal network.  Falls back to the public URL.
const backendApiBase = resolveBackendApiBase();

// Backend JWT lifetime is 8 hours.  We attempt a silent refresh when the
// token is within 1 hour of expiring, keeping the session alive as long
// as the user is active.
const REFRESH_WINDOW_SECONDS = 60 * 60; // 1 hour before expiry

type BackendClaims = {
  platform_role?: string;
  approval_status?: string;
  is_admin?: boolean;
  onboarding_required?: boolean;
  company_profile_id?: string | null;
  company_approval_status?: string | null;
  company_pilot_status?: string | null;
};

type BackendTokenPayload = {
  access_token?: string;
  token_type?: string;
} & BackendClaims;

function decodeBackendClaims(accessToken: string): BackendClaims {
  try {
    const parts = accessToken.split('.');
    if (parts.length !== 3) return {};
    return JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf-8')) as BackendClaims;
  } catch {
    return {};
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

const { handlers, auth } = NextAuth({
  secret: process.env.AUTH_SECRET,
  trustHost: true,
  session: { strategy: 'jwt', maxAge: 60 * 60 * 8 },
  pages: {
    signIn: '/',
  },
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? '',
      authorization: { params: { prompt: 'select_account', access_type: 'offline' } },
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile, user, trigger }) {
      // ── Initial Google sign-in: exchange for a backend JWT ──
      if (account?.provider === 'google') {
        const googleId =
          typeof profile?.sub === 'string'
            ? profile.sub
            : typeof account.providerAccountId === 'string'
              ? account.providerAccountId
              : undefined;
        const email = typeof user?.email === 'string' ? user.email : undefined;

        if (!googleId || !email) {
          throw new Error('Google identity payload incomplete');
        }

        const response = await fetch(`${backendApiBase}/auth/google`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            google_id: googleId,
            email,
            name: user.name ?? email,
            avatar_url: user.image ?? null,
          }),
        });

        if (!response.ok) {
          throw new Error('Backend Google bridge failed');
        }

        const payload = (await response.json()) as BackendTokenPayload;

        if (!payload.access_token || payload.token_type !== 'bearer') {
          throw new Error('Invalid backend token payload');
        }

        token.accessToken = payload.access_token;
        applyBackendClaims(token as Record<string, unknown>, payload);
        return token;
      }

      // Explicit session updates are used after onboarding/approval changes.
      // The backend refresh endpoint accepts a valid signed token even when its
      // auth_version is stale, then rotates it to the current authorization state.
      if (trigger === 'update' && typeof token.accessToken === 'string') {
        try {
          const refreshResponse = await fetch(`${backendApiBase}/auth/refresh`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token.accessToken}`,
            },
          });
          if (refreshResponse.ok) {
            const refreshPayload = (await refreshResponse.json()) as BackendTokenPayload;
            if (refreshPayload.access_token && refreshPayload.token_type === 'bearer') {
              token.accessToken = refreshPayload.access_token;
              applyBackendClaims(token as Record<string, unknown>, refreshPayload);
            }
          }
        } catch {
          // The caller keeps its current session and can retry status refresh.
        }
        return token;
      }

      // ── Subsequent requests: silent refresh when nearing expiry ──
      if (typeof token.accessToken === 'string') {
        try {
          // Decode the JWT payload to read `exp` (seconds since epoch)
          const parts = token.accessToken.split('.');
          if (parts.length === 3) {
            const payload = JSON.parse(
              Buffer.from(parts[1], 'base64url').toString('utf-8'),
            ) as { exp?: number };

            const nowSeconds = Math.floor(Date.now() / 1000);
            const expiresAt = payload.exp ?? 0;

            if (expiresAt - nowSeconds < REFRESH_WINDOW_SECONDS) {
              // Token is within the refresh window — request a fresh one
              const refreshResponse = await fetch(`${backendApiBase}/auth/refresh`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${token.accessToken}`,
                },
              });

              if (refreshResponse.ok) {
                const refreshPayload = (await refreshResponse.json()) as BackendTokenPayload;

                if (refreshPayload.access_token && refreshPayload.token_type === 'bearer') {
                  token.accessToken = refreshPayload.access_token;
                  applyBackendClaims(token as Record<string, unknown>, refreshPayload);
                }
              }
              // If refresh fails the existing (still valid) token is kept;
              // once it fully expires the 401 interceptor handles logout.
            }
          }
        } catch {
          // Decode/refresh failure is non-fatal — keep existing token
        }
      }

      return token;
    },
    async session({ session, token }) {
      (session as { accessToken?: string }).accessToken =
        typeof token.accessToken === 'string' ? token.accessToken : undefined;
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

export const { GET, POST } = handlers;
export { auth };
