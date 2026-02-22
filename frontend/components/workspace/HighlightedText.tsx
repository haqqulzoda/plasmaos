'use client';

import { useMemo } from 'react';
import { FileText, Hash, AlertTriangle } from 'lucide-react';

// ═══════════════════════════════════════════════════════════════
// HighlightedText — Reality Pane Highlighter
//
// Renders the full compiled_master_text with exact source_quote
// matches wrapped in a pulsing red <mark> tag.
// ═══════════════════════════════════════════════════════════════

interface HighlightedTextProps {
    text: string;
    quotes: string[];
    title?: string;
}

/**
 * Escape special regex characters in a string.
 */
function escapeRegex(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Normalize internal whitespace in a quote for flexible matching.
 * Collapses runs of any whitespace into a regex \s+ pattern.
 */
function quoteToPattern(quote: string): string {
    return escapeRegex(quote.trim())
        .replace(/\s+/g, '\\s+');
}

interface TextSegment {
    text: string;
    isHighlight: boolean;
}

/**
 * Parse the raw text and split it into segments: plain text and
 * highlighted matches. Case-insensitive, whitespace-tolerant.
 */
function buildSegments(text: string, quotes: string[]): TextSegment[] {
    // Filter out empty/whitespace-only quotes
    const validQuotes = quotes
        .filter((q) => q && q.trim().length > 0)
        .map(quoteToPattern);

    if (validQuotes.length === 0) {
        return [{ text, isHighlight: false }];
    }

    // Build a single combined regex with alternation
    // Sort by length descending so longer quotes match first
    validQuotes.sort((a, b) => b.length - a.length);
    const combinedPattern = validQuotes.join('|');

    let regex: RegExp;
    try {
        regex = new RegExp(`(${combinedPattern})`, 'gi');
    } catch {
        // If regex construction fails, return plain text
        return [{ text, isHighlight: false }];
    }

    const segments: TextSegment[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(text)) !== null) {
        // Add plain text before match
        if (match.index > lastIndex) {
            segments.push({
                text: text.slice(lastIndex, match.index),
                isHighlight: false,
            });
        }
        // Add highlighted match
        segments.push({
            text: match[0],
            isHighlight: true,
        });
        lastIndex = regex.lastIndex;

        // Safety: prevent infinite loops on zero-length matches
        if (match[0].length === 0) {
            regex.lastIndex++;
        }
    }

    // Add remaining plain text
    if (lastIndex < text.length) {
        segments.push({
            text: text.slice(lastIndex),
            isHighlight: false,
        });
    }

    return segments;
}

export default function HighlightedText({ text, quotes, title }: HighlightedTextProps) {
    const segments = useMemo(() => buildSegments(text, quotes), [text, quotes]);
    const lines = text.split('\n');
    const matchCount = useMemo(() => segments.filter((s) => s.isHighlight).length, [segments]);

    return (
        <div className="flex flex-col h-full bg-zinc-950">
            {/* ── Header Bar ── */}
            <div className="flex items-center gap-3 px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm shrink-0">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                    <FileText className="w-4 h-4 text-indigo-400" />
                </div>
                <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                        Reality Pane
                    </p>
                    <h3 className="text-sm font-semibold text-zinc-200 truncate max-w-md">
                        {title || 'Tender Document'}
                    </h3>
                </div>
                {matchCount > 0 && (
                    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
                        <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                        <span className="text-[11px] font-semibold text-red-400">
                            {matchCount} clause{matchCount !== 1 ? 's' : ''} flagged
                        </span>
                    </div>
                )}
            </div>

            {/* ── Document Body ── */}
            <div className="flex-1 overflow-y-auto">
                <div className="px-5 py-4 font-mono text-[13px] leading-relaxed text-zinc-300 whitespace-pre-wrap break-words">
                    {segments.map((segment, i) =>
                        segment.isHighlight ? (
                            <mark
                                key={i}
                                className="bg-red-500/20 text-red-200 rounded px-0.5 border-b-2 border-red-500/50 transition-all duration-700"
                                style={{
                                    animation: 'riskPulse 3s ease-in-out infinite',
                                }}
                            >
                                {segment.text}
                            </mark>
                        ) : (
                            <span key={i}>{segment.text}</span>
                        )
                    )}
                </div>
            </div>

            {/* ── Footer Status ── */}
            <div className="flex items-center justify-between px-5 py-2 border-t border-zinc-800 bg-zinc-950/80 text-[11px] text-zinc-500 shrink-0">
                <div className="flex items-center gap-1.5">
                    <Hash className="w-3 h-3" />
                    <span>{lines.length} lines</span>
                </div>
                <span>
                    {matchCount > 0
                        ? `${matchCount} risk highlight${matchCount !== 1 ? 's' : ''} active`
                        : 'UTF-8 · Plain Text'}
                </span>
            </div>

            {/* Keyframe for subtle enterprise pulse */}
            <style jsx>{`
                @keyframes riskPulse {
                    0%, 100% {
                        background-color: rgba(239, 68, 68, 0.15);
                        border-bottom-color: rgba(239, 68, 68, 0.4);
                    }
                    50% {
                        background-color: rgba(239, 68, 68, 0.25);
                        border-bottom-color: rgba(239, 68, 68, 0.7);
                    }
                }
            `}</style>
        </div>
    );
}
