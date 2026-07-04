'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, Building2, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';
import {
    expiryState,
    labelForDocumentStatus,
    labelForDocumentType,
    labelForExpiryState,
} from '@/lib/readiness';
import { labelForService, serviceValueSet, useServiceMeta } from '@/lib/services';

type AdminCompany = {
    id: string;
    user_id: string;
    user_name?: string | null;
    user_email?: string | null;
    company_name?: string | null;
    industry?: string | null;
    inn?: string | null;
    website?: string | null;
    phone_contact?: string | null;
    address?: string | null;
    target_regions?: string[] | null;
    target_countries?: string[] | null;
    target_services?: string[] | null;
    pilot_status: string;
    approval_status: string;
};

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

const displayValue = (value?: string | null) => (value && value.trim() ? value : '-');

const statusLabel = (status: string) =>
    status
        ? status
            .split('_')
            .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
            .join(' ')
        : 'Unknown';

const statusClass = (status: string) => {
    if (status === 'approved' || status === 'available') {
        return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
    }
    if (status === 'pending' || status === 'missing') {
        return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
    }
    if (status === 'rejected' || status === 'expired') {
        return 'border-red-500/20 bg-red-500/10 text-red-200';
    }
    return 'border-gray-700 bg-gray-900 text-gray-300';
};

const expiryClass = (state: string) => {
    if (state === 'expired') return 'border-red-500/20 bg-red-500/10 text-red-200';
    if (state === 'expiring_soon') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
    return 'border-gray-700 bg-gray-900 text-gray-300';
};

