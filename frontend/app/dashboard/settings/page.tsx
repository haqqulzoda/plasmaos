'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Building2, User, MapPin, Landmark, Save, Loader2, CheckCircle,
    Phone, Award, ScrollText, TrendingUp, Plus, X, Shield,
} from 'lucide-react';
import { api } from '@/lib/api';

/* ================================================================== */
/*  Types                                                              */
/* ================================================================== */

interface CompanyProfile {
    company_name: string;
    director_name: string;
    address: string;
    phone_contact: string;
    bank_name: string;
    mfo: string;
    account_number: string;
    inn: string;
}

interface CertificationRow {
    _uid: string;
    cert_type: string;
    issue_date: string;   // DD/MM/YYYY display format
    expiry_date: string;  // DD/MM/YYYY display format
}

interface LicenseRow {
    _uid: string;
    license_name: string;
    is_active: boolean;
}

interface FinancialRow {
    _uid: string;
    year: string;
    turnover_uzs: string;
}

type TabId = 'general' | 'certifications' | 'licenses' | 'financials';

interface TabDef {
    id: TabId;
    label: string;
    icon: React.ReactNode;
    count?: number;
}

/* ================================================================== */
/*  Date helpers  DD/MM/YYYY ↔ YYYY-MM-DD                             */
/* ================================================================== */

/** API → Display: "2024-01-15" → "15/01/2024" */
function isoToDisplay(iso: string): string {
    if (!iso) return '';
    const [y, m, d] = iso.split('-');
    if (!y || !m || !d) return iso;
    return `${d}/${m}/${y}`;
}

/** Display → API: "15/01/2024" → "2024-01-15", returns '' on invalid */
function displayToIso(display: string): string {
    if (!display) return '';
    const parts = display.split('/');
    if (parts.length !== 3) return '';
    const [d, m, y] = parts;
    const day = parseInt(d, 10);
    const month = parseInt(m, 10);
    const year = parseInt(y, 10);
    if (isNaN(day) || isNaN(month) || isNaN(year)) return '';
    if (day < 1 || day > 31 || month < 1 || month > 12 || year < 1900 || year > 2099) return '';
    const pad = (n: number, len: number) => String(n).padStart(len, '0');
    return `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`;
}

/** Auto-insert slashes as the user types: "15" → "15/", "1501" → "15/01/" */
function maskDateInput(raw: string, prev: string): string {
    // Strip non-digit non-slash
    let digits = raw.replace(/[^\d]/g, '');
    if (digits.length > 8) digits = digits.slice(0, 8);

    // If user is deleting, allow it
    if (raw.length < prev.length) return raw;

    let result = '';
    for (let i = 0; i < digits.length; i++) {
        if (i === 2 || i === 4) result += '/';
        result += digits[i];
    }
    return result;
}

/* ================================================================== */
/*  Shared styles                                                      */
/* ================================================================== */

const inputClass =
    'w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 text-sm placeholder-gray-600 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all font-mono tracking-wide';

const rowCard =
    'relative p-4 bg-gray-900 border border-gray-800 rounded-xl group hover:border-gray-700 transition-colors';

const removeBtn =
    'absolute top-3 right-3 p-1 rounded text-gray-600 hover:text-red-400 hover:bg-red-500/5 transition-colors';

/* ================================================================== */
/*  Component                                                          */
/* ================================================================== */

