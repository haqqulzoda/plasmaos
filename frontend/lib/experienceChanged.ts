/**
 * "Your experience changed" (R3 Task 2): the re-run request that repeats a run's document
 * selection against the current candidate. Pure and import-free for the node test runner.
 */

type PackItemSelection = { tender_document_id?: string | null; document_version_id?: string | null };
type CandidateSelection = {
    candidate_sha256: string;
    source_documents: { tender_document_id: string; parse_ready: boolean }[];
    private_versions: { document_version_id: string; parse_ready: boolean }[];
};

export type RerunRequest = {
    candidate_sha256: string;
    analysis_language: string;
    source_document_ids: string[];
    private_version_ids: string[];
};

export const EVIDENCE_SECTIONS = ['OWN_EXPERIENCE', 'COMPANY_PROFILE', 'READINESS_RECORDS'] as const;
export type EvidenceSection = (typeof EVIDENCE_SECTIONS)[number];

/** Same documents as the run, still present and parse-ready now; null when none remain. */
export function rerunRequest(
    run: { analysis_language: string; pack_items: readonly PackItemSelection[] },
    candidate: CandidateSelection,
): RerunRequest | null {
    const readySource = new Set(candidate.source_documents.filter((item) => item.parse_ready).map((item) => item.tender_document_id));
    const readyPrivate = new Set(candidate.private_versions.filter((item) => item.parse_ready).map((item) => item.document_version_id));
    const source = [...new Set(run.pack_items.map((item) => item.tender_document_id).filter((id): id is string => Boolean(id && readySource.has(id))))];
    const privateIds = [...new Set(run.pack_items.map((item) => item.document_version_id).filter((id): id is string => Boolean(id && readyPrivate.has(id))))];
    if (!source.length && !privateIds.length) return null;
    return {
        candidate_sha256: candidate.candidate_sha256,
        analysis_language: run.analysis_language,
        source_document_ids: source,
        private_version_ids: privateIds,
    };
}

/** Known sections in a stable order; unknown codes from a newer backend are dropped. */
export function evidenceSections(sections: readonly string[] | null | undefined): EvidenceSection[] {
    const present = new Set(sections ?? []);
    return EVIDENCE_SECTIONS.filter((section) => present.has(section));
}
