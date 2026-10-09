'use client';

import { useEffect, useState } from 'react';
import { Mail } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/Button';
import { SectionHeader, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import { EMAIL_PREFERENCE_FIELDS, emailPreferenceChanges, type EmailPreferences } from '@/lib/emailPreferences';

/** R3 Task 4: per-user e-mail switches. Reading never stores anything; saving sends changes only. */
export function EmailNotificationSettings() {
    const t = useTranslations('settings.emailNotifications');
    const [saved, setSaved] = useState<EmailPreferences | null>(null);
    const [draft, setDraft] = useState<EmailPreferences | null>(null);
    const [busy, setBusy] = useState(false);
    const [state, setState] = useState<'loadFailed' | 'saveFailed' | 'saved' | null>(null);

    useEffect(() => {
        let cancelled = false;
        api.get<EmailPreferences>('/users/me/email-preferences')
            .then(({ data }) => { if (!cancelled) { setSaved(data); setDraft(data); } })
            .catch(() => { if (!cancelled) setState('loadFailed'); });
        return () => { cancelled = true; };
    }, []);

    const changes = saved && draft ? emailPreferenceChanges(saved, draft) : {};
    const save = async () => {
        setBusy(true);
        setState(null);
        try {
            const { data } = await api.put<EmailPreferences>('/users/me/email-preferences', changes);
            setSaved(data);
            setDraft(data);
            setState('saved');
        } catch {
            setState('saveFailed');
        } finally {
            setBusy(false);
        }
    };

    return <Surface className="profile-section" id="email-notifications" aria-labelledby="email-notifications-title" data-email-settings>
        <SectionHeader title={<span id="email-notifications-title"><Mail aria-hidden /> {t('title')}</span>} description={t('help')} />
        {state === 'loadFailed' && <Alert tone="danger" title={t('loadFailed')} />}
        {draft && !draft.email_channel_enabled && <Alert tone="info" title={t('channelOff')} />}
        {draft && <div className="email-preferences">
            {EMAIL_PREFERENCE_FIELDS.map(({ field, labelKey }) => <div key={field} className="email-preference">
                <Checkbox label={t(labelKey)} checked={draft[field]} disabled={busy}
                    onChange={(event) => { setDraft({ ...draft, [field]: event.target.checked }); setState(null); }} />
                <p className="ds-muted ds-text-small">{labelKey === 'digest'
                    ? t('digestHelp', { time: draft.digest_schedule })
                    : t(`${labelKey}Help`)}</p>
            </div>)}
            <div className="ds-row">
                <Button onClick={() => void save()} loading={busy} disabled={!Object.keys(changes).length}>{t('save')}</Button>
                {state === 'saved' && <span role="status" className="ds-muted">{t('saved')}</span>}
            </div>
            {state === 'saveFailed' && <Alert tone="danger" title={t('saveFailed')} />}
        </div>}
    </Surface>;
}
