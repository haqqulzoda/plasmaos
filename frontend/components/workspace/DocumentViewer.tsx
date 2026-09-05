'use client';

import { FileText, Hash } from 'lucide-react';
import { useTranslations } from 'next-intl';

interface DocumentViewerProps {
    title: string;
    content: string;
}

export default function DocumentViewer({ title, content }: DocumentViewerProps) {
    const t = useTranslations('documentViewer');
    const lines = content.split('\n');

    return (
        <div className="flex flex-col h-full bg-zinc-950">
            {/* ── Header Bar ── */}
            <div className="flex items-center gap-3 px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm shrink-0">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                    <FileText className="w-4 h-4 text-indigo-400" />
                </div>
                <div>
                    <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                        {t('sourceDocument')}
                    </p>
                    <h3 dir="auto" className="bidi-auto text-sm font-semibold text-zinc-200 truncate max-w-md">
                        {title}
                    </h3>
                </div>
            </div>

            {/* ── Document Body ── */}
            <div className="flex-1 overflow-y-auto">
                <div dir="ltr" className="flex font-mono text-[13px] leading-relaxed">
                    {/* Line Numbers Gutter */}
                    <div className="shrink-0 select-none border-e border-zinc-800/60 bg-zinc-950">
                        {lines.map((_, i) => (
                            <div
                                key={i}
                                className="px-3 py-[1px] text-end text-zinc-600 tabular-nums"
                                style={{ minWidth: '3rem' }}
                            >
                                {i + 1}
                            </div>
                        ))}
                    </div>

                    {/* Content */}
                    <div className="flex-1 px-5 py-1">
                        {lines.map((line, i) => (
                            <div
                                key={i}
                                dir="auto"
                                className="bidi-auto py-[1px] text-start text-zinc-300 hover:bg-zinc-800/30 transition-colors duration-75"
                            >
                                {line || '\u00A0'}
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* ── Footer Status ── */}
            <div className="flex items-center justify-between px-5 py-2 border-t border-zinc-800 bg-zinc-950/80 text-[11px] text-zinc-500 shrink-0">
                <div className="flex items-center gap-1.5">
                    <Hash className="w-3 h-3" />
                    <span>{t('lineCount', { count: lines.length })}</span>
                </div>
                <span>{t('plainTextEncoding')}</span>
            </div>
        </div>
    );
}
