'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Building2, History, Search, UserRoundSearch, UsersRound } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { Checkbox, Input, Select } from '@/components/ui/Forms';
import { EmptyState, StatusBadge, Surface } from '@/components/ui/Display';
import { api } from '@/lib/api';
import type {
  CandidateAvailabilityStatus,
  CandidateInterestStatus,
  CandidateLibrary,
  CandidateMatch,
  CandidateParticipationRecord,
  CandidateParticipationState,
  CandidateReviewDecision,
  CandidateSearchRun,
  ParticipationConfirmationSource,
  PursuitAnalysis,
  PursuitGap,
  ScenarioDecision,
  TeamScenario,
  TeamScenarioRevision,
} from '@/types/pursuit';

type Props = {
  pursuitId: string;
  headers: Record<string, string | undefined>;
  onScenariosChange?: (scenarios: TeamScenario[]) => void;
};

const DECISIONS: CandidateReviewDecision[] = [
  'SHORTLISTED', 'REJECTED', 'MORE_EVIDENCE_REQUESTED', 'IRRELEVANT', 'CONTRIBUTION_CORRECTED',
];
const AVAILABILITY_STATES: CandidateAvailabilityStatus[] = [
  'UNKNOWN', 'TENTATIVE', 'AVAILABLE', 'PARTIALLY_AVAILABLE', 'UNAVAILABLE',
];
const INTEREST_STATES: CandidateInterestStatus[] = ['UNKNOWN', 'INTERESTED', 'CONDITIONAL', 'DECLINED'];
const PARTICIPATION_STATES: CandidateParticipationState[] = [
  'UNCONFIRMED', 'TENTATIVE', 'CONFIRMED', 'DECLINED', 'WITHDRAWN',
];
const CONFIRMATION_SOURCES: ParticipationConfirmationSource[] = [
  'DIRECT_EMAIL', 'CALL', 'MEETING', 'SIGNED_DOCUMENT', 'OPERATOR_RECORDED', 'CUSTOMER_RECORDED', 'OTHER',
];

const qualificationTone = (state: CandidateMatch['qualification_state']) =>
  state === 'SUPPORTED_BY_EVIDENCE' ? 'success' :
    state === 'NOT_RELEVANT' ? 'neutral' : state === 'EVIDENCE_MISSING' ? 'danger' : 'warning';

const stateTone = (state: string) =>
  ['AVAILABLE', 'INTERESTED', 'CONFIRMED', 'FULL_WINDOW', 'VIABLE', 'COVERED'].includes(state) ? 'success' :
    ['UNAVAILABLE', 'DECLINED', 'WITHDRAWN', 'EXPIRED', 'NO_OVERLAP', 'BLOCKED'].includes(state) ? 'danger' :
      ['TENTATIVE', 'PARTIALLY_AVAILABLE', 'CONDITIONAL', 'NEEDS_RECONFIRMATION', 'PARTIAL_WINDOW', 'NEEDS_REVIEW', 'PARTIAL', 'UNRESOLVED'].includes(state) ? 'warning' : 'neutral';

function readableEvidence(value: unknown): string {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return String(value ?? '');
  const record = value as Record<string, unknown>;
  if (typeof record.project_name === 'string') {
    const friendly = (item: unknown) => typeof item === 'string'
      ? item.toLowerCase().replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
      : item;
    const parts = [record.project_name, friendly(record.role), friendly(record.completion_state), friendly(record.evidence_state)].filter(Boolean);
    return parts.join(' · ');
  }
  if (record.fact) return readableEvidence(record.fact);
  if (typeof record.type === 'string') return record.type.replaceAll('_', ' ');
  return Object.values(record).filter((item) => typeof item === 'string' || typeof item === 'number').join(' · ');
}

function localDateTime(days = 0) {
  const value = new Date(Date.now() + days * 24 * 60 * 60 * 1000);
  value.setMinutes(value.getMinutes() - value.getTimezoneOffset());
  return value.toISOString().slice(0, 16);
}

const toIso = (value: string) => value ? new Date(value).toISOString() : null;
const displayDate = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));

function MatchReview({ match, run, pursuitId, headers, refresh }: {
  match: CandidateMatch; run: CandidateSearchRun; pursuitId: string;
  headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team');
  const [decision, setDecision] = useState<CandidateReviewDecision>('SHORTLISTED');
  const [reason, setReason] = useState('');
  const [correction, setCorrection] = useState(match.proposed_contribution);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api.post(
        `/pursuits/${encodeURIComponent(pursuitId)}/candidate-search-runs/${run.candidate_search_run_id}/matches/${match.candidate_match_id}/reviews`,
        {
          decision,
          corrected_contribution: decision === 'CONTRIBUTION_CORRECTED' ? correction.trim() : null,
          reason: reason.trim(),
        },
        { headers },
      );
      setReason('');
      await refresh();
    } finally { setBusy(false); }
  };
  return <div className="candidate-review-controls">
    <label><span>{t('nextAction')}</span><select className="ds-control" value={decision} onChange={(event) => setDecision(event.target.value as CandidateReviewDecision)}>
      {DECISIONS.map((value) => <option value={value} key={value}>{t(`decisions.${value}`)}</option>)}
    </select></label>
    {decision === 'CONTRIBUTION_CORRECTED' && <Input label={t('correctedContribution')} value={correction} onChange={(event) => setCorrection(event.target.value)} />}
    <Input label={t('reviewReason')} value={reason} onChange={(event) => setReason(event.target.value)} />
    <Button size="sm" variant="secondary" disabled={!reason.trim() || (decision === 'CONTRIBUTION_CORRECTED' && correction.trim().length < 3)} loading={busy} onClick={() => void submit()}>{t('recordDecision')}</Button>
    {match.latest_review && <p className="ds-muted ds-text-small">{t('latestDecision')}: {t(`decisions.${match.latest_review.decision}`)} · <BidiText>{match.latest_review.reason}</BidiText></p>}
  </div>;
}

