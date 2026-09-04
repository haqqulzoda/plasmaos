import {cookies, headers} from 'next/headers';
import {getRequestConfig} from 'next-intl/server';

import {loadMessages} from './messages';
import {loadPseudoMessages} from './messages';
import {isPseudoLocaleEnabled, PSEUDO_LOCALE_CODE, PSEUDO_LOCALE_HEADER} from './pseudoLocale';
import {
    PERSISTED_UI_LOCALE_HEADER,
    UI_LOCALE_COOKIE_NAME,
    resolveRequestLocale,
} from './requestLocale';

export default getRequestConfig(async () => {
    const [requestHeaders, requestCookies] = await Promise.all([headers(), cookies()]);
    const customerLocale = resolveRequestLocale({
        persistedUserLocale: requestHeaders.get(PERSISTED_UI_LOCALE_HEADER),
        presentationCookie: requestCookies.get(UI_LOCALE_COOKIE_NAME)?.value,
        acceptLanguage: requestHeaders.get('accept-language'),
    });

    const pseudo = isPseudoLocaleEnabled() && requestHeaders.get(PSEUDO_LOCALE_HEADER) === '1';
    const locale = pseudo ? PSEUDO_LOCALE_CODE : customerLocale;
    return {
        locale,
        messages: pseudo ? await loadPseudoMessages() : await loadMessages(customerLocale),
        onError(error) {
            // Diagnostics are deliberately key/code-only: never log interpolated customer data.
            console.error(`[i18n:${error.code}]`);
        },
        getMessageFallback() {
            return 'Translation unavailable';
        },
    };
});
