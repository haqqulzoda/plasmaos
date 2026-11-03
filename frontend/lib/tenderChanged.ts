/**
 * Tender-change alerts: the source changes (new deadline, amendment, new document) made to a
 * pursued tender after its analysis. Pure and import-free for the node test runner.
 */

export const TENDER_CHANGE_KINDS = ['DEADLINE', 'AMENDMENT', 'DOCUMENT'] as const;
export type TenderChangeKind = (typeof TENDER_CHANGE_KINDS)[number];

/** Known kinds in a stable order; unknown codes from a newer backend are dropped. */
export function tenderChangeKinds(kinds: readonly string[] | null | undefined): TenderChangeKind[] {
    const present = new Set(kinds ?? []);
    return TENDER_CHANGE_KINDS.filter((kind) => present.has(kind));
}
