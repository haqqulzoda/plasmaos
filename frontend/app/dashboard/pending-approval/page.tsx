'use client';

import { Clock3, LogOut } from 'lucide-react';
import { signOut } from 'next-auth/react';
import { api } from '@/lib/api';

export default function PendingApprovalPage() {
    const handleLogout = async () => {
        await api.post('/auth/logout').catch(() => undefined);
        await signOut({ callbackUrl: '/' });
    };

    return (
        <div className="min-h-[60vh] flex items-center justify-center">
            <section className="w-full max-w-xl border border-gray-800 bg-gray-950 rounded-lg p-8 text-center space-y-5">
                <div className="mx-auto w-12 h-12 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                    <Clock3 className="w-6 h-6 text-amber-300" />
                </div>
                <div className="space-y-2">
                    <h1 className="text-2xl font-semibold text-white">Pending approval</h1>
                    <p className="text-gray-300 leading-6">
                        Your company profile has been submitted. Plasma will review and approve your pilot access shortly.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={handleLogout}
                    className="inline-flex items-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white transition-colors"
                >
                    <LogOut className="w-4 h-4" />
                    Logout
                </button>
            </section>
        </div>
    );
}
