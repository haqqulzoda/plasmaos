/**
 * Plasma AI — Hybrid Compliance Guard
 *
 * Runtime-safe extractor for the hybrid_compliance payload.
 * This is the ONLY entry point for reading hybrid compliance data
 * in the UI. It guarantees that downstream components never receive
 * partial or malformed data.
 */

import type { HybridCompliancePayload, RequirementMatchDetail } from '@/types/compliance';

/**
 * Safely extract the hybrid compliance payload from an API response.
 * Returns null if the payload is absent, malformed, or the wrong shape.
 *
 * Every field is runtime-validated — we don't trust the network.
 */
export function extractHybridCompliance(
    data: Record<string, unknown> | null | undefined,
): HybridCompliancePayload | null {
    if (!data || typeof data !== 'object') return null;

    const raw = (data as { hybrid_compliance?: unknown }).hybrid_compliance;
    if (!raw || typeof raw !== 'object') return null;

    const c = raw as Record<string, unknown>;

    // ── Structural shape guard ──────────────────────────────────────
    if (typeof c.is_eligible !== 'boolean') return null;
    if (typeof c.total_requirements !== 'number') return null;
    if (typeof c.status_message !== 'string') return null;
    if (!Array.isArray(c.failed_dealbreakers)) return null;
    if (!Array.isArray(c.manual_reviews_required)) return null;
    if (!Array.isArray(c.satisfied_requirements)) return null;

    return {
        is_eligible: c.is_eligible,
        total_requirements: c.total_requirements,
        satisfied_count: typeof c.satisfied_count === 'number' ? c.satisfied_count : 0,
        failed_count: typeof c.failed_count === 'number' ? c.failed_count : 0,
        manual_review_count: typeof c.manual_review_count === 'number' ? c.manual_review_count : 0,
        skipped_optional_count: typeof c.skipped_optional_count === 'number' ? c.skipped_optional_count : 0,
        recorded_obligations_count: typeof c.recorded_obligations_count === 'number'
            ? c.recorded_obligations_count
            : undefined,
        skipped_non_bid_obligations_count: typeof c.skipped_non_bid_obligations_count === 'number'
            ? c.skipped_non_bid_obligations_count
            : undefined,
        uuid_match_count: typeof c.uuid_match_count === 'number' ? c.uuid_match_count : 0,
        token_match_count: typeof c.token_match_count === 'number' ? c.token_match_count : 0,
        verdict_status: typeof c.verdict_status === 'string'
            ? c.verdict_status as HybridCompliancePayload['verdict_status']
            : undefined,
        failed_dealbreakers: c.failed_dealbreakers as RequirementMatchDetail[],
        manual_reviews_required: c.manual_reviews_required as RequirementMatchDetail[],
        satisfied_requirements: c.satisfied_requirements as RequirementMatchDetail[],
        recorded_obligations: Array.isArray(c.recorded_obligations)
            ? c.recorded_obligations as RequirementMatchDetail[]
            : undefined,
        status_message: c.status_message,
    };
}