function AvailabilityForm({ record, pursuitId, headers, refresh }: {
  record: CandidateParticipationRecord; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.participation');
  const [status, setStatus] = useState<CandidateAvailabilityStatus>('UNKNOWN');
  const [windowStart, setWindowStart] = useState('');
  const [windowEnd, setWindowEnd] = useState('');
  const [effort, setEffort] = useState('');
  const [capacity, setCapacity] = useState('');
  const [constraints, setConstraints] = useState('');
  const [source, setSource] = useState<ParticipationConfirmationSource>('CUSTOMER_RECORDED');
  const [observed, setObserved] = useState(localDateTime());
  const [validUntil, setValidUntil] = useState(localDateTime(7));
  const [documentVersion, setDocumentVersion] = useState('');
  const [correctLatest, setCorrectLatest] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const positive = ['TENTATIVE', 'AVAILABLE', 'PARTIALLY_AVAILABLE'].includes(status);
  const missingKnownWindow = positive && Boolean(record.assignment_dates) && (!windowStart || !windowEnd);
  const submit = async () => {
    setBusy(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/participation-records/${record.participation_record_id}/availability-facts`, {
        status, window_start: windowStart || null, window_end: windowEnd || null,
        effort_percent: effort ? Number(effort) : null,
        capacity_description: capacity.trim() || null,
        location_travel_constraints: constraints.trim() || null,
        confirmation_source: source, observed_at: toIso(observed),
        valid_until: validUntil ? toIso(validUntil) : null,
        supporting_document_version_id: documentVersion.trim() || null,
        supersedes_fact_id: correctLatest ? record.latest_availability?.fact_id || null : null,
      }, { headers });
      await refresh();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <details className="participation-action"><summary>{t('recordAvailability')}</summary><div className="participation-form">
    <Select label={t('status')} value={status} onChange={(event) => setStatus(event.target.value as CandidateAvailabilityStatus)}>{AVAILABILITY_STATES.map((value) => <option key={value} value={value}>{t(`availabilityStates.${value}`)}</option>)}</Select>
    <Input type="date" label={t('windowStart')} value={windowStart} onChange={(event) => setWindowStart(event.target.value)} />
    <Input type="date" label={t('windowEnd')} value={windowEnd} onChange={(event) => setWindowEnd(event.target.value)} />
    <Input type="number" min="0" max="100" step="0.01" label={t('effort')} value={effort} onChange={(event) => setEffort(event.target.value)} />
    <Input label={t('capacity')} value={capacity} onChange={(event) => setCapacity(event.target.value)} />
    <Input label={t('constraints')} value={constraints} onChange={(event) => setConstraints(event.target.value)} />
    <Select label={t('source')} value={source} onChange={(event) => setSource(event.target.value as ParticipationConfirmationSource)}>{CONFIRMATION_SOURCES.map((value) => <option key={value} value={value}>{t(`sources.${value}`)}</option>)}</Select>
    <Input type="datetime-local" label={t('observedAt')} value={observed} onChange={(event) => setObserved(event.target.value)} />
    <Input type="datetime-local" label={t('validUntil')} value={validUntil} onChange={(event) => setValidUntil(event.target.value)} />
    <Input label={t('supportingDocumentVersion')} value={documentVersion} onChange={(event) => setDocumentVersion(event.target.value)} />
    {record.latest_availability && <Checkbox label={t('correctLatest')} checked={correctLatest} onChange={(event) => setCorrectLatest(event.target.checked)} />}
    {error && <p className="pursuit-upload-error" role="alert">{t('saveFailed')}</p>}
    <Button size="sm" loading={busy} disabled={!observed || (positive && !validUntil) || missingKnownWindow} onClick={() => void submit()}>{t('recordAvailability')}</Button>
  </div></details>;
}

function InterestForm({ record, pursuitId, headers, refresh }: {
  record: CandidateParticipationRecord; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.participation');
  const [status, setStatus] = useState<CandidateInterestStatus>('UNKNOWN');
  const [source, setSource] = useState<ParticipationConfirmationSource>('CUSTOMER_RECORDED');
  const [observed, setObserved] = useState(localDateTime());
  const [validUntil, setValidUntil] = useState('');
  const [conditions, setConditions] = useState('');
  const [documentVersion, setDocumentVersion] = useState('');
  const [correctLatest, setCorrectLatest] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const submit = async () => {
    setBusy(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/participation-records/${record.participation_record_id}/interest-facts`, {
        status, confirmation_source: source, observed_at: toIso(observed), valid_until: toIso(validUntil),
        conditions: conditions.trim() || null,
        supporting_document_version_id: documentVersion.trim() || null,
        supersedes_fact_id: correctLatest ? record.latest_interest?.fact_id || null : null,
      }, { headers });
      await refresh();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <details className="participation-action"><summary>{t('recordInterest')}</summary><div className="participation-form">
    <Select label={t('status')} value={status} onChange={(event) => setStatus(event.target.value as CandidateInterestStatus)}>{INTEREST_STATES.map((value) => <option key={value} value={value}>{t(`interestStates.${value}`)}</option>)}</Select>
    <Select label={t('source')} value={source} onChange={(event) => setSource(event.target.value as ParticipationConfirmationSource)}>{CONFIRMATION_SOURCES.map((value) => <option key={value} value={value}>{t(`sources.${value}`)}</option>)}</Select>
    <Input type="datetime-local" label={t('observedAt')} value={observed} onChange={(event) => setObserved(event.target.value)} />
    <Input type="datetime-local" label={t('validUntilOptional')} value={validUntil} onChange={(event) => setValidUntil(event.target.value)} />
    <Input label={t('conditions')} value={conditions} onChange={(event) => setConditions(event.target.value)} />
    <Input label={t('supportingDocumentVersion')} value={documentVersion} onChange={(event) => setDocumentVersion(event.target.value)} />
    {record.latest_interest && <Checkbox label={t('correctLatest')} checked={correctLatest} onChange={(event) => setCorrectLatest(event.target.checked)} />}
    {error && <p className="pursuit-upload-error" role="alert">{t('saveFailed')}</p>}
    <Button size="sm" loading={busy} disabled={!observed || (status === 'CONDITIONAL' && !conditions.trim())} onClick={() => void submit()}>{t('recordInterest')}</Button>
  </div></details>;
}

function ParticipationDecisionForm({ record, pursuitId, headers, refresh }: {
  record: CandidateParticipationRecord; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.participation');
  const [state, setState] = useState<CandidateParticipationState>('UNCONFIRMED');
  const [source, setSource] = useState<ParticipationConfirmationSource>('CUSTOMER_RECORDED');
  const [observed, setObserved] = useState(localDateTime());
  const [reconfirmBy, setReconfirmBy] = useState(localDateTime(30));
  const [conditions, setConditions] = useState('');
  const [reason, setReason] = useState('');
  const [documentVersion, setDocumentVersion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const fresh = ['TENTATIVE', 'CONFIRMED'].includes(state);
  const terminal = ['DECLINED', 'WITHDRAWN'].includes(state);
  const submit = async () => {
    setBusy(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/participation-records/${record.participation_record_id}/decisions`, {
        state, confirmation_source: source, observed_at: toIso(observed),
        reconfirm_by: fresh ? toIso(reconfirmBy) : null,
        conditions_summary: conditions.trim() || null, reason: reason.trim() || null,
        supporting_document_version_id: documentVersion.trim() || null,
      }, { headers });
      await refresh();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <details className="participation-action"><summary>{t('recordParticipation')}</summary><div className="participation-form">
    <Select label={t('status')} value={state} onChange={(event) => setState(event.target.value as CandidateParticipationState)}>{PARTICIPATION_STATES.map((value) => <option key={value} value={value}>{t(`participationStates.${value}`)}</option>)}</Select>
    <Select label={t('source')} value={source} onChange={(event) => setSource(event.target.value as ParticipationConfirmationSource)}>{CONFIRMATION_SOURCES.map((value) => <option key={value} value={value}>{t(`sources.${value}`)}</option>)}</Select>
    <Input type="datetime-local" label={t('observedAt')} value={observed} onChange={(event) => setObserved(event.target.value)} />
    {fresh && <Input type="datetime-local" label={t('reconfirmBy')} value={reconfirmBy} onChange={(event) => setReconfirmBy(event.target.value)} />}
    <Input label={t('conditions')} value={conditions} onChange={(event) => setConditions(event.target.value)} />
    {terminal && <Input label={t('reason')} value={reason} onChange={(event) => setReason(event.target.value)} />}
    <Input label={t('supportingDocumentVersion')} value={documentVersion} onChange={(event) => setDocumentVersion(event.target.value)} />
    {error && <p className="pursuit-upload-error" role="alert">{t('saveFailed')}</p>}
    <Button size="sm" loading={busy} disabled={!observed || (fresh && !reconfirmBy) || (terminal && reason.trim().length < 3) || (state === 'CONFIRMED' && record.latest_availability?.status === 'PARTIALLY_AVAILABLE' && !conditions.trim())} onClick={() => void submit()}>{t('recordParticipation')}</Button>
  </div></details>;
}

function ParticipationTrail({ record, match, pursuitId, headers, refresh }: {
  record?: CandidateParticipationRecord; match: CandidateMatch; pursuitId: string;
  headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.participation');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const start = async () => {
    if (!match.latest_review) return;
    setBusy(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/candidate-matches/${match.candidate_match_id}/participation-record`, {
        shortlist_decision_id: match.latest_review.decision_id,
      }, { headers });
      await refresh();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  if (!record) return <div className="participation-empty">
    <p className="ds-muted">{t('notStarted')}</p>
    {match.latest_review?.decision === 'SHORTLISTED' && <Button size="sm" loading={busy} onClick={() => void start()}>{t('startTracking')}</Button>}
    {error && <p className="pursuit-upload-error" role="alert">{t('startFailed')}</p>}
  </div>;
  const availability = record.latest_availability;
  const interest = record.latest_interest;
  const participation = record.latest_participation;
  return <div className="participation-trail">
    {record.upstream_stale && <div className="analysis-stale" role="status"><AlertTriangle aria-hidden /><p>{record.upstream_stale_reason || t('upstreamStale')}</p></div>}
    <div className="participation-status-grid">
      <section className="participation-area" aria-label={t('availability')}><header><h5>{t('availability')}</h5><StatusBadge tone={stateTone(availability?.effective_status || 'UNKNOWN')}>{t(`availabilityStates.${availability?.effective_status || 'UNKNOWN'}`)}</StatusBadge></header>
        {availability ? <dl>
          <div><dt>{t('window')}</dt><dd>{availability.window_start && availability.window_end ? `${availability.window_start} – ${availability.window_end}` : t('unknown')}</dd></div>
          <div><dt>{t('effortCapacity')}</dt><dd><BidiText>{availability.effort_percent ? `${availability.effort_percent}%` : availability.capacity_description || t('unknown')}</BidiText></dd></div>
          <div><dt>{t('sourceDate')}</dt><dd>{t('recordedFrom', { source: t(`sources.${availability.confirmation_source}`), date: displayDate(availability.observed_at) })}</dd></div>
          <div><dt>{t('validUntil')}</dt><dd>{availability.valid_until ? displayDate(availability.valid_until) : t('unknown')}</dd></div>
          <div><dt>{t('assignmentCoverage')}</dt><dd><StatusBadge tone={stateTone(record.assignment_window_coverage)}>{t(`coverage.${record.assignment_window_coverage}`)}</StatusBadge></dd></div>
        </dl> : <p className="ds-muted">{t('noAvailability')}</p>}
      </section>
      <section className="participation-area" aria-label={t('interest')}><header><h5>{t('interest')}</h5><StatusBadge tone={stateTone(interest?.effective_status || 'UNKNOWN')}>{t(`interestStates.${interest?.effective_status || 'UNKNOWN'}`)}</StatusBadge></header>
        {interest ? <dl>
          <div><dt>{t('conditions')}</dt><dd><BidiText>{interest.conditions || t('noneRecorded')}</BidiText></dd></div>
          <div><dt>{t('sourceDate')}</dt><dd>{t('recordedFrom', { source: t(`sources.${interest.confirmation_source}`), date: displayDate(interest.observed_at) })}</dd></div>
          <div><dt>{t('validUntil')}</dt><dd>{interest.valid_until ? displayDate(interest.valid_until) : t('notBounded')}</dd></div>
        </dl> : <p className="ds-muted">{t('noInterest')}</p>}
      </section>
      <section className="participation-area" aria-label={t('participation')}><header><h5>{t('participation')}</h5><StatusBadge tone={stateTone(participation?.effective_state || 'UNCONFIRMED')}>{t(`participationStates.${participation?.effective_state || 'UNCONFIRMED'}`)}</StatusBadge></header>
        {participation ? <dl>
          <div><dt>{t('sourceDate')}</dt><dd>{t('recordedFrom', { source: t(`sources.${participation.confirmation_source}`), date: displayDate(participation.observed_at) })}</dd></div>
          <div><dt>{t('reconfirmBy')}</dt><dd>{participation.reconfirm_by ? displayDate(participation.reconfirm_by) : t('notBounded')}</dd></div>
          <div><dt>{t('conditionsReason')}</dt><dd><BidiText>{participation.conditions_summary || participation.reason || t('noneRecorded')}</BidiText></dd></div>
        </dl> : <p className="ds-muted">{t('noParticipation')}</p>}
      </section>
    </div>
    {record.same_candidate_record_ids.length > 0 && <p className="participation-duplicate"><AlertTriangle aria-hidden />{t('duplicateUse', { count: record.same_candidate_record_ids.length })}</p>}
    <div className="participation-actions"><AvailabilityForm {...{ record, pursuitId, headers, refresh }} /><InterestForm {...{ record, pursuitId, headers, refresh }} /><ParticipationDecisionForm {...{ record, pursuitId, headers, refresh }} /></div>
    <details className="participation-history"><summary><History aria-hidden />{t('history')} ({record.history.length})</summary>
      {record.history.length ? <ol>{record.history.map((event) => <li key={event.event_id}>
        <span><strong>{t(`historyKinds.${event.event_kind}`)}</strong> · {event.recorded_state}</span>
        <span>{t('recordedFrom', { source: t(`sources.${event.confirmation_source}`), date: displayDate(event.observed_at) })}</span>
        {event.supersedes_id && <span>{t('correction')}</span>}
      </li>)}</ol> : <p className="ds-muted">{t('historyEmpty')}</p>}
    </details>
  </div>;
}

function MatchCard({ match, run, participationRecord, pursuitId, headers, refresh }: {
  match: CandidateMatch; run: CandidateSearchRun; participationRecord?: CandidateParticipationRecord;
  pursuitId: string; headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team');
  return <Surface className="candidate-match-card" variant="raised">
    <header><div><span className="ds-eyebrow">{t(`kinds.${match.candidate_kind}`)}</span><h4><BidiText>{match.candidate_name}</BidiText></h4></div><StatusBadge tone={qualificationTone(match.qualification_state)}>{t(`qualification.${match.qualification_state}`)}</StatusBadge></header>
    <section className="participation-area participation-fit" aria-label={t('participation.fitEvidence')}>
      <header><h5>{t('participation.fitEvidence')}</h5><StatusBadge tone={qualificationTone(match.qualification_state)}>{t(`qualification.${match.qualification_state}`)}</StatusBadge></header>
      <dl className="candidate-match-facts">
        <div><dt>{t('proposedContribution')}</dt><dd><BidiText>{participationRecord?.proposed_contribution || match.latest_review?.corrected_contribution || match.proposed_contribution}</BidiText></dd></div>
        <div><dt>{t('evidenceReviewState')}</dt><dd>{t(`evidence.${match.candidate_evidence_state}`)}</dd></div>
        <div><dt>{t('scope')}</dt><dd>{t(`scopes.${match.candidate_scope}`)}</dd></div>
      </dl>
      <div className="candidate-evidence-grid">
        <div><h5>{t('strongestEvidence')}</h5>{match.strongest_evidence.length ? <ul>{match.strongest_evidence.map((item, index) => <li key={index}><BidiText>{readableEvidence(item)}</BidiText></li>)}</ul> : <p className="ds-muted">{t('noneRecorded')}</p>}</div>
        <div><h5>{t('remainingWeakness')}</h5>{match.missing_or_weak_evidence.length ? <ul>{match.missing_or_weak_evidence.map((item, index) => <li key={index}><BidiText>{readableEvidence(item)}</BidiText></li>)}</ul> : <p className="ds-muted">{t('noRecordedWeakness')}</p>}</div>
      </div>
      <p className="ds-muted ds-text-small"><BidiText>{match.rationale}</BidiText></p>
    </section>
    {(participationRecord || match.latest_review?.decision === 'SHORTLISTED') && <ParticipationTrail record={participationRecord} {...{ match, pursuitId, headers, refresh }} />}
    <MatchReview {...{ match, run, pursuitId, headers, refresh }} />
  </Surface>;
}

function GapCandidates({ gap, analysis, run, participationByMatch, pursuitId, headers, searching, startSearch, refresh }: {
  gap: PursuitGap; analysis: PursuitAnalysis; run?: CandidateSearchRun;
  participationByMatch: Map<string, CandidateParticipationRecord>; pursuitId: string;
  headers: Props['headers']; searching: boolean; startSearch: (gap: PursuitGap) => Promise<void>;
  refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team');
  const target = gap.position_id
    ? analysis.positions.find((item) => item.position_id === gap.position_id)?.effective_title
    : analysis.requirements.find((item) => item.requirement_id === gap.requirement_id)?.effective_normalized_requirement;
  return <Surface className="candidate-gap-group">
    <header><div><span className="ds-eyebrow">{t('reviewedGap')}</span><h3><BidiText>{target || gap.missing_contribution}</BidiText></h3><p><BidiText>{gap.missing_contribution}</BidiText></p></div><Button size="sm" loading={searching} disabled={analysis.inputs_changed} leadingIcon={<Search aria-hidden />} onClick={() => void startSearch(gap)}>{t('findCandidates')}</Button></header>
    {analysis.inputs_changed && <div className="analysis-stale" role="status"><AlertTriangle aria-hidden /><p>{t('staleBlocked')}</p></div>}
    {run?.is_stale && <div className="analysis-stale" role="status"><AlertTriangle aria-hidden /><p>{run.stale_reason || t('historicalStale')}</p></div>}
    {run ? <div className="candidate-match-list">{run.matches.length ? run.matches.map((match) => <MatchCard key={match.candidate_match_id} {...{ match, run, pursuitId, headers, refresh }} participationRecord={participationByMatch.get(match.candidate_match_id)} />) : <p className="ds-muted">{t('noCandidates')}</p>}</div> : <p className="ds-muted">{t('searchNotRun')}</p>}
  </Surface>;
}

function ScenarioSelection({ records, selected, setSelected }: {
  records: CandidateParticipationRecord[]; selected: Set<string>;
  setSelected: (value: Set<string>) => void;
}) {
  const t = useTranslations('pursuits.team.scenarios');
  if (!records.length) return <p className="ds-muted">{t('noParticipation')}</p>;
  return <div className="scenario-selection">{records.map((record) => <Checkbox
    key={record.participation_record_id}
    label={`${record.candidate_name} · ${record.proposed_contribution}`}
    checked={selected.has(record.participation_record_id)}
    onChange={(event) => {
      const next = new Set(selected);
      if (event.target.checked) next.add(record.participation_record_id);
      else next.delete(record.participation_record_id);
      setSelected(next);
    }}
  />)}</div>;
}

function ScenarioDecisionForm({ scenario, revision, pursuitId, headers, refresh }: {
  scenario: TeamScenario; revision: TeamScenarioRevision; pursuitId: string;
  headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.scenarios');
  const [decision, setDecision] = useState<ScenarioDecision>('PREFERRED');
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const approve = decision === 'APPROVED_FOR_PROPOSAL';
  const submit = async () => {
    setBusy(true); setError(false);
    try {
      await api.post(
        `/pursuits/${encodeURIComponent(pursuitId)}/team-scenarios/${scenario.scenario_id}/revisions/${revision.revision_id}/decisions`,
        { decision, reason: reason.trim(), explicit_confirmation: approve && confirmed },
        { headers },
      );
      setReason(''); setConfirmed(false); await refresh();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <div className="scenario-decision-form">
    <Select label={t('decision')} value={decision} onChange={(event) => setDecision(event.target.value as ScenarioDecision)}>
      {(['PREFERRED', 'REJECTED', 'APPROVED_FOR_PROPOSAL'] as ScenarioDecision[]).map((value) => <option key={value} value={value}>{t(`decisions.${value}`)}</option>)}
    </Select>
    <Input label={t('decisionReason')} value={reason} onChange={(event) => setReason(event.target.value)} />
    {approve && <Checkbox label={t('approvalConfirmation')} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />}
    {error && <p className="pursuit-upload-error" role="alert">{t('decisionFailed')}</p>}
    <Button size="sm" variant="secondary" loading={busy} disabled={reason.trim().length < 3 || (approve && (!confirmed || !revision.scenario_current || revision.current_assessment_state !== 'VIABLE'))} onClick={() => void submit()}>{t('recordDecision')}</Button>
  </div>;
}

function ScenarioCard({ scenario, records, pursuitId, headers, refresh }: {
  scenario: TeamScenario; records: CandidateParticipationRecord[]; pursuitId: string;
  headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.scenarios');
  const revision = scenario.latest_revision;
  const initial = revision ? revision.participants.flatMap((participant) => participant.contributions.map((item) => item.participation_record_id)) : [];
  const [selected, setSelected] = useState(new Set(initial));
  const [revising, setRevising] = useState(false);
  const [error, setError] = useState(false);
  const revise = async () => {
    setRevising(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/team-scenarios/${scenario.scenario_id}/revisions`, {
        participation_record_ids: [...selected],
      }, { headers });
      await refresh();
    } catch { setError(true); }
    finally { setRevising(false); }
  };
  if (!revision) return null;
  const partners = revision.participants.filter((item) => item.participant_type === 'PARTNER_FIRM');
  const experts = revision.participants.filter((item) => item.participant_type === 'EXPERT');
  return <Surface className="team-scenario-card" variant="raised">
    <header><div><span className="ds-eyebrow">{t('revision', { version: revision.version_number })}</span><h4><BidiText>{scenario.title}</BidiText></h4></div><StatusBadge tone={stateTone(revision.current_assessment_state)}>{t(`assessments.${revision.current_assessment_state}`)}</StatusBadge></header>
    <p className="scenario-lead"><strong>{t('leadOrganization')}</strong> · {t('yourOrganization')}</p>
    {!revision.scenario_current && <div className="analysis-stale" role="status"><AlertTriangle aria-hidden /><div><strong>{t('stale')}</strong>{revision.stale_reasons.map((reason) => <p key={reason}><BidiText>{reason}</BidiText></p>)}</div></div>}
    <dl className="scenario-summary">
      <div><dt>{t('gapCoverage')}</dt><dd>{revision.covered_gap_count} / {revision.gap_count}</dd></div>
      <div><dt>{t('unresolved')}</dt><dd>{revision.unresolved_gap_count}</dd></div>
      <div><dt>{t('participants')}</dt><dd>{revision.participant_count}</dd></div>
      <div><dt>{t('confirmed')}</dt><dd>{revision.confirmed_participant_count}</dd></div>
      <div><dt>{t('issues')}</dt><dd>{revision.issue_count}</dd></div>
    </dl>
    <div className="scenario-participant-columns">
      <section><h5>{t('partnerFirms')}</h5>{partners.length ? partners.map((participant) => <article key={participant.participant_id}><strong><BidiText>{participant.display_name}</BidiText></strong><ul>{participant.contributions.map((item) => <li key={item.contribution_id}><BidiText>{item.proposed_contribution}</BidiText> · {t(`windows.${item.assignment_window_result}`)}</li>)}</ul></article>) : <p className="ds-muted">{t('none')}</p>}</section>
      <section><h5>{t('experts')}</h5>{experts.length ? experts.map((participant) => <article key={participant.participant_id}><strong><BidiText>{participant.display_name}</BidiText></strong><ul>{participant.contributions.map((item) => <li key={item.contribution_id}><BidiText>{item.proposed_contribution}</BidiText> · {item.availability_effort_percent ? `${item.availability_effort_percent}%` : t('unknownEffort')}</li>)}</ul></article>) : <p className="ds-muted">{t('none')}</p>}</section>
    </div>
    <details className="scenario-details"><summary>{t('gapAssessments')}</summary><ul>{revision.gap_assessments.map((item, index) => <li key={item.gap_assessment_id}><StatusBadge tone={stateTone(item.state)}>{t(`gapStates.${item.state}`)}</StatusBadge> {t('teamNeed', { number: index + 1 })}{item.is_blocking ? ` · ${t('blocking')}` : ''}</li>)}</ul></details>
    <details className="scenario-details"><summary>{t('issueList')} ({revision.issues.length})</summary>{revision.issues.length ? <ul>{revision.issues.map((item) => <li key={item.issue_id}><StatusBadge tone={item.severity === 'BLOCKING' ? 'danger' : 'warning'}>{t(`severities.${item.severity}`)}</StatusBadge> {t(`issueCodes.${item.issue_code}`)}</li>)}</ul> : <p className="ds-muted">{t('noIssues')}</p>}</details>
    <details className="scenario-details"><summary>{t('decisionHistory')} ({revision.decisions.length})</summary>{revision.decisions.length ? <ol>{revision.decisions.map((item) => <li key={item.decision_id}>{t(`decisions.${item.decision}`)} · <BidiText>{item.reason}</BidiText> · {displayDate(item.created_at)}</li>)}</ol> : <p className="ds-muted">{t('noDecisions')}</p>}</details>
    <details className="scenario-revise"><summary>{t('createRevision')}</summary><ScenarioSelection records={records} {...{ selected, setSelected }} />{error && <p className="pursuit-upload-error" role="alert">{t('revisionFailed')}</p>}<Button size="sm" loading={revising} onClick={() => void revise()}>{t('sealRevision')}</Button></details>
    <ScenarioDecisionForm {...{ scenario, revision, pursuitId, headers, refresh }} />
  </Surface>;
}

function ScenarioWorkspace({ scenarios, records, pursuitId, headers, refresh }: {
  scenarios: TeamScenario[]; records: CandidateParticipationRecord[]; pursuitId: string;
  headers: Props['headers']; refresh: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.team.scenarios');
  const [title, setTitle] = useState('');
  const [selected, setSelected] = useState(new Set<string>());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const create = async () => {
    setBusy(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/team-scenarios`, {
        title: title.trim(), participation_record_ids: [...selected],
      }, { headers });
      setTitle(''); setSelected(new Set()); await refresh();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <section className="team-scenarios" aria-labelledby="team-scenarios-title">
    <header><div><span className="ds-eyebrow">{t('eyebrow')}</span><h3 id="team-scenarios-title">{t('title')}</h3><p>{t('help')}</p></div></header>
    <Surface className="scenario-create"><Input label={t('scenarioName')} value={title} onChange={(event) => setTitle(event.target.value)} /><ScenarioSelection records={records} {...{ selected, setSelected }} />{error && <p className="pursuit-upload-error" role="alert">{t('createFailed')}</p>}<Button size="sm" loading={busy} disabled={!title.trim()} onClick={() => void create()}>{t('create')}</Button></Surface>
    {scenarios.length > 1 && <div className="scenario-comparison"><h4>{t('comparison')}</h4><div className="scenario-table-wrap"><table><thead><tr><th>{t('scenario')}</th><th>{t('assessment')}</th><th>{t('unresolved')}</th><th>{t('partnerFirms')}</th><th>{t('experts')}</th><th>{t('confirmed')}</th><th>{t('stale')}</th><th>{t('blockingIssues')}</th></tr></thead><tbody>{scenarios.map((scenario) => { const revision = scenario.latest_revision; return <tr key={scenario.scenario_id}><th><BidiText>{scenario.title}</BidiText></th><td>{revision ? t(`assessments.${revision.current_assessment_state}`) : t('none')}</td><td>{revision?.unresolved_gap_count ?? 0}</td><td>{revision?.participants.filter((item) => item.participant_type === 'PARTNER_FIRM').length ?? 0}</td><td>{revision?.participants.filter((item) => item.participant_type === 'EXPERT').length ?? 0}</td><td>{revision?.confirmed_participant_count ?? 0}</td><td>{revision?.scenario_current ? t('current') : t('yes')}</td><td>{revision?.blocking_issue_count ?? 0}</td></tr>; })}</tbody></table></div></div>}
    <div className="team-scenario-list">{scenarios.length ? scenarios.map((scenario) => <ScenarioCard key={`${scenario.scenario_id}:${scenario.latest_revision?.revision_id ?? 'none'}`} {...{ scenario, records, pursuitId, headers, refresh }} />) : <p className="ds-muted">{t('empty')}</p>}</div>
  </section>;
}

export function PursuitTeam({ pursuitId, headers, onScenariosChange }: Props) {
  const t = useTranslations('pursuits.team');
  const analysisTrust = useTranslations('pursuits.requirements');
  const [analysis, setAnalysis] = useState<PursuitAnalysis | null>(null);
  const [runs, setRuns] = useState<CandidateSearchRun[]>([]);
  const [participation, setParticipation] = useState<CandidateParticipationRecord[]>([]);
  const [scenarios, setScenarios] = useState<TeamScenario[]>([]);
  const [hasLibrary, setHasLibrary] = useState(false);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const [analysisResponse, runsResponse, libraryResponse, participationResponse, scenariosResponse] = await Promise.all([
        api.get<PursuitAnalysis | null>(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-runs/latest`, { headers }),
        api.get<CandidateSearchRun[]>(`/pursuits/${encodeURIComponent(pursuitId)}/candidate-search-runs`, { headers }),
        api.get<CandidateLibrary>('/candidates', { headers }),
        api.get<CandidateParticipationRecord[]>(`/pursuits/${encodeURIComponent(pursuitId)}/participation-records`, { headers }),
        api.get<TeamScenario[]>(`/pursuits/${encodeURIComponent(pursuitId)}/team-scenarios`, { headers }),
      ]);
      setAnalysis(analysisResponse.data);
      setRuns(runsResponse.data);
      setHasLibrary(Boolean(libraryResponse.data.firms.length || libraryResponse.data.experts.length));
      setParticipation(participationResponse.data);
      setScenarios(scenariosResponse.data);
      onScenariosChange?.(scenariosResponse.data);
      setError(null);
    } catch { setError(t('loadFailed')); }
    finally { setLoading(false); }
  }, [headers, onScenariosChange, pursuitId, t]);
  useEffect(() => { void load(); }, [load]);
  const latestByGap = useMemo(() => {
    const map = new Map<string, CandidateSearchRun>();
    for (const run of runs) if (!map.has(run.gap_id)) map.set(run.gap_id, run);
    return map;
  }, [runs]);
  const participationByMatch = useMemo(() => new Map(participation.map((record) => [record.candidate_match_id, record])), [participation]);
  const eligible = (analysis?.gaps || []).filter((gap) =>
    ['CONFIRMED', 'CORRECTED'].includes(gap.effective_review_state) &&
    ['GAP', 'PARTIAL', 'EVIDENCE_MISSING'].includes(gap.effective_coverage_state) &&
    ['PARTNER_FIRM', 'EXPERT'].includes(gap.effective_resolution_category),
  );
  const partners = eligible.filter((gap) => gap.effective_resolution_category === 'PARTNER_FIRM' && Boolean(gap.requirement_id));
  const experts = eligible.filter((gap) => gap.effective_resolution_category === 'EXPERT' && Boolean(gap.position_id));
  const startSearch = async (gap: PursuitGap) => {
    if (!analysis) return;
    setSearching(gap.gap_id); setError(null);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/candidate-search-runs`, {
        analysis_run_id: analysis.analysis_run_id, gap_id: gap.gap_id, result_limit: 10,
      }, { headers });
      await load();
    } catch { setError(t('searchFailed')); }
    finally { setSearching(null); }
  };
  if (loading) return <p className="ds-muted">{t('loading')}</p>;
  if (!analysis || analysis.status !== 'COMPLETED') return <EmptyState icon={<UserRoundSearch aria-hidden />} title={t('empty')} description={t('emptyHelp')} />;
  if (analysis.quality_state !== 'READY_FOR_REVIEW') return <EmptyState icon={<AlertTriangle aria-hidden />} title={analysisTrust('needsAttentionTitle')} description={analysisTrust('needsAttentionHelp')} />;
  return <div className="pursuit-team">
    <div className="candidate-team-intro"><p>{t('help')}</p>{hasLibrary && <Link href="/dashboard/partners-experts" className="ds-button ds-button-secondary ds-button-sm">{t('openLibrary')}</Link>}</div>
    {error && <p className="pursuit-upload-error" role="alert">{error}</p>}
    {!eligible.length && <EmptyState icon={<UserRoundSearch aria-hidden />} title={t('noTeamNeeds')} description={t('noTeamNeedsHelp')} />}
    <section className="candidate-team-column" aria-labelledby="candidate-partners"><header><Building2 aria-hidden /><div><h3 id="candidate-partners">{t('partners')}</h3><p>{t('partnersHelp')}</p></div></header>
      {partners.length ? partners.map((gap) => <GapCandidates key={gap.gap_id} {...{ gap, analysis, participationByMatch, pursuitId, headers, startSearch }} run={latestByGap.get(gap.gap_id)} searching={searching === gap.gap_id} refresh={load} />) : <p className="ds-muted">{t('noPartnerGaps')}</p>}
    </section>
    <section className="candidate-team-column" aria-labelledby="candidate-experts"><header><UserRoundSearch aria-hidden /><div><h3 id="candidate-experts">{t('experts')}</h3><p>{t('expertsHelp')}</p></div></header>
      {experts.length ? experts.map((gap) => <GapCandidates key={gap.gap_id} {...{ gap, analysis, participationByMatch, pursuitId, headers, startSearch }} run={latestByGap.get(gap.gap_id)} searching={searching === gap.gap_id} refresh={load} />) : <p className="ds-muted">{t('noExpertGaps')}</p>}
    </section>
    {participation.length > 0 ? <ScenarioWorkspace {...{ scenarios, records: participation, pursuitId, headers }} refresh={load} /> : eligible.length > 0 ? <EmptyState icon={<UsersRound aria-hidden />} title={t('scenarios.notReadyTitle')} description={t('scenarios.notReadyHelp')} /> : null}
  </div>;
}
