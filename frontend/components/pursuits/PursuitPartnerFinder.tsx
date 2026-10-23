'use client';

import { useCallback, useEffect, useState } from 'react';
import { Building2, ExternalLink, Handshake, Search, UserRoundSearch } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { Badge, StatusBadge, Surface } from '@/components/ui/Display';
import { Textarea } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import { PLAN_STATUS_EVENT, planErrorCode, type PlanStatus } from '@/lib/plans';
import type {
  ExpertSuggestions,
  PartnerFinderOverview,
  PartnerGap,
  PartnerRequest,
  PartnerRequestKind,
  PartnerRequestStatus,
  PartnerSuggestion,
  PartnerSuggestions,
  PublicAward,
} from '@/types/partnerFinder';

type Props = {
  pursuitId: string;
  headers: Record<string, string | undefined>;
};

export const requestTone = (status: PartnerRequestStatus) =>
  status === 'DECLINED' ? 'danger' : ['ACCEPTED', 'INTRODUCED'].includes(status) ? 'success' : 'info';

function AwardList({ awards }: { awards: PublicAward[] }) {
  const t = useTranslations('pursuits.team.partnerFinder');
  return <ul className="partner-award-list">{awards.map((award) => <li key={`${award.lender}:${award.notice_id}`}>
    <BidiText>{award.title}</BidiText>
    <span className="ds-muted ds-text-small">
      {[award.lender_label, award.country, award.year, award.joint_venture ? t('jointVenture') : null].filter(Boolean).join(' · ')}
      {' · '}
      <a href={award.notice_url} target="_blank" rel="noopener noreferrer">{t('notice', { id: award.notice_id })}<ExternalLink aria-hidden /></a>
    </span>
  </li>)}</ul>;
}

function RequestForm({ kind, label, help, onSubmit }: {
  kind: PartnerRequestKind; label: string; help: string; onSubmit: (note: string) => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<'failed' | 'quota' | null>(null);
  if (!open) return <Button size="sm" variant={kind === 'INTRODUCTION' ? 'primary' : 'secondary'} leadingIcon={<Handshake aria-hidden />} onClick={() => setOpen(true)}>{label}</Button>;
  const submit = async () => {
    setBusy(true); setError(null);
    try { await onSubmit(note.trim()); setOpen(false); setNote(''); }
    catch (failure) {
      // P3: the plan's introductions are used (402).
      setError(planErrorCode(failure) === 'PLAN_INTRODUCTION_LIMIT' ? 'quota' : 'failed');
      window.dispatchEvent(new Event(PLAN_STATUS_EVENT));
    }
    finally { setBusy(false); }
  };
  return <div className="partner-request-form">
    <Textarea label={t('note')} helper={help} rows={2} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} />
    {error && <p className="pursuit-upload-error" role="alert">{t(error === 'quota' ? 'introductionLimit' : 'requestFailed')}</p>}
    <div className="partner-request-actions">
      <Button size="sm" loading={busy} onClick={() => void submit()}>{t('sendRequest')}</Button>
      <Button size="sm" variant="secondary" disabled={busy} onClick={() => setOpen(false)}>{t('cancel')}</Button>
    </div>
  </div>;
}

