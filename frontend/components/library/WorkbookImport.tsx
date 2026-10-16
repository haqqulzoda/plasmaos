'use client';

import { useState } from 'react';
import { Download, FileSpreadsheet, FileUp } from 'lucide-react';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Dialog } from '@/components/ui/Overlay';
import {
    commitWorkbookImport,
    downloadImportTemplate,
    previewWorkbookImport,
    type WorkbookCommitResult,
    type WorkbookPreview,
    type WorkbookRow,
} from '@/lib/libraryApi';

import { useLibraryT } from './useLibraryT';

const KINDS = ['references', 'experts', 'assignments'] as const;
const STATUS_TONE = { NEW: 'success', DUPLICATE: 'info', ERROR: 'danger' } as const;

function rowLabel(row: WorkbookRow): string {
    const values = row.values;
    const text = (key: string) => (values[key] === undefined || values[key] === null ? '' : String(values[key]));
    if (row.kind === 'references') return [text('project_name'), text('firm') && `(${text('firm')})`].filter(Boolean).join(' ');
    if (row.kind === 'experts') return [text('full_name'), text('position')].filter(Boolean).join(' · ');
    return [text('full_name'), text('role'), text('project')].filter(Boolean).join(' · ');
}

function errorMessage(failure: unknown, fallback: string): string {
    const detail = (failure as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail;
    return detail?.message ?? fallback;
}

/**
 * P1 done-for-you onboarding: one workbook (or CSV) with references, experts and their
 * assignments. The server validates and previews every row; Import writes the new rows of
 * exactly the previewed file in one transaction. Records are UNVERIFIED, as typed by hand.
 */
export function WorkbookImportDialog({ organizationId, onClose, onFinished }: {
    organizationId: string; onClose: () => void; onFinished: () => void;
}) {
    const t = useLibraryT();
    const [file, setFile] = useState<File | null>(null);
    const [preview, setPreview] = useState<WorkbookPreview | null>(null);
    const [result, setResult] = useState<WorkbookCommitResult | null>(null);
    const [busy, setBusy] = useState<'preview' | 'commit' | 'template' | null>(null);
    const [error, setError] = useState<string | null>(null);
    const newRows = preview ? KINDS.reduce((sum, kind) => sum + preview.counts[kind].new, 0) : 0;
    const errorRows = preview ? KINDS.reduce((sum, kind) => sum + preview.counts[kind].errors, 0) : 0;

    const choose = async (chosen: File | undefined) => {
        if (!chosen) return;
        setFile(chosen);
        setPreview(null);
        setResult(null);
        setError(null);
        setBusy('preview');
        try {
            setPreview(await previewWorkbookImport(organizationId, chosen));
        } catch (failure) {
            setError(errorMessage(failure, t('workbook.previewFailed')));
        } finally {
            setBusy(null);
        }
    };

    const runImport = async () => {
        if (!file || !preview) return;
        setBusy('commit');
        setError(null);
        try {
            setResult(await commitWorkbookImport(organizationId, file, preview.file_sha256));
        } catch (failure) {
            setError(errorMessage(failure, t('workbook.commitFailed')));
        } finally {
            setBusy(null);
        }
    };

    const template = async (format: 'xlsx' | 'csv', kind?: string) => {
        setBusy('template');
        try {
            await downloadImportTemplate(format, kind);
        } catch {
            setError(t('workbook.templateFailed'));
        } finally {
            setBusy(null);
        }
    };

    return <Dialog open onClose={() => { if (!busy) onClose(); }} closeLabel={t('close')}
        title={t('workbook.title')} description={t('workbook.description')}
        footer={<div className="library-form-actions">
            {result ? <Button onClick={() => { onFinished(); onClose(); }}>{t('import.done')}</Button> : <>
                <Button variant="secondary" onClick={onClose} disabled={Boolean(busy)}>{t('cancel')}</Button>
                <Button disabled={!newRows || busy !== null} loading={busy === 'commit'} data-workbook-commit onClick={() => void runImport()}>
                    {t('workbook.commit', { count: newRows })}
                </Button>
            </>}
        </div>}>
        <div className="ds-stack library-import" data-workbook-import>
            <ol className="library-workbook-steps">
                <li>{t('workbook.step1')}</li>
                <li>{t('workbook.step2')}</li>
                <li>{t('workbook.step3')}</li>
            </ol>
            <div className="library-actions">
                <Button variant="secondary" size="sm" leadingIcon={<FileSpreadsheet aria-hidden />} disabled={busy !== null}
                    data-workbook-template onClick={() => void template('xlsx')}>{t('workbook.templateXlsx')}</Button>
                {KINDS.map((kind) => <Button key={kind} variant="ghost" size="sm" leadingIcon={<Download aria-hidden />}
                    disabled={busy !== null} onClick={() => void template('csv', kind)}>{t(`workbook.templateCsv.${kind}`)}</Button>)}
            </div>
            <label className="ds-button ds-button-secondary library-file">
                <FileUp aria-hidden />
                <span>{file?.name || t('workbook.choose')}</span>
                <input type="file" accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
                    className="sr-only" disabled={busy !== null || Boolean(result)} data-workbook-file
                    onChange={(event) => void choose(event.target.files?.[0])} />
            </label>
            {busy === 'preview' && <p role="status" className="ds-muted">{t('workbook.checking')}</p>}
            {error && <Alert tone="danger" title={error} />}
            {preview && !result && <>
                <dl className="library-workbook-counts" data-workbook-counts>
                    {KINDS.map((kind) => <div key={kind} className="ds-surface-subtle">
                        <dt>{t(`workbook.kinds.${kind}`)}</dt>
                        <dd>{t('workbook.counts', {
                            new: preview.counts[kind].new, duplicates: preview.counts[kind].duplicates, errors: preview.counts[kind].errors,
                        })}</dd>
                    </div>)}
                </dl>
                {preview.warnings.map((warning) => <Alert key={warning} tone="warning" title={warning} />)}
                {errorRows > 0 && <Alert tone="warning" title={t('workbook.errorsTitle', { count: errorRows })}>{t('workbook.errorsHelp')}</Alert>}
                <div className="library-import-table" role="region" aria-label={t('import.preview')} tabIndex={0}>
                    <table>
                        <thead><tr>
                            <th scope="col">{t('workbook.sheet')}</th><th scope="col">{t('import.line')}</th>
                            <th scope="col">{t('import.record')}</th><th scope="col">{t('import.status')}</th>
                        </tr></thead>
                        <tbody>{preview.rows.map((row) => <tr key={`${row.kind}-${row.row}`} data-workbook-row={row.status}>
                            <td>{t(`workbook.kinds.${row.kind}`)}</td>
                            <td className="ds-numeric">{row.row}</td>
                            <td><BidiText>{rowLabel(row) || '—'}</BidiText></td>
                            <td>
                                <StatusBadge tone={STATUS_TONE[row.status]}>{t(`workbook.status.${row.status}`)}</StatusBadge>
                                {row.duplicate && <span className="ds-muted ds-text-small"> {row.duplicate}</span>}
                                {row.errors.length > 0 && <ul className="library-import-errors">{row.errors.map((message) => <li key={message}>{message}</li>)}</ul>}
                            </td>
                        </tr>)}</tbody>
                    </table>
                </div>
            </>}
            {result && <div data-workbook-result><Alert tone="success" title={t('workbook.done')}>
                {t('workbook.result', {
                    references: result.references_created, firms: result.partner_firms_created, experts: result.experts_created,
                    assignments: result.assignments_attached, duplicates: result.skipped_duplicates, errors: result.skipped_errors,
                })}
            </Alert></div>}
        </div>
    </Dialog>;
}
