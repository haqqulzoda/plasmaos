/**
 * Partners & Experts library (D2-02): pure form, CSV and import logic.
 *
 * Nothing here talks to the network; callers inject the requests, so every rule
 * is testable without React. Validation mirrors the backend request contracts
 * (ProjectReferenceCreateRequest, FirmCreateRequest, ExpertCreateRequest,
 * CVVersionCreateRequest) so a form or CSV row that passes here is accepted there.
 */

export type EvidenceState = 'VERIFIED' | 'REVIEWED' | 'UNVERIFIED' | 'EVIDENCE_MISSING';

export const REFERENCE_ROLES = [
    'LEAD', 'JV_MEMBER', 'CONSORTIUM_MEMBER', 'SUBCONSULTANT', 'SUBCONTRACTOR', 'OTHER', 'UNKNOWN',
] as const;
export const VALUE_BASES = ['FIRM_SHARE', 'CONSORTIUM_TOTAL', 'CONTRACT_TOTAL', 'UNKNOWN'] as const;
export const COMPLETION_STATES = ['COMPLETED', 'ONGOING', 'NOT_COMPLETED', 'UNKNOWN'] as const;
/** A form records a claim; REVIEWED comes only from the explicit "Mark as reviewed" action. */
export const FORM_EVIDENCE_STATES = ['UNVERIFIED', 'EVIDENCE_MISSING'] as const;
export const LIBRARY_TABS = ['own', 'partners', 'experts'] as const;
export type LibraryTab = (typeof LIBRARY_TABS)[number];
export const IMPORT_ROW_LIMIT = 200;

/** Tab from the ``tab`` query value; anything unknown opens "Our experience". */
export function libraryTab(value: string | null | undefined): LibraryTab {
    return (LIBRARY_TABS as readonly string[]).includes(value ?? '') ? (value as LibraryTab) : 'own';
}

export type FieldError = {field: string; code: string};

const text = (value: unknown): string => (value === null || value === undefined ? '' : String(value)).trim();
const optional = (value: unknown): string | null => text(value) || null;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^\d+(\.\d+)?$/;

