import axios from 'axios';

/**
 * Plasma AI API Client
 * 
 * Axios instance configured with base URL and automatic JWT token injection.
 */
const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request interceptor to attach JWT token
api.interceptors.request.use(
    (config) => {
        // Only run on client-side
        if (typeof window !== 'undefined') {
            const token = localStorage.getItem('plasma_token');
            if (token) {
                config.headers.Authorization = `Bearer ${token}`;
            }
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor for error handling
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // Handle 401 errors (token expired/invalid)
        if (error.response?.status === 401) {
            if (typeof window !== 'undefined') {
                localStorage.removeItem('plasma_token');
                // Optionally redirect to login
                // window.location.href = '/';
            }
        }
        return Promise.reject(error);
    }
);

export { api };
