/**
 * Tender Details "Analysis" card (D2-02): what the pursuit workspace's latest
 * analysis says, read passively. Pure so it is testable without React.
 */

type RunLike = {
    status: string;
    completed_at?: string | null;
    requirements?: {effective_coverage_state?: string}[];
    positions?: unknown[];
    gaps?: unknown[];
    /** D2-01: informational statements and submission instructions, outside every evidence count. */
    submission_and_notes?: unknown[];
} | null | undefined;

export type AnalysisCardState =
    | {kind: 'none'}
    | {kind: 'running'}
    | {kind: 'failed'}
    | {
        kind: 'ready';
        requirements: number;
        positions: number;
        gaps: number;
        evidenceMissing: number;
        notes: number;
        completedAt: string | null;
    };

export function analysisCardState(run: RunLike): AnalysisCardState {
    if (!run) return {kind: 'none'};
    if (run.status === 'QUEUED' || run.status === 'RUNNING') return {kind: 'running'};
    if (run.status !== 'COMPLETED') return {kind: 'failed'};
    const requirements = run.requirements ?? [];
    return {
        kind: 'ready',
        requirements: requirements.length,
        positions: run.positions?.length ?? 0,
        gaps: run.gaps?.length ?? 0,
        evidenceMissing: requirements.filter((item) => item.effective_coverage_state === 'EVIDENCE_MISSING').length,
        notes: run.submission_and_notes?.length ?? 0,
        completedAt: run.completed_at ?? null,
    };
}

/** The organization's SOURCE pursuit for a tender, if one exists (never created here). */
export function sourcePursuitFor<T extends {origin: string; source_tender_id: string | null}>(
    pursuits: readonly T[], tenderId: string,
): T | null {
    return pursuits.find((item) => item.origin === 'SOURCE' && item.source_tender_id === tenderId) ?? null;
}