function validDate(value: string): boolean {
    if (!ISO_DATE.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

// ---- project references ---------------------------------------------------------------------------

export type ReferenceDraft = {
    project_name: string;
    client_name: string;
    country: string;
    sector: string;
    service: string;
    role: string;
    contract_share_percent: string;
    contract_value: string;
    contract_currency: string;
    value_basis: string;
    start_date: string;
    completion_date: string;
    completion_state: string;
    relevant_scope: string;
    evidence_state: string;
};

export type ReferencePayload = {
    project_name: string;
    client_name: string | null;
    country: string | null;
    sector: string | null;
    service: string | null;
    role: string;
    contract_share_percent: string | null;
    contract_value: string | null;
    contract_currency: string | null;
    value_basis: string;
    start_date: string | null;
    completion_date: string | null;
    completion_state: string;
    relevant_scope: string | null;
    evidence_state: string;
};

export const REFERENCE_FIELDS = [
    'project_name', 'client_name', 'country', 'sector', 'service', 'role', 'contract_share_percent',
    'contract_value', 'contract_currency', 'value_basis', 'start_date', 'completion_date', 'completion_state',
    'relevant_scope', 'evidence_state',
] as const satisfies readonly (keyof ReferenceDraft)[];

export function emptyReferenceDraft(): ReferenceDraft {
    return {
        project_name: '', client_name: '', country: '', sector: '', service: '', role: 'LEAD',
        contract_share_percent: '', contract_value: '', contract_currency: '', value_basis: 'UNKNOWN',
        start_date: '', completion_date: '', completion_state: 'COMPLETED', relevant_scope: '',
        evidence_state: 'UNVERIFIED',
    };
}

/** A stored reference as an editable draft. */
export function referenceDraft(reference: Partial<Record<keyof ReferenceDraft, unknown>>): ReferenceDraft {
    const draft = emptyReferenceDraft();
    for (const field of REFERENCE_FIELDS) {
        if (reference[field] !== undefined && reference[field] !== null) draft[field] = String(reference[field]);
    }
    return draft;
}

function normalizedEnum(value: string, allowed: readonly string[]): string | null {
    const candidate = value.trim().toUpperCase().replace(/[\s-]+/g, '_');
    return allowed.includes(candidate) ? candidate : null;
}

/** Every rule of ProjectReferenceCreateRequest, as field errors. */
export function referenceErrors(draft: ReferenceDraft): FieldError[] {
    const errors: FieldError[] = [];
    const name = text(draft.project_name);
    if (!name) errors.push({field: 'project_name', code: 'required'});
    else if (name.length < 2) errors.push({field: 'project_name', code: 'tooShort'});
    else if (name.length > 700) errors.push({field: 'project_name', code: 'tooLong'});
    for (const [field, max] of [['client_name', 500], ['country', 150], ['sector', 300], ['service', 300], ['relevant_scope', 10000]] as const) {
        if (text(draft[field]).length > max) errors.push({field, code: 'tooLong'});
    }
    if (!normalizedEnum(draft.role, REFERENCE_ROLES)) errors.push({field: 'role', code: 'invalid'});
    if (!normalizedEnum(draft.completion_state, COMPLETION_STATES)) errors.push({field: 'completion_state', code: 'invalid'});
    if (!normalizedEnum(draft.evidence_state, ['VERIFIED', 'REVIEWED', ...FORM_EVIDENCE_STATES])) {
        errors.push({field: 'evidence_state', code: 'invalid'});
    }
    const basis = normalizedEnum(draft.value_basis || 'UNKNOWN', VALUE_BASES);
    if (!basis) errors.push({field: 'value_basis', code: 'invalid'});

    const share = text(draft.contract_share_percent);
    if (share && (!DECIMAL.test(share) || Number(share) > 100)) errors.push({field: 'contract_share_percent', code: 'share'});
    const value = text(draft.contract_value).replace(/[\s,]/g, '');
    const currency = text(draft.contract_currency).toUpperCase();
    if (value && !DECIMAL.test(value)) errors.push({field: 'contract_value', code: 'number'});
    if (currency && !/^[A-Z]{3}$/.test(currency)) errors.push({field: 'contract_currency', code: 'currencyFormat'});
    if (value && !currency) errors.push({field: 'contract_currency', code: 'valueNeedsCurrency'});
    if (currency && !value) errors.push({field: 'contract_value', code: 'currencyNeedsValue'});
    if (value && basis === 'UNKNOWN') errors.push({field: 'value_basis', code: 'valueNeedsBasis'});

    const start = text(draft.start_date);
    const end = text(draft.completion_date);
    if (start && !validDate(start)) errors.push({field: 'start_date', code: 'date'});
    if (end && !validDate(end)) errors.push({field: 'completion_date', code: 'date'});
    if (start && end && validDate(start) && validDate(end) && end < start) {
        errors.push({field: 'completion_date', code: 'datesOrder'});
    }
    return errors;
}

export function referencePayload(draft: ReferenceDraft): ReferencePayload {
    const value = text(draft.contract_value).replace(/[\s,]/g, '');
    return {
        project_name: text(draft.project_name),
        client_name: optional(draft.client_name),
        country: optional(draft.country),
        sector: optional(draft.sector),
        service: optional(draft.service),
        role: normalizedEnum(draft.role, REFERENCE_ROLES) ?? 'UNKNOWN',
        contract_share_percent: optional(draft.contract_share_percent),
        contract_value: value || null,
        contract_currency: optional(draft.contract_currency)?.toUpperCase() ?? null,
        value_basis: normalizedEnum(draft.value_basis || 'UNKNOWN', VALUE_BASES) ?? 'UNKNOWN',
        start_date: optional(draft.start_date),
        completion_date: optional(draft.completion_date),
        completion_state: normalizedEnum(draft.completion_state, COMPLETION_STATES) ?? 'UNKNOWN',
        relevant_scope: optional(draft.relevant_scope),
        evidence_state: normalizedEnum(draft.evidence_state, ['VERIFIED', 'REVIEWED', ...FORM_EVIDENCE_STATES]) ?? 'UNVERIFIED',
    };
}

function sameValue(field: keyof ReferencePayload, left: unknown, right: unknown): boolean {
    if (left === null || left === undefined || left === '') return right === null || right === undefined || right === '';
    if (field === 'contract_value' || field === 'contract_share_percent') return Number(left) === Number(right);
    return String(left) === String(right);
}

/** PATCH body: only the fields that changed. An empty object means nothing to save. */
export function referenceChanges(
    stored: Partial<Record<keyof ReferencePayload, unknown>>,
    draft: ReferenceDraft,
): Partial<ReferencePayload> {
    const next = referencePayload(draft);
    const changes: Partial<ReferencePayload> = {};
    for (const field of REFERENCE_FIELDS) {
        if (!sameValue(field, stored[field], next[field])) (changes as Record<string, unknown>)[field] = next[field];
    }
    return changes;
}

// ---- firms and experts ------------------------------------------------------------------------------

export type FirmDraft = {
    display_name: string;
    legal_name: string;
    country: string;
    services: string;
    sectors: string;
    capabilities: string;
    regions: string;
};

export type ExpertDraft = {
    display_name: string;
    qualifications: string;
    languages: string;
    specializations: string;
};

/** "a; b, c" -> ["a", "b", "c"], trimmed, de-duplicated case-insensitively. */
export function listValue(value: string): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const part of value.split(/[;,\n]/)) {
        const item = part.trim().replace(/\s+/g, ' ');
        if (item && !seen.has(item.toLocaleLowerCase())) {
            seen.add(item.toLocaleLowerCase());
            result.push(item);
        }
    }
    return result;
}

