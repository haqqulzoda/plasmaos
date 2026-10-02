'use client';

import { useState, type FormEvent, type ReactNode } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useLibraryT, type LibraryTranslator } from './useLibraryT';

import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Feedback';
import { Input, Select, Textarea } from '@/components/ui/Forms';
import { Drawer } from '@/components/ui/Overlay';
import {
    COMPLETION_STATES,
    FORM_EVIDENCE_STATES,
    REFERENCE_ROLES,
    VALUE_BASES,
    cvErrors,
    emptyAssignment,
    emptyCertification,
    emptyCvDraft,
    emptyEducation,
    emptyLanguage,
    expertErrors,
    firmErrors,
    referenceErrors,
    type CvDraft,
    type ExpertDraft,
    type FieldError,
    type FirmDraft,
    type ReferenceDraft,
} from '@/lib/library';

type Translator = LibraryTranslator;

function errorText(t: Translator, errors: FieldError[], field: string): string | undefined {
    const error = errors.find((item) => item.field === field);
    return error ? t(`errors.${error.code}`) : undefined;
}

function FormDrawer({
    open, onClose, title, description, submitLabel, busy, failure, onSubmit, children, formId,
}: {
    open: boolean; onClose: () => void; title: string; description?: string; submitLabel: string;
    busy: boolean; failure: string | null; onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    children: ReactNode; formId: string;
}) {
    const t = useLibraryT();
    return <Drawer
        open={open} onClose={onClose} title={title} description={description} closeLabel={t('close')} side="end"
        footer={<div className="library-form-actions">
            <Button variant="secondary" onClick={onClose} disabled={busy}>{t('cancel')}</Button>
            <Button type="submit" form={formId} loading={busy}>{submitLabel}</Button>
        </div>}
    >
        <form id={formId} className="library-form ds-stack" noValidate onSubmit={onSubmit}>
            {failure && <Alert tone="danger" title={t('saveFailed')}>{failure}</Alert>}
            {children}
        </form>
    </Drawer>;
}

// ---- project reference ----------------------------------------------------------------------------

export function ReferenceForm({
    open, onClose, initial, storedEvidence, editing, onSubmit,
}: {
    open: boolean; onClose: () => void; initial: ReferenceDraft; storedEvidence?: string; editing: boolean;
    onSubmit: (draft: ReferenceDraft) => Promise<string | null>;
}) {
    const t = useLibraryT();
    const [draft, setDraft] = useState<ReferenceDraft>(initial);
    const [errors, setErrors] = useState<FieldError[]>([]);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    const set = (field: keyof ReferenceDraft) => (event: { target: { value: string } }) =>
        setDraft((current) => ({ ...current, [field]: event.target.value }));
    const evidenceOptions = [...new Set([...(storedEvidence ? [storedEvidence] : []), ...FORM_EVIDENCE_STATES])];
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const found = referenceErrors(draft);
        setErrors(found);
        if (found.length) return;
        setBusy(true);
        setFailure(null);
        const problem = await onSubmit(draft);
        setBusy(false);
        if (problem) setFailure(problem);
    };
    const field = (name: keyof ReferenceDraft, props: Record<string, unknown> = {}) => <Input
        label={t(`fields.${name}`)} value={draft[name]} onChange={set(name)} error={errorText(t, errors, name)}
        name={name} {...props}
    />;
    return <FormDrawer
        open={open} onClose={onClose} formId="library-reference-form" busy={busy} failure={failure} onSubmit={submit}
        title={editing ? t('reference.editTitle') : t('reference.addTitle')}
        description={editing ? t('reference.editHelp') : t('reference.addHelp')}
        submitLabel={editing ? t('reference.saveChanges') : t('reference.save')}
    >
        {errors.length > 0 && <Alert tone="warning" title={t('fixErrors', { count: errors.length })} />}
        {field('project_name', { required: true, maxLength: 700 })}
        <div className="library-form-grid">
            {field('client_name', { maxLength: 500 })}
            {field('country', { maxLength: 150 })}
            {field('sector', { maxLength: 300 })}
            {field('service', { maxLength: 300 })}
        </div>
        <div className="library-form-grid">
            <Select label={t('fields.role')} value={draft.role} onChange={set('role')} error={errorText(t, errors, 'role')} name="role">
                {REFERENCE_ROLES.map((role) => <option key={role} value={role}>{t(`roles.${role}`)}</option>)}
            </Select>
            {field('contract_share_percent', { inputMode: 'decimal', helper: t('help.share') })}
        </div>
        <fieldset className="library-fieldset">
            <legend>{t('reference.valueLegend')}</legend>
            <p className="ds-field-help">{t('help.value')}</p>
            <div className="library-form-grid">
                {field('contract_value', { inputMode: 'decimal' })}
                {field('contract_currency', { maxLength: 3, placeholder: 'USD', autoCapitalize: 'characters' })}
                <Select label={t('fields.value_basis')} value={draft.value_basis} onChange={set('value_basis')}
                    error={errorText(t, errors, 'value_basis')} name="value_basis">
                    {VALUE_BASES.map((basis) => <option key={basis} value={basis}>{t(`valueBases.${basis}`)}</option>)}
                </Select>
            </div>
        </fieldset>
        <div className="library-form-grid">
            {field('start_date', { type: 'date' })}
            {field('completion_date', { type: 'date' })}
            <Select label={t('fields.completion_state')} value={draft.completion_state} onChange={set('completion_state')}
                error={errorText(t, errors, 'completion_state')} name="completion_state">
                {COMPLETION_STATES.map((state) => <option key={state} value={state}>{t(`completion.${state}`)}</option>)}
            </Select>
        </div>
        <Textarea label={t('fields.relevant_scope')} value={draft.relevant_scope} onChange={set('relevant_scope')}
            error={errorText(t, errors, 'relevant_scope')} name="relevant_scope" rows={4} maxLength={10000} />
        <Select label={t('fields.evidence_state')} value={draft.evidence_state} onChange={set('evidence_state')}
            helper={t('help.evidence')} error={errorText(t, errors, 'evidence_state')} name="evidence_state">
            {evidenceOptions.map((state) => <option key={state} value={state}>{t(`evidence.${state}`)}</option>)}
        </Select>
    </FormDrawer>;
}

