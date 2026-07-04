export type ReadinessOption = {
    value: string;
    label: string;
};

export type ExpiryState = 'expired' | 'expiring_soon' | 'valid' | 'none';

export const DOCUMENT_TYPE_OPTIONS: ReadinessOption[] = [
    { value: 'license', label: 'License' },
    { value: 'certificate', label: 'Certificate' },
    { value: 'tax_clearance', label: 'Tax Clearance' },
    { value: 'financial_statement', label: 'Financial Statement' },
    { value: 'registration_document', label: 'Registration Document' },
    { value: 'power_of_attorney', label: 'Power of Attorney' },
    { value: 'personnel_document', label: 'Personnel Document' },
    { value: 'other', label: 'Other' },
];

export const DOCUMENT_STATUS_OPTIONS: ReadinessOption[] = [
    { value: 'available', label: 'Available' },
    { value: 'missing', label: 'Missing' },
    { value: 'expired', label: 'Expired' },
    { value: 'unknown', label: 'Unknown' },
];

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