export function joinList(values: unknown[] | null | undefined): string {
    return (values ?? []).map(String).join('; ');
}

export function nameErrors(name: string): FieldError[] {
    const value = text(name);
    if (!value) return [{field: 'display_name', code: 'required'}];
    if (value.length < 2) return [{field: 'display_name', code: 'tooShort'}];
    if (value.length > 500) return [{field: 'display_name', code: 'tooLong'}];
    return [];
}

export function firmErrors(draft: FirmDraft): FieldError[] {
    const errors = nameErrors(draft.display_name);
    if (text(draft.legal_name).length > 500) errors.push({field: 'legal_name', code: 'tooLong'});
    if (text(draft.country).length > 150) errors.push({field: 'country', code: 'tooLong'});
    for (const [field, max] of [['services', 50], ['sectors', 50], ['capabilities', 100], ['regions', 50]] as const) {
        if (listValue(draft[field]).length > max) errors.push({field, code: 'tooMany'});
    }
    return errors;
}

/** Fields shared by a partner firm (FirmCreateRequest) and the organization's own firm (PUT self-firm). */
export function firmFields(draft: FirmDraft) {
    return {
        display_name: text(draft.display_name).replace(/\s+/g, ' '),
        legal_name: optional(draft.legal_name),
        country: optional(draft.country),
        services: listValue(draft.services),
        sectors: listValue(draft.sectors),
        capabilities: listValue(draft.capabilities),
        regions: listValue(draft.regions),
    };
}

/** A partner firm created in this UI is always private to the organization. */
export function partnerFirmPayload(draft: FirmDraft) {
    const fields = firmFields(draft);
    return {
        ...fields, scope: 'ORGANIZATION_PRIVATE' as const, canonical_name: fields.display_name,
        source_type: 'MANUAL' as const, evidence_state: 'UNVERIFIED' as const,
    };
}

export function expertErrors(draft: ExpertDraft): FieldError[] {
    const errors = nameErrors(draft.display_name);
    for (const [field, max] of [['qualifications', 100], ['languages', 50], ['specializations', 100]] as const) {
        if (listValue(draft[field]).length > max) errors.push({field, code: 'tooMany'});
    }
    return errors;
}

export function expertFields(draft: ExpertDraft) {
    return {
        display_name: text(draft.display_name).replace(/\s+/g, ' '),
        qualifications: listValue(draft.qualifications),
        languages: listValue(draft.languages),
        specializations: listValue(draft.specializations),
    };
}

