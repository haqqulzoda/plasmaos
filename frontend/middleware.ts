import { NextResponse, type NextRequest } from 'next/server';
import { getToken } from 'next-auth/jwt';

import { resolveBackendApiBase } from '@/lib/backendApiBase';
import { isCustomerSelectableLocale, UI_LOCALE_COOKIE_NAME } from '@/i18n/locales';
import { PERSISTED_UI_LOCALE_HEADER } from '@/i18n/requestLocale';

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

function unavailableResponse(request: NextRequest) {
  const locale = request.cookies.get(UI_LOCALE_COOKIE_NAME)?.value ?? 'en';
  const copy: Record<string, [string, string]> = {
    en: ['Access verification is temporarily unavailable.', 'Retry'],
    uz: ['Kirish huquqini tekshirish vaqtincha mavjud emas.', 'Qayta urinish'],
    ru: ['Проверка доступа временно недоступна.', 'Повторить'],
    ar: ['التحقق من الوصول غير متاح مؤقتًا.', 'إعادة المحاولة'],
  };
  const selected = copy[locale] ?? copy.en;
  const lang = Object.hasOwn(copy, locale) ? locale : 'en';
  return new NextResponse(`<!doctype html><html lang="${lang}" dir="${lang === 'ar' ? 'rtl' : 'ltr'}"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${selected[0]}</title><body><main><h1>${selected[0]}</h1><a href="">${selected[1]}</a></main></body></html>`, {
    status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Retry-After': '5'},
  });
}

export async function middleware(request: NextRequest) {
  if (isPublicPath(request.nextUrl.pathname)) {
    const requestHeaders = new Headers(request.headers);
    requestHeaders.delete(PERSISTED_UI_LOCALE_HEADER);
    return NextResponse.next({request: {headers: requestHeaders}});
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

  // Backend API routes enforce canonical authority themselves. The extra /me
  // call per API request adds no authorization and amplifies page loads.
  if (request.nextUrl.pathname.startsWith('/api/v1/')) {
    const requestHeaders = new Headers(request.headers);
    requestHeaders.delete(PERSISTED_UI_LOCALE_HEADER);
    return NextResponse.next({request: {headers: requestHeaders}});
  }

  try {
    const authorityResponse = await fetch(`${backendApiBase}/users/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
      redirect: 'manual',
    });
    if (!authorityResponse.ok) {
      if (authorityResponse.status >= 500) return unavailableResponse(request);
      return denyRequest(request);
    }

    const currentUser = await authorityResponse.json() as { ui_locale?: unknown };
    const requestHeaders = new Headers(request.headers);
    requestHeaders.delete(PERSISTED_UI_LOCALE_HEADER);
    const persistedLocale = isCustomerSelectableLocale(currentUser.ui_locale)
      ? currentUser.ui_locale
      : null;
    if (persistedLocale) requestHeaders.set(PERSISTED_UI_LOCALE_HEADER, persistedLocale);

    const nextResponse = NextResponse.next({request: {headers: requestHeaders}});
    if (persistedLocale && request.cookies.get(UI_LOCALE_COOKIE_NAME)?.value !== persistedLocale) {
      nextResponse.cookies.set(UI_LOCALE_COOKIE_NAME, persistedLocale, {
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
        path: '/',
        maxAge: 60 * 60 * 24 * 365,
      });
    }
    return nextResponse;
  } catch {
    return unavailableResponse(request);
  }
}

export const config = {
  matcher: ['/', '/dashboard/:path*', '/admin/:path*', '/api/:path*'],
};