// ---- firm (partner or own) ------------------------------------------------------------------------

export function FirmForm({
    open, onClose, initial, title, description, submitLabel, onSubmit,
}: {
    open: boolean; onClose: () => void; initial: FirmDraft; title: string; description?: string; submitLabel: string;
    onSubmit: (draft: FirmDraft) => Promise<string | null>;
}) {
    const t = useLibraryT();
    const [draft, setDraft] = useState<FirmDraft>(initial);
    const [errors, setErrors] = useState<FieldError[]>([]);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    const set = (field: keyof FirmDraft) => (event: { target: { value: string } }) =>
        setDraft((current) => ({ ...current, [field]: event.target.value }));
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const found = firmErrors(draft);
        setErrors(found);
        if (found.length) return;
        setBusy(true);
        setFailure(null);
        const problem = await onSubmit(draft);
        setBusy(false);
        if (problem) setFailure(problem);
    };
    return <FormDrawer open={open} onClose={onClose} formId="library-firm-form" busy={busy} failure={failure}
        onSubmit={submit} title={title} description={description} submitLabel={submitLabel}>
        <Input label={t('fields.display_name')} value={draft.display_name} onChange={set('display_name')} required
            error={errorText(t, errors, 'display_name')} name="display_name" maxLength={500} />
        <Input label={t('fields.legal_name')} value={draft.legal_name} onChange={set('legal_name')}
            error={errorText(t, errors, 'legal_name')} name="legal_name" maxLength={500} />
        <Input label={t('fields.country')} value={draft.country} onChange={set('country')}
            error={errorText(t, errors, 'country')} name="country" maxLength={150} />
        {(['services', 'sectors', 'capabilities', 'regions'] as const).map((name) => <Input
            key={name} label={t(`fields.${name}`)} value={draft[name]} onChange={set(name)} helper={t('help.list')}
            error={errorText(t, errors, name)} name={name}
        />)}
    </FormDrawer>;
}

// ---- expert -----------------------------------------------------------------------------------------

