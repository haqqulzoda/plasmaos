'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Building2, Check, Globe2, Loader2, Phone, Save } from 'lucide-react';
import { api } from '@/lib/api';
import { CENTRAL_ASIA_REGION, useGeographyMeta } from '@/lib/geography';
import type { ServiceOption } from '@/lib/services';
import { labelForService, useServiceMeta } from '@/lib/services';

type CompanyProfile = {
    company_name: string;
    industry: string;
    inn: string;
    website: string;
    phone_contact: string;
    address: string;
    target_regions: string[];
    target_countries: string[];
    target_services: string[];
    pilot_status: string;
    approval_status: string;
};

const emptyProfile: CompanyProfile = {
    company_name: '',
    industry: '',
    inn: '',
    website: '',
    phone_contact: '',
    address: '',
    target_regions: [],
    target_countries: [],
    target_services: [],
    pilot_status: '',
    approval_status: '',
};

const inputClass =
    'w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 text-sm placeholder-gray-600 outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500 transition-all';

const labelClass = 'text-sm font-medium text-gray-300';

const statusLabel = (status: string) =>
    status
        ? status
            .split('_')
            .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
            .join(' ')
        : 'Unknown';

const statusClass = (status: string) => {
    if (status === 'approved') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
    if (status === 'pending') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
    if (status === 'rejected') return 'border-red-500/20 bg-red-500/10 text-red-200';
    if (status === 'disabled') return 'border-gray-700 bg-gray-900 text-gray-300';
    return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200';
};

function toggleValue(values: string[], value: string): string[] {
    if (values.includes(value)) {
        return values.filter((item) => item !== value);
    }
    return [...values, value];
}

function normalizeProfile(data: Partial<CompanyProfile>): CompanyProfile {
    return {
        company_name: data.company_name ?? '',
        industry: data.industry ?? '',
        inn: data.inn ?? '',
        website: data.website ?? '',
        phone_contact: data.phone_contact ?? '',
        address: data.address ?? '',
        target_regions: data.target_regions ?? [],
        target_countries: data.target_countries ?? [],
        target_services: data.target_services ?? [],
        pilot_status: data.pilot_status ?? '',
        approval_status: data.approval_status ?? '',
    };
}

export default function CompanyProfilePage() {
    const geography = useGeographyMeta();
    const services = useServiceMeta();
    const [profile, setProfile] = useState<CompanyProfile>(emptyProfile);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const loadProfile = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await api.get<Partial<CompanyProfile>>('/users/me/company');
            setProfile(normalizeProfile(response.data));
        } catch (err) {
            console.error('Failed to load company profile:', err);
            setError('Company profile could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadProfile();
    }, [loadProfile]);

    const updateField = (field: keyof CompanyProfile, value: string) => {
        setProfile((current) => ({ ...current, [field]: value }));
    };

    const toggleListField = (
        field: 'target_regions' | 'target_countries' | 'target_services',
        value: string,
    ) => {
        setProfile((current) => ({
            ...current,
            [field]: toggleValue(current[field], value),
        }));
    };

    const toggleCentralAsiaCountries = () => {
        setProfile((current) => {
            const selected = geography.central_asia_countries.every((country) =>
                current.target_countries.includes(country),
            );
            const centralAsiaCountrySet = new Set(geography.central_asia_countries);

            return {
                ...current,
                target_countries: selected
                    ? current.target_countries.filter((country) => !centralAsiaCountrySet.has(country))
                    : Array.from(new Set([...current.target_countries, ...geography.central_asia_countries])),
            };
        });
    };

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setSaving(true);
        setSaved(false);
        setError(null);

        try {
            const response = await api.put<Partial<CompanyProfile>>('/users/me/company', {
                company_name: profile.company_name || null,
                industry: profile.industry || null,
                inn: profile.inn || null,
                website: profile.website || null,
                phone_contact: profile.phone_contact || null,
                address: profile.address || null,
                target_regions: profile.target_regions,
                target_countries: profile.target_countries,
                target_services: profile.target_services,
            });
            setProfile(normalizeProfile(response.data));
            setSaved(true);
            window.setTimeout(() => setSaved(false), 2500);
        } catch (err) {
            console.error('Failed to save company profile:', err);
            setError('Company profile could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="flex h-64 items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-cyan-300" />
            </div>
        );
    }

    return (
        <div className="mx-auto w-full max-w-5xl space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-500/20 bg-cyan-500/10">
                        <Building2 className="h-5 w-5 text-cyan-300" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-semibold text-white">Company profile</h1>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs">
                            <span className={`rounded border px-2 py-1 ${statusClass(profile.pilot_status)}`}>
                                Pilot: {statusLabel(profile.pilot_status)}
                            </span>
                            <span className={`rounded border px-2 py-1 ${statusClass(profile.approval_status)}`}>
                                Approval: {statusLabel(profile.approval_status)}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error}
                </div>
            )}

            <TargetSummary profile={profile} services={services} />

            <form onSubmit={handleSubmit} className="space-y-6">
                <section className="space-y-5 rounded-lg border border-gray-800 bg-gray-950 p-6">
                    <div className="flex items-center gap-2 text-gray-200">
                        <Building2 className="h-4 w-4 text-cyan-300" />
                        <h2 className="text-base font-semibold">Company</h2>
                    </div>
                    <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                        <label className="space-y-2">
                            <span className={labelClass}>Company name</span>
                            <input
                                className={inputClass}
                                value={profile.company_name}
                                onChange={(event) => updateField('company_name', event.target.value)}
                            />
                        </label>
                        <label className="space-y-2">
                            <span className={labelClass}>Industry</span>
                            <input
                                className={inputClass}
                                value={profile.industry}
                                onChange={(event) => updateField('industry', event.target.value)}
                            />
                        </label>
                        <label className="space-y-2">
                            <span className={labelClass}>INN / registration number</span>
                            <input
                                className={inputClass}
                                value={profile.inn}
                                onChange={(event) => updateField('inn', event.target.value)}
                            />
                        </label>
                        <label className="space-y-2">
                            <span className={labelClass}>Website</span>
                            <input
                                className={inputClass}
                                value={profile.website}
                                onChange={(event) => updateField('website', event.target.value)}
                                placeholder="https://"
                                type="url"
                            />
                        </label>
                        <label className="space-y-2">
                            <span className={labelClass}>Phone</span>
                            <div className="relative">
                                <Phone className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                                <input
                                    className={`${inputClass} pl-11`}
                                    value={profile.phone_contact}
                                    onChange={(event) => updateField('phone_contact', event.target.value)}
                                />
                            </div>
                        </label>
                        <label className="space-y-2">
                            <span className={labelClass}>Address</span>
                            <input
                                className={inputClass}
                                value={profile.address}
                                onChange={(event) => updateField('address', event.target.value)}
                            />
                        </label>
                    </div>
                </section>

                <section className="space-y-5 rounded-lg border border-gray-800 bg-gray-950 p-6">
                    <div className="flex items-center gap-2 text-gray-200">
                        <Globe2 className="h-4 w-4 text-emerald-300" />
                        <h2 className="text-base font-semibold">Markets and services</h2>
                    </div>
                    <OptionGrid
                        label="Target regions"
                        options={geography.regions.map((region) => ({ value: region, label: region }))}
                        values={profile.target_regions}
                        onToggle={(value) => toggleListField('target_regions', value)}
                    />
                    <OptionGrid
                        label="Central Asia countries"
                        options={geography.central_asia_countries.map((country) => ({
                            value: country,
                            label: country,
                        }))}
                        values={profile.target_countries}
                        onToggle={(value) => toggleListField('target_countries', value)}
                        actionLabel={
                            geography.central_asia_countries.every((country) =>
                                profile.target_countries.includes(country),
                            )
                                ? 'Clear Central Asia'
                                : 'Select all Central Asia'
                        }
                        onAction={toggleCentralAsiaCountries}
                    />
                    <OptionGrid
                        label="Target services"
                        options={services}
                        values={profile.target_services}
                        onToggle={(value) => toggleListField('target_services', value)}
                    />
                </section>

                <div className="flex items-center justify-end gap-3">
                    {saved && (
                        <span className="inline-flex items-center gap-2 text-sm text-emerald-300">
                            <Check className="h-4 w-4" />
                            Saved
                        </span>
                    )}
                    <button
                        type="submit"
                        disabled={saving}
                        className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:bg-gray-700 disabled:text-gray-400"
                    >
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                        Save profile
                    </button>
                </div>
            </form>
        </div>
    );
}

