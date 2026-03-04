import NextAuth from 'next-auth';
import GoogleProvider from 'next-auth/providers/google';

// Server-side calls (NextAuth callbacks) use BACKEND_INTERNAL_URL to reach
// the backend via Docker's internal network.  Falls back to the public URL.
const backendApiBase = (
  process.env.BACKEND_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  'http://localhost:8000/api/v1'
).replace(/\/$/, '');

// Backend JWT lifetime is 8 hours.  We attempt a silent refresh when the
// token is within 1 hour of expiring, keeping the session alive as long
// as the user is active.
const REFRESH_WINDOW_SECONDS = 60 * 60; // 1 hour before expiry

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
    async jwt({ token, account, profile, user }) {
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

        const payload = (await response.json()) as {
          access_token?: string;
          token_type?: string;
        };

        if (!payload.access_token || payload.token_type !== 'bearer') {
          throw new Error('Invalid backend token payload');
        }

        token.accessToken = payload.access_token;
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
                const refreshPayload = (await refreshResponse.json()) as {
                  access_token?: string;
                  token_type?: string;
                };

                if (refreshPayload.access_token && refreshPayload.token_type === 'bearer') {
                  token.accessToken = refreshPayload.access_token;
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
      return session;
    },
  },
});

export const { GET, POST } = handlers;
export { auth };
