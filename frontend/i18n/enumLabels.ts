import type {TenderStatus} from '@/types/tender';

export type EnumLabelTranslator = (key: string) => string;

export function tenderStatusMessageKey(status: TenderStatus | string): string {
    if (status === 'OPEN') return 'tenderStatus.open';
    if (status === 'CLOSED') return 'tenderStatus.closed';
    if (status === 'CANCELLED') return 'tenderStatus.cancelled';
    return 'tenderStatus.unknown';
}

export function translateTenderStatus(
    status: TenderStatus | string,
    translate: EnumLabelTranslator,
): string {
    return translate(tenderStatusMessageKey(status));
}
