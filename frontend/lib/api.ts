import axios, { InternalAxiosRequestConfig } from 'axios';
import { getSession, signOut } from 'next-auth/react';

import { organizationHeader, readSelectedOrganization, writeSelectedOrganization } from './organizationSelection';

type SessionWithAccessToken = {
    accessToken?: string;
} | null;

const ACCESS_TOKEN_CACHE_TTL_MS = 5 * 60 * 1000;

let accessTokenCache: string | null = null;
let accessTokenCachedAt = 0;
let sessionTokenRequestInFlight: Promise<string | null> | null = null;

const now = () => Date.now();

const hasFreshCachedToken = () =>
    Boolean(accessTokenCache) &&
    now() - accessTokenCachedAt < ACCESS_TOKEN_CACHE_TTL_MS;

export const setApiAccessToken = (token: string | null): void => {
    accessTokenCache = token;
    accessTokenCachedAt = now();
};

const readAccessTokenFromSession = async (): Promise<string | null> => {
    if (hasFreshCachedToken()) {
        return accessTokenCache;
    }

    if (!sessionTokenRequestInFlight) {
        sessionTokenRequestInFlight = (async () => {
            const session = (await getSession().catch(() => null)) as SessionWithAccessToken;
            const resolvedToken =
                typeof session?.accessToken === 'string' ? session.accessToken : null;
            setApiAccessToken(resolvedToken);
            return resolvedToken;
        })().finally(() => {
            sessionTokenRequestInFlight = null;
        });
    }

    return sessionTokenRequestInFlight;
};

const attachAuthorizationHeader = (
    config: InternalAxiosRequestConfig,
    token: string,
): void => {
    const authValue = `Bearer ${token}`;

    if (typeof config.headers?.set === 'function') {
        config.headers.set('Authorization', authValue);
        return;
    }

    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>).Authorization = authValue;
};

/**
 * Plasma AI API Client
 *
 * Axios instance configured with base URL and automatic JWT token injection.
 */
const apiBaseUrl = '/api/v1';

const api = axios.create({
    baseURL: apiBaseUrl,
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request interceptor to attach backend JWT from NextAuth session callback
api.interceptors.request.use(
    async (config) => {
        if (typeof window !== 'undefined') {
            const token = await readAccessTokenFromSession();
            if (token) {
                attachAuthorizationHeader(config, token);
            }
            // R3 Task 6: the selected organization, unless the request names one itself.
            const existing = typeof config.headers?.get === 'function'
                ? config.headers.get('X-Organization-ID')
                : (config.headers as Record<string, string> | undefined)?.['X-Organization-ID'];
            const organizationId = organizationHeader(existing ? String(existing) : null, readSelectedOrganization());
            if (organizationId) {
                if (typeof config.headers?.set === 'function') config.headers.set('X-Organization-ID', organizationId);
                (config as InternalAxiosRequestConfig & { plasmaSelectedOrganization?: boolean }).plasmaSelectedOrganization = true;
            }
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor — redirect to login on 401 (expired / invalid token)
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (error.response?.status === 401 && typeof window !== 'undefined') {
            setApiAccessToken(null);
            await signOut({ callbackUrl: '/' });
        }
        // A stored organization the user no longer belongs to: forget it and retry once
        // in the default organization (R3 Task 6).
        const config = error.config as (InternalAxiosRequestConfig & { plasmaSelectedOrganization?: boolean; plasmaRetried?: boolean }) | undefined;
        if (
            error.response?.status === 404 && error.response?.data?.detail === 'Organization not found'
            && config?.plasmaSelectedOrganization && !config.plasmaRetried
        ) {
            writeSelectedOrganization(null);
            config.plasmaRetried = true;
            if (typeof config.headers?.delete === 'function') config.headers.delete('X-Organization-ID');
            return api.request(config);
        }
        return Promise.reject(error);
    }
);

export { api };
