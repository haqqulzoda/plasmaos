'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
    Archive,
    Check,
    Edit3,
    Loader2,
    Plus,
    Save,
    Trash2,
    X,
} from 'lucide-react';
import { api } from '@/lib/api';
import {
    DOCUMENT_STATUS_OPTIONS,
    DOCUMENT_TYPE_OPTIONS,
    expiryState,
    documentStatusMessageKey,
    documentTypeMessageKey,
    expiryMessageKey,
} from '@/lib/readiness';
import { formatDate } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { translateServiceLabel } from '@/i18n/taxonomy';
import { labelForService, serviceValueSet, useServiceMeta } from '@/lib/services';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';

type ReadinessDocument = {
    id: string;
    company_profile_id: string;
    document_type: string;
    document_name: string;
    document_number?: string | null;
    issuer?: string | null;
    issue_date?: string | null;
    expiry_date?: string | null;
    status: string;
    related_service?: string | null;
    notes?: string | null;
    optional_file_url?: string | null;
};

type FormState = {
    document_type: string;
    document_name: string;
    document_number: string;
    issuer: string;
    issue_date: string;
    expiry_date: string;
    status: string;
    related_service: string;
    notes: string;
    optional_file_url: string;
};

type Filters = {
    document_type: string;
    status: string;
    related_service: string;
};

type ReadinessTranslator = (key: string, values?: Record<string, string | number>) => string;

const emptyForm: FormState = {
    document_type: 'license',
    document_name: '',
    document_number: '',
    issuer: '',
    issue_date: '',
    expiry_date: '',
    status: 'unknown',
    related_service: '',
    notes: '',
    optional_file_url: '',
};

const emptyFilters: Filters = {
    document_type: '',
    status: '',
    related_service: '',
};

const inputClass =
    'w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-gray-100 text-sm placeholder-gray-600 outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500 transition-all';

const labelClass = 'text-sm font-medium text-gray-300';

function displayValue(value?: string | null) {
    return value && value.trim() ? value : '-';
}

function toForm(document: ReadinessDocument): FormState {
    return {
        document_type: document.document_type,
        document_name: document.document_name,
        document_number: document.document_number ?? '',
        issuer: document.issuer ?? '',
        issue_date: document.issue_date ?? '',
        expiry_date: document.expiry_date ?? '',
        status: document.status,
        related_service: document.related_service ?? '',
        notes: document.notes ?? '',
        optional_file_url: document.optional_file_url ?? '',
    };
}

function toPayload(form: FormState) {
    return {
        document_type: form.document_type,
        document_name: form.document_name,
        document_number: form.document_number || null,
        issuer: form.issuer || null,
        issue_date: form.issue_date || null,
        expiry_date: form.expiry_date || null,
        status: form.status,
        related_service: form.related_service || null,
        notes: form.notes || null,
        optional_file_url: form.optional_file_url || null,
    };
}

const statusClass = (status: string) => {
    if (status === 'available') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
    if (status === 'missing') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
    if (status === 'expired') return 'border-red-500/20 bg-red-500/10 text-red-200';
    return 'border-gray-700 bg-gray-900 text-gray-300';
};

const expiryClass = (state: string) => {
    if (state === 'expired') return 'border-red-500/20 bg-red-500/10 text-red-200';
    if (state === 'expiring_soon') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
    return 'border-gray-700 bg-gray-900 text-gray-300';
};

function apiStatus(error: unknown): number | undefined {
    if (
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        typeof (error as { response?: { status?: unknown } }).response?.status === 'number'
    ) {
        return (error as { response: { status: number } }).response.status;
    }
    return undefined;
}

