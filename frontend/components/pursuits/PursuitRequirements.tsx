'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCheck, CheckCircle2, FileSearch, RefreshCw, Sparkles, UserRoundSearch } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { useLocale, useTranslations } from 'next-intl';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Forms';
import { EmptyState, StatusBadge, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { api } from '@/lib/api';
import { requestFailure } from '@/lib/libraryApi';
import { analysisLanguageForLocale, initialPackSelection, type AnalysisLanguage } from '@/lib/packSelection';
import {
  REQUIREMENT_GROUPS,
  bulkConfirmPlan,
  defaultBulkReason,
  gapsByRequirement,
  groupRequirements,
  referenceNames,
  runSequential,
  type RequirementGroup,
  type SequentialReport,
} from '@/lib/requirementsReview';
import type { CandidateLibrary } from '@/types/pursuit';
import type {
  AnalysisPackCandidate,
  CoverageState,
  PursuitAnalysis,
  PursuitGap,
  PursuitPosition,
  PursuitRequirement,
  PursuitSubmissionNote,
} from '@/types/pursuit';

const COVERAGE_STATES: CoverageState[] = [
  'SUPPORTED', 'PARTIAL', 'GAP', 'EVIDENCE_MISSING', 'NEEDS_INTERPRETATION',
  'NOT_APPLICABLE', 'LATER_STAGE_OBLIGATION',
];

type Props = {
  pursuitId: string;
  headers: Record<string, string | undefined>;
  initialReviewableAnalysis?: PursuitAnalysis | null;
  onAnalysisChange?: (analysis: PursuitAnalysis | null) => void;
};

type Loose = (key: string, values?: Record<string, string | number>) => string;

const tone = (state: CoverageState) => state === 'SUPPORTED' ? 'success' :
  state === 'GAP' ? 'danger' : state === 'PARTIAL' || state === 'EVIDENCE_MISSING' ||
  state === 'NEEDS_INTERPRETATION' ? 'warning' : 'info';

function reviewUrl(pursuitId: string, runId: string) {
  return `/pursuits/${encodeURIComponent(pursuitId)}/analysis-runs/${runId}/reviews`;
}

function ReviewControls({ runId, pursuitId, headers, kind, itemId, gapId, currentState, onReviewed, correctedLabel }:
  Props & { runId: string; kind: 'REQUIREMENT' | 'POSITION' | 'GAP'; itemId: string; gapId?: string; currentState: CoverageState; onReviewed: () => Promise<void>; correctedLabel?: string }) {
  const t = useTranslations('pursuits.requirements');
  const [state, setState] = useState<CoverageState>(currentState);
  const [reason, setReason] = useState('');
  const [correction, setCorrection] = useState(correctedLabel || '');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const submit = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    setFailure(null);
    const corrected = correction !== (correctedLabel || '');
    try {
      await api.post(reviewUrl(pursuitId, runId), {
        target_kind: kind, target_id: itemId, new_coverage_state: state,
        new_review_state: corrected ? 'CORRECTED' : 'CONFIRMED',
        corrected_fields: corrected ? { normalized_text: correction.trim() } : {},
        reason: reason.trim(),
      }, { headers });
      // The requirement's Gap carries the same review, so partner and expert search can use it.
      if (gapId) {
        await api.post(reviewUrl(pursuitId, runId), {
          target_kind: 'GAP', target_id: gapId, new_coverage_state: state, new_review_state: 'CONFIRMED',
          corrected_fields: {}, reason: reason.trim(),
        }, { headers });
      }
      setReason('');
      await onReviewed();
    } catch (error) {
      setFailure(requestFailure(error));
    } finally { setBusy(false); }
  };
  return <div className="analysis-review-controls">
    {correctedLabel !== undefined && <Input label={t('correctedFact')} value={correction} onChange={(event) => setCorrection(event.target.value)} />}
    <label><span>{t('reviewCoverage')}</span><select className="ds-control" value={state} onChange={(event) => setState(event.target.value as CoverageState)}>
      {COVERAGE_STATES.map((value) => <option key={value} value={value}>{t(`coverage.${value}`)}</option>)}
    </select></label>
    <Input label={t('reviewReason')} value={reason} onChange={(event) => setReason(event.target.value)} />
    <Button size="sm" variant="secondary" disabled={!reason.trim()} loading={busy} onClick={() => void submit()}>{t('recordReview')}</Button>
    {failure && <p className="ds-field-error" role="alert">{failure}</p>}
  </div>;
}