export default function SettingsPage() {
    /* ---- Tab state ---- */
    const [activeTab, setActiveTab] = useState<TabId>('general');

    /* ---- Root profile state ---- */
    const [profile, setProfile] = useState<CompanyProfile>({
        company_name: '',
        director_name: '',
        address: '',
        phone_contact: '',
        bank_name: '',
        mfo: '',
        account_number: '',
        inn: '',
    });

    /* ---- Nested arrays state ---- */
    const [certifications, setCertifications] = useState<CertificationRow[]>([]);
    const [licenses, setLicenses] = useState<LicenseRow[]>([]);
    const [financialHistory, setFinancialHistory] = useState<FinancialRow[]>([]);

    /* ---- UI state ---- */
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    /* ============================================================== */
    /*  Data fetching — GET /vault                                     */
    /* ============================================================== */

    useEffect(() => {
        const fetchVault = async () => {
            try {
                const res = await api.get('/vault');
                const d = res.data;

                setProfile({
                    company_name: d.company_name || '',
                    director_name: d.director_name || '',
                    address: d.address || '',
                    phone_contact: d.phone_contact || '',
                    bank_name: d.bank_name || '',
                    mfo: d.mfo || '',
                    account_number: d.account_number || '',
                    inn: d.inn || '',
                });

                setCertifications(
                    (d.certifications ?? []).map((c: { cert_type: string; issue_date: string; expiry_date: string }) => ({
                        _uid: crypto.randomUUID(),
                        cert_type: c.cert_type,
                        issue_date: isoToDisplay(c.issue_date),
                        expiry_date: isoToDisplay(c.expiry_date),
                    })),
                );
                setLicenses(
                    (d.licenses ?? []).map((l: { license_name: string; is_active: boolean }) => ({
                        _uid: crypto.randomUUID(),
                        license_name: l.license_name,
                        is_active: l.is_active,
                    })),
                );
                setFinancialHistory(
                    (d.financial_history ?? []).map((f: { year: number; turnover_uzs: number }) => ({
                        _uid: crypto.randomUUID(),
                        year: String(f.year),
                        turnover_uzs: String(f.turnover_uzs),
                    })),
                );
            } catch (err: unknown) {
                const isAxios = typeof err === 'object' && err !== null && 'response' in err;
                if (isAxios && (err as { response?: { status?: number } }).response?.status === 404) {
                    // Vault doesn't exist yet
                } else {
                    console.error('Failed to fetch vault:', err);
                    setError('Failed to load company vault');
                }
            } finally {
                setLoading(false);
            }
        };
        fetchVault();
    }, []);

    /* ============================================================== */
    /*  Mutation — PUT /vault                                          */
    /* ============================================================== */

    const handleSave = useCallback(async () => {
        setSaving(true);
        setSaved(false);
        setError(null);

        // Validate dates before sending
        for (const cert of certifications) {
            if (cert.issue_date && !displayToIso(cert.issue_date)) {
                setError(`Invalid issue date: "${cert.issue_date}". Use DD/MM/YYYY format.`);
                setSaving(false);
                return;
            }
            if (cert.expiry_date && !displayToIso(cert.expiry_date)) {
                setError(`Invalid expiry date: "${cert.expiry_date}". Use DD/MM/YYYY format.`);
                setSaving(false);
                return;
            }
        }

        try {
            const payload = {
                ...profile,
                certifications: certifications.map(({ cert_type, issue_date, expiry_date }) => ({
                    cert_type,
                    issue_date: displayToIso(issue_date),
                    expiry_date: displayToIso(expiry_date),
                })),
                licenses: licenses.map(({ license_name, is_active }) => ({
                    license_name,
                    is_active,
                })),
                financial_history: financialHistory.map(({ year, turnover_uzs }) => ({
                    year: Number(year),
                    turnover_uzs: Number(turnover_uzs),
                })),
            };

            await api.put('/vault', payload);
            setSaved(true);
            setTimeout(() => setSaved(false), 3000);
        } catch (err) {
            console.error('Failed to save vault:', err);
            setError('Failed to save company vault');
        } finally {
            setSaving(false);
        }
    }, [profile, certifications, licenses, financialHistory]);

    /* ============================================================== */
    /*  Field helpers                                                   */
    /* ============================================================== */

    const updateField = (field: keyof CompanyProfile, value: string) => {
        setProfile(prev => ({ ...prev, [field]: value }));
    };

    /* ---- certifications ---- */
    const addCert = () =>
        setCertifications(prev => [
            ...prev,
            { _uid: crypto.randomUUID(), cert_type: '', issue_date: '', expiry_date: '' },
        ]);
    const removeCert = (uid: string) =>
        setCertifications(prev => prev.filter(c => c._uid !== uid));
    const updateCert = (uid: string, field: keyof Omit<CertificationRow, '_uid'>, value: string) =>
        setCertifications(prev =>
            prev.map(c => (c._uid === uid ? { ...c, [field]: value } : c)),
        );

    /* ---- licenses ---- */
    const addLicense = () =>
        setLicenses(prev => [
            ...prev,
            { _uid: crypto.randomUUID(), license_name: '', is_active: true },
        ]);
    const removeLicense = (uid: string) =>
        setLicenses(prev => prev.filter(l => l._uid !== uid));
    const updateLicense = (uid: string, field: keyof Omit<LicenseRow, '_uid'>, value: string | boolean) =>
        setLicenses(prev =>
            prev.map(l => (l._uid === uid ? { ...l, [field]: value } : l)),
        );

    /* ---- financial history ---- */
    const addFinancial = () =>
        setFinancialHistory(prev => [
            ...prev,
            { _uid: crypto.randomUUID(), year: '', turnover_uzs: '' },
        ]);
    const removeFinancial = (uid: string) =>
        setFinancialHistory(prev => prev.filter(f => f._uid !== uid));
    const updateFinancial = (uid: string, field: keyof Omit<FinancialRow, '_uid'>, value: string) =>
        setFinancialHistory(prev =>
            prev.map(f => (f._uid === uid ? { ...f, [field]: value } : f)),
        );

    /* ============================================================== */
    /*  Tab definitions                                                */
    /* ============================================================== */

    const tabs: TabDef[] = [
        { id: 'general', label: 'General', icon: <Building2 className="w-4 h-4" /> },
        { id: 'certifications', label: 'Certifications', icon: <Award className="w-4 h-4" />, count: certifications.length },
        { id: 'licenses', label: 'Licenses', icon: <ScrollText className="w-4 h-4" />, count: licenses.length },
        { id: 'financials', label: 'Financials', icon: <TrendingUp className="w-4 h-4" />, count: financialHistory.length },
    ];

    /* ============================================================== */
    /*  Loading                                                        */
    /* ============================================================== */

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
            </div>
        );
    }

    /* ============================================================== */
    /*  Render                                                         */
    /* ============================================================== */

    return (
        <div className="w-full max-w-screen-2xl mx-auto space-y-6">
            {/* Page header */}
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
                <div className="flex items-center gap-3 mb-1">
                    <Shield className="w-5 h-5 text-gray-500" />
                    <h1 className="text-xl font-semibold text-white tracking-tight">Company Vault</h1>
                </div>
                <p className="text-gray-500 text-sm ml-8">Secured company profile, credentials and financial records</p>
            </motion.div>

            {/* Error banner */}
            {error && (
                <div className="text-red-400 bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-sm font-mono">
                    {error}
                </div>
            )}

            {/* Main layout: sidebar + content */}
            <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.1 }}
                className="flex gap-0 border border-gray-800 rounded-xl overflow-hidden bg-gray-950 min-h-[520px]"
            >
                {/* ═════ Left sidebar ═════ */}
                <nav className="w-56 shrink-0 border-r border-gray-800 bg-gray-950/50 flex flex-col justify-between">
                    <div className="py-2">
                        {tabs.map((tab) => {
                            const isActive = activeTab === tab.id;
                            return (
                                <button
                                    key={tab.id}
                                    onClick={() => setActiveTab(tab.id)}
                                    className={`
                                        w-full flex items-center gap-3 px-5 py-3 text-sm font-medium transition-all duration-150
                                        ${isActive
                                            ? 'bg-indigo-900/20 text-indigo-400 border-l-2 border-indigo-500'
                                            : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 border-l-2 border-transparent'
                                        }
                                    `}
                                >
                                    {tab.icon}
                                    <span>{tab.label}</span>
                                    {tab.count !== undefined && tab.count > 0 && (
                                        <span className={`ml-auto text-xs px-1.5 py-0.5 rounded font-mono ${isActive ? 'bg-indigo-500/20 text-indigo-300' : 'bg-gray-800 text-gray-500'
                                            }`}>
                                            {tab.count}
                                        </span>
                                    )}
                                </button>
                            );
                        })}
                    </div>

                    {/* Save button — always visible in sidebar footer */}
                    <div className="p-4 border-t border-gray-800">
                        {saved && (
                            <motion.div
                                initial={{ opacity: 0, y: 4 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="flex items-center gap-2 text-green-400 text-xs mb-3 font-mono"
                            >
                                <CheckCircle className="w-3.5 h-3.5" />
                                <span>Vault saved</span>
                            </motion.div>
                        )}
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-3 rounded-lg shadow-md transition-colors disabled:bg-gray-700 disabled:text-gray-500"
                        >
                            {saving ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Saving…
                                </>
                            ) : (
                                <>
                                    <Save className="w-4 h-4" />
                                    Save Changes
                                </>
                            )}
                        </button>
                    </div>
                </nav>

                {/* ═════ Right content pane ═════ */}
                <div className="flex-1 overflow-y-auto">
                    <AnimatePresence mode="wait">
                        <motion.div
                            key={activeTab}
                            initial={{ opacity: 0, x: 8 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: -8 }}
                            transition={{ duration: 0.2 }}
                            className="p-6"
                        >
                            {activeTab === 'general' && (
                                <GeneralTab profile={profile} updateField={updateField} />
                            )}
                            {activeTab === 'certifications' && (
                                <CertificationsTab
                                    certifications={certifications}
                                    addCert={addCert}
                                    removeCert={removeCert}
                                    updateCert={updateCert}
                                />
                            )}
                            {activeTab === 'licenses' && (
                                <LicensesTab
                                    licenses={licenses}
                                    addLicense={addLicense}
                                    removeLicense={removeLicense}
                                    updateLicense={updateLicense}
                                />
                            )}
                            {activeTab === 'financials' && (
                                <FinancialsTab
                                    financialHistory={financialHistory}
                                    addFinancial={addFinancial}
                                    removeFinancial={removeFinancial}
                                    updateFinancial={updateFinancial}
                                />
                            )}
                        </motion.div>
                    </AnimatePresence>
                </div>
            </motion.div>
        </div>
    );
}

