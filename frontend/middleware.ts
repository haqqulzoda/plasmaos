import { NextResponse, type NextRequest } from 'next/server';
import { getToken } from 'next-auth/jwt';

import { resolveBackendApiBase } from '@/lib/backendApiBase';

const PUBLIC_PATHS = ['/', '/api/auth', '/api/build', '/_next', '/favicon.ico'];
const PUBLIC_EXACT_PATHS = ['/api/v1/health/version'];

function isPublicPath(pathname: string): boolean {
    if (PUBLIC_EXACT_PATHS.includes(pathname)) {
        return true;
    }
    return PUBLIC_PATHS.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function denyRequest(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith('/api/')) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }
  const redirectUrl = new URL('/', request.url);
  redirectUrl.searchParams.set('next', request.nextUrl.pathname);
  return NextResponse.redirect(redirectUrl);
}

export async function middleware(request: NextRequest) {
  if (isPublicPath(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const token = await getToken({
    req: request,
    secret: process.env.AUTH_SECRET,
    secureCookie: process.env.NODE_ENV === 'production',
  });

  if (!token) {
    return denyRequest(request);
  }

  const accessToken = typeof token.accessToken === 'string' ? token.accessToken : null;
  const backendApiBase = resolveBackendApiBase();
  if (!accessToken || !/^https?:\/\//i.test(backendApiBase)) {
    return denyRequest(request);
  }

  try {
    const authorityResponse = await fetch(`${backendApiBase}/users/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
      redirect: 'manual',
    });
    if (!authorityResponse.ok) {
      return denyRequest(request);
    }
  } catch {
    return denyRequest(request);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/admin/:path*', '/api/:path*'],
};