function Locator({ item, packName }: { item: PursuitRequirement | PursuitPosition; packName: string }) {
  const t = useTranslations('pursuits.requirements');
  const page = item.source_locator.page_number;
  const paragraph = item.source_locator.paragraph_number;
  return <p className="analysis-locator ds-muted ds-text-small" data-locator>
    <BidiText>{packName}</BidiText> · {typeof page === 'number' ? t('page', { page }) : t('paragraph', { paragraph: typeof paragraph === 'number' ? paragraph : '?' })}
  </p>;
}

function RequirementCard({ item, packName, group, gap, matchedNames, review }: {
  item: PursuitRequirement; packName: string; group: RequirementGroup; gap?: PursuitGap;
  matchedNames: { names: string[]; unresolved: number }; review: React.ReactNode;
}) {
  const t = useTranslations('pursuits.requirements');
  const tl = t as unknown as Loose;
  const note = group === 'notes' ? (item as PursuitSubmissionNote) : null;
  const state = item.effective_coverage_state;
  return <article className="analysis-requirement-card" data-requirement-id={item.requirement_id} data-group={group}>
    <header>
      {note ? <StatusBadge tone="info">{tl(`review.noteKinds.${note.note_kind}`)}</StatusBadge>
        : <StatusBadge tone={tone(state)}>{t(`coverage.${state}`)}</StatusBadge>}
      <strong><BidiText>{item.effective_normalized_requirement}</BidiText></strong>
      {!note && <span className="ds-muted ds-text-small">{t(`distinctions.${item.distinction}`)}</span>}
    </header>
    <blockquote className="analysis-quote"><BidiText>{item.original_quote}</BidiText></blockquote>
    <Locator item={item} packName={packName} />
    {item.generated_interpretation && <p className="analysis-interpretation" data-generated-interpretation>
      <span>{tl('review.generatedLabel')}</span> <BidiText>{item.generated_interpretation}</BidiText>
    </p>}
    {(matchedNames.names.length > 0 || matchedNames.unresolved > 0) && <p className="analysis-matched" data-matched-references>
      <span>{tl('review.matchedExperience')}</span> <BidiText>{matchedNames.names.join('; ')}</BidiText>
      {matchedNames.unresolved > 0 && <small> {tl('review.matchedUnresolved', { count: matchedNames.unresolved })}</small>}
    </p>}
    {gap && <p className="ds-muted ds-text-small">{t('resolution')}: {t(`resolutionTypes.${gap.effective_resolution_category}`)}</p>}
    {item.effective_review_state !== 'PROVISIONAL' && <p className="ds-text-small"><CheckCircle2 aria-hidden /> {tl(`review.reviewStates.${item.effective_review_state}`)}</p>}
    <details className="analysis-review-details"><summary>{tl('review.reviewItem')}</summary>{review}</details>
  </article>;
}

