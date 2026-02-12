'use client';

import { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { LayoutDashboard, Radar, FileText, Settings, LogOut, Sparkles } from 'lucide-react';
import { clsx } from 'clsx';

interface NavItem {
    name: string;
    href: string;
    icon: ReactNode;
}

const navItems: NavItem[] = [
    { name: 'Dashboard', href: '/dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { name: 'Hunter Feed', href: '/dashboard/tenders', icon: <Radar className="w-5 h-5" /> },
    { name: 'My Bids', href: '/dashboard/bids', icon: <FileText className="w-5 h-5" /> },
    { name: 'Settings', href: '/dashboard/settings', icon: <Settings className="w-5 h-5" /> },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
    const pathname = usePathname();
    const router = useRouter();

    const handleLogout = () => {
        localStorage.removeItem('plasma_token');
        router.push('/');
    };

    return (
        <div className="min-h-screen bg-black flex">
            {/* Sidebar */}
            <aside className="w-64 bg-zinc-950 border-r border-zinc-800 flex flex-col">
                {/* Logo */}
                <div className="p-6 border-b border-zinc-800">
                    <Link href="/dashboard" className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                            <Sparkles className="w-5 h-5 text-white" />
                        </div>
                        <span className="text-xl font-bold text-white">Plasma AI</span>
                    </Link>
                </div>

                {/* Navigation */}
                <nav className="flex-1 p-4 space-y-1">
                    {navItems.map((item) => {
                        const isActive = pathname === item.href;
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={clsx(
                                    'flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200',
                                    isActive
                                        ? 'bg-zinc-800 text-white'
                                        : 'text-zinc-400 hover:text-white hover:bg-zinc-900'
                                )}
                            >
                                {item.icon}
                                <span className="font-medium">{item.name}</span>
                            </Link>
                        );
                    })}
                </nav>

                {/* Logout */}
                <div className="p-4 border-t border-zinc-800">
                    <button
                        onClick={handleLogout}
                        className="flex items-center gap-3 px-4 py-3 rounded-xl text-zinc-400 hover:text-red-400 hover:bg-zinc-900 transition-all duration-200 w-full"
                    >
                        <LogOut className="w-5 h-5" />
                        <span className="font-medium">Logout</span>
                    </button>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 overflow-auto">
                <div className="p-8">
                    {children}
                </div>
            </main>
        </div>
    );
}
