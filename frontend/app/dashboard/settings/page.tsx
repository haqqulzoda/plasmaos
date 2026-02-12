'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Building2, User, MapPin, Landmark, Save, Loader2, CheckCircle, Phone } from 'lucide-react';
import { api } from '@/lib/api';

interface CompanyProfile {
    company_name: string | null;
    director_name: string | null;
    address: string | null;
    phone_contact: string | null;
    bank_name: string | null;
    mfo: string | null;
    account_number: string | null;
    inn: string | null;
}

export default function SettingsPage() {
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
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Fetch company profile on mount
    useEffect(() => {
        const fetchProfile = async () => {
            try {
                const response = await api.get('/users/me/company');
                setProfile({
                    company_name: response.data.company_name || '',
                    director_name: response.data.director_name || '',
                    address: response.data.address || '',
                    phone_contact: response.data.phone_contact || '',
                    bank_name: response.data.bank_name || '',
                    mfo: response.data.mfo || '',
                    account_number: response.data.account_number || '',
                    inn: response.data.inn || '',
                });
            } catch (err) {
                console.error('Failed to fetch company profile:', err);
                setError('Failed to load company profile');
            } finally {
                setLoading(false);
            }
        };

        fetchProfile();
    }, []);

    // Handle form submission
    const handleSave = async () => {
        setSaving(true);
        setSaved(false);
        setError(null);

        try {
            await api.put('/users/me/company', profile);
            setSaved(true);
            setTimeout(() => setSaved(false), 3000);
        } catch (err) {
            console.error('Failed to save company profile:', err);
            setError('Failed to save company profile');
        } finally {
            setSaving(false);
        }
    };

    // Update field handler
    const updateField = (field: keyof CompanyProfile, value: string) => {
        setProfile(prev => ({ ...prev, [field]: value }));
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            </div>
        );
    }

    return (
        <div className="space-y-8 max-w-3xl">
            {/* Header */}
            <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
            >
                <h1 className="text-3xl font-bold text-white">Settings</h1>
                <p className="text-zinc-400 mt-1">Manage your company profile for Commercial Proposals</p>
            </motion.div>

            {/* Error Message */}
            {error && (
                <div className="text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-4">
                    {error}
                </div>
            )}

            {/* Company Profile Form */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.1 }}
                className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden"
            >
                {/* Section Header */}
                <div className="px-6 py-4 border-b border-zinc-800 flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center">
                        <Building2 className="w-5 h-5 text-indigo-400" />
                    </div>
                    <div>
                        <h2 className="text-lg font-semibold text-white">Company Profile</h2>
                        <p className="text-sm text-zinc-500">This information appears on your Commercial Proposals</p>
                    </div>
                </div>

                {/* Form Fields */}
                <div className="p-6 space-y-6">
                    {/* Company Name & Director */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">
                                <Building2 className="w-4 h-4 inline mr-2" />
                                Company Name
                            </label>
                            <input
                                type="text"
                                value={profile.company_name || ''}
                                onChange={(e) => updateField('company_name', e.target.value)}
                                placeholder="Plasma Construction LLC"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">
                                <User className="w-4 h-4 inline mr-2" />
                                Director Name
                            </label>
                            <input
                                type="text"
                                value={profile.director_name || ''}
                                onChange={(e) => updateField('director_name', e.target.value)}
                                placeholder="Akmal Abdullayev"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                            />
                        </div>
                    </div>

                    {/* Address */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">
                                <MapPin className="w-4 h-4 inline mr-2" />
                                Address
                            </label>
                            <input
                                type="text"
                                value={profile.address || ''}
                                onChange={(e) => updateField('address', e.target.value)}
                                placeholder="Tashkent, Amir Temur 1"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">
                                <Phone className="w-4 h-4 inline mr-2" />
                                Phone
                            </label>
                            <input
                                type="text"
                                value={profile.phone_contact || ''}
                                onChange={(e) => updateField('phone_contact', e.target.value)}
                                placeholder="+998 90 123 45 67"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                            />
                        </div>
                    </div>

                    {/* Banking Section Header */}
                    <div className="pt-4 border-t border-zinc-800">
                        <div className="flex items-center gap-2 mb-4">
                            <Landmark className="w-5 h-5 text-indigo-400" />
                            <h3 className="text-white font-medium">Banking Details</h3>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-zinc-400 mb-2">Bank Name</label>
                                <input
                                    type="text"
                                    value={profile.bank_name || ''}
                                    onChange={(e) => updateField('bank_name', e.target.value)}
                                    placeholder="Hamkorbank"
                                    className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-zinc-400 mb-2">MFO (Bank Code)</label>
                                <input
                                    type="text"
                                    value={profile.mfo || ''}
                                    onChange={(e) => updateField('mfo', e.target.value)}
                                    placeholder="00873"
                                    className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-zinc-400 mb-2">Account Number</label>
                                <input
                                    type="text"
                                    value={profile.account_number || ''}
                                    onChange={(e) => updateField('account_number', e.target.value)}
                                    placeholder="20208000123456789012"
                                    className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-zinc-400 mb-2">INN (Tax ID)</label>
                                <input
                                    type="text"
                                    value={profile.inn || ''}
                                    onChange={(e) => updateField('inn', e.target.value)}
                                    placeholder="123456789"
                                    className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
                                />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Save Button */}
                <div className="px-6 py-4 border-t border-zinc-800 flex items-center justify-end gap-4">
                    {saved && (
                        <motion.div
                            initial={{ opacity: 0, x: 10 }}
                            animate={{ opacity: 1, x: 0 }}
                            className="flex items-center gap-2 text-green-400"
                        >
                            <CheckCircle className="w-5 h-5" />
                            <span>Saved successfully!</span>
                        </motion.div>
                    )}
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:cursor-not-allowed text-white font-medium rounded-xl transition-colors"
                    >
                        {saving ? (
                            <>
                                <Loader2 className="w-5 h-5 animate-spin" />
                                Saving...
                            </>
                        ) : (
                            <>
                                <Save className="w-5 h-5" />
                                Save Changes
                            </>
                        )}
                    </button>
                </div>
            </motion.div>

            {/* Telegram Notifications Section */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden"
            >
                {/* Section Header */}
                <div className="px-6 py-4 border-b border-zinc-800 flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center">
                        <svg className="w-5 h-5 text-blue-400" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
                        </svg>
                    </div>
                    <div>
                        <h2 className="text-lg font-semibold text-white">Telegram Notifications</h2>
                        <p className="text-sm text-zinc-500">Receive real-time alerts for new tenders</p>
                    </div>
                </div>

                {/* Status Display */}
                <div className="p-6">
                    <div className="flex items-center gap-4 p-4 bg-green-500/10 border border-green-500/20 rounded-xl">
                        <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse" />
                        <div>
                            <p className="text-green-400 font-medium">✅ Connected via Telegram</p>
                            <p className="text-zinc-500 text-sm mt-1">
                                You'll receive instant alerts when new tenders match your profile
                            </p>
                        </div>
                    </div>

                    <div className="mt-4 p-4 bg-zinc-800/50 rounded-xl">
                        <h4 className="text-white font-medium mb-2">🔔 What you'll receive:</h4>
                        <ul className="space-y-2 text-zinc-400 text-sm">
                            <li>• New tender alerts with budget and region</li>
                            <li>• Direct links to open tenders in PlasmaOS</li>
                            <li>• Proposal status updates</li>
                        </ul>
                    </div>
                </div>
            </motion.div>
        </div>
    );
}