function BulkConfirm({ items, gaps, pursuitId, runId, headers, onDone }: {
  items: PursuitRequirement[]; gaps: Map<string, PursuitGap>; pursuitId: string; runId: string;
  headers: Props['headers']; onDone: () => Promise<void>;
}) {
  const t = useTranslations('pursuits.requirements') as unknown as Loose;
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [report, setReport] = useState<SequentialReport | null>(null);
  const defaultReason = defaultBulkReason(t('review.bulkDefaultReason'), session?.user?.name);
  const pending = items.filter((item) => item.effective_review_state === 'PROVISIONAL');
  if (!pending.length && !report) return null;
  const run = async () => {
    const chosen = pending.filter((item) => !excluded.has(item.requirement_id));
    const plan = bulkConfirmPlan(chosen, gaps, reason.trim() || defaultReason, overrides);
    setReport(null);
    const result = await runSequential(plan, (entry) => entry.requirementId, async (entry) => {
      for (const post of entry.posts) await api.post(reviewUrl(pursuitId, runId), post, { headers });
    }, (done, total) => setProgress({ done, total }), requestFailure);
    setReport(result);
    setProgress(null);
    setOpen(false);
    await onDone();
  };
  return <div className="analysis-bulk" data-bulk-confirm>
    {!open ? pending.length > 0 && <Button size="sm" variant="secondary" leadingIcon={<CheckCheck aria-hidden />} onClick={() => { setOpen(true); setReport(null); }}>
      {t('review.confirmGroup', { count: pending.length })}
    </Button> : <div className="analysis-bulk-panel ds-stack">
      <Input label={t('review.bulkReason')} placeholder={defaultReason} value={reason} onChange={(event) => setReason(event.target.value)}
        helper={t('review.bulkReasonHelp')} />
      <ul className="analysis-bulk-items">
        {pending.map((item) => <li key={item.requirement_id}>
          <label><input type="checkbox" checked={!excluded.has(item.requirement_id)} onChange={(event) => setExcluded((current) => {
            const next = new Set(current);
            if (event.target.checked) next.delete(item.requirement_id); else next.add(item.requirement_id);
            return next;
          })} /> <BidiText>{item.effective_normalized_requirement}</BidiText></label>
          <input className="ds-control analysis-bulk-override" aria-label={t('review.itemReason')} placeholder={t('review.itemReason')}
            value={overrides[item.requirement_id] ?? ''} onChange={(event) => setOverrides((current) => ({ ...current, [item.requirement_id]: event.target.value }))} />
        </li>)}
      </ul>
      <div className="ds-row">
        <Button size="sm" loading={progress !== null} onClick={() => void run()} data-bulk-run
          disabled={pending.every((item) => excluded.has(item.requirement_id))}>
          {t('review.confirmSelected', { count: pending.filter((item) => !excluded.has(item.requirement_id)).length })}
        </Button>
        <Button size="sm" variant="ghost" disabled={progress !== null} onClick={() => setOpen(false)}>{t('review.cancel')}</Button>
      </div>
      {progress && <p role="status" data-bulk-progress>{t('review.bulkProgress', { done: progress.done, total: progress.total })}</p>}
    </div>}
    {report && <Alert tone={report.failed.length ? 'warning' : 'success'} title={t('review.bulkReport', { done: report.done - report.failed.length, failed: report.failed.length })}>
      {report.failed.length > 0 && <span data-bulk-failures>{report.failed.map((item) => {
        const label = items.find((entry) => entry.requirement_id === item.id)?.effective_normalized_requirement || item.id;
        return `${label}: ${item.message}`;
      }).join(' · ')}</span>}
    </Alert>}
  </div>;
}

