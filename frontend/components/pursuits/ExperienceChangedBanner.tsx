'use client';

import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Feedback';
import { api } from '@/lib/api';
import { evidenceSections, rerunRequest } from '@/lib/experienceChanged';
import type { AnalysisPackCandidate, PursuitAnalysis } from '@/types/pursuit';

/**
 * R3 Task 2: the run's sealed company snapshot differs from the current records. Re-run
 * repeats the run's document selection through the existing explicit POST.
 */
export function ExperienceChangedBanner({
    pursuitId,
    headers,
    runId,
    sections,
    onStarted,
}: {
    pursuitId: string;
    headers: Record<string, string | undefined>;
    runId: string;
    sections?: readonly string[] | null;
    onStarted: () => void;
}) {
    const t = useTranslations('pursuits.experienceChanged');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<'noDocuments' | 'rerunFailed' | null>(null);
    const base = `/pursuits/${encodeURIComponent(pursuitId)}`;
    const known = evidenceSections(sections);

    const rerun = async () => {
        setBusy(true);
        setError(null);
        try {
            const [run, candidate] = await Promise.all([
                api.get<PursuitAnalysis>(`${base}/analysis-runs/${encodeURIComponent(runId)}`, { headers }),
                api.get<AnalysisPackCandidate>(`${base}/analysis-pack-candidate`, { headers }),
            ]);
            const body = rerunRequest(run.data, candidate.data);
            if (!body) {
                setError('noDocuments');
                return;
            }
            await api.post(`${base}/analysis-runs`, body, { headers });
            onStarted();
        } catch {
            setError('rerunFailed');
        } finally {
            setBusy(false);
        }
    };

    return <div data-experience-changed>
        <Alert tone="warning" title={t('title')}
            action={<Button size="sm" variant="secondary" loading={busy} onClick={() => void rerun()} leadingIcon={<RefreshCw aria-hidden />}>
                {t('rerun')}
            </Button>}>
            {known.length ? t('changed', { sections: known.map((section) => t(`sections.${section}`)).join(', ') }) : t('help')}
        </Alert>
        {error && <p className="pursuit-upload-error" role="alert">{t(error)}</p>}
    </div>;
}
