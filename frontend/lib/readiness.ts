export type ReadinessOption = {
    value: string;
    label: string;
    messageKey: string;
};

export type ExpiryState = 'expired' | 'expiring_soon' | 'valid' | 'none';

export const DOCUMENT_TYPE_OPTIONS: ReadinessOption[] = [
    { value: 'license', label: 'License', messageKey: 'types.license' },
    { value: 'certificate', label: 'Certificate', messageKey: 'types.certificate' },
    { value: 'tax_clearance', label: 'Tax Clearance', messageKey: 'types.taxClearance' },
    { value: 'financial_statement', label: 'Financial Statement', messageKey: 'types.financialStatement' },
    { value: 'registration_document', label: 'Registration Document', messageKey: 'types.registrationDocument' },
    { value: 'power_of_attorney', label: 'Power of Attorney', messageKey: 'types.powerOfAttorney' },
    { value: 'personnel_document', label: 'Personnel Document', messageKey: 'types.personnelDocument' },
    { value: 'other', label: 'Other', messageKey: 'types.other' },
];

export const DOCUMENT_STATUS_OPTIONS: ReadinessOption[] = [
    { value: 'available', label: 'Available', messageKey: 'statuses.available' },
    { value: 'missing', label: 'Missing', messageKey: 'statuses.missing' },
    { value: 'expired', label: 'Expired', messageKey: 'statuses.expired' },
    { value: 'unknown', label: 'Unknown', messageKey: 'statuses.unknown' },
];

export function documentTypeMessageKey(value: string | null | undefined): string {
    return DOCUMENT_TYPE_OPTIONS.find((option) => option.value === value)?.messageKey ?? 'types.unknown';
}

export function documentStatusMessageKey(value: string | null | undefined): string {
    return DOCUMENT_STATUS_OPTIONS.find((option) => option.value === value)?.messageKey ?? 'statuses.unknown';
}

export function expiryMessageKey(state: ExpiryState): string {
    if (state === 'expired') return 'expiry.expired';
    if (state === 'expiring_soon') return 'expiry.expiringSoon';
    if (state === 'valid') return 'expiry.valid';
    return 'expiry.unknown';
}

export function labelForDocumentType(value: string | null | undefined): string {
    if (!value) {
        return '';
    }
    return DOCUMENT_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function labelForDocumentStatus(value: string | null | undefined): string {
    if (!value) {
        return '';
    }
    return DOCUMENT_STATUS_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function expiryState(expiryDate?: string | null, now = new Date()): ExpiryState {
    if (!expiryDate) {
        return 'none';
    }

    const expiry = new Date(`${expiryDate}T00:00:00`);
    if (Number.isNaN(expiry.getTime())) {
        return 'none';
    }

    const today = new Date(now);
    today.setHours(0, 0, 0, 0);

    if (expiry < today) {
        return 'expired';
    }

    const msUntilExpiry = expiry.getTime() - today.getTime();
    const daysUntilExpiry = msUntilExpiry / (1000 * 60 * 60 * 24);
    return daysUntilExpiry <= 30 ? 'expiring_soon' : 'valid';
}

export function labelForExpiryState(state: ExpiryState): string {
    if (state === 'expired') return 'Expired';
    if (state === 'expiring_soon') return 'Expiring Soon';
    return '';
}