function SuggestionCard({ suggestion, onRequest }: {
  suggestion: PartnerSuggestion; onRequest: (note: string) => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const reasons = [
    t('similarAwards', { count: suggestion.similar_award_count }),
    suggestion.latest_award_year ? t('latestAward', { year: suggestion.latest_award_year }) : null,
    suggestion.same_country ? t('sameCountry') : null,
    suggestion.in_procurement_category ? t('sameCategory') : null,
  ].filter(Boolean).join(' · ');
  return <Surface className="partner-suggestion-card" variant="raised">
    <header>
      <div>
        <span className="ds-eyebrow">#{suggestion.rank}</span>
        <h4><BidiText>{suggestion.firm_name}</BidiText></h4>
        <p className="ds-muted ds-text-small">{[suggestion.firm_country, reasons].filter(Boolean).join(' · ')}</p>
      </div>
      <div className="partner-suggestion-badges">
        {suggestion.presence !== 'UNKNOWN' && <Badge tone={suggestion.presence_matches_gap ? 'success' : 'neutral'}>{t(`presence.${suggestion.presence}`)}</Badge>}
        <Badge tone={suggestion.match_strength === 'STRONG' ? 'success' : 'warning'}>{t(`strength.${suggestion.match_strength}`)}</Badge>
      </div>
    </header>
    <p className="partner-source-label"><Badge tone="info">{t('sourceLabel')}</Badge></p>
    {(suggestion.matched_terms.length > 0 || suggestion.matched_sectors.length > 0) && <p className="ds-text-small">
      <strong>{t('matchedOn')}</strong> <BidiText>{[...suggestion.matched_terms, ...suggestion.matched_sectors].join(', ')}</BidiText>
    </p>}
    <AwardList awards={suggestion.awards} />
    {suggestion.request
      ? <p className="partner-request-status"><StatusBadge tone={requestTone(suggestion.request.status)}>{t(`status.${suggestion.request.status}`)}</StatusBadge> <span className="ds-muted ds-text-small">{t('requestedHelp')}</span></p>
      : <RequestForm kind="INTRODUCTION" label={t('requestIntroduction')} help={t('requestHelp')} onSubmit={onRequest} />}
  </Surface>;
}

function FirmSuggestions({ gap, analysisRunId, pursuitId, headers, refresh }: {
  gap: PartnerGap; analysisRunId: string; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const [result, setResult] = useState<PartnerSuggestions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const response = await api.get<PartnerSuggestions>(`/pursuits/${encodeURIComponent(pursuitId)}/partner-suggestions`, {
        headers, params: { analysis_run_id: analysisRunId, gap_id: gap.gap_id },
      });
      setResult(response.data);
    } catch { setError(true); }
    finally { setLoading(false); }
  }, [analysisRunId, gap.gap_id, headers, pursuitId]);
  const request = async (suggestion: PartnerSuggestion, note: string) => {
    await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/partner-requests`, {
      analysis_run_id: analysisRunId, gap_id: gap.gap_id, kind: 'INTRODUCTION', firm_key: suggestion.firm_key, note: note || null,
    }, { headers });
    await Promise.all([load(), refresh()]);
    window.dispatchEvent(new Event(PLAN_STATUS_EVENT));
  };
  if (!result) return <div className="partner-finder-actions">
    <Button size="sm" loading={loading} leadingIcon={<Search aria-hidden />} onClick={() => void load()}>{t('suggestFirms')}</Button>
    {error && <p className="pursuit-upload-error" role="alert">{t('loadFailed')}</p>}
  </div>;
  return <div className="partner-suggestions">
    {result.jv_rule_check && <p className="partner-jv-note ds-text-small">{t('jvRuleCheck')}</p>}
    {result.suggestions.length
      ? result.suggestions.map((suggestion) => <SuggestionCard key={suggestion.firm_key} suggestion={suggestion} onRequest={(note) => request(suggestion, note)} />)
      : <p className="ds-muted">{t('noSuggestions', { count: result.awards_considered })}</p>}
    <p className="ds-muted ds-text-small">{t('rankingNote', { count: result.awards_considered })}</p>
  </div>;
}

function ExpertOptions({ gap, analysisRunId, pursuitId, headers, refresh }: {
  gap: PartnerGap; analysisRunId: string; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const team = useTranslations('pursuits.team');
  const [result, setResult] = useState<ExpertSuggestions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const response = await api.get<ExpertSuggestions>(`/pursuits/${encodeURIComponent(pursuitId)}/expert-suggestions`, {
        headers, params: { analysis_run_id: analysisRunId, gap_id: gap.gap_id },
      });
      setResult(response.data);
    } catch { setError(true); }
    finally { setLoading(false); }
  }, [analysisRunId, gap.gap_id, headers, pursuitId]);
  useEffect(() => { void load(); }, [load]);
  const source = async (note: string) => {
    await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/partner-requests`, {
      analysis_run_id: analysisRunId, gap_id: gap.gap_id, kind: 'EXPERT_SOURCING', note: note || null,
    }, { headers });
    await Promise.all([load(), refresh()]);
    window.dispatchEvent(new Event(PLAN_STATUS_EVENT));
  };
  return <div className="partner-suggestions">
    {loading && !result && <p className="ds-muted">{t('loadingExperts')}</p>}
    {error && <p className="pursuit-upload-error" role="alert">{t('loadFailed')}</p>}
    {result && (result.experts.length
      ? <ul className="partner-expert-list">{result.experts.map((expert) => <li key={expert.expert_id}>
        <div><strong><BidiText>{expert.display_name}</BidiText></strong> <Badge tone={expert.scope === 'NETWORK_SHARED' ? 'info' : 'neutral'}>{t(`expertScope.${expert.scope}`)}</Badge></div>
        <span className="ds-muted ds-text-small"><BidiText>{expert.rationale}</BidiText></span>
        <StatusBadge tone={expert.qualification_state === 'SUPPORTED_BY_EVIDENCE' ? 'success' : expert.qualification_state === 'EVIDENCE_MISSING' ? 'danger' : 'warning'}>{team(`qualification.${expert.qualification_state}`)}</StatusBadge>
      </li>)}</ul>
      : <p className="ds-muted">{t('noExperts')}</p>)}
    {result?.sourcing_request
      ? <p className="partner-request-status"><StatusBadge tone={requestTone(result.sourcing_request.status)}>{t(`status.${result.sourcing_request.status}`)}</StatusBadge> <span className="ds-muted ds-text-small">{t('sourcingRequested')}</span></p>
      : result && <RequestForm kind="EXPERT_SOURCING" label={t('askSourcing')} help={t('sourcingHelp')} onSubmit={source} />}
  </div>;
}