/* ================================================================== */
/*  Tab: General                                                       */
/* ================================================================== */

function GeneralTab({
    profile,
    updateField,
}: {
    profile: CompanyProfile;
    updateField: (field: keyof CompanyProfile, value: string) => void;
}) {
    return (
        <div className="space-y-6">
            <div className="flex items-center gap-2 mb-1">
                <Building2 className="w-4 h-4 text-gray-500" />
                <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">Company Information</h2>
            </div>

            <div className="grid grid-cols-2 gap-4 mt-5">
                <FieldBlock label="Company Name" icon={<Building2 className="w-3.5 h-3.5" />}>
                    <input
                        type="text"
                        value={profile.company_name}
                        onChange={(e) => updateField('company_name', e.target.value)}
                        placeholder="Plasma Construction LLC"
                        className={inputClass}
                    />
                </FieldBlock>
                <FieldBlock label="Director" icon={<User className="w-3.5 h-3.5" />}>
                    <input
                        type="text"
                        value={profile.director_name}
                        onChange={(e) => updateField('director_name', e.target.value)}
                        placeholder="Akmal Abdullayev"
                        className={inputClass}
                    />
                </FieldBlock>
                <FieldBlock label="Address" icon={<MapPin className="w-3.5 h-3.5" />}>
                    <input
                        type="text"
                        value={profile.address}
                        onChange={(e) => updateField('address', e.target.value)}
                        placeholder="Tashkent, Amir Temur 1"
                        className={inputClass}
                    />
                </FieldBlock>
                <FieldBlock label="Phone" icon={<Phone className="w-3.5 h-3.5" />}>
                    <input
                        type="text"
                        value={profile.phone_contact}
                        onChange={(e) => updateField('phone_contact', e.target.value)}
                        placeholder="+998 90 123 45 67"
                        className={inputClass}
                    />
                </FieldBlock>
            </div>

            {/* Banking separator */}
            <div className="pt-2">
                <div className="flex items-center gap-2 mb-4">
                    <Landmark className="w-4 h-4 text-gray-500" />
                    <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">Banking Details</h2>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <FieldBlock label="Bank Name">
                        <input
                            type="text"
                            value={profile.bank_name}
                            onChange={(e) => updateField('bank_name', e.target.value)}
                            placeholder="Hamkorbank"
                            className={inputClass}
                        />
                    </FieldBlock>
                    <FieldBlock label="MFO">
                        <input
                            type="text"
                            value={profile.mfo}
                            onChange={(e) => updateField('mfo', e.target.value)}
                            placeholder="00873"
                            className={inputClass}
                        />
                    </FieldBlock>
                    <FieldBlock label="Account Number">
                        <input
                            type="text"
                            value={profile.account_number}
                            onChange={(e) => updateField('account_number', e.target.value)}
                            placeholder="20208000123456789012"
                            className={inputClass}
                        />
                    </FieldBlock>
                    <FieldBlock label="INN (Tax ID)">
                        <input
                            type="text"
                            value={profile.inn}
                            onChange={(e) => updateField('inn', e.target.value)}
                            placeholder="123456789"
                            className={inputClass}
                        />
                    </FieldBlock>
                </div>
            </div>
        </div>
    );
}

