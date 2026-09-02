export const EXPLORER_PATH = '/dashboard/tenders';
export const EXPLORER_RETURN_STATE_KEY = 'plasmaos:tender-explorer:return';

export interface ExplorerReturnState {
    explorerUrl: string;
    tenderId: string;
    scrollY: number;
    page: number;
    createdAt: number;
}

const isExplorerUrl = (value: string): boolean =>
    value === EXPLORER_PATH || value.startsWith(`${EXPLORER_PATH}?`);

export function writeExplorerReturnState(state: ExplorerReturnState): void {
    if (typeof window === 'undefined' || !isExplorerUrl(state.explorerUrl)) return;
    window.sessionStorage.setItem(EXPLORER_RETURN_STATE_KEY, JSON.stringify(state));
}

export function readExplorerReturnState(): ExplorerReturnState | null {
    if (typeof window === 'undefined') return null;
    const rawState = window.sessionStorage.getItem(EXPLORER_RETURN_STATE_KEY);
    if (!rawState) return null;

    try {
        const parsed = JSON.parse(rawState) as Partial<ExplorerReturnState>;
        if (
            typeof parsed.explorerUrl !== 'string'
            || !isExplorerUrl(parsed.explorerUrl)
            || typeof parsed.tenderId !== 'string'
            || typeof parsed.scrollY !== 'number'
            || !Number.isFinite(parsed.scrollY)
            || typeof parsed.page !== 'number'
            || !Number.isInteger(parsed.page)
            || parsed.page < 1
            || typeof parsed.createdAt !== 'number'
            || !Number.isFinite(parsed.createdAt)
        ) {
            window.sessionStorage.removeItem(EXPLORER_RETURN_STATE_KEY);
            return null;
        }
        return parsed as ExplorerReturnState;
    } catch {
        window.sessionStorage.removeItem(EXPLORER_RETURN_STATE_KEY);
        return null;
    }
}

export function clearExplorerReturnState(): void {
    if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem(EXPLORER_RETURN_STATE_KEY);
    }
}