export default function ReadinessVaultPage() {
    const translate = useTranslations('readiness');
    const t = translate as ReadinessTranslator;
    const tCommon = useTranslations('common');
    const locale = useLocale() as CustomerSelectableLocale;
    const translateRef = useRef(t);
    useEffect(() => { translateRef.current = t; }, [t]);
    const services = useServiceMeta();
    const [documents, setDocuments] = useState<ReadinessDocument[]>([]);
    const [form, setForm] = useState<FormState>(emptyForm);
    const [editingId, setEditingId] = useState<string | null>(null);
    const [formOpen, setFormOpen] = useState(false);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [profileRequired, setProfileRequired] = useState(false);
    const [filters, setFilters] = useState<Filters>(emptyFilters);

    const editingDocument = useMemo(
        () => documents.find((document) => document.id === editingId) ?? null,
        [documents, editingId],
    );
    const serviceValues = useMemo(() => serviceValueSet(services), [services]);
    const filteredDocuments = useMemo(
        () =>
            documents.filter((document) => {
                if (filters.document_type && document.document_type !== filters.document_type) {
                    return false;
                }
                if (filters.status && document.status !== filters.status) {
                    return false;
                }
                if (filters.related_service && document.related_service !== filters.related_service) {
                    return false;
                }
                return true;
            }),
        [documents, filters],
    );

    const loadDocuments = useCallback(async () => {
        setLoading(true);
        setError(null);
        setProfileRequired(false);
        try {
            const response = await api.get<ReadinessDocument[]>('/vault/readiness');
            setDocuments(response.data ?? []);
        } catch (err) {
            if (apiStatus(err) === 404) {
                setDocuments([]);
                setProfileRequired(true);
                return;
            }
            setError(translateRef.current('loadFailed'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadDocuments();
    }, [loadDocuments]);

    const openCreateForm = () => {
        if (profileRequired) {
            setError(t('profileRequiredAdd'));
            return;
        }
        setEditingId(null);
        setForm(emptyForm);
        setFormOpen(true);
        setSaved(false);
        setError(null);
    };

    const openEditForm = (document: ReadinessDocument) => {
        const nextForm = toForm(document);
        if (nextForm.related_service && !serviceValues.has(nextForm.related_service)) {
            nextForm.related_service = '';
        }

        setEditingId(document.id);
        setForm(nextForm);
        setFormOpen(true);
        setSaved(false);
        setError(null);
    };

    const closeForm = () => {
        setFormOpen(false);
        setEditingId(null);
        setForm(emptyForm);
    };

    const updateField = (field: keyof FormState, value: string) => {
        setForm((current) => ({ ...current, [field]: value }));
    };

    const updateFilter = (field: keyof Filters, value: string) => {
        setFilters((current) => ({ ...current, [field]: value }));
    };

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!form.document_name.trim()) {
            setError(t('nameRequired'));
            return;
        }

        setSaving(true);
        setSaved(false);
        setError(null);
        try {
            if (editingId) {
                const response = await api.put<ReadinessDocument>(
                    `/vault/readiness/${editingId}`,
                    toPayload(form),
                );
                setDocuments((current) =>
                    current.map((document) =>
                        document.id === editingId ? response.data : document,
                    ),
                );
            } else {
                const response = await api.post<ReadinessDocument>(
                    '/vault/readiness',
                    toPayload(form),
                );
                setDocuments((current) => [...current, response.data]);
            }
            setSaved(true);
            closeForm();
            window.setTimeout(() => setSaved(false), 2500);
        } catch (err) {
            if (apiStatus(err) === 404) {
                setProfileRequired(true);
                setError(t('profileRequiredSave'));
                return;
            }
            setError(t('saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    const deleteDocument = async (document: ReadinessDocument) => {
        const confirmed = window.confirm(t('deleteConfirm', { name: document.document_name }));
        if (!confirmed) return;

        setDeletingId(document.id);
        setError(null);
        try {
            await api.delete(`/vault/readiness/${document.id}`);
            setDocuments((current) => current.filter((item) => item.id !== document.id));
            if (editingId === document.id) {
                closeForm();
            }
        } catch (err) {
            if (apiStatus(err) === 404) {
                setError(t('notFound'));
                return;
            }
            setError(t('deleteFailed'));
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <div className="mx-auto w-full max-w-7xl space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-500/20 bg-cyan-500/10">
                        <Archive className="h-5 w-5 text-cyan-300" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-semibold text-white">{t('title')}</h1>
                        <p className="text-sm text-gray-400">
                            {t('recordCount', { shown: filteredDocuments.length, total: documents.length })}
                        </p>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={openCreateForm}
                    disabled={profileRequired}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:bg-gray-700 disabled:text-gray-400"
                >
                    <Plus className="h-4 w-4" />
                    {t('addRecord')}
                </button>
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error}
                </div>
            )}

            {profileRequired && (
                <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                    {t('profileRequiredView')}
                </div>
            )}

            {saved && (
                <div className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
                    <Check className="h-4 w-4" />
                    {t('saved')}
                </div>
            )}

            {formOpen && (
                <form
                    onSubmit={handleSubmit}
                    className="space-y-5 rounded-lg border border-gray-800 bg-gray-950 p-5"
                >
                    <div className="flex items-center justify-between gap-3">
                        <h2 className="text-base font-semibold text-white">
                            {editingDocument ? t('editRecord') : t('addRecordTitle')}
                        </h2>
                        <button
                            type="button"
                            onClick={closeForm}
                            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-900 hover:text-white"
                            aria-label={t('closeForm')}
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>

                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                        <FormField label={t('documentType')}>
                            <select
                                className={inputClass}
                                value={form.document_type}
                                onChange={(event) => updateField('document_type', event.target.value)}
                            >
                                {DOCUMENT_TYPE_OPTIONS.map((type) => (
                                    <option key={type.value} value={type.value}>
                                        {t(type.messageKey)}
                                    </option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label={t('documentName')}>
                            <input
                                dir="auto"
                                className={inputClass}
                                value={form.document_name}
                                onChange={(event) => updateField('document_name', event.target.value)}
                                required
                            />
                        </FormField>
                        <FormField label={t('documentNumber')}>
                            <input
                                dir="ltr"
                                className={inputClass}
                                value={form.document_number}
                                onChange={(event) => updateField('document_number', event.target.value)}
                            />
                        </FormField>
                        <FormField label={t('issuer')}>
                            <input
                                dir="auto"
                                className={inputClass}
                                value={form.issuer}
                                onChange={(event) => updateField('issuer', event.target.value)}
                            />
                        </FormField>
                        <FormField label={t('issueDate')}>
                            <input
                                dir="ltr"
                                className={inputClass}
                                value={form.issue_date}
                                onChange={(event) => updateField('issue_date', event.target.value)}
                                type="date"
                            />
                        </FormField>
                        <FormField label={t('expiryDate')}>
                            <input
                                dir="ltr"
                                className={inputClass}
                                value={form.expiry_date}
                                onChange={(event) => updateField('expiry_date', event.target.value)}
                                type="date"
                            />
                        </FormField>
                        <FormField label={t('status')}>
                            <select
                                className={inputClass}
                                value={form.status}
                                onChange={(event) => updateField('status', event.target.value)}
                            >
                                {DOCUMENT_STATUS_OPTIONS.map((status) => (
                                    <option key={status.value} value={status.value}>
                                        {t(status.messageKey)}
                                    </option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label={t('relatedService')}>
                            <select
                                className={inputClass}
                                value={form.related_service}
                                onChange={(event) => updateField('related_service', event.target.value)}
                            >
                                <option value="">{t('none')}</option>
                                {services.map((service) => (
                                    <option key={service.value} value={service.value}>
                                        {translateServiceLabel(service.value, tCommon, service.label)}
                                    </option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label={t('fileReference')}>
                            <input
                                dir="ltr"
                                className={inputClass}
                                value={form.optional_file_url}
                                onChange={(event) => updateField('optional_file_url', event.target.value)}
                                placeholder={t('fileReferencePlaceholder')}
                            />
                        </FormField>
                    </div>

                    <FormField label={t('notes')}>
                        <textarea
                            dir="auto"
                            className={`${inputClass} min-h-24 resize-y`}
                            value={form.notes}
                            onChange={(event) => updateField('notes', event.target.value)}
                        />
                    </FormField>

                    <div className="flex justify-end">
                        <button
                            type="submit"
                            disabled={saving}
                            className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:bg-gray-700 disabled:text-gray-400"
                        >
                            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                            {t('saveRecord')}
                        </button>
                    </div>
                </form>
            )}

            <section className="grid grid-cols-1 gap-3 rounded-lg border border-gray-800 bg-gray-950 p-4 md:grid-cols-4">
                <FormField label={t('documentType')}>
                    <select
                        className={inputClass}
                        value={filters.document_type}
                        onChange={(event) => updateFilter('document_type', event.target.value)}
                    >
                        <option value="">{t('allTypes')}</option>
                        {DOCUMENT_TYPE_OPTIONS.map((type) => (
                            <option key={type.value} value={type.value}>
                                {t(type.messageKey)}
                            </option>
                        ))}
                    </select>
                </FormField>
                <FormField label={t('status')}>
                    <select
                        className={inputClass}
                        value={filters.status}
                        onChange={(event) => updateFilter('status', event.target.value)}
                    >
                        <option value="">{t('allStatuses')}</option>
                        {DOCUMENT_STATUS_OPTIONS.map((status) => (
                            <option key={status.value} value={status.value}>
                                {t(status.messageKey)}
                            </option>
                        ))}
                    </select>
                </FormField>
                <FormField label={t('relatedService')}>
                    <select
                        className={inputClass}
                        value={filters.related_service}
                        onChange={(event) => updateFilter('related_service', event.target.value)}
                    >
                        <option value="">{t('allServices')}</option>
                        {services.map((service) => (
                            <option key={service.value} value={service.value}>
                                {translateServiceLabel(service.value, tCommon, service.label)}
                            </option>
                        ))}
                    </select>
                </FormField>
                <div className="flex items-end">
                    <button
                        type="button"
                        onClick={() => setFilters(emptyFilters)}
                        className="min-h-10 rounded-lg border border-gray-700 px-3 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-900 hover:text-white"
                    >
                        {t('resetFilters')}
                    </button>
                </div>
            </section>

            <section className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950">
                {loading ? (
                    <div role="status" aria-label={t('loading')} className="flex h-56 items-center justify-center">
                        <Loader2 className="h-6 w-6 animate-spin text-cyan-300" />
                    </div>
                ) : documents.length === 0 ? (
                    <div className="p-8 text-sm text-gray-400">{t('empty')}</div>
                ) : filteredDocuments.length === 0 ? (
                    <div className="p-8 text-sm text-gray-400">{t('noMatches')}</div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-[1100px] w-full text-sm">
                            <thead className="bg-gray-900 text-gray-400">
                                <tr>
                                    {(['type', 'name', 'number', 'issuer', 'issue', 'expiry', 'status', 'service', 'file'] as const).map((key) => <th key={key} className="px-4 py-3 text-start font-medium">{t(`table.${key}`)}</th>)}
                                    <th className="px-4 py-3 text-end font-medium">{t('table.actions')}</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {filteredDocuments.map((document) => {
                                    const expiry = expiryState(document.expiry_date);
                                    return (
                                    <tr key={document.id} className="text-gray-300">
                                        <td className="px-4 py-3">{t(documentTypeMessageKey(document.document_type))}</td>
                                        <td className="px-4 py-3 text-white"><BidiText>{document.document_name}</BidiText></td>
                                        <td className="px-4 py-3"><TechnicalText>{displayValue(document.document_number)}</TechnicalText></td>
                                        <td className="px-4 py-3"><BidiText>{displayValue(document.issuer)}</BidiText></td>
                                        <td className="px-4 py-3">{document.issue_date ? formatDate(document.issue_date, locale) : displayValue(null)}</td>
                                        <td className="px-4 py-3">
                                            <div>{document.expiry_date ? formatDate(document.expiry_date, locale) : displayValue(null)}</div>
                                            {expiry !== 'valid' && expiry !== 'none' && (
                                                <span className={`mt-1 inline-flex rounded border px-2 py-1 text-xs ${expiryClass(expiry)}`}>
                                                    {t(expiryMessageKey(expiry))}
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`rounded border px-2 py-1 text-xs ${statusClass(document.status)}`}>
                                                {t(documentStatusMessageKey(document.status))}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            {serviceValues.has(document.related_service ?? '')
                                                ? translateServiceLabel(document.related_service ?? '', tCommon, labelForService(document.related_service, services))
                                                : displayValue(null)}
                                        </td>
                                        <td className="max-w-48 truncate px-4 py-3">
                                            <TechnicalText>{displayValue(document.optional_file_url)}</TechnicalText>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex justify-end gap-2">
                                                <button
                                                    type="button"
                                                    onClick={() => openEditForm(document)}
                                                    className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-900 hover:text-cyan-200"
                                                    aria-label={t('editNamed', { name: document.document_name })}
                                                >
                                                    <Edit3 className="h-4 w-4" />
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => deleteDocument(document)}
                                                    disabled={deletingId === document.id}
                                                    className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-red-500/10 hover:text-red-300 disabled:text-gray-600"
                                                    aria-label={t('deleteNamed', { name: document.document_name })}
                                                >
                                                    {deletingId === document.id ? (
                                                        <Loader2 className="h-4 w-4 animate-spin" />
                                                    ) : (
                                                        <Trash2 className="h-4 w-4" />
                                                    )}
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
}

function FormField({
    label,
    children,
}: {
    label: string;
    children: ReactNode;
}) {
    return (
        <label className="block space-y-2">
            <span className={labelClass}>{label}</span>
            {children}
        </label>
    );
}
