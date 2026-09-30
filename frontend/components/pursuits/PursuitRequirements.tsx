'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileSearch, RefreshCw, Sparkles, UserRoundSearch } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Forms';
import { EmptyState, StatusBadge, Surface } from '@/components/ui/Display';
import { api } from '@/lib/api';
import { analysisLanguageForLocale, initialPackSelection, type AnalysisLanguage } from '@/lib/packSelection';
import type {
  AnalysisPackCandidate,
  CoverageState,
  PursuitAnalysis,
  PursuitGap,
  PursuitPosition,
  PursuitRequirement,
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

const tone = (state: CoverageState) => state === 'SUPPORTED' ? 'success' :
  state === 'GAP' ? 'danger' : state === 'PARTIAL' || state === 'EVIDENCE_MISSING' ||
  state === 'NEEDS_INTERPRETATION' ? 'warning' : 'info';

function ReviewControls({ runId, pursuitId, headers, kind, itemId, currentState, onReviewed, correctedLabel }:
  Props & { runId: string; kind: 'REQUIREMENT' | 'POSITION' | 'GAP'; itemId: string; currentState: CoverageState; onReviewed: () => Promise<void>; correctedLabel?: string }) {
  const t = useTranslations('pursuits.requirements');
  const [state, setState] = useState<CoverageState>(currentState);
  const [reason, setReason] = useState('');
  const [correction, setCorrection] = useState(correctedLabel || '');
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-runs/${runId}/reviews`, {
        target_kind: kind, target_id: itemId, new_coverage_state: state,
        new_review_state: correction !== (correctedLabel || '') ? 'CORRECTED' : 'CONFIRMED',
        corrected_fields: correction !== (correctedLabel || '') ? { normalized_text: correction.trim() } : {},
        reason: reason.trim(),
      }, { headers });
      setReason('');
      await onReviewed();
    } finally { setBusy(false); }
  };
  return <div className="analysis-review-controls">
    {correctedLabel !== undefined && <Input label={t('correctedFact')} value={correction} onChange={(event) => setCorrection(event.target.value)} />}
    <label><span>{t('reviewCoverage')}</span><select className="ds-control" value={state} onChange={(event) => setState(event.target.value as CoverageState)}>
      {COVERAGE_STATES.map((value) => <option key={value} value={value}>{t(`coverage.${value}`)}</option>)}
    </select></label>
    <Input label={t('reviewReason')} value={reason} onChange={(event) => setReason(event.target.value)} />
    <Button size="sm" variant="secondary" disabled={!reason.trim()} loading={busy} onClick={() => void submit()}>{t('recordReview')}</Button>
  </div>;
}

function Evidence({ item, packName }: { item: PursuitRequirement | PursuitPosition; packName: string }) {
  const t = useTranslations('pursuits.requirements');
  const page = item.source_locator.page_number;
  const paragraph = item.source_locator.paragraph_number;
  return <div className="analysis-evidence">
    <h4>{t('sourceEvidence')} · {t('sourceRequirement')}</h4>
    <p className="ds-muted ds-text-small"><BidiText>{packName}</BidiText> · {typeof page === 'number' ? t('page', { page }) : t('paragraph', { paragraph: typeof paragraph === 'number' ? paragraph : '?' })}</p>
    <blockquote><BidiText>{item.original_quote}</BidiText></blockquote>
    {item.source_context && <><h4>{t('sourceContext')}</h4><blockquote><BidiText>{item.source_context}</BidiText></blockquote></>}
  </div>;
}

export function PursuitRequirements({ pursuitId, headers, initialReviewableAnalysis, onAnalysisChange }: Props) {
  const t = useTranslations('pursuits.requirements');
  const documentRoleLabel = (role: string) => role === 'RFP' ? t('documentRoles.RFP') :
    role === 'OFFICIAL_NOTICE' ? t('documentRoles.OFFICIAL_NOTICE') :
    role === 'TOR' ? t('documentRoles.TOR') : role === 'NOTICE' ? t('documentRoles.NOTICE') :
      role === 'ADDENDUM' ? t('documentRoles.ADDENDUM') : role === 'CLARIFICATION' ? t('documentRoles.CLARIFICATION') :
        role === 'FORM' ? t('documentRoles.FORM') : role === 'ANNEX' ? t('documentRoles.ANNEX') : t('documentRoles.OTHER');
  const [candidate, setCandidate] = useState<AnalysisPackCandidate | null>(null);
  const [analysis, setAnalysis] = useState<PursuitAnalysis | null>(null);
  const [lastReadyAnalysis, setLastReadyAnalysis] = useState<PursuitAnalysis | null>(initialReviewableAnalysis || null);
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
  const packNames = useMemo(() => new Map(resultAnalysis?.pack_items.map((item) => [item.pack_item_id, item.display_name]) || []), [resultAnalysis]);
  const grouped = useMemo(() => {
    const values = new Map<CoverageState, PursuitRequirement[]>();
    for (const state of COVERAGE_STATES) values.set(state, []);
    for (const item of resultAnalysis?.requirements || []) values.get(item.effective_coverage_state)?.push(item);
    return values;
  }, [resultAnalysis]);
  const currentGaps = (resultAnalysis?.gaps || []).filter((gap) => !['NOT_APPLICABLE', 'LATER_STAGE_OBLIGATION', 'SUPPORTED'].includes(gap.effective_coverage_state));
  const qualityReady = resultAnalysis?.quality_state === 'READY_FOR_REVIEW';
  const analysisFailed = Boolean(analysis && (analysis.status === 'FAILED' || analysis.quality_state === 'FAILED'));
  const analysisRunning = Boolean(analysis && ['QUEUED', 'RUNNING'].includes(analysis.status));
  const coverageCounts = useMemo(() => {
    const counts = new Map<CoverageState, number>();
    for (const state of COVERAGE_STATES) counts.set(state, 0);
    for (const requirement of resultAnalysis?.requirements || []) counts.set(requirement.effective_coverage_state, (counts.get(requirement.effective_coverage_state) || 0) + 1);
    return counts;
  }, [resultAnalysis]);

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
      <Surface className="analysis-run-summary"><header><div><h3>{t('summary')}</h3><p>{analysis.limit_disclosure}</p></div><StatusBadge tone={analysis.quality_state === 'READY_FOR_REVIEW' ? 'success' : analysis.quality_state === 'FAILED' ? 'danger' : 'warning'}>{t(`quality.${analysis.quality_state}`)}</StatusBadge></header>
        {resultAnalysis && <dl><div><dt>{t('needsAttentionCount')}</dt><dd>{currentGaps.length}</dd></div><div><dt>{t('evidenceMissingCount')}</dt><dd>{coverageCounts.get('EVIDENCE_MISSING') || 0}</dd></div><div><dt>{t('interpretationCount')}</dt><dd>{coverageCounts.get('NEEDS_INTERPRETATION') || 0}</dd></div><div><dt>{t('supportedCount')}</dt><dd>{coverageCounts.get('SUPPORTED') || 0}</dd></div><div><dt>{t('laterStageCount')}</dt><dd>{coverageCounts.get('LATER_STAGE_OBLIGATION') || 0}</dd></div><div><dt>{t('positionsCount')}</dt><dd>{resultAnalysis.positions.length}</dd></div></dl>}
        <p><strong>{t('processingStatus')}:</strong> {analysisRunning ? t('runStates.inProgress') : analysisFailed ? t('runStates.failed') : t('runStates.complete')} · <strong>{t('qualityStatus')}:</strong> {t(`quality.${analysis.quality_state}`)}</p>
        <p className="ds-muted">{t(`qualityHelp.${analysis.quality_state}`)}</p>
        <details className="analysis-technical-details"><summary>{t('technicalDetails')}</summary><p>{analysis.quality_summary}</p><TechnicalText>{analysis.pipeline_version}</TechnicalText></details>
      </Surface>
      {analysisRunning && <div className="analysis-run-state" role="status"><RefreshCw aria-hidden /><div><strong>{t('runningTitle')}</strong><p>{t('runningHelp')}</p></div></div>}
      {analysisFailed && <div className="analysis-run-state is-failed" role="alert"><AlertTriangle aria-hidden /><div><strong>{t('failed')}</strong><p>{t('failedHelp')}</p><Button size="sm" variant="secondary" loading={busy} disabled={!candidate || (!selectedSource.size && !selectedPrivate.size)} onClick={() => void start()}>{t('retryAnalysis')}</Button></div></div>}
      {!currentQualityReady && resultAnalysis && <p className="analysis-previous-result" role="status">{t('previousResultVisible')}</p>}
      {analysis.status === 'COMPLETED' && !currentQualityReady && !analysisFailed && <div className="analysis-stale" role="alert"><AlertTriangle aria-hidden /><div><strong>{t('needsAttentionTitle')}</strong><p>{t('needsAttentionHelp')}</p><div className="ds-row"><Button size="sm" variant="secondary" onClick={() => window.document.getElementById('pursuit-requirements-title')?.scrollIntoView({ behavior: 'smooth' })}>{t('reviewAnalysis')}</Button><Button size="sm" loading={busy} disabled={!candidate || (!selectedSource.size && !selectedPrivate.size)} onClick={() => void start()}>{t('rerunAnalysis')}</Button></div></div></div>}
      {resultAnalysis && <>
        {qualityReady && <section className="analysis-result-group" aria-labelledby="analysis-current-gaps"><h3 id="analysis-current-gaps">{t('currentGaps')}</h3>
          {currentGaps.length ? currentGaps.map((gap: PursuitGap) => <Surface key={gap.gap_id} className="analysis-gap-row"><div><StatusBadge tone={tone(gap.effective_coverage_state)}>{t(`coverage.${gap.effective_coverage_state}`)}</StatusBadge><strong><BidiText>{gap.missing_contribution}</BidiText></strong><p>{gap.rationale}</p><small>{t('resolution')}: {t(`resolutionTypes.${gap.effective_resolution_category}`)}</small></div><ReviewControls {...{ pursuitId, headers }} runId={resultAnalysis.analysis_run_id} kind="GAP" itemId={gap.gap_id} currentState={gap.effective_coverage_state} onReviewed={() => load(false)} /></Surface>) : <p className="ds-muted">{t('noCurrentGaps')}</p>}
        </section>}
        {COVERAGE_STATES.map((state) => {
          const items = grouped.get(state) || [];
          if (!items.length) return null;
          return <section className="analysis-result-group" key={state}><h3>{t(`groups.${state}`)}</h3>{items.map((item) => <details key={item.requirement_id} className="analysis-requirement-row"><summary><StatusBadge tone={tone(state)}>{t(`coverage.${state}`)}</StatusBadge><strong><BidiText>{item.effective_normalized_requirement}</BidiText></strong><span>{t(`distinctions.${item.distinction}`)}</span></summary><Evidence item={item} packName={packNames.get(item.pack_item_id) || t('unknownDocument')} /><div className="analysis-assessment"><h4>{t('plasmaAssessment')}</h4><span className="sr-only">{t('generatedInterpretation')}</span>{item.generated_interpretation && <p><BidiText>{item.generated_interpretation}</BidiText></p>}<p>{t('assessmentState')}: {t(`coverage.${item.effective_coverage_state}`)}</p></div><div className="analysis-organization-evidence"><h4>{t('organizationEvidence')}</h4><p>{t('organizationEvidenceHelp')}</p><ReviewControls {...{ pursuitId, headers }} runId={resultAnalysis.analysis_run_id} kind="REQUIREMENT" itemId={item.requirement_id} currentState={item.effective_coverage_state} correctedLabel={item.effective_normalized_requirement} onReviewed={() => load(false)} /></div></details>)}</section>;
        })}
        <section className="analysis-result-group" aria-labelledby="analysis-positions"><h3 id="analysis-positions"><UserRoundSearch aria-hidden />{t('requiredPositions')}</h3>
          {resultAnalysis.positions.length ? resultAnalysis.positions.map((item) => <details className="analysis-requirement-row" key={item.position_id}><summary><StatusBadge tone={tone(item.effective_coverage_state)}>{t(`coverage.${item.effective_coverage_state}`)}</StatusBadge><strong><BidiText>{item.effective_title}</BidiText></strong><span>{item.quantity ? t('quantity', { count: item.quantity }) : t(`distinctions.${item.distinction}`)}</span></summary><Evidence item={item} packName={packNames.get(item.pack_item_id) || t('unknownDocument')} /><div className="analysis-assessment"><h4>{t('plasmaAssessment')}</h4>{item.generated_interpretation && <p><BidiText>{item.generated_interpretation}</BidiText></p>}<p>{t('assessmentState')}: {t(`coverage.${item.effective_coverage_state}`)}</p></div>{item.qualification_criteria.length > 0 && <div className="analysis-position-criteria"><h4>{t('qualificationCriteria')}</h4><ul>{item.qualification_criteria.map((criterion, index) => <li key={`${criterion.distinction}:${index}`}><StatusBadge tone={criterion.distinction === 'MANDATORY' ? 'info' : 'neutral'}>{t(`qualificationDistinctions.${criterion.distinction}`)}</StatusBadge><BidiText>{criterion.normalized_text}</BidiText></li>)}</ul></div>}<div className="analysis-organization-evidence"><h4>{t('organizationEvidence')}</h4><p>{t('organizationEvidenceHelp')}</p><ReviewControls {...{ pursuitId, headers }} runId={resultAnalysis.analysis_run_id} kind="POSITION" itemId={item.position_id} currentState={item.effective_coverage_state} correctedLabel={item.effective_title} onReviewed={() => load(false)} /></div></details>) : <p className="ds-muted">{t('noPositions')}</p>}
        </section>
      </>}
    </>}
    <Button variant="ghost" size="sm" onClick={() => void load(false)} leadingIcon={<RefreshCw aria-hidden />}>{t('refresh')}</Button>
    <p className="analysis-provisional"><CheckCircle2 aria-hidden />{t('provisionalNotice')}</p>
  </div>;
}
