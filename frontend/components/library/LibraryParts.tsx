'use client';

import { useMemo, useState } from 'react';
import { Archive, Download, FileUp, Pencil, ShieldCheck } from 'lucide-react';
import { useLibraryT } from './useLibraryT';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Dialog } from '@/components/ui/Overlay';
import {
    IMPORT_ROW_LIMIT,
    csvTemplate,
    prepareImport,
    reviewedState,
    runImport,
    type ImportKind,
    type ImportPreview,
    type ImportReport,
} from '@/lib/library';
import { requestFailure } from '@/lib/libraryApi';
import type { CandidateProjectReference } from '@/types/pursuit';

export function EvidenceBadge({ state }: { state: string }) {
    const t = useLibraryT();
    return <StatusBadge tone={reviewedState(state) ? 'success' : 'warning'}>{t(`evidence.${state}`)}</StatusBadge>;
}

/** "Mark as reviewed" with an explicit statement that the review is the organization's own. */
export function ReviewAction({ state, subject, onConfirm }: {
    state: string; subject: string; onConfirm: () => Promise<string | null>;
}) {
    const t = useLibraryT();
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    if (reviewedState(state)) return null;
    return <>
        <Button variant="ghost" size="sm" leadingIcon={<ShieldCheck aria-hidden />} onClick={() => { setFailure(null); setOpen(true); }}
            data-review-action>
            {t('review.action')}
        </Button>
        {open && <Dialog open onClose={() => setOpen(false)} title={t('review.title')} closeLabel={t('close')}
            description={t('review.subject', { subject })}
            footer={<div className="library-form-actions">
                <Button variant="secondary" onClick={() => setOpen(false)} disabled={busy}>{t('cancel')}</Button>
                <Button loading={busy} data-review-confirm onClick={async () => {
                    setBusy(true);
                    const problem = await onConfirm();
                    setBusy(false);
                    if (problem) setFailure(problem);
                    else setOpen(false);
                }}>{t('review.confirm')}</Button>
            </div>}>
            <div className="ds-stack library-review-body">
                <p>{t('review.explanation')}</p>
                <p className="ds-muted">{t('review.notVerification')}</p>
                {failure && <Alert tone="danger" title={t('saveFailed')}>{failure}</Alert>}
            </div>
        </Dialog>}
    </>;
}

export function ReferenceList({
    references, onEdit, onArchive, onReview, readOnly = false,
}: {
    references: CandidateProjectReference[];
    onEdit: (reference: CandidateProjectReference) => void;
    onArchive: (reference: CandidateProjectReference) => Promise<string | null>;
    onReview: (reference: CandidateProjectReference) => Promise<string | null>;
    readOnly?: boolean;
}) {
    const t = useLibraryT();
    const [archiving, setArchiving] = useState<CandidateProjectReference | null>(null);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    if (!references.length) return <p className="ds-muted">{t('noReferences')}</p>;
    return <>
        <ul className="library-reference-list">
            {references.map((reference) => {
                const period = [reference.start_date, reference.completion_date].filter(Boolean).join(' – ');
                const value = reference.contract_value
                    ? `${reference.contract_value} ${reference.contract_currency ?? ''} · ${t(`valueBases.${reference.value_basis}`)}` : null;
                return <li className="library-reference" key={reference.reference_id} data-reference-id={reference.reference_id}>
                    <div className="library-reference-main">
                        <h4><BidiText>{reference.project_name}</BidiText></h4>
                        <p className="ds-muted">
                            {[reference.client_name, reference.country, reference.sector, reference.service]
                                .filter(Boolean).map((item) => <BidiText key={String(item)}>{item}</BidiText>)
                                .reduce<React.ReactNode[]>((all, item, index) => (index ? [...all, ' · ', item] : [item]), [])}
                        </p>
                        <p className="library-reference-facts">
                            <span>{t(`roles.${reference.role}`)}</span>
                            <span>{t(`completion.${reference.completion_state}`)}</span>
                            {period && <span dir="ltr">{period}</span>}
                            {value && <span>{value}</span>}
                            {reference.contract_share_percent && <span>{t('sharePercent', { value: reference.contract_share_percent })}</span>}
                        </p>
                        {reference.relevant_scope && <p className="library-reference-scope"><BidiText>{reference.relevant_scope}</BidiText></p>}
                    </div>
                    <div className="library-reference-side">
                        <EvidenceBadge state={reference.evidence_state} />
                        {reference.evidence_basis && <small className="ds-muted">{t(`basis.${reference.evidence_basis}`)}</small>}
                        {!readOnly && <div className="library-actions">
                            <Button variant="ghost" size="sm" leadingIcon={<Pencil aria-hidden />} onClick={() => onEdit(reference)}>{t('edit')}</Button>
                            <ReviewAction state={reference.evidence_state} subject={reference.project_name} onConfirm={() => onReview(reference)} />
                            <Button variant="ghost" size="sm" leadingIcon={<Archive aria-hidden />}
                                onClick={() => { setFailure(null); setArchiving(reference); }}>{t('archive.action')}</Button>
                        </div>}
                    </div>
                </li>;
            })}
        </ul>
        {archiving && <Dialog open onClose={() => setArchiving(null)} title={t('archive.title')} closeLabel={t('close')}
            description={t('archive.subject', { subject: archiving.project_name })}
            footer={<div className="library-form-actions">
                <Button variant="secondary" onClick={() => setArchiving(null)} disabled={busy}>{t('cancel')}</Button>
                <Button variant="danger" loading={busy} onClick={async () => {
                    setBusy(true);
                    const problem = await onArchive(archiving);
                    setBusy(false);
                    if (problem) setFailure(problem);
                    else setArchiving(null);
                }}>{t('archive.confirm')}</Button>
            </div>}>
            <div className="ds-stack"><p>{t('archive.explanation')}</p>
                {failure && <Alert tone="danger" title={t('saveFailed')}>{failure}</Alert>}</div>
        </Dialog>}
    </>;
}

