'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FileText } from 'lucide-react';
import { useLibraryT } from './useLibraryT';

import { BidiText } from '@/components/i18n/BidiText';
import { Button, ButtonLink } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Dialog } from '@/components/ui/Overlay';
import { cvDraftPending } from '@/lib/library';
import { listCvDrafts, requestFailure, uploadCv, type CvDraftSummary } from '@/lib/libraryApi';

const ACCEPT = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export function cvReviewHref(organizationId: string, draftId: string): string {
    return `/dashboard/partners-experts/cv/${encodeURIComponent(draftId)}?organization=${encodeURIComponent(organizationId)}`;
}

/** R3 Task 3: upload one CV for a new or an existing expert, then open its review. */
export function CvUploadDialog({
    organizationId, expert, onClose,
}: {
    organizationId: string; expert: { expert_id: string; display_name: string } | null; onClose: () => void;
}) {
    const t = useLibraryT();
    const router = useRouter();
    const [file, setFile] = useState<File | null>(null);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!file) return;
        setBusy(true);
        setFailure(null);
        try {
            const draft = await uploadCv(organizationId, file, expert?.expert_id ?? null);
            router.push(cvReviewHref(organizationId, draft.cv_draft_id));
        } catch (error) {
            setFailure(requestFailure(error));
            setBusy(false);
        }
    };
    return <Dialog open onClose={onClose} closeLabel={t('cvUpload.cancel')}
        title={expert ? t('cvUpload.titleFor', { name: expert.display_name }) : t('cvUpload.titleNew')}
        description={t('cvUpload.help')}
        footer={<>
            <Button variant="secondary" onClick={onClose}>{t('cvUpload.cancel')}</Button>
            <Button type="submit" form="cv-upload-form" loading={busy} disabled={!file}>{t('cvUpload.submit')}</Button>
        </>}>
        <form id="cv-upload-form" className="ds-stack" onSubmit={submit} data-cv-upload>
            <label className="ds-field">
                <span className="ds-field-label">{t('cvUpload.file')}</span>
                <input className="ds-control" type="file" accept={ACCEPT} required
                    onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                <span className="ds-field-help">{t('cvUpload.limits')}</span>
            </label>
            <p className="ds-muted ds-text-small">{t('cvUpload.noAutoSave')}</p>
            {failure && <Alert tone="danger" title={t('cvUpload.failed')}>{failure}</Alert>}
        </form>
    </Dialog>;
}

/** Drafts not yet saved as a CV: reading, ready for review, or failed (manual entry). */
export function PendingCvDrafts({ organizationId, version }: { organizationId: string; version: number }) {
    const t = useLibraryT();
    const [drafts, setDrafts] = useState<CvDraftSummary[]>([]);
    useEffect(() => {
        let cancelled = false;
        listCvDrafts(organizationId)
            .then((rows) => { if (!cancelled) setDrafts(rows.filter((row) => row.state !== 'CONFIRMED')); })
            .catch(() => { /* the experts list stays usable without drafts */ });
        return () => { cancelled = true; };
    }, [organizationId, version]);
    if (!drafts.length) return null;
    const tone = (draft: CvDraftSummary) => draft.state === 'READY' ? 'success' : draft.state === 'FAILED' ? 'warning' : 'info';
    return <section className="library-cv-drafts" aria-labelledby="cv-drafts-title" data-cv-drafts>
        <h3 id="cv-drafts-title">{t('cvDrafts.title')}</h3>
        <ul>{drafts.map((draft) => <li key={draft.cv_draft_id} data-cv-draft={draft.state}>
            <FileText aria-hidden />
            <span><strong><BidiText>{draft.display_filename}</BidiText></strong>
                <small className="ds-muted"><BidiText>{draft.expert_name ?? t('cvDrafts.newExpert')}</BidiText></small></span>
            <StatusBadge tone={tone(draft)}>{t(`cvDrafts.states.${draft.state}`)}</StatusBadge>
            <ButtonLink size="sm" variant={cvDraftPending(draft.state) ? 'secondary' : 'primary'}
                href={cvReviewHref(organizationId, draft.cv_draft_id)}>{t('cvDrafts.review')}</ButtonLink>
        </li>)}</ul>
    </section>;
}
