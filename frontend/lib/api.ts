import axios from 'axios';
import { signOut } from 'next-auth/react';

/**
 * Plasma AI API Client
 *
 * Axios instance configured with base URL and automatic JWT token injection.
 */
const api = axios.create({
    baseURL: '/api/v1',
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request interceptor to attach backend JWT from NextAuth session callback
api.interceptors.request.use(
    async (config) => {
        if (typeof window !== 'undefined') {
            const sessionResponse = await fetch('/api/auth/session', {
                credentials: 'include',
                cache: 'no-store',
            }).catch(() => null);
            if (sessionResponse?.ok) {
                const session = (await sessionResponse.json()) as { accessToken?: string };
                if (session.accessToken) {
                    config.headers.Authorization = `Bearer ${session.accessToken}`;
                }
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
            await signOut({ callbackUrl: '/login' });
        }
        return Promise.reject(error);
    }
);

export { api };
