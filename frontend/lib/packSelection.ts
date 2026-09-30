/**
 * Initial analysis-pack selection and language for the pursuit workspace (D1-06).
 *
 * For a SOURCE pursuit the system-generated OFFICIAL_NOTICE is pre-selected, so the
 * customer can analyse the tender as published with one click; their own private
 * documents stay selected too. Nothing is started here: the customer still confirms
 * with Analyze. Pure functions, so node tests can run them directly.
 */

export type PackSelectionCandidate = {
    pursuit_origin?: string | null;
    source_documents: ReadonlyArray<{tender_document_id: string; role: string; parse_ready: boolean}>;
    private_versions: ReadonlyArray<{document_version_id: string; parse_ready: boolean}>;
};

export type AnalysisLanguage = 'en' | 'uz' | 'ru';

export function initialPackSelection(candidate: PackSelectionCandidate): {source: string[]; private: string[]} {
    const readySource = candidate.source_documents.filter((item) => item.parse_ready);
    const notice = readySource.find((item) => item.role === 'OFFICIAL_NOTICE');
    const source =
        candidate.pursuit_origin === 'SOURCE' && notice
            ? [notice.tender_document_id]
            : readySource.map((item) => item.tender_document_id);
    return {
        source,
        private: candidate.private_versions.filter((item) => item.parse_ready).map((item) => item.document_version_id),
    };
}

/** Analysis language defaults to the UI locale when it is one the analyzer writes in. */
export function analysisLanguageForLocale(locale: string | null | undefined): AnalysisLanguage {
    const base = String(locale ?? '').trim().toLowerCase().split(/[-_]/, 1)[0];
    return base === 'ru' || base === 'uz' ? base : 'en';
}