/* ================================================================== */
/*  Tab: Certifications                                                */
/* ================================================================== */

function CertificationsTab({
    certifications,
    addCert,
    removeCert,
    updateCert,
}: {
    certifications: CertificationRow[];
    addCert: () => void;
    removeCert: (uid: string) => void;
    updateCert: (uid: string, field: keyof Omit<CertificationRow, '_uid'>, value: string) => void;
}) {
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                    <Award className="w-4 h-4 text-gray-500" />
                    <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">Certifications</h2>
                </div>
                <span className="text-xs text-gray-600 font-mono">{certifications.length} record{certifications.length !== 1 ? 's' : ''}</span>
            </div>

            {certifications.length === 0 && (
                <div className="text-center py-12 text-gray-600 text-sm">
                    No certifications registered.
                </div>
            )}

            {certifications.map((cert, idx) => (
                <div key={cert._uid} className={rowCard}>
                    <button type="button" onClick={() => removeCert(cert._uid)} className={removeBtn} aria-label="Remove">
                        <X className="w-3.5 h-3.5" />
                    </button>

                    <div className="text-xs text-gray-600 font-mono mb-3">CERT-{String(idx + 1).padStart(3, '0')}</div>

                    <div className="grid grid-cols-3 gap-3 pr-8">
                        <FieldBlock label="Type" compact>
                            <input
                                type="text"
                                value={cert.cert_type}
                                onChange={(e) => updateCert(cert._uid, 'cert_type', e.target.value)}
                                placeholder="ISO 9001"
                                className={inputClass}
                            />
                        </FieldBlock>
                        <FieldBlock label="Issue Date" compact>
                            <input
                                type="text"
                                value={cert.issue_date}
                                onChange={(e) => updateCert(cert._uid, 'issue_date', maskDateInput(e.target.value, cert.issue_date))}
                                placeholder="DD/MM/YYYY"
                                maxLength={10}
                                className={inputClass}
                            />
                        </FieldBlock>
                        <FieldBlock label="Expiry Date" compact>
                            <input
                                type="text"
                                value={cert.expiry_date}
                                onChange={(e) => updateCert(cert._uid, 'expiry_date', maskDateInput(e.target.value, cert.expiry_date))}
                                placeholder="DD/MM/YYYY"
                                maxLength={10}
                                className={inputClass}
                            />
                        </FieldBlock>
                    </div>
                </div>
            ))}

            <button
                type="button"
                onClick={addCert}
                className="flex items-center justify-center gap-2 w-full py-2.5 text-xs font-medium text-gray-500 border border-dashed border-gray-800 rounded-lg hover:text-gray-300 hover:border-gray-700 transition-colors"
            >
                <Plus className="w-3.5 h-3.5" />
                Add Certification
            </button>
        </div>
    );
}

