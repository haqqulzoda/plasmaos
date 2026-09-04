import {NextResponse} from 'next/server';

import {
    UI_LOCALE_COOKIE_NAME,
    isCustomerSelectableLocale,
} from '@/i18n/locales';

export async function POST(request: Request) {
    let body: unknown;
    try {
        body = await request.json();
    } catch {
        return NextResponse.json({code: 'invalid_request'}, {status: 400});
    }

    const uiLocale = body && typeof body === 'object'
        ? (body as {ui_locale?: unknown}).ui_locale
        : null;
    if (!isCustomerSelectableLocale(uiLocale)) {
        return NextResponse.json({code: 'unsupported_ui_locale'}, {status: 422});
    }

    const response = new NextResponse(null, {status: 204});
    response.cookies.set(UI_LOCALE_COOKIE_NAME, uiLocale, {
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
        path: '/',
        maxAge: 60 * 60 * 24 * 365,
    });
    return response;
}
