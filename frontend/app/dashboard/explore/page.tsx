'use client';

import { useCallback, useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { CalendarClock, CheckCircle2, ExternalLink, FileText, Rocket, Search, Sparkles, Users } from 'lucide-react';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { CoverageStrip } from '@/components/source-refresh/CoverageStrip';
import { SourceRefreshProvider } from '@/components/source-refresh/SourceRefreshProvider';
import { Button } from '@/components/ui/Button';
import { StatusBadge, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Textarea } from '@/components/ui/Forms';
import { SegmentedControl } from '@/components/ui/Navigation';
import { formatDate } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';

type Overview = { organization_name?: string | null; book_call_url?: string | null; demo_available: boolean };
type Opportunity = {
    tender: {
        id: string; title: string; buyer?: string | null; country?: string | null; deadline?: string | null;
        source_system: string; source_url?: string | null; notice_type?: string | null;
    };
};
type DemoRequirement = { text: string; category?: string; status: 'MET' | 'PARTIAL' | 'GAP'; evidence?: string };
type DemoGap = { text: string; action?: string };
type DemoExpert = { name: string; role: string; match: string };
type Demo = {
    tender: { title: string; client?: string; country?: string; source?: string; reference?: string; notice_type?: string;
        deadline?: string | null; source_url?: string | null };
    firm: { name: string; note?: string };
    metrics?: { requirements?: number; met?: number; partial?: number; gaps?: number; run_seconds?: number };
    steps: {
        requirements?: DemoRequirement[];
        gaps?: DemoGap[];
        team?: DemoExpert[];
        eoi?: { excerpt: string; status_label?: string };
    };
};
type DemoStep = 'requirements' | 'gaps' | 'team' | 'eoi';
const DEMO_STEPS: DemoStep[] = ['requirements', 'gaps', 'team', 'eoi'];
const STATUS_TONE = { MET: 'success', PARTIAL: 'warning', GAP: 'danger' } as const;

/** The walkthrough shows only the steps the exported run has data for. */
function availableSteps(demo: Demo): DemoStep[] {
    return DEMO_STEPS.filter((key) => key === 'eoi' ? Boolean(demo.steps.eoi?.excerpt) : (demo.steps[key]?.length ?? 0) > 0);
}

/**
 * P1 Explore view: an organization that has not started a pilot sees open opportunities, source
 * coverage and one guided demo analysis, with "Start a pilot" and "Book a call". Uploads, its own
 * analyses and the award ledger come with a pilot (the backend refuses them for explore).
 */
export default function ExplorePage() {
    return <SourceRefreshProvider enabled><ExploreContent /></SourceRefreshProvider>;
}

function ExploreContent() {
    const t = useTranslations('auth.explore');
    const locale = useLocale() as CustomerSelectableLocale;
    const [overview, setOverview] = useState<Overview | null>(null);
    const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
    const [demo, setDemo] = useState<Demo | null>(null);
    const [step, setStep] = useState<DemoStep>('requirements');
    const [message, setMessage] = useState('');
    const [sending, setSending] = useState<'pilot' | 'call' | null>(null);
    const [sent, setSent] = useState<'pilot' | 'call' | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        api.get<Overview>('/explore/overview').then((r) => { if (!cancelled) setOverview(r.data); }).catch(() => undefined);
        api.get<{ items: Opportunity[] }>('/explorer/tenders', { params: { view: 'all', limit: 8, sort: 'deadline_soonest' } })
            .then((r) => { if (!cancelled) setOpportunities(r.data.items); })
            .catch(() => { if (!cancelled) setOpportunities([]); });
        api.get<Demo>('/explore/demo-analysis').then((r) => { if (!cancelled) setDemo(r.data); }).catch(() => undefined);
        return () => { cancelled = true; };
    }, []);

    const sendRequest = useCallback(async (kind: 'pilot' | 'call') => {
        setSending(kind);
        setError(null);
        try {
            await api.post('/explore/requests', { request: kind, message: message.trim() || null });
            setSent(kind);
        } catch {
            setError(t('requestFailed'));
        } finally {
            setSending(null);
        }
    }, [message, t]);

    const organization = overview?.organization_name;

    return (
        <div className="customer-page explore-page" data-explore-page>
            <header className="explore-hero">
                <span className="ds-eyebrow"><Sparkles aria-hidden /> {t('eyebrow')}</span>
                <h1><BidiText>{organization ? t('titleWithOrganization', { organization }) : t('title')}</BidiText></h1>
                <p className="ds-muted">{t('lead')}</p>
            </header>

            <Surface className="explore-cta" aria-labelledby="explore-cta-title">
                <div>
                    <h2 id="explore-cta-title"><Rocket aria-hidden /> {t('ctaTitle')}</h2>
                    <ul className="explore-pilot-list">
                        <li><CheckCircle2 aria-hidden />{t('pilotIncludesUpload')}</li>
                        <li><CheckCircle2 aria-hidden />{t('pilotIncludesAnalysis')}</li>
                        <li><CheckCircle2 aria-hidden />{t('pilotIncludesLedger')}</li>
                    </ul>
                </div>
                {sent ? (
                    <Alert tone="success" title={sent === 'call' ? t('callRequested') : t('pilotRequested')}>{t('requestedHelp')}</Alert>
                ) : (
                    <div className="explore-cta-actions">
                        <Textarea label={t('messageLabel')} helper={t('messageHelp')} rows={2} maxLength={1000}
                            value={message} onChange={(event) => setMessage(event.target.value)} />
                        {error && <Alert tone="danger" title={error} />}
                        <div className="ds-row">
                            <Button size="lg" loading={sending === 'pilot'} disabled={sending !== null}
                                leadingIcon={<Rocket aria-hidden />} onClick={() => void sendRequest('pilot')}>{t('startPilot')}</Button>
                            {overview?.book_call_url ? (
                                <a className="ds-button ds-button-secondary ds-button-lg" href={overview.book_call_url} target="_blank"
                                    rel="noopener noreferrer"><CalendarClock aria-hidden /> {t('bookCall')}</a>
                            ) : (
                                <Button size="lg" variant="secondary" loading={sending === 'call'} disabled={sending !== null}
                                    leadingIcon={<CalendarClock aria-hidden />} onClick={() => void sendRequest('call')}>{t('bookCall')}</Button>
                            )}
                        </div>
                    </div>
                )}
            </Surface>

            <CoverageStrip />

            <section className="explore-section" aria-labelledby="explore-opportunities-title">
                <h2 id="explore-opportunities-title"><Search aria-hidden /> {t('opportunitiesTitle')}</h2>
                <p className="ds-muted">{t('opportunitiesHelp')}</p>
                {opportunities === null ? <p role="status" className="ds-muted">{t('loading')}</p>
                : opportunities.length === 0 ? <p className="ds-muted">{t('noOpportunities')}</p>
                : <ul className="explore-opportunities">
                    {opportunities.map(({ tender }) => (
                        <li key={tender.id} className="ds-surface-subtle">
                            <strong><BidiText>{tender.title}</BidiText></strong>
                            <span className="ds-muted">
                                <BidiText>{[tender.buyer, tender.country].filter(Boolean).join(' · ')}</BidiText>
                            </span>
                            <span className="explore-opportunity-meta">
                                {tender.deadline ? t('deadline', { date: formatDate(tender.deadline, locale) }) : t('noDeadline')}
                                {tender.source_url && <a href={tender.source_url} target="_blank" rel="noopener noreferrer">
                                    {t('officialNotice')} <ExternalLink aria-hidden /></a>}
                            </span>
                        </li>
                    ))}
                </ul>}
            </section>

            {demo && (
                <section className="explore-section explore-demo" aria-labelledby="explore-demo-title" data-explore-demo>
                    <h2 id="explore-demo-title"><FileText aria-hidden /> {t('demoTitle')}</h2>
                    <p className="ds-muted">{t('demoHelp', { firm: demo.firm.name })}</p>
                    <Surface className="explore-demo-notice">
                        <span className="ds-eyebrow">{demo.tender.notice_type ?? t('notice')}</span>
                        <strong><BidiText>{demo.tender.title}</BidiText></strong>
                        <span className="ds-muted"><BidiText>{[demo.tender.client, demo.tender.country, demo.tender.source].filter(Boolean).join(' · ')}</BidiText>
                            {demo.tender.reference && <> · <TechnicalText>{demo.tender.reference}</TechnicalText></>}</span>
                        {demo.metrics && <span className="explore-demo-metrics">
                            {t('demoMetrics', {
                                requirements: demo.metrics.requirements ?? 0, met: demo.metrics.met ?? 0,
                                partial: demo.metrics.partial ?? 0, gaps: demo.metrics.gaps ?? 0,
                            })}
                        </span>}
                    </Surface>
                    <SegmentedControl
                        label={t('demoSteps')}
                        value={step}
                        onChange={(value) => setStep(value as DemoStep)}
                        options={availableSteps(demo).map((key, index) => ({ value: key, label: `${index + 1}. ${t(`steps.${key}`)}` }))}
                    />
                    <div className="explore-demo-step" role="region" aria-live="polite" aria-label={t(`steps.${step}`)}>
                        <p className="ds-muted">{t(`stepHelp.${step}`)}</p>
                        {step === 'requirements' && <ul className="explore-demo-list">
                            {(demo.steps.requirements ?? []).map((item, index) => (
                                <li key={index}>
                                    <StatusBadge tone={STATUS_TONE[item.status]}>{t(`status.${item.status}`)}</StatusBadge>
                                    <div><BidiText>{item.text}</BidiText>
                                        {item.evidence && <p className="ds-muted ds-text-small"><BidiText>{item.evidence}</BidiText></p>}</div>
                                </li>
                            ))}
                        </ul>}
                        {step === 'gaps' && <ul className="explore-demo-list">
                            {(demo.steps.gaps ?? []).map((item, index) => (
                                <li key={index}>
                                    <StatusBadge tone="danger">{t('status.GAP')}</StatusBadge>
                                    <div><BidiText>{item.text}</BidiText>
                                        {item.action && <p className="ds-muted ds-text-small"><BidiText>{item.action}</BidiText></p>}</div>
                                </li>
                            ))}
                        </ul>}
                        {step === 'team' && <ul className="explore-demo-list">
                            {(demo.steps.team ?? []).map((item, index) => (
                                <li key={index}>
                                    <Users aria-hidden />
                                    <div><strong><BidiText>{item.name}</BidiText></strong> · <BidiText>{item.role}</BidiText>
                                        <p className="ds-muted ds-text-small"><BidiText>{item.match}</BidiText></p></div>
                                </li>
                            ))}
                        </ul>}
                        {step === 'eoi' && demo.steps.eoi && <Surface className="explore-demo-eoi">
                            {demo.steps.eoi.status_label && <StatusBadge tone="warning">{demo.steps.eoi.status_label}</StatusBadge>}
                            <p className="explore-demo-eoi-text"><BidiText>{demo.steps.eoi.excerpt}</BidiText></p>
                        </Surface>}
                    </div>
                    {demo.firm.note && <p className="ds-muted ds-text-small">{demo.firm.note}</p>}
                </section>
            )}
        </div>
    );
}
