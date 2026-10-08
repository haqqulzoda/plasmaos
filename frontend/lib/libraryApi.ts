/**
 * Partners & Experts requests (D2-02). Every call names the organization explicitly.
 * Self-firm and reference edit/archive endpoints follow the D2-01 contract; before
 * D2-01 is deployed, GET /candidates/self-firm answers 404, which reads as "not set up yet".
 */
import { api } from './api';
import { isNotFound, type CvDraftState, type CvProposal, type ReferencePayload } from './library';
import type { CandidateCVVersion, CandidateExpert, CandidateFirm, CandidateLibrary, CandidateProjectReference } from '@/types/pursuit';

const scoped = (organizationId: string) => ({ headers: { 'X-Organization-ID': organizationId } });

export async function getLibrary(organizationId: string): Promise<CandidateLibrary> {
    return (await api.get<CandidateLibrary>('/candidates', scoped(organizationId))).data;
}

export async function getSelfFirm(organizationId: string): Promise<CandidateFirm | null> {
    try {
        return (await api.get<CandidateFirm>('/candidates/self-firm', scoped(organizationId))).data;
    } catch (error) {
        if (isNotFound(error)) return null;
        throw error;
    }
}

export async function saveSelfFirm(organizationId: string, body: Record<string, unknown>): Promise<CandidateFirm> {
    return (await api.put<CandidateFirm>('/candidates/self-firm', body, scoped(organizationId))).data;
}

export async function createFirm(organizationId: string, body: Record<string, unknown>): Promise<CandidateFirm> {
    return (await api.post<CandidateFirm>('/candidates/firms', body, scoped(organizationId))).data;
}

export async function updateFirm(organizationId: string, firmId: string, body: Record<string, unknown>): Promise<CandidateFirm> {
    return (await api.patch<CandidateFirm>(`/candidates/firms/${encodeURIComponent(firmId)}`, body, scoped(organizationId))).data;
}

export async function createReference(
    organizationId: string, firmId: string, body: ReferencePayload,
): Promise<CandidateProjectReference> {
    return (await api.post<CandidateProjectReference>(
        `/candidates/firms/${encodeURIComponent(firmId)}/project-references`, body, scoped(organizationId),
    )).data;
}

/** Edit by supersede (D2-01): the response is the reference that now holds the facts. */
export async function updateReference(
    organizationId: string, firmId: string, referenceId: string, changes: Partial<ReferencePayload>,
): Promise<CandidateProjectReference> {
    return (await api.patch<CandidateProjectReference>(
        `/candidates/firms/${encodeURIComponent(firmId)}/project-references/${encodeURIComponent(referenceId)}`,
        changes, scoped(organizationId),
    )).data;
}

export async function archiveReference(
    organizationId: string, firmId: string, referenceId: string,
): Promise<CandidateProjectReference> {
    return (await api.post<CandidateProjectReference>(
        `/candidates/firms/${encodeURIComponent(firmId)}/project-references/${encodeURIComponent(referenceId)}/archive`,
        undefined, scoped(organizationId),
    )).data;
}

export async function createExpert(organizationId: string, body: Record<string, unknown>): Promise<CandidateExpert> {
    return (await api.post<CandidateExpert>('/candidates/experts', body, scoped(organizationId))).data;
}

export async function updateExpert(organizationId: string, expertId: string, body: Record<string, unknown>): Promise<CandidateExpert> {
    return (await api.patch<CandidateExpert>(`/candidates/experts/${encodeURIComponent(expertId)}`, body, scoped(organizationId))).data;
}

export async function createCvVersion(
    organizationId: string, expertId: string, body: Record<string, unknown>,
): Promise<CandidateCVVersion> {
    return (await api.post<CandidateCVVersion>(
        `/candidates/experts/${encodeURIComponent(expertId)}/cv-versions`, body, scoped(organizationId),
    )).data;
}

/** A short, customer-safe reason for a failed request (the server's own detail when it is text). */
export function requestFailure(error: unknown): string {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail.trim().slice(0, 240);
    if (Array.isArray(detail) && detail.length) {
        const first = detail[0] as { msg?: unknown };
        if (typeof first?.msg === 'string') return first.msg.slice(0, 240);
    }
    return response?.status ? `HTTP ${response.status}` : 'Network error';
}

// ---- CV upload -> reviewed CV draft (R3 Task 3) -------------------------------------------------------

export type CvDraftSummary = {
    cv_draft_id: string; expert_id: string | null; expert_name: string | null;
    state: CvDraftState; failure_code: string | null; display_filename: string;
    private_document_id: string; document_version_id: string; model_name: string | null;
    proposed_counts: Record<string, number>; confirmed_cv_version_id: string | null;
    created_at: string; updated_at: string;
};
export type CvDraftReview = CvDraftSummary & {
    document_text: string | null; document_text_truncated: boolean;
    proposal: CvProposal; extraction_summary: Record<string, unknown>;
};

/** Multipart upload through the private intake (PDF/DOCX, 25 MiB). Nothing is saved as a CV. */
export async function uploadCv(organizationId: string, file: File, expertId: string | null): Promise<CvDraftSummary> {
    const form = new FormData();
    form.append('file', file);
    if (expertId) form.append('expert_id', expertId);
    return (await api.post<CvDraftSummary>('/candidates/cv-uploads', form, {
        headers: { 'X-Organization-ID': organizationId, 'Content-Type': 'multipart/form-data' },
    })).data;
}

export async function listCvDrafts(organizationId: string): Promise<CvDraftSummary[]> {
    return (await api.get<CvDraftSummary[]>('/candidates/cv-drafts', scoped(organizationId))).data;
}

export async function getCvDraft(organizationId: string, draftId: string): Promise<CvDraftReview> {
    return (await api.get<CvDraftReview>(`/candidates/cv-drafts/${encodeURIComponent(draftId)}`, scoped(organizationId))).data;
}

export async function confirmCvDraft(
    organizationId: string, draftId: string, body: Record<string, unknown>,
): Promise<{ expert_id: string; expert_name: string; cv_version: CandidateCVVersion }> {
    return (await api.post(`/candidates/cv-drafts/${encodeURIComponent(draftId)}/confirm`, body, scoped(organizationId))).data;
}