/** A private expert record needs no consent record (NOT_REQUIRED_PRIVATE). */
export function expertPayload(draft: ExpertDraft) {
    return {
        ...expertFields(draft), scope: 'ORGANIZATION_PRIVATE' as const,
        consent_state: 'NOT_REQUIRED_PRIVATE' as const, evidence_state: 'UNVERIFIED' as const,
    };
}

// ---- structured CV versions -------------------------------------------------------------------------

export type EducationRow = {degree: string; institution: string; year: string};
export type AssignmentRow = {
    role: string; client: string; country: string; sector: string; start: string; end: string; description: string;
};
export type LanguageRow = {language: string; level: string};
export type CertificationRow = {name: string; issuer: string; year: string};
export type CvDraft = {
    education: EducationRow[];
    assignments: AssignmentRow[];
    languages: LanguageRow[];
    certifications: CertificationRow[];
};

export const emptyEducation = (): EducationRow => ({degree: '', institution: '', year: ''});
export const emptyAssignment = (): AssignmentRow => ({
    role: '', client: '', country: '', sector: '', start: '', end: '', description: '',
});
export const emptyLanguage = (): LanguageRow => ({language: '', level: ''});
export const emptyCertification = (): CertificationRow => ({name: '', issuer: '', year: ''});
export const emptyCvDraft = (): CvDraft => ({
    education: [emptyEducation()], assignments: [emptyAssignment()], languages: [emptyLanguage()],
    certifications: [],
});

const filled = (row: Record<string, string>) => Object.values(row).some((value) => text(value));
const YEAR = /^\d{4}$/;
// A year alone is allowed: CVs often state assignment periods in years (R3 CV upload).
const MONTH_OR_DATE = /^\d{4}(-\d{2}(-\d{2})?)?$/;

/** Errors keyed "section.index.field"; empty rows are ignored. */
export function cvErrors(draft: CvDraft): FieldError[] {
    const errors: FieldError[] = [];
    draft.education.forEach((row, index) => {
        if (!filled(row)) return;
        if (!text(row.degree)) errors.push({field: `education.${index}.degree`, code: 'required'});
        if (text(row.year) && !YEAR.test(text(row.year))) errors.push({field: `education.${index}.year`, code: 'year'});
    });
    draft.assignments.forEach((row, index) => {
        if (!filled(row)) return;
        if (!text(row.role)) errors.push({field: `assignments.${index}.role`, code: 'required'});
        const start = text(row.start);
        const end = text(row.end);
        if (start && !MONTH_OR_DATE.test(start)) errors.push({field: `assignments.${index}.start`, code: 'month'});
        if (end && !MONTH_OR_DATE.test(end)) errors.push({field: `assignments.${index}.end`, code: 'month'});
        if (start && end && MONTH_OR_DATE.test(start) && MONTH_OR_DATE.test(end) && end < start) {
            errors.push({field: `assignments.${index}.end`, code: 'datesOrder'});
        }
    });
    draft.languages.forEach((row, index) => {
        if (filled(row) && !text(row.language)) errors.push({field: `languages.${index}.language`, code: 'required'});
    });
    draft.certifications.forEach((row, index) => {
        if (!filled(row)) return;
        if (!text(row.name)) errors.push({field: `certifications.${index}.name`, code: 'required'});
        if (text(row.year) && !YEAR.test(text(row.year))) errors.push({field: `certifications.${index}.year`, code: 'year'});
    });
    const total = [draft.education, draft.assignments, draft.languages, draft.certifications]
        .reduce((count, rows) => count + (rows as Record<string, string>[]).filter(filled).length, 0);
    if (!total) errors.push({field: 'cv', code: 'emptyCv'});
    return errors;
}

function compact<T extends Record<string, string>>(rows: T[]): Record<string, string>[] {
    return rows.filter(filled).map((row) => Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key, text(value)]).filter(([, value]) => value),
    ));
}