export default function AdminCompanyDetailPage() {
    const params = useParams<{ companyProfileId: string }>();
    const companyProfileId = params.companyProfileId;
    const services = useServiceMeta();
    const serviceValues = serviceValueSet(services);
    const [company, setCompany] = useState<AdminCompany | null>(null);
    const [documents, setDocuments] = useState<ReadinessDocument[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadCompany = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [companyResponse, readinessResponse] = await Promise.all([
                api.get<AdminCompany>(`/admin/companies/${companyProfileId}`),
                api.get<ReadinessDocument[]>(`/admin/companies/${companyProfileId}/readiness`),
            ]);
            setCompany(companyResponse.data);
            setDocuments(readinessResponse.data ?? []);
        } catch (err) {
            console.error('Failed to load company detail:', err);
            setError('Company detail could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, [companyProfileId]);

    useEffect(() => {
        loadCompany();
    }, [loadCompany]);

    if (loading) {
        return (
            <div className="flex h-64 items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-cyan-300" />
            </div>
        );
    }

    if (error || !company) {
        return (
            <div className="space-y-4">
                <BackLink />
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error ?? 'Company profile was not found.'}
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <BackLink />

            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-500/20 bg-cyan-500/10">
                        <Building2 className="h-5 w-5 text-cyan-300" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-semibold text-white">
                            {company.company_name ?? 'Company detail'}
                        </h1>
                        <p className="text-sm text-gray-400">{displayValue(company.user_email)}</p>
                    </div>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                    <span className={`rounded border px-2 py-1 ${statusClass(company.approval_status)}`}>
                        Approval: {statusLabel(company.approval_status)}
                    </span>
                    <span className={`rounded border px-2 py-1 ${statusClass(company.pilot_status)}`}>
                        Pilot: {statusLabel(company.pilot_status)}
                    </span>
                </div>
            </div>

            <section className="grid grid-cols-1 gap-4 rounded-lg border border-gray-800 bg-gray-950 p-5 md:grid-cols-2 xl:grid-cols-3">
                <InfoItem label="User" value={company.user_name} />
                <InfoItem label="Email" value={company.user_email} />
                <InfoItem label="Industry" value={company.industry} />
                <InfoItem label="INN / registration" value={company.inn} />
                <InfoItem label="Phone" value={company.phone_contact} />
                <InfoItem label="Website" value={company.website} />
                <InfoItem label="Address" value={company.address} wide />
            </section>

            <section className="grid grid-cols-1 gap-4 rounded-lg border border-gray-800 bg-gray-950 p-5 md:grid-cols-3">
                <ChipGroup label="Target regions" values={company.target_regions ?? []} />
                <ChipGroup label="Target countries" values={company.target_countries ?? []} />
                <ChipGroup
                    label="Target services"
                    values={(company.target_services ?? []).map((service) => labelForService(service, services))}
                />
            </section>

            <section className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950">
                <div className="border-b border-gray-800 px-5 py-4">
                    <h2 className="text-base font-semibold text-white">Readiness documents</h2>
                    <p className="text-sm text-gray-400">{documents.length} records</p>
                </div>
                {documents.length === 0 ? (
                    <div className="p-8 text-sm text-gray-400">No readiness records yet.</div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-[1050px] w-full text-sm">
                            <thead className="bg-gray-900 text-gray-400">
                                <tr>
                                    <th className="px-4 py-3 text-left font-medium">Type</th>
                                    <th className="px-4 py-3 text-left font-medium">Name</th>
                                    <th className="px-4 py-3 text-left font-medium">Issuer</th>
                                    <th className="px-4 py-3 text-left font-medium">Status</th>
                                    <th className="px-4 py-3 text-left font-medium">Expiry</th>
                                    <th className="px-4 py-3 text-left font-medium">Service</th>
                                    <th className="px-4 py-3 text-left font-medium">File/reference</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {documents.map((document) => {
                                    const expiry = expiryState(document.expiry_date);
                                    return (
                                        <tr key={document.id} className="text-gray-300">
                                            <td className="px-4 py-3">{labelForDocumentType(document.document_type)}</td>
                                            <td className="px-4 py-3 text-white">{document.document_name}</td>
                                            <td className="px-4 py-3">{displayValue(document.issuer)}</td>
                                            <td className="px-4 py-3">
                                                <span className={`rounded border px-2 py-1 text-xs ${statusClass(document.status)}`}>
                                                    {labelForDocumentStatus(document.status)}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                <div>{displayValue(document.expiry_date)}</div>
                                                {expiry !== 'valid' && expiry !== 'none' && (
                                                    <span className={`mt-1 inline-flex rounded border px-2 py-1 text-xs ${expiryClass(expiry)}`}>
                                                        {labelForExpiryState(expiry)}
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3">
                                                {serviceValues.has(document.related_service ?? '')
                                                    ? labelForService(document.related_service, services)
                                                    : '-'}
                                            </td>
                                            <td className="max-w-60 truncate px-4 py-3">
                                                {displayValue(document.optional_file_url)}
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

function BackLink() {
    return (
        <Link
            href="/admin/approvals"
            className="inline-flex items-center gap-2 text-sm text-gray-400 transition-colors hover:text-white"
        >
            <ArrowLeft className="h-4 w-4" />
            Approval queue
        </Link>
    );
}

function InfoItem({
    label,
    value,
    wide,
}: {
    label: string;
    value?: string | null;
    wide?: boolean;
}) {
    return (
        <div className={wide ? 'xl:col-span-3' : undefined}>
            <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
            <div className="mt-1 text-sm text-gray-200">{displayValue(value)}</div>
        </div>
    );
}

function ChipGroup({
    label,
    values,
}: {
    label: string;
    values: string[];
}) {
    return (
        <div className="space-y-3">
            <div className="text-sm font-medium text-gray-300">{label}</div>
            <div className="flex flex-wrap gap-2">
                {values.length > 0 ? (
                    values.map((value) => (
                        <span
                            key={value}
                            className={`rounded border px-2 py-1 text-xs ${
                                value === 'Central Asia'
                                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                                    : 'border-gray-700 bg-gray-900 text-gray-300'
                            }`}
                        >
                            {value}
                        </span>
                    ))
                ) : (
                    <span className="text-sm text-gray-500">None selected</span>
                )}
            </div>
        </div>
    );
}
