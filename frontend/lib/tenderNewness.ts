export interface ServerClockReference {
    serverEpochMs: number;
    browserMonotonicMs: number;
}

export const createServerClockReference = (
    serverTime: string,
    browserMonotonicMs: number,
): ServerClockReference | null => {
    const serverEpochMs = Date.parse(serverTime);
    if (!Number.isFinite(serverEpochMs) || !Number.isFinite(browserMonotonicMs)) return null;
    return { serverEpochMs, browserMonotonicMs };
};

export const adjustedServerNow = (
    reference: ServerClockReference,
    browserMonotonicMs: number,
): number => reference.serverEpochMs + Math.max(0, browserMonotonicMs - reference.browserMonotonicMs);

export const shouldShowNewBadge = (
    backendIsNew: boolean,
    newUntil: string,
    reference: ServerClockReference | null,
    browserMonotonicMs: number,
): boolean => {
    if (!backendIsNew || !reference) return false;
    const expiry = Date.parse(newUntil);
    if (!Number.isFinite(expiry)) return false;
    return adjustedServerNow(reference, browserMonotonicMs) < expiry;
};

export const nextBadgeTickDelay = (
    newUntilValues: string[],
    reference: ServerClockReference | null,
    browserMonotonicMs: number,
): number => {
    if (!reference) return 60_000;
    const now = adjustedServerNow(reference, browserMonotonicMs);
    const remaining = newUntilValues
        .map((value) => Date.parse(value) - now)
        .filter((value) => Number.isFinite(value) && value > 0);
    if (!remaining.length) return 60_000;
    return Math.max(250, Math.min(60_000, Math.min(...remaining)));
};