function GapCard({ gap, analysisRunId, pursuitId, headers, refresh }: {
  gap: PartnerGap; analysisRunId: string; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const features = gap.features;
  const facts = [
    features.country,
    features.procurement_group,
    features.presence !== 'ANY' ? t(`needs.${features.presence}`) : null,
  ].filter(Boolean).join(' · ');
  return <Surface className="partner-gap-card">
    <header>
      <div>
        <span className="ds-eyebrow">{t(`basis.${features.basis}`)}</span>
        <h4><BidiText>{features.summary || gap.missing_contribution}</BidiText></h4>
        <p className="ds-muted ds-text-small">{facts}</p>
        {features.keywords.length > 0 && <p className="ds-text-small"><strong>{t('keywords')}</strong> <BidiText>{features.keywords.slice(0, 12).join(', ')}</BidiText></p>}
      </div>
      {features.category === 'EXPERT' ? <UserRoundSearch aria-hidden /> : <Building2 aria-hidden />}
    </header>
    {features.category === 'EXPERT'
      ? <ExpertOptions {...{ gap, analysisRunId, pursuitId, headers, refresh }} />
      : <FirmSuggestions {...{ gap, analysisRunId, pursuitId, headers, refresh }} />}
  </Surface>;
}

/** P3: the plan's introductions this period ("Introductions: 1 of 2 used"). */
function IntroductionAllowance({ headers }: { headers: Props['headers'] }) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const [plan, setPlan] = useState<PlanStatus | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const refresh = () => setVersion((value) => value + 1);
    window.addEventListener(PLAN_STATUS_EVENT, refresh);
    return () => window.removeEventListener(PLAN_STATUS_EVENT, refresh);
  }, []);
  useEffect(() => {
    let active = true;
    api.get<PlanStatus>('/organizations/plan', { headers }).then((response) => { if (active) setPlan(response.data); }, () => undefined);
    return () => { active = false; };
  }, [headers, version]);
  if (!plan) return null;
  const { used, limit } = plan.introductions;
  return <p className="partner-allowance ds-text-small" data-introductions-used={used}>
    {limit === null ? t('introductionsUnlimited') : t('introductionsUsed', { used, limit })}
  </p>;
}

function RequestList({ requests }: { requests: PartnerRequest[] }) {
  const t = useTranslations('pursuits.team.partnerFinder');
  if (!requests.length) return null;
  return <div className="partner-request-list">
    <h4>{t('yourRequests')}</h4>
    <ul>{requests.map((request) => {
      const last = [...request.history].reverse().find((event) => event.message);
      return <li key={request.request_id}>
        <StatusBadge tone={requestTone(request.status)}>{t(`status.${request.status}`)}</StatusBadge>
        <div>
          <strong><BidiText>{request.kind === 'INTRODUCTION' ? request.firm_name || '' : t('expertSourcing')}</BidiText></strong>
          <span className="ds-muted ds-text-small"><BidiText>{request.gap_summary}</BidiText></span>
          {last?.message && <span className="ds-text-small">{t('teamMessage')}: <BidiText>{last.message}</BidiText></span>}
        </div>
      </li>;
    })}</ul>
  </div>;
}

/** P2: firms that won similar development-bank contracts, from public award records (unverified). */
export function PursuitPartnerFinder({ pursuitId, headers }: Props) {
  const t = useTranslations('pursuits.team.partnerFinder');
  const [overview, setOverview] = useState<PartnerFinderOverview | null>(null);
  // P3: 'plan' when the organization's plan has no partner search (403 PLAN_FEATURE).
  const [error, setError] = useState<false | 'failed' | 'plan'>(false);
  const failed = (failure: unknown) => setError(planErrorCode(failure) === 'PLAN_FEATURE' ? 'plan' : 'failed');
  const load = useCallback(() => api.get<PartnerFinderOverview>(
    `/pursuits/${encodeURIComponent(pursuitId)}/partner-finder`, { headers },
  ).then((response) => { setOverview(response.data); setError(false); }, failed), [headers, pursuitId]);
  useEffect(() => {
    let active = true;
    api.get<PartnerFinderOverview>(`/pursuits/${encodeURIComponent(pursuitId)}/partner-finder`, { headers })
      .then((response) => { if (active) { setOverview(response.data); setError(false); } }, (failure) => { if (active) failed(failure); });
    return () => { active = false; };
  }, [headers, pursuitId]);
  if (error === 'plan') return <p className="ds-muted partner-not-on-plan">{t('notOnPlan')}</p>;
  if (error) return <p className="pursuit-upload-error" role="alert">{t('loadFailed')}</p>;
  if (!overview?.analysis_run_id) return null;
  const analysisRunId = overview.analysis_run_id;
  return <section className="partner-finder" aria-labelledby="partner-finder-title">
    <header>
      <Handshake aria-hidden />
      <div>
        <span className="ds-eyebrow">{t('eyebrow')}</span>
        <h3 id="partner-finder-title">{t('title')}</h3>
        <p>{t('help')}</p>
      </div>
    </header>
    {overview.gaps.length
      ? overview.gaps.map((gap) => <GapCard key={gap.gap_id} {...{ gap, analysisRunId, pursuitId, headers }} refresh={load} />)
      : <p className="ds-muted">{t('noGaps')}</p>}
    <IntroductionAllowance headers={headers} />
    <RequestList requests={overview.requests} />
  </section>;
}
