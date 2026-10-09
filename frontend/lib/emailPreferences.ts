/** R3 Task 4: e-mail notification preferences (GET/PUT /users/me/email-preferences). Import-free. */

export type EmailPreferences = {
    email_channel_enabled: boolean;
    analysis_enabled: boolean;
    eoi_enabled: boolean;
    digest_enabled: boolean;
    digest_schedule: string;
};

export type EmailPreferenceField = 'analysis_enabled' | 'eoi_enabled' | 'digest_enabled';

export const EMAIL_PREFERENCE_FIELDS: readonly { field: EmailPreferenceField; labelKey: 'analysis' | 'eoi' | 'digest' }[] = [
    { field: 'analysis_enabled', labelKey: 'analysis' },
    { field: 'eoi_enabled', labelKey: 'eoi' },
    { field: 'digest_enabled', labelKey: 'digest' },
];

/** Only switches that differ from what is saved are sent; unchanged ones keep their defaults. */
export function emailPreferenceChanges(saved: EmailPreferences, draft: EmailPreferences): Partial<Record<EmailPreferenceField, boolean>> {
    const changes: Partial<Record<EmailPreferenceField, boolean>> = {};
    for (const { field } of EMAIL_PREFERENCE_FIELDS) {
        if (saved[field] !== draft[field]) changes[field] = draft[field];
    }
    return changes;
}