/* ================================================================== */
/*  Tab: Licenses                                                      */
/* ================================================================== */

function LicensesTab({
    licenses,
    addLicense,
    removeLicense,
    updateLicense,
}: {
    licenses: LicenseRow[];
    addLicense: () => void;
    removeLicense: (uid: string) => void;
    updateLicense: (uid: string, field: keyof Omit<LicenseRow, '_uid'>, value: string | boolean) => void;
}) {
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                    <ScrollText className="w-4 h-4 text-gray-500" />
                    <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">Licenses</h2>
                </div>
                <span className="text-xs text-gray-600 font-mono">{licenses.length} record{licenses.length !== 1 ? 's' : ''}</span>
            </div>

            {licenses.length === 0 && (
                <div className="text-center py-12 text-gray-600 text-sm">
                    No licenses registered.
                </div>
            )}

            {licenses.map((lic, idx) => (
                <div key={lic._uid} className={rowCard}>
                    <button type="button" onClick={() => removeLicense(lic._uid)} className={removeBtn} aria-label="Remove">
                        <X className="w-3.5 h-3.5" />
                    </button>

                    <div className="text-xs text-gray-600 font-mono mb-3">LIC-{String(idx + 1).padStart(3, '0')}</div>

                    <div className="flex items-end gap-4 pr-8">
                        <div className="flex-1">
                            <FieldBlock label="License Name" compact>
                                <input
                                    type="text"
                                    value={lic.license_name}
                                    onChange={(e) => updateLicense(lic._uid, 'license_name', e.target.value)}
                                    placeholder="Construction License Cat-III"
                                    className={inputClass}
                                />
                            </FieldBlock>
                        </div>
                        <div className="pb-0.5 flex items-center gap-3">
                            <button
                                type="button"
                                role="switch"
                                aria-checked={lic.is_active}
                                onClick={() => updateLicense(lic._uid, 'is_active', !lic.is_active)}
                                className={`relative inline-flex h-6 w-10 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${lic.is_active ? 'bg-white' : 'bg-gray-700'
                                    }`}
                            >
                                <span
                                    className={`pointer-events-none inline-block h-5 w-5 rounded-full shadow-sm ring-0 transition duration-200 mt-0.5 ${lic.is_active
                                        ? 'translate-x-[18px] bg-gray-950 ml-0'
                                        : 'translate-x-0.5 bg-gray-500'
                                        }`}
                                />
                            </button>
                            <span className={`text-xs font-mono tracking-wider ${lic.is_active ? 'text-white' : 'text-gray-600'}`}>
                                {lic.is_active ? 'ACTIVE' : 'INACTIVE'}
                            </span>
                        </div>
                    </div>
                </div>
            ))}

            <button
                type="button"
                onClick={addLicense}
                className="flex items-center justify-center gap-2 w-full py-2.5 text-xs font-medium text-gray-500 border border-dashed border-gray-800 rounded-lg hover:text-gray-300 hover:border-gray-700 transition-colors"
            >
                <Plus className="w-3.5 h-3.5" />
                Add License
            </button>
        </div>
    );
}

