/**
 * Auth.js error codes shown on /auth/error. Unknown or missing codes read as "default".
 * Import-free for the node test runner.
 */

export const AUTH_ERROR_KINDS = ['configuration', 'accessDenied', 'verification', 'default'] as const;
export type AuthErrorKind = (typeof AUTH_ERROR_KINDS)[number];

const CODES: Record<string, AuthErrorKind> = {
    configuration: 'configuration',
    accessdenied: 'accessDenied',
    verification: 'verification',
};

export function authErrorKind(code: string | null | undefined): AuthErrorKind {
    return CODES[(code ?? '').trim().toLowerCase()] ?? 'default';
}
