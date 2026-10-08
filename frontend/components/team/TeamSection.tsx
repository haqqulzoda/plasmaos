'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Copy, MailPlus, RefreshCw, UserMinus, Users, XCircle } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { Button } from '@/components/ui/Button';
import { SectionHeader, StatusBadge, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Input, Select } from '@/components/ui/Forms';
import { Dialog } from '@/components/ui/Overlay';
import { formatDate } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import {
    changeMemberRole,
    invitationErrorKey,
    invitationLink,
    invitationTone,
    inviteByEmail,
    listInvitations,
    listMembers,
    memberTone,
    pendingInvitations,
    resendInvitation,
    revokeInvitation,
    revokeMember,
    sortMembers,
    type MemberRole,
    type TeamInvitation,
    type TeamErrorKey,
    type TeamMember,
} from '@/lib/teamApi';
import type { OrganizationSummary } from '@/types/pursuit';

type Issued = { email: string; link: string; delivery: TeamInvitation['email_delivery'] };

export function TeamSection() {
    const t = useTranslations('settings.team');
    const locale = useLocale() as CustomerSelectableLocale;
    const [organizationId, setOrganizationId] = useState('');
    const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
    const [members, setMembers] = useState<TeamMember[]>([]);
    const [invitations, setInvitations] = useState<TeamInvitation[]>([]);
    const [loading, setLoading] = useState(false);
    const [loadFailed, setLoadFailed] = useState(false);
    const [email, setEmail] = useState('');
    const [role, setRole] = useState<MemberRole>('MEMBER');
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<TeamErrorKey | null>(null);
    const [issued, setIssued] = useState<Issued | null>(null);
    const [copied, setCopied] = useState(false);
    const [confirmRevoke, setConfirmRevoke] = useState<TeamMember | null>(null);
    const [version, setVersion] = useState(0);

    const current = organizations.find((item) => item.organization_id === organizationId);
    const isOwner = current?.membership_role === 'OWNER';
    const chooseOrganization = useCallback((value: string) => {
        setOrganizationId(value); setIssued(null); setError(null);
    }, []);

    useEffect(() => {
        if (!organizationId || !isOwner) return;
        let cancelled = false;
        setLoading(true);
        setLoadFailed(false);
        Promise.all([listMembers(organizationId), listInvitations(organizationId)])
            .then(([loadedMembers, loadedInvitations]) => {
                if (cancelled) return;
                setMembers(sortMembers(loadedMembers));
                setInvitations(loadedInvitations);
            })
            .catch(() => { if (!cancelled) setLoadFailed(true); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [organizationId, isOwner, version]);

    const reload = () => setVersion((value) => value + 1);
    const showIssued = (invitation: TeamInvitation) => {
        const link = invitationLink(invitation, window.location.origin);
        if (link) setIssued({ email: invitation.email, link, delivery: invitation.email_delivery ?? null });
        setCopied(false);
    };
    const run = async (key: string, action: () => Promise<void>) => {
        setBusy(key);
        setError(null);
        try {
            await action();
        } catch (failure) {
            setError(invitationErrorKey(failure));
        } finally {
            setBusy(null);
        }
    };

    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        void run('invite', async () => {
            const invitation = await inviteByEmail(organizationId, email.trim(), role);
            showIssued(invitation);
            setEmail('');
            setRole('MEMBER');
            reload();
        });
    };
    const copyLink = async (link: string) => {
        try {
            await navigator.clipboard.writeText(link);
            setCopied(true);
        } catch {
            setCopied(false);
        }
    };

    const pending = pendingInvitations(invitations);
    const activeOwners = members.filter((member) => member.state === 'ACTIVE' && member.role === 'OWNER').length;

    return <Surface className="profile-section team-section" aria-labelledby="team-title" data-team-section>
        <SectionHeader title={<span id="team-title">{t('title')}</span>} description={t('help')} />
        <OrganizationContextPicker value={organizationId} onChange={chooseOrganization} onOrganizations={setOrganizations} />
        {current && !isOwner && <Alert tone="info" title={t('ownerOnlyTitle')}>{t('ownerOnlyHelp')}</Alert>}
        {error && <Alert tone="danger" title={t(`errors.${error}`)} onDismiss={() => setError(null)} dismissLabel={t('dismiss')} />}
        {isOwner && loadFailed && <Alert tone="danger" title={t('loadFailed')}
            action={<Button variant="secondary" onClick={reload}><RefreshCw aria-hidden />{t('retry')}</Button>} />}
        {isOwner && <>
            <div className="team-block" data-team-members>
                <h3><Users aria-hidden /> {t('members.title')}</h3>
                {loading && !members.length ? <p role="status" className="ds-muted">{t('loading')}</p> : <ul className="team-list">
                    {members.map((member) => {
                        const self = member.membership_id === current?.membership_id;
                        const lastOwner = member.role === 'OWNER' && member.state === 'ACTIVE' && activeOwners <= 1;
                        return <li key={member.membership_id} className="team-row" data-member-row>
                            <div className="team-identity">
                                <strong><BidiText>{member.user_name || member.user_email || t('members.unnamed')}</BidiText></strong>
                                {member.user_email && <TechnicalText>{member.user_email}</TechnicalText>}
                            </div>
                            <StatusBadge tone={memberTone(member.state)}>{t(`members.states.${member.state}`)}</StatusBadge>
                            {member.state === 'ACTIVE' && !self ? <Select
                                label={t('members.role')}
                                value={member.role}
                                disabled={busy !== null || lastOwner}
                                onChange={(event) => void run(`role:${member.membership_id}`, async () => {
                                    await changeMemberRole(organizationId, member.membership_id, event.target.value as MemberRole);
                                    reload();
                                })}
                            >
                                <option value="MEMBER">{t('roles.MEMBER')}</option>
                                <option value="OWNER">{t('roles.OWNER')}</option>
                            </Select> : <span className="ds-muted">{t(`roles.${member.role}`)}{self ? ` · ${t('members.you')}` : ''}</span>}
                            {member.state !== 'REVOKED' && !self && <Button variant="secondary" size="sm"
                                disabled={busy !== null || lastOwner}
                                onClick={() => setConfirmRevoke(member)}>
                                <UserMinus aria-hidden />{t('members.revoke')}
                            </Button>}
                        </li>;
                    })}
                </ul>}
            </div>

            <form className="team-block team-invite" onSubmit={submit} data-team-invite>
                <h3><MailPlus aria-hidden /> {t('invite.title')}</h3>
                <p className="ds-muted">{t('invite.help')}</p>
                <div className="team-invite-fields">
                    <Input label={t('invite.email')} type="email" dir="ltr" required autoComplete="off"
                        value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy !== null} />
                    <Select label={t('invite.role')} value={role} disabled={busy !== null}
                        onChange={(event) => setRole(event.target.value as MemberRole)}>
                        <option value="MEMBER">{t('roles.MEMBER')}</option>
                        <option value="OWNER">{t('roles.OWNER')}</option>
                    </Select>
                    <Button type="submit" loading={busy === 'invite'} disabled={busy !== null || !email.trim()}>
                        {t('invite.submit')}
                    </Button>
                </div>
            </form>

            {issued && <Alert tone="success" title={t('link.title', { email: issued.email })}
                onDismiss={() => setIssued(null)} dismissLabel={t('dismiss')}>
                {issued.delivery === 'QUEUED' ? t('link.emailQueued') : issued.delivery === 'SKIPPED' ? t('link.linkOnly') : t('link.emailDisabled')}
            </Alert>}
            {issued && <div className="team-link ds-row" data-invite-link>
                <Input label={t('link.label')} value={issued.link} readOnly dir="ltr" onFocus={(event) => event.target.select()} />
                <Button variant="secondary" onClick={() => void copyLink(issued.link)}>
                    <Copy aria-hidden />{copied ? t('link.copied') : t('link.copy')}
                </Button>
            </div>}

            <div className="team-block" data-team-pending>
                <h3>{t('pending.title')}</h3>
                {!pending.length ? <p className="ds-muted">{t('pending.empty')}</p> : <ul className="team-list">
                    {pending.map((invitation) => <li key={invitation.invitation_id} className="team-row" data-invitation-row>
                        <div className="team-identity">
                            <TechnicalText>{invitation.email}</TechnicalText>
                            <span className="ds-muted ds-text-small">
                                {t('pending.meta', {
                                    role: t(`roles.${invitation.role}`),
                                    date: formatDate(invitation.expires_at, locale),
                                    count: invitation.send_count,
                                })}
                            </span>
                        </div>
                        <StatusBadge tone={invitationTone(invitation.status)}>{t(`pending.states.${invitation.status}`)}</StatusBadge>
                        <div className="ds-row team-actions">
                            <Button variant="secondary" size="sm" title={t('pending.copyHelp')} disabled={busy !== null}
                                loading={busy === `copy:${invitation.invitation_id}`}
                                onClick={() => void run(`copy:${invitation.invitation_id}`, async () => {
                                    const fresh = await resendInvitation(organizationId, invitation.invitation_id, false);
                                    showIssued(fresh);
                                    const link = invitationLink(fresh, window.location.origin);
                                    if (link) await copyLink(link);
                                    reload();
                                })}>
                                <Copy aria-hidden />{t('pending.copy')}
                            </Button>
                            <Button variant="secondary" size="sm" disabled={busy !== null}
                                loading={busy === `resend:${invitation.invitation_id}`}
                                onClick={() => void run(`resend:${invitation.invitation_id}`, async () => {
                                    showIssued(await resendInvitation(organizationId, invitation.invitation_id, true));
                                    reload();
                                })}>
                                <RefreshCw aria-hidden />{t('pending.resend')}
                            </Button>
                            <Button variant="secondary" size="sm" disabled={busy !== null}
                                loading={busy === `revoke:${invitation.invitation_id}`}
                                onClick={() => void run(`revoke:${invitation.invitation_id}`, async () => {
                                    await revokeInvitation(organizationId, invitation.invitation_id);
                                    if (issued?.email === invitation.email) setIssued(null);
                                    reload();
                                })}>
                                <XCircle aria-hidden />{t('pending.revoke')}
                            </Button>
                        </div>
                    </li>)}
                </ul>}
            </div>
        </>}
        <Dialog open={confirmRevoke !== null} onClose={() => setConfirmRevoke(null)} closeLabel={t('dismiss')}
            title={t('members.revokeTitle')}
            description={t('members.revokeHelp', { name: confirmRevoke?.user_name || confirmRevoke?.user_email || '' })}
            footer={<>
                <Button variant="secondary" onClick={() => setConfirmRevoke(null)}>{t('cancel')}</Button>
                <Button loading={busy === 'revoke-member'} onClick={() => {
                    const target = confirmRevoke;
                    if (!target) return;
                    void run('revoke-member', async () => {
                        await revokeMember(organizationId, target.membership_id);
                        setConfirmRevoke(null);
                        reload();
                    });
                }}>{t('members.revokeConfirm')}</Button>
            </>}>
            <p className="ds-muted">{t('members.revokeDetail')}</p>
        </Dialog>
    </Surface>;
}