/** CVVersionCreateRequest. The version is immutable once saved; a correction is a new version. */
export function cvPayload(draft: CvDraft) {
    return {
        education: compact(draft.education),
        qualifications: [],
        certifications: compact(draft.certifications),
        assignments: compact(draft.assignments),
        languages: compact(draft.languages),
        evidence_provenance: {entry: 'MANUAL_STRUCTURED_CV'},
        evidence_state: 'UNVERIFIED' as const,
    };
}

/** Newest first: CV history is shown from the latest immutable version down. */
export function newestFirst<T extends {version_number: number}>(versions: readonly T[]): T[] {
    return [...versions].sort((a, b) => b.version_number - a.version_number);
}

// ---- CSV --------------------------------------------------------------------------------------------

/** RFC 4180: quoted fields, doubled quotes, commas and line breaks inside quotes, CRLF or LF, a BOM. */
export function parseCsv(input: string): string[][] {
    const source = input.replace(/^﻿/, '');
    const rows: string[][] = [];
    let row: string[] = [];
    let field = '';
    let quoted = false;
    for (let index = 0; index < source.length; index += 1) {
        const character = source[index];
        if (quoted) {
            if (character === '"') {
                if (source[index + 1] === '"') {
                    field += '"';
                    index += 1;
                } else {
                    quoted = false;
                }
            } else {
                field += character;
            }
        } else if (character === '"' && field === '') {
            quoted = true;
        } else if (character === ',') {
            row.push(field);
            field = '';
        } else if (character === '\n' || character === '\r') {
            if (character === '\r' && source[index + 1] === '\n') index += 1;
            row.push(field);
            rows.push(row);
            row = [];
            field = '';
        } else {
            field += character;
        }
    }
    if (field !== '' || row.length) {
        row.push(field);
        rows.push(row);
    }
    return rows.filter((cells) => cells.some((cell) => cell.trim() !== ''));
}

