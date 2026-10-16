'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { FileClock } from 'lucide-react';

import { BidiText } from '@/components/i18n/BidiText';
import { Surface } from '@/components/ui/Display';
import { formatDate } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';

type LegacyProposal = {
    id: string;
    tender_title: string;
    tender_deadline: string | null;
    created_at: string;
    engagement_status: string | null;
};

const PAGE = 100;
const MAX_PAGES = 5;

/**
 * P1 (Deploy 4 step 8b): bid drafts made before My Tenders listed pursuits. A proposal whose
 * tender has no pursuit in the user's organization would otherwise open only by its old link
 * now that /bid-preparation redirects here; they stay listed, each opening its bid page.
 */
export function LegacyBidDrafts() {
    const t = useTranslations('myTenders.legacyDrafts');
    const locale = useLocale() as CustomerSelectableLocale;
    const [items, setItems] = useState<LegacyProposal[]>([]);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            const found: LegacyProposal[] = [];
            for (let page = 0; page < MAX_PAGES; page += 1) {
                const response = await api.get<LegacyProposal[]>('/proposals', { params: { limit: PAGE, offset: page * PAGE } });
                found.push(...response.data.filter((item) => item.engagement_status === null));
                if (response.data.length < PAGE) break;
            }
            if (!cancelled) setItems(found);
        })().catch(() => undefined);
        return () => { cancelled = true; };
    }, []);

    if (items.length === 0) return null;
    return (
        <Surface className="legacy-bid-drafts" data-legacy-bid-drafts>
            <details>
                <summary>
                    <FileClock aria-hidden />
                    <span>{t('title', { count: items.length })}</span>
                </summary>
                <p className="ds-muted">{t('help')}</p>
                <ul>
                    {items.map((item) => (
                        <li key={item.id}>
                            <Link href={`/dashboard/bid-preparation/${encodeURIComponent(item.id)}`}>
                                <BidiText>{item.tender_title}</BidiText>
                            </Link>
                            <span className="ds-muted ds-text-small">
                                {item.tender_deadline
                                    ? t('deadline', { date: formatDate(item.tender_deadline, locale) })
                                    : t('started', { date: formatDate(item.created_at, locale) })}
                            </span>
                        </li>
                    ))}
                </ul>
            </details>
        </Surface>
    );
}