function TargetSummary({
    profile,
    services,
}: {
    profile: CompanyProfile;
    services: ServiceOption[];
}) {
    return (
        <section className="grid grid-cols-1 gap-4 rounded-lg border border-gray-800 bg-gray-950 p-5 md:grid-cols-3">
            <SummaryGroup label="Target regions" values={profile.target_regions} />
            <SummaryGroup label="Target countries" values={profile.target_countries} />
            <SummaryGroup
                label="Target services"
                values={profile.target_services.map((service) => labelForService(service, services))}
            />
        </section>
    );
}

function SummaryGroup({
    label,
    values,
}: {
    label: string;
    values: string[];
}) {
    return (
        <div className="space-y-3">
            <div className={labelClass}>{label}</div>
            <div className="flex flex-wrap gap-2">
                {values.length > 0 ? (
                    values.map((value) => {
                        const isCentralAsia = value === CENTRAL_ASIA_REGION;
                        return (
                            <span
                                key={value}
                                className={`rounded border px-2 py-1 text-xs ${
                                    isCentralAsia
                                        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                                        : 'border-gray-700 bg-gray-900 text-gray-300'
                                }`}
                            >
                                {value}
                            </span>
                        );
                    })
                ) : (
                    <span className="text-sm text-gray-500">None selected</span>
                )}
            </div>
        </div>
    );
}

function OptionGrid({
    label,
    options,
    values,
    onToggle,
    actionLabel,
    onAction,
}: {
    label: string;
    options: ServiceOption[];
    values: string[];
    onToggle: (value: string) => void;
    actionLabel?: string;
    onAction?: () => void;
}) {
    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
                <span className={labelClass}>{label}</span>
                {actionLabel && onAction && (
                    <button
                        type="button"
                        onClick={onAction}
                        className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-100 transition-colors hover:border-emerald-300"
                    >
                        <Check className="h-3.5 w-3.5" />
                        {actionLabel}
                    </button>
                )}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {options.map((option) => {
                    const selected = values.includes(option.value);
                    const isCentralAsia = option.value === CENTRAL_ASIA_REGION;
                    return (
                        <button
                            key={option.value}
                            type="button"
                            onClick={() => onToggle(option.value)}
                            className={`flex min-h-12 items-center justify-between rounded-lg border px-4 py-3 text-left text-sm transition-colors ${
                                selected
                                    ? isCentralAsia
                                        ? 'border-emerald-400 bg-emerald-500/15 text-emerald-100'
                                        : 'border-cyan-400 bg-cyan-500/10 text-cyan-100'
                                    : isCentralAsia
                                        ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-200 hover:border-emerald-400'
                                        : 'border-gray-800 bg-gray-900 text-gray-300 hover:border-gray-700'
                            }`}
                        >
                            <span className="break-words">{option.label}</span>
                            {selected && <Check className="ml-3 h-4 w-4 shrink-0" />}
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
