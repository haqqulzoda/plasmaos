export const ACCOUNT_STATUSES = ['pending', 'approved', 'rejected', 'disabled'] as const;
export type AccountStatus = (typeof ACCOUNT_STATUSES)[number];

export const ACCOUNT_ROLES = ['admin', 'operator', 'user'] as const;
export type AccountRole = (typeof ACCOUNT_ROLES)[number];

export const LIFECYCLE_ACTIONS = ['approve', 'reject', 'disable', 'restore'] as const;
export type LifecycleAction = (typeof LIFECYCLE_ACTIONS)[number];

export type AdminAccount = {
    id: string;
    name: string;
    email: string;
    approval_status: AccountStatus;
    role: AccountRole;
    is_current_actor: boolean;
    restore_target_status?: AccountStatus | null;
    allowed_actions: LifecycleAction[];
    company?: {
        id: string;
        company_name?: string | null;
        industry?: string | null;
        approval_status: string;
        pilot_status: string;
    } | null;
    created_at?: string | null;
};

export type AdminAccountsPage = {
    items: AdminAccount[];
    total: number;
    limit: number;
    offset: number;
};

export const statusLabel = (status?: string | null): string => {
    if (status === 'pending') return 'Pending';
    if (status === 'approved') return 'Approved';
    if (status === 'rejected') return 'Rejected';
    if (status === 'disabled') return 'Disabled';
    return 'Unavailable';
};

export const roleLabel = (role?: string | null): string => {
    if (role === 'admin') return 'Admin';
    if (role === 'operator') return 'Operator';
    return 'User';
};

export const actionLabel = (action: LifecycleAction): string => {
    if (action === 'approve') return 'Approve';
    if (action === 'reject') return 'Reject';
    if (action === 'disable') return 'Disable';
    return 'Restore';
};

export const actionConsequence = (
    action: LifecycleAction,
    restoreTargetStatus?: AccountStatus | null,
): string => {
    if (action === 'approve') {
        return 'The account will become Approved. Existing credentials remain invalid, so the user must sign in again.';
    }
    if (action === 'reject') {
        return 'The account will become Rejected and existing credentials will become invalid. A later explicit approval remains possible.';
    }
    if (action === 'disable') {
        return 'Access will stop immediately and existing sessions and credentials will become invalid. A later restore still requires fresh authentication.';
    }
    return `The account will return to ${statusLabel(restoreTargetStatus ?? 'pending')}. Old sessions remain invalid and the user must sign in again.`;
};

type ApiErrorLike = {
    response?: {
        status?: number;
        data?: { detail?: unknown };
    };
};

export type AdminActionError = {
    message: string;
    refresh: boolean;
    authorityLost: boolean;
};

export const adminActionError = (error: unknown): AdminActionError => {
    const candidate = error as ApiErrorLike;
    const status = candidate?.response?.status;
    const detail = candidate?.response?.data?.detail;
    const safeDetail = typeof detail === 'string' ? detail.toLowerCase() : '';
    if (status === 401) {
        return {
            message: 'Your authentication is no longer valid. Sign in again.',
            refresh: false,
            authorityLost: true,
        };
    }
    if (status === 403) {
        return {
            message: 'Your current account no longer has administrator authority.',
            refresh: false,
            authorityLost: true,
        };
    }
    if (status === 404) {
        return {
            message: 'This account no longer exists. The account list has been refreshed.',
            refresh: true,
            authorityLost: false,
        };
    }
    if (status === 409) {
        if (safeDetail.includes('at least one effective administrator')) {
            return {
                message: 'This action would remove the last active administrator. No account state changed.',
                refresh: true,
                authorityLost: false,
            };
        }
        if (safeDetail.includes('own account')) {
            return {
                message: 'Administrators cannot reject or disable their own account. No account state changed.',
                refresh: true,
                authorityLost: false,
            };
        }
        return {
            message: 'The account changed after this page loaded. No change was claimed; the latest state has been refreshed.',
            refresh: true,
            authorityLost: false,
        };
    }
    return {
        message: 'The administrative action could not be completed. No change is being shown as successful.',
        refresh: false,
        authorityLost: false,
    };
};

export const auditReasonLabel = (reasonCode?: string | null): string | null => {
    if (reasonCode === 'SELF_ACTION_PROHIBITED') return 'Self-action blocked';
    if (reasonCode === 'LAST_EFFECTIVE_ADMIN') return 'Last-admin protection';
    if (reasonCode === 'INVALID_LIFECYCLE_TRANSITION') return 'Invalid or stale account state';
    if (reasonCode === 'STALE_ACTOR_AUTHORITY') return 'Administrator authority changed';
    if (reasonCode === 'TRANSACTION_FAILED') return 'Transaction failed; no state changed';
    return null;
};

export const safeStateSummary = (state?: Record<string, unknown> | null): string[] => {
    if (!state) return [];
    const rows: string[] = [];
    if (typeof state.approval_status === 'string') {
        rows.push(`Account status: ${statusLabel(state.approval_status)}`);
    }
    if (typeof state.company_approval_status === 'string') {
        rows.push(`Company status: ${statusLabel(state.company_approval_status)}`);
    }
    if (state.credentials_invalidated === true) {
        rows.push('Credentials invalidated: Yes');
    }
    const user = state.user;
    if (user && typeof user === 'object') {
        const nested = user as Record<string, unknown>;
        if (typeof nested.approval_status === 'string') {
            rows.push(`Account status: ${statusLabel(nested.approval_status)}`);
        }
        if (nested.credentials_invalidated === true) {
            rows.push('Credentials invalidated: Yes');
        }
    }
    return [...new Set(rows)];
};
