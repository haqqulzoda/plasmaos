'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { signIn, signOut, useSession } from 'next-auth/react';
import { useLocale, useTranslations } from 'next-intl';
import { MailCheck } from 'lucide-react';

import { PlasmaLogo } from '@/components/brand/PlasmaLogo';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { LanguageSelector } from '@/components/i18n/LanguageSelector';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { formatDate } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { acceptInvitation, invitationErrorKey, previewInvitation, type InvitationPreview } from '@/lib/teamApi';

/**
 * Invitation landing page (R3 Task 1). The token only identifies the invitation; joining
 * happens at Google sign-in when the verified e-mail equals the invited address exactly.
 */
export default function InvitePage() {
    const t = useTranslations('auth.invite');
    const roles = useTranslations('settings.team.roles');
    const locale = useLocale() as CustomerSelectableLocale;
    const { token } = useParams<{ token: string }>();
    const { status } = useSession();
    const [preview, setPreview] = useState<InvitationPreview | null>(null);
    const [missing, setMissing] = useState(false);
    const [busy, setBusy] = useState(false);
    const [accepted, setAccepted] = useState(false);
    const [error, setError] = useState<'emailMismatch' | 'notApproved' | 'failed' | null>(null);
    const returnUrl = `/invite/${encodeURIComponent(token)}`;

    useEffect(() => {
        let cancelled = false;
        previewInvitation(token)
            .then((data) => { if (!cancelled) setPreview(data); })
            .catch(() => { if (!cancelled) setMissing(true); });
        return () => { cancelled = true; };
    }, [token]);

    const accept = async () => {
        setBusy(true);
        setError(null);
        try {
            await acceptInvitation(token);
            setAccepted(true);
        } catch (failure) {
            const key = invitationErrorKey(failure);
            const detail = (failure as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail;
            setError(key === 'emailMismatch' ? 'emailMismatch' : detail?.code === 'ORGANIZATION_NOT_APPROVED' ? 'notApproved' : 'failed');
        } finally {
            setBusy(false);
        }
    };
    // Approval changes the account's authority, so a fresh sign-in opens the workspace.
    const openWorkspace = () => signIn('google', { callbackUrl: '/dashboard' });

    const organization = preview?.organization_name || t('unknownOrganization');
    const role = preview ? roles(preview.role) : '';

    return <main className="ds-theme invite-page" data-invite-page>
        <Surface className="invite-card" aria-labelledby="invite-title">
            <header className="auth-header"><PlasmaLogo /><LanguageSelector surface="auth" /></header>
            <span className="ds-eyebrow"><MailCheck aria-hidden /> {t('eyebrow')}</span>
            {/* The preview answers only for a usable invitation: unknown, expired, revoked and accepted
                links all read "not found" (a signed-in invitee may already have joined at sign-in). */}
            {missing && !accepted ? <Alert tone="warning" title={t('notFound')}
                action={status === 'authenticated' ? <ButtonLink href="/dashboard">{t('goToWorkspace')}</ButtonLink> : undefined} />
            : !preview ? <p role="status" className="ds-muted">{t('loading')}</p> : <>
                <h1 id="invite-title"><BidiText>{t('title', { organization })}</BidiText></h1>
                <p><BidiText>{preview.inviter_name
                    ? t('body', { inviter: preview.inviter_name, role })
                    : t('bodyNoInviter', { role })}</BidiText></p>
                {accepted ? <>
                    <Alert tone="success" title={t('accepted')} />
                    <Button onClick={openWorkspace}>{t('goToWorkspace')}</Button>
                </> : <>
                    <p className="ds-muted">{t('emailHint', { email: preview.email_hint })}</p>
                    <p><TechnicalText>{preview.email_hint}</TechnicalText></p>
                    <p className="ds-muted ds-text-small">{t('expires', { date: formatDate(preview.expires_at, locale) })}</p>
                    {error && <Alert tone="danger" title={t(`errors.${error}`)}
                        action={error === 'emailMismatch' ? <Button variant="secondary" onClick={() => signOut({ callbackUrl: returnUrl })}>{t('signOut')}</Button> : undefined} />}
                    {status === 'authenticated'
                        ? <Button loading={busy} onClick={() => void accept()}>{t('accept')}</Button>
                        : <Button loading={status === 'loading'} onClick={() => signIn('google', { callbackUrl: returnUrl })}>{t('signIn')}</Button>}
                </>}
            </>}
        </Surface>
    </main>;
}
