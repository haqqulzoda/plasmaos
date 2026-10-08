/**
 * Team section (R3 Task 1): members and e-mail invitations of one organization.
 * Every call names the organization in the path; the backend requires an OWNER membership.
 */
import { api } from './api';

import type { InvitationPreview, MemberRole, TeamInvitation, TeamMember } from './team';

export * from './team';

const base = (organizationId: string) => `/organizations/${encodeURIComponent(organizationId)}`;

export async function listMembers(organizationId: string): Promise<TeamMember[]> {
    return (await api.get<TeamMember[]>(`${base(organizationId)}/members`)).data;
}

export async function listInvitations(organizationId: string): Promise<TeamInvitation[]> {
    return (await api.get<TeamInvitation[]>(`${base(organizationId)}/invitations-by-email`)).data;
}

export async function inviteByEmail(organizationId: string, email: string, role: MemberRole): Promise<TeamInvitation> {
    return (await api.post<TeamInvitation>(`${base(organizationId)}/invitations-by-email`, { email, role })).data;
}

/** A new link every time: the previous link stops working. ``sendEmail: false`` only issues the link. */
export async function resendInvitation(organizationId: string, invitationId: string, sendEmail: boolean): Promise<TeamInvitation> {
    return (await api.post<TeamInvitation>(
        `${base(organizationId)}/invitations-by-email/${encodeURIComponent(invitationId)}/resend`,
        { send_email: sendEmail },
    )).data;
}

export async function revokeInvitation(organizationId: string, invitationId: string): Promise<TeamInvitation> {
    return (await api.post<TeamInvitation>(
        `${base(organizationId)}/invitations-by-email/${encodeURIComponent(invitationId)}/revoke`,
    )).data;
}

export async function changeMemberRole(organizationId: string, membershipId: string, role: MemberRole): Promise<TeamMember> {
    return (await api.patch<TeamMember>(`${base(organizationId)}/members/${encodeURIComponent(membershipId)}/role`, { role })).data;
}

export async function revokeMember(organizationId: string, membershipId: string): Promise<TeamMember> {
    return (await api.post<TeamMember>(`${base(organizationId)}/members/${encodeURIComponent(membershipId)}/revoke`, {})).data;
}

export async function previewInvitation(token: string): Promise<InvitationPreview> {
    return (await api.post<InvitationPreview>('/invitations/preview', { token })).data;
}

export async function acceptInvitation(token: string): Promise<TeamMember> {
    return (await api.post<TeamMember>('/invitations/accept', { token })).data;
}