function csvCell(value: string): string {
    return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export type ImportKind = 'references' | 'experts';

export const CSV_COLUMNS: Record<ImportKind, readonly string[]> = {
    references: REFERENCE_FIELDS,
    experts: ['display_name', 'qualifications', 'languages', 'specializations'],
};
const REQUIRED_COLUMNS: Record<ImportKind, readonly string[]> = {
    references: ['project_name', 'role', 'completion_state'],
    experts: ['display_name'],
};
const EXAMPLES: Record<ImportKind, string[][]> = {
    references: [[
        'Substation design, Navoi region', 'Regional electricity company', 'Uzbekistan', 'Energy',
        'Detailed engineering design', 'LEAD', '', '250000', 'USD', 'CONTRACT_TOTAL', '2021-03-01', '2022-11-30',
        'COMPLETED', 'Design of two 110 kV substations', 'UNVERIFIED',
    ]],
    experts: [['Example Expert', 'MSc Electrical Engineering', 'English; Russian; Uzbek', 'Substation design; Grid studies']],
};

/** Template with the header row and one example row (to be replaced). */
export function csvTemplate(kind: ImportKind): string {
    return [CSV_COLUMNS[kind], ...EXAMPLES[kind]].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

export type ImportRow<T> = {line: number; payload: T | null; errors: FieldError[]; label: string};
export type ImportPreview<T> = {kind: ImportKind; errors: FieldError[]; rows: ImportRow<T>[]};

export function prepareImport(kind: 'references', input: string): ImportPreview<ReferencePayload>;
export function prepareImport(kind: 'experts', input: string): ImportPreview<ReturnType<typeof expertPayload>>;
export function prepareImport(kind: ImportKind, input: string): ImportPreview<unknown> {
    const table = parseCsv(input);
    const preview: ImportPreview<unknown> = {kind, errors: [], rows: []};
    if (!table.length) {
        preview.errors.push({field: 'file', code: 'emptyFile'});
        return preview;
    }
    const header = table[0].map((cell) => cell.trim().toLowerCase());
    const known = CSV_COLUMNS[kind];
    for (const column of header) {
        if (column && !known.includes(column)) preview.errors.push({field: column, code: 'unknownColumn'});
    }
    for (const column of REQUIRED_COLUMNS[kind]) {
        if (!header.includes(column)) preview.errors.push({field: column, code: 'missingColumn'});
    }
    const body = table.slice(1);
    if (!body.length) preview.errors.push({field: 'file', code: 'noRows'});
    if (body.length > IMPORT_ROW_LIMIT) preview.errors.push({field: 'file', code: 'tooManyRows'});
    if (preview.errors.length) return preview;

    body.forEach((cells, index) => {
        const values: Record<string, string> = {};
        header.forEach((column, position) => { values[column] = (cells[position] ?? '').trim(); });
        const line = index + 2; // header is line 1
        if (cells.length > header.length && cells.slice(header.length).some((cell) => cell.trim())) {
            preview.rows.push({line, payload: null, errors: [{field: 'row', code: 'extraCells'}], label: values[known[0]] ?? ''});
            return;
        }
        if (kind === 'references') {
            const draft = {...emptyReferenceDraft(), value_basis: '', evidence_state: 'UNVERIFIED'};
            for (const field of REFERENCE_FIELDS) if (field in values) draft[field] = values[field];
            if (!draft.value_basis) draft.value_basis = 'UNKNOWN';
            if (!draft.evidence_state) draft.evidence_state = 'UNVERIFIED';
            const errors = referenceErrors(draft);
            // A CSV cannot claim review: REVIEWED/VERIFIED come only from an explicit action.
            if (['REVIEWED', 'VERIFIED'].includes(draft.evidence_state.trim().toUpperCase())) {
                errors.push({field: 'evidence_state', code: 'reviewNotImportable'});
            }
            preview.rows.push({line, payload: errors.length ? null : referencePayload(draft), errors, label: draft.project_name});
        } else {
            const draft: ExpertDraft = {
                display_name: values.display_name ?? '', qualifications: values.qualifications ?? '',
                languages: values.languages ?? '', specializations: values.specializations ?? '',
            };
            const errors = expertErrors(draft);
            preview.rows.push({line, payload: errors.length ? null : expertPayload(draft), errors, label: draft.display_name});
        }
    });
    return preview;
}

export type ImportFailure = {line: number; label: string; message: string};
export type ImportReport = {created: number; failed: ImportFailure[]; skipped: number};

/**
 * Post the valid rows one by one, in file order. Invalid rows are counted as
 * skipped, and every failed request is reported with its line, so an import is
 * never partially silent.
 */
export async function runImport<T>(
    rows: readonly ImportRow<T>[],
    post: (payload: T) => Promise<unknown>,
    onProgress?: (done: number, total: number) => void,
    describe: (error: unknown) => string = (error) => (error instanceof Error ? error.message : String(error)),
): Promise<ImportReport> {
    const valid = rows.filter((row) => row.payload !== null);
    const report: ImportReport = {created: 0, failed: [], skipped: rows.length - valid.length};
    let done = 0;
    onProgress?.(0, valid.length);
    for (const row of valid) {
        try {
            await post(row.payload as T);
            report.created += 1;
        } catch (error) {
            report.failed.push({line: row.line, label: row.label, message: describe(error)});
        }
        done += 1;
        onProgress?.(done, valid.length);
    }
    return report;
}

// ---- the organization's own firm --------------------------------------------------------------------

export type OwnFirmDeps<F extends {firm_id: string}> = {
    /** GET /candidates/self-firm; resolves null on 404 ("not set up yet"). */
    getSelfFirm: () => Promise<F | null>;
    /** PUT /candidates/self-firm with no fields: creates it with the organization's name. */
    createSelfFirm: () => Promise<F>;
};

/** The own firm's id, creating the firm first when it is not set up yet. Called from actions only. */
export async function ensureSelfFirm<F extends {firm_id: string}>(
    known: F | null,
    deps: OwnFirmDeps<F>,
): Promise<F> {
    if (known) return known;
    return (await deps.getSelfFirm()) ?? deps.createSelfFirm();
}

export function isNotFound(error: unknown): boolean {
    const status = (error as {response?: {status?: number}} | null)?.response?.status;
    return status === 404;
}

export function reviewedState(evidenceState: string): boolean {
    return evidenceState === 'REVIEWED' || evidenceState === 'VERIFIED';
}

// ---- CV upload -> reviewed CV draft (R3 Task 3) -------------------------------------------------------

export type CvDraftState = 'PROCESSING_DOCUMENT' | 'QUEUED' | 'EXTRACTING' | 'READY' | 'FAILED' | 'CONFIRMED';
type QuotedRow = Record<string, string> & { quote?: string };
export type CvProposal = {
    full_name?: { value: string; quote: string } | null;
    education?: QuotedRow[]; assignments?: QuotedRow[]; languages?: QuotedRow[]; certifications?: QuotedRow[];
};
/** Rows under review keep the model's quote (shown beside the field, sent back as provenance). */
export type ReviewDraft = {
    education: (EducationRow & { quote?: string })[];
    assignments: (AssignmentRow & { quote?: string })[];
    languages: (LanguageRow & { quote?: string })[];
    certifications: (CertificationRow & { quote?: string })[];
};

export const CV_DRAFT_PENDING: readonly CvDraftState[] = ['PROCESSING_DOCUMENT', 'QUEUED', 'EXTRACTING'];

/** Still being read: poll. Confirmation is allowed once the document itself is processed. */
export function cvDraftPending(state: CvDraftState): boolean {
    return CV_DRAFT_PENDING.includes(state);
}

export function cvDraftConfirmable(state: CvDraftState, failureCode?: string | null): boolean {
    return state !== 'CONFIRMED' && state !== 'PROCESSING_DOCUMENT' && failureCode !== 'DOCUMENT_REJECTED';
}

function rowsFrom<T extends Record<string, string>>(rows: QuotedRow[] | undefined, empty: () => T): (T & { quote?: string })[] {
    return (rows ?? []).map((row) => {
        const base = empty();
        const filledRow = Object.fromEntries(Object.keys(base).map((key) => [key, text(row[key])])) as T;
        return row.quote ? { ...filledRow, quote: text(row.quote) } : filledRow;
    });
}

/** Proposed rows become editable rows; a section with nothing proposed starts with one empty row. */
export function reviewDraftFromProposal(proposal: CvProposal | null | undefined): ReviewDraft {
    const draft: ReviewDraft = {
        education: rowsFrom(proposal?.education, emptyEducation),
        assignments: rowsFrom(proposal?.assignments, emptyAssignment),
        languages: rowsFrom(proposal?.languages, emptyLanguage),
        certifications: rowsFrom(proposal?.certifications, emptyCertification),
    };
    if (!draft.education.length) draft.education.push(emptyEducation());
    if (!draft.assignments.length) draft.assignments.push(emptyAssignment());
    if (!draft.languages.length) draft.languages.push(emptyLanguage());
    return draft;
}

function withoutQuote<T extends { quote?: string }>(row: T): Omit<T, 'quote'> {
    const copy = { ...row };
    delete copy.quote;
    return copy;
}

/** The same field rules as a manual CV version; the quote is not a field. */
export function reviewDraftErrors(draft: ReviewDraft, expertName: string | null): FieldError[] {
    const errors = cvErrors({
        education: draft.education.map(withoutQuote), assignments: draft.assignments.map(withoutQuote),
        languages: draft.languages.map(withoutQuote), certifications: draft.certifications.map(withoutQuote),
    });
    if (expertName !== null && text(expertName).length < 2) errors.push({field: 'expert_name', code: 'required'});
    return errors;
}

/** CVDraftConfirmRequest: empty rows dropped, quotes kept for provenance (verified server-side). */
export function cvConfirmPayload(draft: ReviewDraft, expertName: string | null) {
    const keep = (rows: Record<string, string | undefined>[]) => rows
        .filter((row) => Object.entries(row).some(([key, value]) => key !== 'quote' && text(value)))
        .map((row) => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, text(value)]).filter(([, value]) => value)));
    return {
        ...(expertName !== null ? { new_expert_name: text(expertName).replace(/\s+/g, ' ') } : {}),
        education: keep(draft.education), assignments: keep(draft.assignments),
        languages: keep(draft.languages), certifications: keep(draft.certifications),
    };
}
