/**
 * Deterministic fact chips (D1-08). They replace the Hunter numeric score and the
 * generated rationale everywhere: each chip states one checkable fact, computed from
 * existing data, with no number that lacks a meaning.
 *
 *   country   the tender's country is one of the profile's target countries
 *   service   a profile target service is found in the tender (server-computed match)
 *   notice    the notice type: expression of interest / invitation for bids / prequalification
 *   daysLeft  whole days until the deadline (only while it has not passed)
 *
 * Pure functions so node tests can run them directly.
 */

export type NoticeKind = 'eoi' | 'ifb' | 'prequalification';

export type FactChip =
    | {kind: 'country'; country: string}
    | {kind: 'service'; service: string}
    | {kind: 'noticeType'; type: NoticeKind}
    | {kind: 'daysLeft'; days: number};

export type ProfileMatch = {country?: string | null; services?: string[] | null} | null | undefined;

export type FactTender = {
    deadline?: string | null;
    notice_type?: string | null;
    status?: string | null;
};

const NOTICE_PATTERNS: ReadonlyArray<readonly [NoticeKind, RegExp]> = [
    ['prequalification', /pre-?\s?qualification/i],
    ['eoi', /expression[s]? of interest|\bR?EOI\b/i],
    ['ifb', /invitation (for|to) bid[s]?|request for bid[s]?|\bIFB\b|\bRFB\b|\bITB\b/i],
];

export function noticeKind(noticeType: string | null | undefined): NoticeKind | null {
    const text = (noticeType ?? '').trim();
    if (!text) return null;
    return NOTICE_PATTERNS.find(([, pattern]) => pattern.test(text))?.[0] ?? null;
}

/**
 * Whole days until the deadline, or null when there is no readable deadline or it has
 * passed. Reads the stored deadline directly; session A's truthful helper
 * (lib/tenderTruth `daysLeft`, conservative effective instant) replaces this after the rebase.
 */
export function deadlineDaysLeft(deadline: string | null | undefined, now: number = Date.now()): number | null {
    if (!deadline) return null;
    const time = new Date(deadline).getTime();
    if (!Number.isFinite(time) || time < now) return null;
    return Math.ceil((time - now) / (1000 * 60 * 60 * 24));
}

export function deriveFactChips(
    tender: FactTender,
    profileMatch: ProfileMatch,
    now: number = Date.now(),
): FactChip[] {
    const chips: FactChip[] = [];
    const country = profileMatch?.country?.trim();
    if (country) chips.push({kind: 'country', country});
    for (const service of profileMatch?.services ?? []) {
        if (service?.trim()) chips.push({kind: 'service', service: service.trim()});
    }
    const notice = noticeKind(tender.notice_type);
    if (notice) chips.push({kind: 'noticeType', type: notice});
    const days = deadlineDaysLeft(tender.deadline, now);
    if (days !== null) chips.push({kind: 'daysLeft', days});
    return chips;
}

/** A tender "matches your profile" when at least one country or service fact holds. */
export function matchesProfile(profileMatch: ProfileMatch): boolean {
    return Boolean(profileMatch?.country?.trim() || (profileMatch?.services ?? []).some((value) => value?.trim()));
}
