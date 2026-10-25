import { NextResponse, type NextRequest } from 'next/server';

import { ATTRIBUTION_COOKIE, attributionFrom } from '@/lib/billing';

/**
 * B1/RC-5: the public checkout link (/billing/start?plan=…&offer=…&ref=…&utm_*=…). It keeps every parameter on the
 * way to the checkout inside the signed-in app, and stores ref/utm_* in a 30-day cookie so they survive a sign-in
 * on the way. The Location is relative: correct behind any proxy.
 */
export function GET(request: NextRequest) {
  const params = new URLSearchParams();
  for (const key of ['plan', 'offer', 'ref', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) params.set(key, value.slice(0, 200));
  }
  const target = params.get('plan') ? `/dashboard/billing/start?${params.toString()}` : '/dashboard/billing';
  const response = new NextResponse(null, { status: 307, headers: { Location: target, 'Cache-Control': 'no-store' } });
  const attribution = attributionFrom(request.nextUrl.searchParams);
  if (attribution) {
    response.cookies.set(ATTRIBUTION_COOKIE, new URLSearchParams(attribution).toString(),
      { path: '/', maxAge: 30 * 24 * 3600, sameSite: 'lax', secure: request.nextUrl.protocol === 'https:' });
  }
  return response;
}