export function ExpertForm({
    open, onClose, initial, editing, onSubmit,
}: {
    open: boolean; onClose: () => void; initial: ExpertDraft; editing: boolean;
    onSubmit: (draft: ExpertDraft) => Promise<string | null>;
}) {
    const t = useLibraryT();
    const [draft, setDraft] = useState<ExpertDraft>(initial);
    const [errors, setErrors] = useState<FieldError[]>([]);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    const set = (field: keyof ExpertDraft) => (event: { target: { value: string } }) =>
        setDraft((current) => ({ ...current, [field]: event.target.value }));
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const found = expertErrors(draft);
        setErrors(found);
        if (found.length) return;
        setBusy(true);
        setFailure(null);
        const problem = await onSubmit(draft);
        setBusy(false);
        if (problem) setFailure(problem);
    };
    return <FormDrawer open={open} onClose={onClose} formId="library-expert-form" busy={busy} failure={failure}
        onSubmit={submit} title={editing ? t('expert.editTitle') : t('expert.addTitle')}
        description={t('expert.privacyHelp')} submitLabel={editing ? t('expert.saveChanges') : t('expert.save')}>
        <Input label={t('fields.expert_name')} value={draft.display_name} onChange={set('display_name')} required
            error={errorText(t, errors, 'display_name')} name="display_name" maxLength={500} />
        {(['specializations', 'qualifications', 'languages'] as const).map((name) => <Input
            key={name} label={t(`fields.${name}`)} value={draft[name]} onChange={set(name)} helper={t('help.list')}
            error={errorText(t, errors, name)} name={name}
        />)}
    </FormDrawer>;
}

// ---- structured CV version --------------------------------------------------------------------------

type Section = keyof CvDraft;
const SECTION_FIELDS: Record<Section, string[]> = {
    education: ['degree', 'institution', 'year'],
    assignments: ['role', 'client', 'country', 'sector', 'start', 'end', 'description'],
    languages: ['language', 'level'],
    certifications: ['name', 'issuer', 'year'],
};
const EMPTY_ROW: Record<Section, () => Record<string, string>> = {
    education: emptyEducation, assignments: emptyAssignment, languages: emptyLanguage, certifications: emptyCertification,
};

export function CvVersionForm({
    open, onClose, expertName, nextVersion, onSubmit,
}: {
    open: boolean; onClose: () => void; expertName: string; nextVersion: number;
    onSubmit: (draft: CvDraft) => Promise<string | null>;
}) {
    const t = useLibraryT();
    const [draft, setDraft] = useState<CvDraft>(emptyCvDraft);
    const [errors, setErrors] = useState<FieldError[]>([]);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    const update = (section: Section, index: number, field: string, value: string) => setDraft((current) => ({
        ...current,
        [section]: (current[section] as Record<string, string>[]).map((row, position) => (
            position === index ? { ...row, [field]: value } : row
        )),
    }));
    const add = (section: Section) => setDraft((current) => ({ ...current, [section]: [...current[section], EMPTY_ROW[section]()] }));
    const remove = (section: Section, index: number) => setDraft((current) => ({
        ...current, [section]: (current[section] as Record<string, string>[]).filter((_, position) => position !== index),
    }));
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const found = cvErrors(draft);
        setErrors(found);
        if (found.length) return;
        setBusy(true);
        setFailure(null);
        const problem = await onSubmit(draft);
        setBusy(false);
        if (problem) setFailure(problem);
    };
    return <FormDrawer open={open} onClose={onClose} formId="library-cv-form" busy={busy} failure={failure}
        onSubmit={submit} title={t('cv.addTitle', { version: nextVersion })}
        description={t('cv.immutableHelp', { name: expertName })} submitLabel={t('cv.save')}>
        {errorText(t, errors, 'cv') && <Alert tone="warning" title={errorText(t, errors, 'cv') ?? ''} />}
        {(Object.keys(SECTION_FIELDS) as Section[]).map((section) => <fieldset className="library-fieldset" key={section}
            data-cv-section={section}>
            <legend>{t(`cv.sections.${section}`)}</legend>
            {(draft[section] as Record<string, string>[]).map((row, index) => <div className="library-cv-row" key={index}>
                <div className="library-form-grid">
                    {SECTION_FIELDS[section].map((name) => {
                        const key = `${section}.${index}.${name}`;
                        const common = {
                            label: t(`cv.fields.${section}.${name}`), value: row[name] ?? '', name: key,
                            error: errorText(t, errors, key),
                            onChange: (event: { target: { value: string } }) => update(section, index, name, event.target.value),
                        };
                        return name === 'description'
                            ? <Textarea key={name} {...common} rows={3} />
                            : <Input key={name} {...common}
                                placeholder={name === 'start' || name === 'end' ? 'YYYY-MM' : name === 'year' ? 'YYYY' : undefined} />;
                    })}
                </div>
                <Button variant="ghost" size="sm" onClick={() => remove(section, index)}
                    leadingIcon={<Trash2 aria-hidden />}>{t('cv.removeRow')}</Button>
            </div>)}
            <Button variant="secondary" size="sm" onClick={() => add(section)} leadingIcon={<Plus aria-hidden />}>
                {t(`cv.add.${section}`)}
            </Button>
        </fieldset>)}
    </FormDrawer>;
}