export function PursuitRequirements({ pursuitId, headers, initialReviewableAnalysis, onAnalysisChange }: Props) {
  const t = useTranslations('pursuits.requirements');
  const tl = t as unknown as Loose;
  const documentRoleLabel = (role: string) => role === 'RFP' ? t('documentRoles.RFP') :
    role === 'OFFICIAL_NOTICE' ? t('documentRoles.OFFICIAL_NOTICE') :
    role === 'TOR' ? t('documentRoles.TOR') : role === 'NOTICE' ? t('documentRoles.NOTICE') :
      role === 'ADDENDUM' ? t('documentRoles.ADDENDUM') : role === 'CLARIFICATION' ? t('documentRoles.CLARIFICATION') :
        role === 'FORM' ? t('documentRoles.FORM') : role === 'ANNEX' ? t('documentRoles.ANNEX') : t('documentRoles.OTHER');
  const [candidate, setCandidate] = useState<AnalysisPackCandidate | null>(null);
  const [analysis, setAnalysis] = useState<PursuitAnalysis | null>(null);
  const [lastReadyAnalysis, setLastReadyAnalysis] = useState<PursuitAnalysis | null>(initialReviewableAnalysis || null);
  const [library, setLibrary] = useState<Map<string, string>>(new Map());
  const [selectedSource, setSelectedSource] = useState<Set<string>>(new Set());
  const [selectedPrivate, setSelectedPrivate] = useState<Set<string>>(new Set());
  const locale = useLocale();
  // Defaults to the UI locale (en/ru/uz, else en); the customer can still change it.
  const [language, setLanguage] = useState<AnalysisLanguage>(() => analysisLanguageForLocale(locale));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (initializeSelection = false) => {
    try {
      const [candidateResponse, analysisResponse] = await Promise.all([
        api.get<AnalysisPackCandidate>(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-pack-candidate`, { headers }),
        api.get<PursuitAnalysis | null>(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-runs/latest`, { headers }),
      ]);
      setCandidate(candidateResponse.data);
      setAnalysis(analysisResponse.data);
      if (analysisResponse.data?.status === 'COMPLETED' && analysisResponse.data.quality_state === 'READY_FOR_REVIEW') {
        setLastReadyAnalysis(analysisResponse.data);
      }
      onAnalysisChange?.(analysisResponse.data);
      if (initializeSelection) {
        // D1-06: a SOURCE pursuit starts with its OFFICIAL_NOTICE pre-selected.
        const selection = initialPackSelection(candidateResponse.data);
        setSelectedSource(new Set(selection.source));
        setSelectedPrivate(new Set(selection.private));
      }
      setError(null);
    } catch { setError(t('loadFailed')); }
    finally { setLoading(false); }
  }, [headers, onAnalysisChange, pursuitId, t]);

  useEffect(() => { void load(true); }, [load]);
  useEffect(() => {
    if (!analysis || !['QUEUED', 'RUNNING'].includes(analysis.status)) return;
    const timer = window.setInterval(() => void load(false), 4_000);
    return () => window.clearInterval(timer);
  }, [analysis, load]);
  // Matched experience is shown by name: one passive read of the organization's library.
  useEffect(() => {
    let cancelled = false;
    void api.get<CandidateLibrary>('/candidates', { headers }).then((response) => {
      if (cancelled) return;
      const names = new Map<string, string>();
      for (const firm of [response.data.self_firm, ...response.data.firms]) {
        for (const reference of firm?.project_references ?? []) names.set(reference.reference_id, reference.project_name);
      }
      setLibrary(names);
    }).catch(() => { /* names are optional; ids stay counted */ });
    return () => { cancelled = true; };
  }, [headers]);

  const start = async () => {
    if (!candidate || (!selectedSource.size && !selectedPrivate.size)) return;
    setBusy(true); setError(null);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-runs`, {
        candidate_sha256: candidate.candidate_sha256, analysis_language: language,
        source_document_ids: [...selectedSource], private_version_ids: [...selectedPrivate],
      }, { headers });
      await load(false);
    } catch { setError(t('startFailed')); }
    finally { setBusy(false); }
  };

  const currentQualityReady = analysis?.status === 'COMPLETED' && analysis.quality_state === 'READY_FOR_REVIEW';
  const resultAnalysis = currentQualityReady ? analysis : lastReadyAnalysis;
  const packNames = useMemo(() => new Map(resultAnalysis?.pack_items.map((item) => [
    item.pack_item_id, item.role === 'OFFICIAL_NOTICE' ? t('documentRoles.OFFICIAL_NOTICE') : item.display_name,
  ]) || []), [resultAnalysis, t]);
  const groups = useMemo(() => groupRequirements(resultAnalysis), [resultAnalysis]);
  const gaps = useMemo(() => gapsByRequirement(resultAnalysis?.gaps || []), [resultAnalysis]);
  const analysisFailed = Boolean(analysis && (analysis.status === 'FAILED' || analysis.quality_state === 'FAILED'));
  const analysisRunning = Boolean(analysis && ['QUEUED', 'RUNNING'].includes(analysis.status));

  if (loading) return <p className="ds-muted">{t('loading')}</p>;
  return <div className="pursuit-requirements">
    {error && <p className="pursuit-upload-error" role="alert">{error}</p>}
    <details className="analysis-pack-review ds-surface" open={!resultAnalysis}>
      <summary><span><strong>{t('packTitle')}</strong><small>{t('packHelp')}</small></span><FileSearch aria-hidden /></summary>
      {candidate && <>
        <div className="analysis-candidate-list">
          {candidate.source_documents.map((item) => <label key={item.tender_document_id} className="analysis-candidate-row">
            <input type="checkbox" checked={selectedSource.has(item.tender_document_id)} disabled={!item.parse_ready || busy} onChange={(event) => setSelectedSource((current) => { const next = new Set(current); if (event.target.checked) next.add(item.tender_document_id); else next.delete(item.tender_document_id); return next; })} />
            <span><strong><BidiText>{item.role === 'OFFICIAL_NOTICE' ? t('documentRoles.OFFICIAL_NOTICE') : item.display_name}</BidiText></strong><small>{t('sourceDocument')} · {documentRoleLabel(item.role)} · {item.page_count_known ? t('pages', { count: item.page_count || 0 }) : t('pagesUnknown')}</small>{item.duplicate_warning && <em>{item.duplicate_warning}</em>}</span>
            <StatusBadge tone={item.parse_ready ? 'success' : 'warning'}>{item.parse_ready ? t('ready') : t('notReady')}</StatusBadge>
          </label>)}
          {candidate.private_versions.map((item) => <label key={item.document_version_id} className="analysis-candidate-row">
            <input type="checkbox" checked={selectedPrivate.has(item.document_version_id)} disabled={!item.parse_ready || busy} onChange={(event) => setSelectedPrivate((current) => { const next = new Set(current); if (event.target.checked) next.add(item.document_version_id); else next.delete(item.document_version_id); return next; })} />
            <span><strong><BidiText>{item.display_name}</BidiText></strong><small>{t('privateDocument')} · {documentRoleLabel(item.role)} · {t('version', { version: item.version_number })} · {item.page_count_known ? t('pages', { count: item.page_count || 0 }) : t('pagesUnknown')}</small>{item.duplicate_warning && <em>{item.duplicate_warning}</em>}</span>
            <StatusBadge tone={item.parse_ready ? 'success' : 'warning'}>{item.parse_ready ? t('ready') : t('notReady')}</StatusBadge>
          </label>)}
        </div>
        <div className="analysis-pack-actions"><label><span>{t('analysisLanguage')}</span><select className="ds-control" value={language} onChange={(event) => setLanguage(event.target.value as AnalysisLanguage)} disabled={busy}><option value="en">English</option><option value="uz">O‘zbekcha</option><option value="ru">Русский</option></select></label>
          <Button onClick={() => void start()} loading={busy} disabled={!selectedSource.size && !selectedPrivate.size} leadingIcon={<Sparkles aria-hidden />}>{t('analyzeSelected')}</Button></div>
        <p className="ds-muted ds-text-small">{candidate.page_count_total === null ? t('alternateLimitDisclosure') : t('candidatePages', { count: candidate.page_count_total })}</p>
      </>}
    </details>

    {!analysis ? <EmptyState icon={<FileSearch aria-hidden />} title={t('empty')} description={t('emptyHelp')} /> : <>
      {analysis.inputs_changed && <div className="analysis-stale" role="status"><AlertTriangle aria-hidden /><div><strong>{t('staleTitle')}</strong><p>{t('staleHelp')}</p></div></div>}
      <Surface className="analysis-run-summary"><header><div><h3>{t('summary')}</h3></div><StatusBadge tone={analysis.quality_state === 'READY_FOR_REVIEW' ? 'success' : analysis.quality_state === 'FAILED' ? 'danger' : 'warning'}>{t(`quality.${analysis.quality_state}`)}</StatusBadge></header>
        {resultAnalysis && <dl data-group-counts>{REQUIREMENT_GROUPS.filter((group) => group !== 'settled').map((group) => <div key={group}><dt>{tl(`review.groups.${group}`)}</dt><dd>{groups[group].length}</dd></div>)}<div><dt>{t('positionsCount')}</dt><dd>{resultAnalysis.positions.length}</dd></div></dl>}
        <p className="ds-muted">{analysisRunning ? t('runStates.inProgress') : analysisFailed ? t('runStates.failed') : t(`qualityHelp.${analysis.quality_state}`)}</p>
        <details className="analysis-technical-details"><summary>{t('technicalDetails')}</summary><p>{t('processingStatus')}: {analysisRunning ? t('runStates.inProgress') : analysisFailed ? t('runStates.failed') : t('runStates.complete')} · {t('qualityStatus')}: {t(`quality.${analysis.quality_state}`)}</p><p>{analysis.quality_summary}</p><p data-limit-disclosure>{analysis.limit_disclosure}</p><TechnicalText>{analysis.pipeline_version}</TechnicalText></details>
      </Surface>
      {analysisRunning && <div className="analysis-run-state" role="status"><RefreshCw aria-hidden /><div><strong>{t('runningTitle')}</strong><p>{t('runningHelp')}</p></div></div>}
      {analysisFailed && <div className="analysis-run-state is-failed" role="alert"><AlertTriangle aria-hidden /><div><strong>{t('failed')}</strong><p>{t('failedHelp')}</p><Button size="sm" variant="secondary" loading={busy} disabled={!candidate || (!selectedSource.size && !selectedPrivate.size)} onClick={() => void start()}>{t('retryAnalysis')}</Button></div></div>}
      {!currentQualityReady && resultAnalysis && <p className="analysis-previous-result" role="status">{t('previousResultVisible')}</p>}
      {analysis.status === 'COMPLETED' && !currentQualityReady && !analysisFailed && <div className="analysis-stale" role="alert"><AlertTriangle aria-hidden /><div><strong>{t('needsAttentionTitle')}</strong><p>{t('needsAttentionHelp')}</p><div className="ds-row"><Button size="sm" loading={busy} disabled={!candidate || (!selectedSource.size && !selectedPrivate.size)} onClick={() => void start()}>{t('rerunAnalysis')}</Button></div></div></div>}
      {resultAnalysis && <>
        {REQUIREMENT_GROUPS.map((group) => {
          const items = groups[group];
          if (!items.length) return null;
          return <section className="analysis-result-group" key={group} data-requirement-group={group} aria-labelledby={`analysis-group-${group}`}>
            <header className="analysis-group-header">
              <div><h3 id={`analysis-group-${group}`}>{tl(`review.groups.${group}`)} <span className="ds-muted">({items.length})</span></h3><p className="ds-muted ds-text-small">{tl(`review.groupHelp.${group}`)}</p></div>
              <BulkConfirm items={items} gaps={gaps} pursuitId={pursuitId} runId={resultAnalysis.analysis_run_id} headers={headers} onDone={() => load(false)} />
            </header>
            {items.map((item) => <RequirementCard key={item.requirement_id} item={item} group={group}
              packName={packNames.get(item.pack_item_id) || t('unknownDocument')} gap={gaps.get(item.requirement_id)}
              matchedNames={referenceNames(item.matched_reference_ids, library)}
              review={<ReviewControls {...{ pursuitId, headers }} runId={resultAnalysis.analysis_run_id} kind="REQUIREMENT"
                itemId={item.requirement_id} gapId={gaps.get(item.requirement_id)?.gap_id} currentState={item.effective_coverage_state}
                correctedLabel={item.effective_normalized_requirement} onReviewed={() => load(false)} />} />)}
          </section>;
        })}
        <section className="analysis-result-group" aria-labelledby="analysis-positions"><h3 id="analysis-positions"><UserRoundSearch aria-hidden />{t('requiredPositions')}</h3>
          {resultAnalysis.positions.length ? resultAnalysis.positions.map((item) => <article className="analysis-requirement-card" key={item.position_id}>
            <header><StatusBadge tone={tone(item.effective_coverage_state)}>{t(`coverage.${item.effective_coverage_state}`)}</StatusBadge><strong><BidiText>{item.effective_title}</BidiText></strong><span className="ds-muted ds-text-small">{item.quantity ? t('quantity', { count: item.quantity }) : t(`distinctions.${item.distinction}`)}</span></header>
            <blockquote className="analysis-quote"><BidiText>{item.original_quote}</BidiText></blockquote>
            <Locator item={item} packName={packNames.get(item.pack_item_id) || t('unknownDocument')} />
            {item.generated_interpretation && <p className="analysis-interpretation"><span>{tl('review.generatedLabel')}</span> <BidiText>{item.generated_interpretation}</BidiText></p>}
            {item.qualification_criteria.length > 0 && <div className="analysis-position-criteria"><h4>{t('qualificationCriteria')}</h4><ul>{item.qualification_criteria.map((criterion, index) => <li key={`${criterion.distinction}:${index}`}><StatusBadge tone={criterion.distinction === 'MANDATORY' ? 'info' : 'neutral'}>{t(`qualificationDistinctions.${criterion.distinction}`)}</StatusBadge><BidiText>{criterion.normalized_text}</BidiText></li>)}</ul></div>}
            <details className="analysis-review-details"><summary>{tl('review.reviewItem')}</summary><ReviewControls {...{ pursuitId, headers }} runId={resultAnalysis.analysis_run_id} kind="POSITION" itemId={item.position_id}
              gapId={resultAnalysis.gaps.find((gap) => gap.position_id === item.position_id)?.gap_id}
              currentState={item.effective_coverage_state} correctedLabel={item.effective_title} onReviewed={() => load(false)} /></details>
          </article>) : <p className="ds-muted">{t('noPositions')}</p>}
        </section>
      </>}
    </>}
    <Button variant="ghost" size="sm" onClick={() => void load(false)} leadingIcon={<RefreshCw aria-hidden />}>{t('refresh')}</Button>
    <p className="analysis-provisional"><CheckCircle2 aria-hidden />{t('provisionalNotice')}</p>
  </div>;
}
