/**
 * Team section (R3 Task 1): types and pure helpers, free of runtime imports so the
 * node test runner can load them. Requests live in ./teamApi.
 */

export type MemberRole = 'OWNER' | 'MEMBER';
export type MemberState = 'INVITED' | 'ACTIVE' | 'REVOKED';
export type InvitationStatus = 'OPEN' | 'EXPIRED' | 'ACCEPTED' | 'REVOKED';
export type EmailDelivery = 'QUEUED' | 'DISABLED' | 'SKIPPED';

export type TeamMember = {
    membership_id: string;
    organization_id: string;
    user_id: string;
    role: MemberRole;
    state: MemberState;
    created_at: string;
    activated_at?: string | null;
    revoked_at?: string | null;
    user_name?: string | null;
    user_email?: string | null;
};

export type TeamInvitation = {
    invitation_id: string;
    organization_id: string;
    email: string;
    role: MemberRole;
    status: InvitationStatus;
    invited_by_name?: string | null;
    expires_at: string;
    created_at: string;
    last_sent_at: string;
    send_count: number;
    accepted_at?: string | null;
    revoked_at?: string | null;
    invite_path?: string | null;
    invite_url?: string | null;
    email_delivery?: EmailDelivery | null;
};

export type InvitationPreview = {
    organization_name: string | null;
    inviter_name: string | null;
    role: MemberRole;
    email_hint: string;
    expires_at: string;
};

/** The absolute link to copy: the backend's URL when configured, else this origin + path. */
export function invitationLink(invitation: Pick<TeamInvitation, 'invite_url' | 'invite_path'>, origin: string): string | null {
    if (invitation.invite_url) return invitation.invite_url;
    if (!invitation.invite_path) return null;
    return `${origin.replace(/\/+$/, '')}${invitation.invite_path}`;
}

/** Pending = still actionable by the OWNER (open or expired); accepted and revoked are history. */
export function pendingInvitations(invitations: readonly TeamInvitation[]): TeamInvitation[] {
    return invitations.filter((item) => item.status === 'OPEN' || item.status === 'EXPIRED');
}

export function invitationTone(status: InvitationStatus): 'success' | 'warning' | 'neutral' | 'danger' {
    if (status === 'OPEN') return 'success';
    if (status === 'EXPIRED') return 'warning';
    if (status === 'REVOKED') return 'danger';
    return 'neutral';
}

export function memberTone(state: MemberState): 'success' | 'warning' | 'neutral' {
    return state === 'ACTIVE' ? 'success' : state === 'INVITED' ? 'warning' : 'neutral';
}

/** Active members first, then invited, then revoked; owners before members; then by name. */
export function sortMembers(members: readonly TeamMember[]): TeamMember[] {
    const stateRank: Record<MemberState, number> = { ACTIVE: 0, INVITED: 1, REVOKED: 2 };
    return [...members].sort((left, right) =>
        stateRank[left.state] - stateRank[right.state]
        || (left.role === right.role ? 0 : left.role === 'OWNER' ? -1 : 1)
        || (left.user_name ?? left.user_email ?? '').localeCompare(right.user_name ?? right.user_email ?? ''));
}

export type TeamErrorKey =
    | 'alreadyMember' | 'alreadyInvited' | 'tooMany' | 'emailMismatch'
    | 'invalidEmail' | 'ownerOnly' | 'lastOwner' | 'failed';

/** Maps a backend 409/403 detail to a message key under ``settings.team.errors``. */
export function invitationErrorKey(error: unknown): TeamErrorKey {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
    const detail = response?.data?.detail;
    const code = typeof detail === 'object' && detail && 'code' in detail ? String((detail as { code: unknown }).code) : '';
    if (code === 'ALREADY_MEMBER') return 'alreadyMember';
    if (code === 'ALREADY_INVITED') return 'alreadyInvited';
    if (code === 'TOO_MANY_OPEN') return 'tooMany';
    if (code === 'EMAIL_MISMATCH') return 'emailMismatch';
    if (response?.status === 422) return 'invalidEmail';
    if (response?.status === 403) return 'ownerOnly';
    if (response?.status === 409 && typeof detail === 'string' && /owner/i.test(detail)) return 'lastOwner';
    return 'failed';
}