/* ================================================================== */
/*  Tab: Financials                                                    */
/* ================================================================== */

function FinancialsTab({
    financialHistory,
    addFinancial,
    removeFinancial,
    updateFinancial,
}: {
    financialHistory: FinancialRow[];
    addFinancial: () => void;
    removeFinancial: (uid: string) => void;
    updateFinancial: (uid: string, field: keyof Omit<FinancialRow, '_uid'>, value: string) => void;
}) {
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-gray-500" />
                    <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">Financial History</h2>
                </div>
                <span className="text-xs text-gray-600 font-mono">{financialHistory.length} record{financialHistory.length !== 1 ? 's' : ''}</span>
            </div>

            {financialHistory.length === 0 && (
                <div className="text-center py-12 text-gray-600 text-sm">
                    No financial records registered.
                </div>
            )}

            {/* Table header */}
            {financialHistory.length > 0 && (
                <div className="grid grid-cols-2 gap-3 px-4 pb-1">
                    <span className="text-[10px] text-gray-600 font-mono uppercase tracking-widest">Year</span>
                    <span className="text-[10px] text-gray-600 font-mono uppercase tracking-widest">Turnover (UZS)</span>
                </div>
            )}

            {financialHistory.map((fin, idx) => (
                <div key={fin._uid} className={rowCard}>
                    <button type="button" onClick={() => removeFinancial(fin._uid)} className={removeBtn} aria-label="Remove">
                        <X className="w-3.5 h-3.5" />
                    </button>

                    <div className="text-xs text-gray-600 font-mono mb-3">FY-{String(idx + 1).padStart(3, '0')}</div>

                    <div className="grid grid-cols-2 gap-3 pr-8">
                        <input
                            type="number"
                            value={fin.year}
                            onChange={(e) => updateFinancial(fin._uid, 'year', e.target.value)}
                            placeholder="2024"
                            min="2000"
                            max="2099"
                            className={inputClass}
                        />
                        <input
                            type="number"
                            value={fin.turnover_uzs}
                            onChange={(e) => updateFinancial(fin._uid, 'turnover_uzs', e.target.value)}
                            placeholder="5,000,000,000"
                            min="0"
                            className={inputClass}
                        />
                    </div>
                </div>
            ))}

            <button
                type="button"
                onClick={addFinancial}
                className="flex items-center justify-center gap-2 w-full py-2.5 text-xs font-medium text-gray-500 border border-dashed border-gray-800 rounded-lg hover:text-gray-300 hover:border-gray-700 transition-colors"
            >
                <Plus className="w-3.5 h-3.5" />
                Add Year
            </button>
        </div>
    );
}

/* ================================================================== */
/*  Shared: FieldBlock                                                 */
/* ================================================================== */

function FieldBlock({
    label,
    icon,
    compact,
    children,
}: {
    label: string;
    icon?: React.ReactNode;
    compact?: boolean;
    children: React.ReactNode;
}) {
    return (
        <div>
            <label className={`flex items-center gap-1.5 font-medium text-gray-500 mb-1.5 ${compact ? 'text-[11px]' : 'text-xs'}`}>
                {icon && <span className="text-gray-600">{icon}</span>}
                {label}
            </label>
            {children}
        </div>
    );
}
