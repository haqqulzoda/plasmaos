/**
 * Tender truth on every customer surface (D1-05, D1-05b, D1-05c).
 *
 * - Budgets: null, zero, negative or non-finite is "Not published", never an amount.
 * - Deadlines: the API sends the published wall time (`deadline`, stored with a UTC
 *   label) plus its basis. It is displayed unconverted (UTC formatting of the stored
 *   value) with a basis label, never converted to the viewer's time zone.
 *   Countdowns, "days left", urgency and "passed" use `deadline_effective_at`, the
 *   server's conservative instant (published local time read at UTC+14 when the
 *   zone is unknown), so remaining time is never overstated.
 * - Status: the API's `status` is already deadline-derived; `status_reason`
 *   DEADLINE_PASSED means "Closed (deadline passed)".
 *
 * Pure functions (labels are passed in) so node tests can run them directly.
 */
import {INVALID_FORMAT_VALUE, formatCurrency, formatDate, formatDateTime} from '../i18n/formatters.ts';
import type {CustomerSelectableLocale} from '../i18n/locales.ts';

export type DeadlineTimeBasis = 'UTC' | 'EXPLICIT_TZ' | 'SOURCE_LOCAL_UNSPECIFIED' | 'DATE_ONLY';

export type TenderTruth = {
    status?: string | null;
    status_reason?: string | null;
    deadline?: string | null;
    deadline_time_basis?: DeadlineTimeBasis | string | null;
    deadline_timezone?: string | null;
    deadline_published_local?: string | null;
    deadline_effective_at?: string | null;
};

export type TenderTruthLabels = {
    notPublished: string;
    localTimeAsPublished: string;
    /** Receives the IANA zone, e.g. "Asia/Tashkent". */
    zoneTimeAsPublished: (zone: string) => string;
    dateAsPublished: string;
    closedDeadlinePassed: string;
};

export const DEADLINE_PASSED = 'DEADLINE_PASSED';
/** Backend 404 detail for a tender whose source is hidden from customers (D1-04b). */
export const TENDER_SOURCE_UNAVAILABLE_MESSAGE = 'Tender source temporarily unavailable';

export function isBudgetPublished(value: number | string | null | undefined): boolean {
    if (value === null || value === undefined || value === '') return false;
    const amount = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(amount) && amount > 0;
}

/** The one budget renderer: an amount, or the localized "Not published". */
export function formatBudget(
    value: number | string | null | undefined,
    currency: string | null | undefined,
    locale: CustomerSelectableLocale,
    notPublished: string,
    options: Omit<Intl.NumberFormatOptions, 'style' | 'currency'> = {},
): string {
    if (!isBudgetPublished(value)) return notPublished;
    const amount = typeof value === 'number' ? value : Number(value);
    const formatted = formatCurrency(
        amount,
        currency || 'USD',
        locale,
        Number.isInteger(amount) ? {maximumFractionDigits: 0, ...options} : options,
    );
    return formatted === INVALID_FORMAT_VALUE ? notPublished : formatted;
}

/** Basis label shown next to a published deadline; null when none applies. */
export function deadlineBasisLabel(truth: TenderTruth, labels: TenderTruthLabels): string | null {
    switch (truth.deadline_time_basis) {
        case 'SOURCE_LOCAL_UNSPECIFIED':
            return labels.localTimeAsPublished;
        case 'EXPLICIT_TZ':
            return truth.deadline_timezone ? labels.zoneTimeAsPublished(truth.deadline_timezone) : labels.localTimeAsPublished;
        case 'DATE_ONLY':
            return labels.dateAsPublished;
        case 'UTC':
            return 'UTC';
        default:
            return null;
    }
}

/**
 * The published deadline, unconverted. `value` defaults to the tender deadline; pass
 * another deadline of the same source (e.g. contact submission_deadline) to format
 * it on the same basis.
 */
export function formatPublishedDeadline(
    truth: TenderTruth,
    locale: CustomerSelectableLocale,
    labels: TenderTruthLabels,
    value: string | null | undefined = truth.deadline,
    {withTime = true}: {withTime?: boolean} = {},
): string {
    if (!value) return INVALID_FORMAT_VALUE;
    const dateOnly = truth.deadline_time_basis === 'DATE_ONLY';
    const text = dateOnly || !withTime ? formatDate(value, locale) : formatDateTime(value, locale);
    if (text === INVALID_FORMAT_VALUE) return text;
    const label = deadlineBasisLabel(truth, labels);
    return label ? `${text} (${label})` : text;
}

/** Epoch ms to count down to: the server's conservative instant, else the stored value. */
export function effectiveDeadlineMs(truth: TenderTruth): number | null {
    const raw = truth.deadline_effective_at || truth.deadline;
    if (!raw) return null;
    const ms = new Date(raw).getTime();
    return Number.isFinite(ms) ? ms : null;
}

export function isDeadlinePassed(truth: TenderTruth, now: number = Date.now()): boolean {
    const ms = effectiveDeadlineMs(truth);
    return ms !== null && ms < now;
}

/** Whole days left (ceil), negative once passed; null without a deadline. */
export function daysLeft(truth: TenderTruth, now: number = Date.now()): number | null {
    const ms = effectiveDeadlineMs(truth);
    return ms === null ? null : Math.ceil((ms - now) / (1000 * 60 * 60 * 24));
}

/**
 * Open only when the (derived) status is OPEN and the effective deadline has not
 * passed. A deadline that is present but unreadable cannot be verified: not open.
 */
export function isTenderOpen(truth: TenderTruth, now: number = Date.now()): boolean {
    if (String(truth.status ?? '').trim().toUpperCase() !== 'OPEN') return false;
    const hasDeadline = Boolean(truth.deadline_effective_at || truth.deadline);
    if (hasDeadline && effectiveDeadlineMs(truth) === null) return false;
    return !isDeadlinePassed(truth, now);
}

export function isClosedByDeadline(truth: TenderTruth, now: number = Date.now()): boolean {
    if (truth.status_reason === DEADLINE_PASSED) return true;
    const status = String(truth.status ?? '').trim().toUpperCase();
    return (status === 'OPEN' || status === 'UNKNOWN') && isDeadlinePassed(truth, now);
}