function download(name: string, content: string) {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

/**
 * CSV import: template, client-side parse, per-row preview, sequential POSTs with a
 * progress count, and a final report that names every row not created.
 */
export function CsvImportDialog({ kind, targetName, onClose, post, onFinished }: {
    kind: ImportKind; targetName: string; onClose: () => void;
    post: (payload: never) => Promise<unknown>; onFinished: () => void;
}) {
    const t = useLibraryT();
    const [fileName, setFileName] = useState('');
    const [preview, setPreview] = useState<ImportPreview<unknown> | null>(null);
    const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
    const [report, setReport] = useState<ImportReport | null>(null);
    const counts = useMemo(() => ({
        valid: preview?.rows.filter((row) => row.payload !== null).length ?? 0,
        invalid: preview?.rows.filter((row) => row.payload === null).length ?? 0,
    }), [preview]);
    const running = progress !== null && report === null;
    const errorLabel = (field: string, code: string) => t('import.cellError', {
        // An unknown column is shown as written in the file; every other field has a label.
        field: code === 'unknownColumn' ? field : t(`fields.${field}`), message: t(`errors.${code}`),
    });
    return <Dialog open onClose={() => { if (!running) onClose(); }} closeLabel={t('close')}
        title={t(`import.title.${kind}`)} description={t('import.target', { target: targetName, limit: IMPORT_ROW_LIMIT })}
        footer={<div className="library-form-actions">
            {report ? <Button onClick={() => { onFinished(); onClose(); }}>{t('import.done')}</Button> : <>
                <Button variant="secondary" onClick={onClose} disabled={running}>{t('cancel')}</Button>
                <Button disabled={!counts.valid || Boolean(preview?.errors.length)} loading={running} data-import-start
                    onClick={async () => {
                        if (!preview) return;
                        const result = await runImport(preview.rows, (payload) => post(payload as never),
                            (done, total) => setProgress({ done, total }), requestFailure);
                        setReport(result);
                    }}>
                    {t('import.start', { count: counts.valid })}
                </Button>
            </>}
        </div>}>
        <div className="ds-stack library-import" data-import-kind={kind}>
            <p>{t(`import.help.${kind}`)}</p>
            <div className="library-actions">
                <Button variant="secondary" size="sm" leadingIcon={<Download aria-hidden />}
                    onClick={() => download(`plasma-${kind}-template.csv`, csvTemplate(kind))}>{t('import.template')}</Button>
                <label className="ds-button ds-button-secondary ds-button-sm library-file">
                    <FileUp aria-hidden />
                    <span>{fileName || t('import.choose')}</span>
                    <input type="file" accept=".csv,text/csv" className="sr-only" disabled={running || Boolean(report)}
                        data-import-file
                        onChange={async (event) => {
                            const file = event.target.files?.[0];
                            if (!file) return;
                            setFileName(file.name);
                            setReport(null);
                            setProgress(null);
                            const content = await file.text();
                            setPreview(kind === 'references' ? prepareImport('references', content) : prepareImport('experts', content));
                        }} />
                </label>
            </div>
            {preview && preview.errors.length > 0 && <Alert tone="danger" title={t('import.fileRejected')}>
                {preview.errors.map((error) => errorLabel(error.field, error.code)).join(' · ')}
            </Alert>}
            {preview && !preview.errors.length && <>
                <p role="status" data-import-summary>{t('import.summary', { valid: counts.valid, invalid: counts.invalid })}</p>
                {counts.invalid > 0 && <Alert tone="warning" title={t('import.invalidRows', { count: counts.invalid })}>
                    {t('import.invalidHelp')}
                </Alert>}
                <div className="library-import-table" role="region" aria-label={t('import.preview')} tabIndex={0}>
                    <table>
                        <thead><tr><th scope="col">{t('import.line')}</th><th scope="col">{t('import.record')}</th><th scope="col">{t('import.status')}</th></tr></thead>
                        <tbody>{preview.rows.map((row) => <tr key={row.line} data-import-row={row.line} data-valid={row.payload !== null}>
                            <td className="ds-numeric">{row.line}</td>
                            <td><BidiText>{row.label || '—'}</BidiText></td>
                            <td>{row.payload !== null ? t('import.ready')
                                : <ul className="library-row-errors">{row.errors.map((error, index) => <li key={index}>{errorLabel(error.field, error.code)}</li>)}</ul>}</td>
                        </tr>)}</tbody>
                    </table>
                </div>
            </>}
            {progress && !report && <p role="status" data-import-progress>{t('import.progress', { done: progress.done, total: progress.total })}</p>}
            {report && <Alert tone={report.failed.length ? 'warning' : 'success'} title={t('import.report', {
                created: report.created, failed: report.failed.length, skipped: report.skipped,
            })}>
                {report.failed.length > 0 && <span data-import-failures>{report.failed.map((failure) => t('import.failedRow', {
                    line: failure.line, label: failure.label, message: failure.message,
                })).join(' · ')}</span>}
            </Alert>}
        </div>
    </Dialog>;
}
