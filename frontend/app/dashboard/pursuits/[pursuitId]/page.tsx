'use client';

import { Suspense, use, useCallback, useEffect, useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  ClipboardList,
  Download,
  FileCheck2,
  FileSignature,
  FileText,
  FolderOpen,
  LayoutDashboard,
  PackageCheck,
  Pencil,
  RefreshCw,
  Replace,
  ShieldCheck,
  UsersRound,
} from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';

import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { PursuitRequirements } from '@/components/pursuits/PursuitRequirements';
import { PursuitTeam } from '@/components/pursuits/PursuitTeam';
import { PursuitProposal } from '@/components/pursuits/PursuitProposal';
import { PursuitEoi } from '@/components/pursuits/PursuitEoi';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Input } from '@/components/ui/Forms';
import { EmptyState, PageHeader, PageSkeleton, StatusBadge, Surface, type Tone } from '@/components/ui/Display';
import { formatDateTime, formatFileSize } from '@/i18n/formatters';
import { formatPublishedDeadline, isDeadlinePassed, type TenderTruth } from '@/lib/tenderTruth';
import { useTenderTruthLabels } from '@/lib/useTenderTruthLabels';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';
import { eoiRunId } from '@/lib/eoiBuilder';
import { pursuitDisplayTitle } from '@/lib/requirementsReview';
import type { TenderDetailsResponse } from '@/types/tender-details';
import type {
  AnalysisPackCandidate,
  PrivateDocument,
  PrivateDocumentRole,
  Pursuit,
  PursuitAnalysis,
  PursuitContext,
  PursuitRequirement,
  PursuitStage,
  TeamScenario,
} from '@/types/pursuit';
import { customerProcessingState } from '@/types/pursuit';

const ACTIVE_STATES = new Set(['UPLOADING', 'QUEUED', 'CHECKING', 'EXTRACTING']);
// The header shows where the pursuit stands; document processing states live in Documents & Evidence.
const STAGE_TONES: Record<PursuitStage, Tone> = {
  SAVED: 'neutral', EVALUATING: 'info', PREPARING: 'info', SUBMITTED: 'info', WON: 'success', LOST: 'neutral', DISMISSED: 'neutral',
};
const DOCUMENT_ROLES: PrivateDocumentRole[] = ['RFP', 'TOR', 'NOTICE', 'ADDENDUM', 'CLARIFICATION', 'FORM', 'ANNEX', 'OTHER'];
// D2-05: the EOI package sits between Requirements and Team.
const WORKSPACE_TABS = ['overview', 'requirements', 'eoi', 'team', 'documents', 'proposal'] as const;
type WorkspaceTab = typeof WORKSPACE_TABS[number];

const isWorkspaceTab = (value: string | null): value is WorkspaceTab =>
  Boolean(value && WORKSPACE_TABS.includes(value as WorkspaceTab));

const isLaterStage = (item: PursuitRequirement) =>
  item.effective_coverage_state === 'LATER_STAGE_OBLIGATION' ||
  ['CONTRACT_EXECUTION', 'POST_AWARD_OBLIGATION'].includes(item.stage_scope);

const isSubmissionItem = (item: PursuitRequirement) => {
  const signal = `${item.stage_scope} ${item.requirement_type} ${item.category}`.toUpperCase();
  return /SUBMISSION|PROPOSAL|FORM|ARTIFACT|DELIVERY/.test(signal) && !isLaterStage(item);
};

const isEvaluationItem = (item: PursuitRequirement) => {
  const signal = `${item.stage_scope} ${item.requirement_type} ${item.category}`.toUpperCase();
  return /EVALUATION|QUALIFICATION|EXPERIENCE|REFERENCE|RESPONSIB|PRICE|AVAILABILITY/.test(signal) && !isLaterStage(item);
};

function OverviewList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return <section className="pursuit-overview-section">
    <h3>{title}</h3>
    {items.length ? <ul>{items.map((item, index) => <li key={`${index}:${item}`}><BidiText>{item}</BidiText></li>)}</ul> : <p className="ds-muted">{empty}</p>}
  </section>;
}

function PursuitWorkspace({ pursuitId }: { pursuitId: string }) {
  const t = useTranslations('pursuits');
  const locale = useLocale() as CustomerSelectableLocale;
  const truthLabels = useTenderTruthLabels();
  const search = useSearchParams();
  const initialTab = search.get('tab');
  const [activeTab, setActiveTab] = useState<WorkspaceTab>(isWorkspaceTab(initialTab) ? initialTab : 'overview');
  const [organizationId, setOrganizationId] = useState(search.get('organization_id') || '');
  const [pursuit, setPursuit] = useState<Pursuit | null>(null);
  const [documents, setDocuments] = useState<PrivateDocument[]>([]);
  const [documentCandidate, setDocumentCandidate] = useState<AnalysisPackCandidate | null>(null);
  const [documentCandidateLoading, setDocumentCandidateLoading] = useState(false);
  const [context, setContext] = useState<PursuitContext | null>(null);
  const [analysis, setAnalysis] = useState<PursuitAnalysis | null>(null);
  const [lastReviewableAnalysis, setLastReviewableAnalysis] = useState<PursuitAnalysis | null>(null);
  const [scenarios, setScenarios] = useState<TeamScenario[]>([]);
  const [sourceDetails, setSourceDetails] = useState<TenderDetailsResponse | null>(null);
  const [contextValues, setContextValues] = useState<Record<string, string>>({});
  const [contextEditing, setContextEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [contextBusy, setContextBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const chooseOrganization = useCallback((value: string) => setOrganizationId(value), []);
  const headers = useMemo(() => organizationId ? { 'X-Organization-ID': organizationId } : {}, [organizationId]);
  const handleAnalysisChange = useCallback((value: PursuitAnalysis | null) => {
    setAnalysis(value);
    if (value?.status === 'COMPLETED' && value.quality_state === 'READY_FOR_REVIEW') setLastReviewableAnalysis(value);
  }, []);
  const documentRoleLabel = (role: string) => role === 'RFP' ? t('roles.RFP') : role === 'TOR' ? t('roles.TOR') :
    role === 'OFFICIAL_NOTICE' ? t('roles.OFFICIAL_NOTICE') : role === 'NOTICE' ? t('roles.NOTICE') : role === 'ADDENDUM' ? t('roles.ADDENDUM') :
      role === 'CLARIFICATION' ? t('roles.CLARIFICATION') : role === 'FORM' ? t('roles.FORM') :
        role === 'ANNEX' ? t('roles.ANNEX') : t('roles.OTHER');

  const selectTab = useCallback((tab: WorkspaceTab, focus = false) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    if (tab === 'overview') url.searchParams.delete('tab');
    else url.searchParams.set('tab', tab);
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    if (focus) window.requestAnimationFrame(() => window.document.getElementById(`pursuit-tab-${tab}`)?.focus());
  }, []);

  const onTabKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = WORKSPACE_TABS.indexOf(activeTab);
    const rtl = window.getComputedStyle(event.currentTarget).direction === 'rtl';
    const delta = event.key === 'ArrowRight' ? (rtl ? -1 : 1) : event.key === 'ArrowLeft' ? (rtl ? 1 : -1) : 0;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? WORKSPACE_TABS.length - 1 : (current + delta + WORKSPACE_TABS.length) % WORKSPACE_TABS.length;
    selectTab(WORKSPACE_TABS[next] || 'overview', true);
  };

  useEffect(() => {
    const restoreTab = () => {
      const value = new URL(window.location.href).searchParams.get('tab');
      setActiveTab(isWorkspaceTab(value) ? value : 'overview');
    };
    window.addEventListener('popstate', restoreTab);
    return () => window.removeEventListener('popstate', restoreTab);
  }, []);

  const load = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    setError(false);
    try {
      const [pursuitResponse, documentResponse, contextResponse, analysisResponse, scenariosResponse] = await Promise.all([
        api.get<Pursuit>(`/pursuits/${encodeURIComponent(pursuitId)}`, { headers }),
        api.get<{ items: PrivateDocument[] }>(`/pursuits/${encodeURIComponent(pursuitId)}/documents`, { headers }),
        api.get<PursuitContext>(`/pursuits/${encodeURIComponent(pursuitId)}/context`, { headers }),
        api.get<PursuitAnalysis | null>(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-runs/latest`, { headers }),
        api.get<TeamScenario[]>(`/pursuits/${encodeURIComponent(pursuitId)}/team-scenarios`, { headers }),
      ]);
      setPursuit(pursuitResponse.data);
      setDocuments(documentResponse.data.items);
      setContext(contextResponse.data);
      setAnalysis(analysisResponse.data);
      if (analysisResponse.data?.status === 'COMPLETED' && analysisResponse.data.quality_state === 'READY_FOR_REVIEW') {
        setLastReviewableAnalysis(analysisResponse.data);
      }
      setScenarios(scenariosResponse.data);
      setContextValues({
        title: contextResponse.data.title || '', buyer: contextResponse.data.buyer || '',
        declared_funder: contextResponse.data.declared_funder || '', country: contextResponse.data.country || '',
        reference: contextResponse.data.reference || '', procurement_stage: contextResponse.data.procurement_stage || '',
        external_deadline: contextResponse.data.external_deadline ? contextResponse.data.external_deadline.slice(0, 16) : '',
        deadline_timezone: contextResponse.data.deadline_timezone || '', source_url: contextResponse.data.source_url || '',
      });
    } catch { setError(true); }
    finally { setLoading(false); }
  }, [headers, organizationId, pursuitId]);

  useEffect(() => { void load(); }, [load]);
  const hasActiveProcessing = documents.some((document) => ACTIVE_STATES.has(document.processing_state));
  const hasActiveAnalysis = Boolean(analysis && ['QUEUED', 'RUNNING'].includes(analysis.status));
  useEffect(() => {
    if (!hasActiveProcessing && !hasActiveAnalysis) return;
    const timer = window.setInterval(() => void load(), 4_000);
    return () => window.clearInterval(timer);
  }, [hasActiveAnalysis, hasActiveProcessing, load]);

  useEffect(() => {
    if (activeTab !== 'overview' || pursuit?.origin !== 'SOURCE' || !pursuit.source_tender_id) {
      if (pursuit?.origin !== 'SOURCE') setSourceDetails(null);
      return;
    }
    let active = true;
    void api.get<TenderDetailsResponse>(`/tenders/${pursuit.source_tender_id}/details`).then((response) => {
      if (active) setSourceDetails(response.data);
    }).catch(() => { if (active) setSourceDetails(null); });
    return () => { active = false; };
  }, [activeTab, pursuit?.origin, pursuit?.source_tender_id]);

  useEffect(() => {
    if (activeTab !== 'documents' || !organizationId || documentCandidate) return;
    let active = true;
    setDocumentCandidateLoading(true);
    void api.get<AnalysisPackCandidate>(`/pursuits/${encodeURIComponent(pursuitId)}/analysis-pack-candidate`, { headers })
      .then((response) => { if (active) setDocumentCandidate(response.data); })
      .catch(() => { if (active) setDocumentCandidate(null); })
      .finally(() => { if (active) setDocumentCandidateLoading(false); });
    return () => { active = false; };
  }, [activeTab, documentCandidate, headers, organizationId, pursuitId]);

  const saveContext = async () => {
    if (!pursuit || pursuit.origin !== 'UPLOAD' || contextBusy) return;
    setContextBusy(true);
    setActionError(null);
    const payload: Record<string, string | string[]> = {};
    const confirmedFields: string[] = [];
    for (const [field, value] of Object.entries(contextValues)) {
      if (!value.trim()) continue;
      payload[field] = field === 'external_deadline' ? new Date(value).toISOString() : value.trim();
      confirmedFields.push(field);
    }
    payload.confirmed_fields = confirmedFields;
    try {
      const response = await api.patch<PursuitContext>(`/pursuits/${encodeURIComponent(pursuitId)}/context`, payload, { headers });
      setContext(response.data);
      setContextEditing(false);
      await load();
    } catch { setActionError(t('context.saveFailed')); }
    finally { setContextBusy(false); }
  };

  const download = async (document: PrivateDocument) => {
    setActionBusy(document.document_id);
    setActionError(null);
    try {
      const response = await api.get(
        `/pursuits/${encodeURIComponent(pursuitId)}/documents/${document.document_id}/versions/${document.current_version_id}/download`,
        { headers, responseType: 'blob' },
      );
      const url = URL.createObjectURL(new Blob([response.data], { type: document.media_type }));
      const link = window.document.createElement('a');
      link.href = url;
      link.download = document.display_name;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch { setActionError(t('documents.downloadFailed')); }
    finally { setActionBusy(null); }
  };

  const retry = async (document: PrivateDocument) => {
    setActionBusy(document.document_id);
    setActionError(null);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/documents/${document.document_id}/retry`, undefined, { headers });
      await load();
    } catch { setActionError(t('documents.retryFailed')); }
    finally { setActionBusy(null); }
  };

  const replace = async (document: PrivateDocument, file: File) => {
    setActionBusy(document.document_id);
    setActionError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      await api.post(
        `/pursuits/${encodeURIComponent(pursuitId)}/documents/${document.document_id}/versions`,
        form,
        { headers: { ...headers, 'Content-Type': 'multipart/form-data' } },
      );
      setDocumentCandidate(null);
      await load();
    } catch { setActionError(t('documents.replaceFailed')); }
    finally { setActionBusy(null); }
  };

  const correctRole = async (document: PrivateDocument, role: PrivateDocumentRole) => {
    setActionBusy(document.document_id);
    setActionError(null);
    try {
      await api.patch(
        `/pursuits/${encodeURIComponent(pursuitId)}/documents/${document.document_id}/role`,
        { role },
        { headers },
      );
      setDocuments((current) => current.map((item) => item.document_id === document.document_id ? { ...item, role } : item));
      setDocumentCandidate(null);
    } catch { setActionError(t('documents.roleUpdateFailed')); }
    finally { setActionBusy(null); }
  };

  const contextFieldLabel = (field: string) => {
    if (field === 'title') return t('fields.title');
    if (field === 'buyer') return t('fields.buyer');
    if (field === 'declared_funder') return t('fields.funder');
    if (field === 'country') return t('fields.country');
    if (field === 'reference') return t('fields.reference');
    if (field === 'procurement_stage') return t('fields.procurementStage');
    if (field === 'external_deadline') return t('fields.deadline');
    if (field === 'deadline_timezone') return t('fields.timezone');
    return t('fields.sourceUrl');
  };

  if (!organizationId) return <main className="customer-page pursuit-workspace ds-container-content">
    <PageHeader eyebrow={t('workspace.eyebrow')} title={t('workspace.titleFallback')} description={t('organizations.help')} />
    <Surface className="pursuit-org-context"><OrganizationContextPicker value={organizationId} onChange={chooseOrganization} /></Surface>
  </main>;
  if (loading && !pursuit) return <PageSkeleton label={t('workspace.loading')} />;
  if (error || !pursuit) return <main className="customer-page pursuit-workspace ds-container-content"><EmptyState
    icon={<FileText aria-hidden />} title={t('workspace.failed')} description={t('workspace.failedHelp')}
    action={<Button variant="secondary" onClick={() => void load()} leadingIcon={<RefreshCw aria-hidden />}>{t('actions.retry')}</Button>}
  /></main>;

  const title = pursuitDisplayTitle(pursuit, (date) => t('values.uploadedOn', { date: formatDateTime(date, locale) }));
  const sourceDeadline = context?.field_provenance.find((item) => item.field_name === 'external_deadline')?.source_value || null;
  const deadline = sourceDeadline || pursuit.external_deadline || pursuit.source_deadline;
  // The linked source tender's deadline is a published wall time: shown as published
  // and judged at its conservative instant (D1-05b). User-entered deadlines are instants.
  const sourceTruth: TenderTruth = {
    status: pursuit.source_tender_status, status_reason: pursuit.source_tender_status_reason,
    deadline: pursuit.source_deadline, deadline_time_basis: pursuit.source_deadline_time_basis,
    deadline_timezone: pursuit.source_deadline_timezone, deadline_published_local: pursuit.source_deadline_published_local,
    deadline_effective_at: pursuit.source_deadline_effective_at,
    deadline_closes_at: pursuit.source_deadline_closes_at,
  };
  const usesSourceDeadline = !sourceDeadline && !pursuit.external_deadline && Boolean(pursuit.source_deadline);
  const historicalDeadline = usesSourceDeadline
    ? isDeadlinePassed(sourceTruth)
    : Boolean(deadline && new Date(deadline).getTime() < Date.now());
  const presentDeadline = (value: string) => usesSourceDeadline ? formatPublishedDeadline(sourceTruth, locale, truthLabels) : formatDateTime(value, locale);
  const reviewedCandidateGap = Boolean(analysis?.gaps.some((gap) =>
    ['CONFIRMED', 'CORRECTED'].includes(gap.effective_review_state) &&
    ['PARTNER_FIRM', 'EXPERT'].includes(gap.effective_resolution_category) &&
    ['GAP', 'PARTIAL', 'EVIDENCE_MISSING'].includes(gap.effective_coverage_state),
  ));
  const viableScenario = scenarios.some((scenario) => scenario.latest_revision?.scenario_current && scenario.latest_revision.current_assessment_state === 'VIABLE');
  const approvedViableScenario = scenarios.some((scenario) => {
    const revision = scenario.latest_revision;
    const latestDecision = revision?.decisions.at(-1);
    return revision?.scenario_current && revision.current_assessment_state === 'VIABLE' && latestDecision?.decision === 'APPROVED_FOR_PROPOSAL';
  });
  const noUploadDocuments = pursuit.origin === 'UPLOAD' && documents.length === 0;
  const analysisFailed = Boolean(analysis && (analysis.status === 'FAILED' || analysis.quality_state === 'FAILED'));
  const nextAction = noUploadDocuments ? t('workspace.addDocuments') : hasActiveProcessing ? t('workspace.waitForProcessing') :
    !analysis ? t('workspace.chooseDocuments') : analysisFailed ? t('workspace.analysisFailedAction') :
      ['QUEUED', 'RUNNING'].includes(analysis.status) ? t('workspace.analysisInProgress') :
        analysis.quality_state !== 'READY_FOR_REVIEW' ? t('workspace.analysisNeedsAttention') :
          approvedViableScenario ? t('workspace.prepareEvidencePack') : viableScenario ? t('workspace.reviewApproveTeam') :
            scenarios.length ? t('workspace.completeTeamParticipation') : reviewedCandidateGap ? t('workspace.reviewPartnerExpertOptions') :
              t('workspace.reviewRequirementsGaps');
  const nextActionTab: WorkspaceTab = noUploadDocuments || hasActiveProcessing ? 'documents' :
    !analysis || analysisFailed || ['QUEUED', 'RUNNING'].includes(analysis.status) || analysis.quality_state !== 'READY_FOR_REVIEW' ? 'requirements' :
      approvedViableScenario ? 'proposal' : reviewedCandidateGap || scenarios.length || viableScenario ? 'team' : 'requirements';
  const contextConflicts = context?.field_provenance.filter((item) => item.provenance_state === 'USER_OVERRIDE_CONFLICTS_WITH_SOURCE') || [];
  const contextConfirmed = Boolean(context?.confirmed_fields.length);
  const showContextEditor = !contextConfirmed || contextEditing;
  const reviewableAnalysis = analysis?.status === 'COMPLETED' && analysis.quality_state === 'READY_FOR_REVIEW' ? analysis : lastReviewableAnalysis;
  const requirements = reviewableAnalysis?.requirements || [];
  const submissionItems = requirements.filter(isSubmissionItem).map((item) => item.effective_normalized_requirement);
  const evaluationItems = [
    ...requirements.filter(isEvaluationItem).map((item) => item.effective_normalized_requirement),
    ...(reviewableAnalysis?.positions.flatMap((position) => position.qualification_criteria.map((criterion) => criterion.normalized_text)) || []),
  ];
  const laterItems = requirements.filter(isLaterStage).map((item) => item.effective_normalized_requirement);
  const classified = new Set([...requirements.filter(isSubmissionItem), ...requirements.filter(isEvaluationItem), ...requirements.filter(isLaterStage)].map((item) => item.requirement_id));
  const unclassifiedScope = requirements.filter((item) => !classified.has(item.requirement_id));
  const scopeItems = (unclassifiedScope.length ? unclassifiedScope : requirements.filter((item) => !isLaterStage(item))).map((item) => item.effective_normalized_requirement);
  const project = sourceDetails?.project_context.data;
  const leadership = sourceDetails?.project_leadership.data?.items || [];

  const reviewConflict = (field: string) => {
    setContextEditing(true);
    window.requestAnimationFrame(() => window.document.getElementById(`context-field-${field}`)?.focus());
  };

  return <main className="customer-page pursuit-workspace ds-container-content">
    <PageHeader
      eyebrow={pursuit.origin === 'UPLOAD' ? t('workspace.uploadOrigin') : t('workspace.sourceOrigin')}
      title={title}
      description={t('workspace.description')}
      status={<span data-pursuit-stage={pursuit.stage}><StatusBadge tone={STAGE_TONES[pursuit.stage]}>{t(`stages.${pursuit.stage}`)}</StatusBadge></span>}
      metadata={<>
        {pursuit.reference && <span><BidiText>{pursuit.reference}</BidiText></span>}
        {deadline && <span>{presentDeadline(deadline)}</span>}
        {historicalDeadline && <StatusBadge tone="warning">{t('context.historicalRfp')} · {t('context.deadlinePassed')}</StatusBadge>}
      </>}
      primaryAction={<Button onClick={() => selectTab(nextActionTab)}>{nextAction}</Button>}
      secondaryAction={<ButtonLink href={pursuit.origin === 'UPLOAD' ? '/dashboard/uploaded-tenders' : `/dashboard/tenders/${pursuit.source_tender_id}`} variant="secondary">{t('actions.back')}</ButtonLink>}
    />
    {search.get('duplicates') === '1' && <p className="pursuit-advisory" role="status">{t('upload.duplicateWarning')}</p>}
    {actionError && <p className="pursuit-upload-error" role="alert">{actionError}</p>}

    <nav className="pursuit-workspace-nav" aria-label={t('workspace.navigationLabel')}>
      <div role="tablist" aria-orientation="horizontal" onKeyDown={onTabKeyDown}>
        {WORKSPACE_TABS.map((tab) => {
          const Icon = tab === 'overview' ? LayoutDashboard : tab === 'requirements' ? ClipboardList : tab === 'eoi' ? FileSignature : tab === 'team' ? UsersRound : tab === 'documents' ? FolderOpen : PackageCheck;
          return <button
            key={tab} id={`pursuit-tab-${tab}`} type="button" role="tab"
            aria-selected={activeTab === tab} aria-controls={`pursuit-panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1} onClick={() => selectTab(tab)}
          ><Icon aria-hidden /><span>{t(`workspace.tabs.${tab}`)}</span></button>;
        })}
      </div>
    </nav>

    {activeTab === 'overview' && <section id="pursuit-panel-overview" role="tabpanel" aria-labelledby="pursuit-tab-overview" className="pursuit-workspace-panel">
      <div className="pursuit-overview-grid">
        <Surface className="pursuit-overview-card">
          <div className="pursuit-panel-heading"><div><span className="ds-eyebrow">{t('workspace.overviewEyebrow')}</span><h2 id="pursuit-overview-title">{t('workspace.overview')}</h2></div></div>
          <dl className="pursuit-facts">
            <div><dt>{t('fields.buyer')}</dt><dd><BidiText>{pursuit.buyer || t('values.unknown')}</BidiText></dd></div>
            <div><dt>{t('fields.funder')}</dt><dd><BidiText>{pursuit.declared_funder || t('values.unknown')}</BidiText></dd></div>
            <div><dt>{t('fields.reference')}</dt><dd><BidiText>{pursuit.reference || t('values.unknown')}</BidiText></dd></div>
            <div><dt>{t('fields.deadline')}</dt><dd>{pursuit.external_deadline ? formatDateTime(pursuit.external_deadline, locale) : pursuit.source_deadline ? formatPublishedDeadline(sourceTruth, locale, truthLabels) : t('values.unknown')}{historicalDeadline && <small className="pursuit-historical-deadline">{sourceDeadline && sourceDeadline !== pursuit.external_deadline ? `${formatDateTime(sourceDeadline, locale)} · ` : ''}{t('context.historicalDeadline')}</small>}</dd></div>
            <div><dt>{t('fields.stage')}</dt><dd>{t(`stages.${pursuit.stage}`)}</dd></div>
            <div><dt>{t('workspace.identity')}</dt><dd>{pursuit.origin === 'UPLOAD' ? t('workspace.uploadedTender') : t('workspace.officialSourceTender')}</dd></div>
          </dl>
        </Surface>
        <Surface className="pursuit-next-action" aria-live="polite">
          <ShieldCheck aria-hidden />
          <h2>{t('workspace.nextAction')}</h2>
          <p>{nextAction}</p>
          <Button size="sm" onClick={() => selectTab(nextActionTab)}>{t('workspace.continue')}</Button>
        </Surface>
      </div>

      {pursuit.origin === 'UPLOAD' && <Surface className="pursuit-context-form">
        <header><div><h2>{t('context.title')}</h2><p>{contextConfirmed ? t('context.confirmedHelp') : t('context.help')}</p></div>{contextConfirmed && !contextEditing && <Button type="button" variant="secondary" size="sm" onClick={() => setContextEditing(true)} leadingIcon={<Pencil aria-hidden />}>{t('context.edit')}</Button>}</header>
        {!showContextEditor && <dl className="pursuit-context-summary">
          {context?.field_provenance.filter((item) => item.user_confirmed_value || item.source_value).map((item) => <div key={item.field_name}><dt>{contextFieldLabel(item.field_name)}</dt><dd><BidiText>{item.user_confirmed_value || item.source_value || t('values.unknown')}</BidiText><small>{t(`context.provenance.${item.provenance_state}`)}</small></dd></div>)}
        </dl>}
        {showContextEditor && <>
          <div className="pursuit-context-grid">
            {(['title', 'buyer', 'declared_funder', 'country', 'reference', 'procurement_stage', 'deadline_timezone', 'source_url'] as const).map((field) => <Input
              key={field} id={`context-field-${field}`} type={field === 'source_url' ? 'url' : 'text'} label={t(`fields.${field === 'declared_funder' ? 'funder' : field === 'procurement_stage' ? 'procurementStage' : field === 'deadline_timezone' ? 'timezone' : field === 'source_url' ? 'sourceUrl' : field}`)}
              value={contextValues[field] || ''} onChange={(event) => setContextValues((current) => ({ ...current, [field]: event.target.value }))}
            />)}
            <Input id="context-field-external_deadline" type="datetime-local" label={t('fields.deadline')} value={contextValues.external_deadline || ''} onChange={(event) => setContextValues((current) => ({ ...current, external_deadline: event.target.value }))} />
          </div>
          <div className="ds-row"><Button type="button" onClick={() => void saveContext()} loading={contextBusy}>{t('context.save')}</Button>{contextConfirmed && <Button type="button" variant="ghost" onClick={() => setContextEditing(false)}>{t('actions.cancel')}</Button>}</div>
        </>}
        {contextConflicts.length > 0 && <div className="context-conflicts" role="status"><h3>{t('context.conflicts')}</h3><p>{t('context.conflictsHelp')}</p>{contextConflicts.map((conflict) => <div key={conflict.field_name} className="context-conflict-row"><div><strong>{contextFieldLabel(conflict.field_name)}</strong><p>{t('context.userConfirmed')}: <BidiText>{conflict.user_confirmed_value || t('values.unknown')}</BidiText></p><p>{t('context.sourceIndicates')}: <BidiText>{conflict.source_value || t('values.unknown')}</BidiText></p></div><Button type="button" size="sm" variant="secondary" onClick={() => reviewConflict(conflict.field_name)}>{t('context.reviewConflict')}</Button></div>)}</div>}
        {showContextEditor && context?.suggestions.length ? <div className="context-suggestions"><h3>{t('context.suggestions')}</h3>{context.suggestions.map((suggestion) => <div key={suggestion.suggestion_id}>
          <div><strong>{contextFieldLabel(suggestion.field_name)}</strong><BidiText>{suggestion.suggested_value}</BidiText><small>{t('context.provisional')}</small></div>
          {suggestion.evidence_span && <blockquote><BidiText>{suggestion.evidence_span}</BidiText><cite>{t('context.evidence', { page: suggestion.page_number || t('values.unknown'), version: suggestion.document_version_id.slice(0, 8) })}</cite></blockquote>}
          <Button type="button" size="sm" variant="secondary" onClick={() => setContextValues((current) => ({ ...current, [suggestion.field_name]: suggestion.suggested_value }))}>{t('context.useSuggestion')}</Button>
        </div>)}</div> : null}
      </Surface>}

      {pursuit.origin === 'SOURCE' && <div className="pursuit-source-project-grid">
        <Surface><h2>{t('workspace.projectContext')}</h2>{project ? <dl className="pursuit-context-summary">
          <div><dt>{t('workspace.projectName')}</dt><dd><BidiText>{project.name || t('values.unknown')}</BidiText></dd></div>
          <div><dt>{t('fields.country')}</dt><dd><BidiText>{[project.country, project.region].filter(Boolean).join(' / ') || t('values.unknown')}</BidiText></dd></div>
          {project.project_status && <div><dt>{t('workspace.projectStatus')}</dt><dd><BidiText>{project.project_status.replaceAll('_', ' ')}</BidiText></dd></div>}
        </dl> : <p className="ds-muted">{t('workspace.projectContextUnavailable')}</p>}</Surface>
        <Surface><h2>{t('workspace.projectLeadership')}</h2>{leadership.length ? <ul className="pursuit-leadership-list">{leadership.map((item) => <li key={item.role_id}><strong><BidiText>{item.display_name}</BidiText></strong><span><BidiText>{item.native_role || item.canonical_role}</BidiText></span></li>)}</ul> : <p className="ds-muted">{t('workspace.projectLeadershipUnavailable')}</p>}</Surface>
        {pursuit.source_tender_id && <ButtonLink href={`/dashboard/tenders/${pursuit.source_tender_id}#project-context`} variant="secondary">{t('workspace.openSourceContext')}</ButtonLink>}
      </div>}

      <div className="pursuit-overview-insights">
        <OverviewList title={t('workspace.scope')} items={scopeItems} empty={reviewableAnalysis ? t('workspace.noScopeIdentified') : t('workspace.analyzeForOverview')} />
        <OverviewList title={t('workspace.evaluation')} items={evaluationItems} empty={reviewableAnalysis ? t('workspace.noEvaluationIdentified') : t('workspace.analyzeForOverview')} />
        <OverviewList title={t('workspace.submissionChecklist')} items={submissionItems} empty={reviewableAnalysis ? t('workspace.noSubmissionIdentified') : t('workspace.analyzeForOverview')} />
        <OverviewList title={t('workspace.laterStage')} items={laterItems} empty={reviewableAnalysis ? t('workspace.noLaterStageIdentified') : t('workspace.analyzeForOverview')} />
      </div>
    </section>}

    {activeTab === 'requirements' && <section id="pursuit-panel-requirements" role="tabpanel" aria-labelledby="pursuit-tab-requirements" className="pursuit-workspace-panel">
      <div className="pursuit-panel-heading"><div><span className="ds-eyebrow">{t('workspace.analysisEyebrow')}</span><h2 id="pursuit-requirements-title">{t('workspace.requirements')}</h2><p>{t('workspace.requirementsHelp')}</p></div></div>
      <PursuitRequirements pursuitId={pursuitId} headers={headers} initialReviewableAnalysis={lastReviewableAnalysis} onAnalysisChange={handleAnalysisChange} />
    </section>}

    {activeTab === 'eoi' && <section id="pursuit-panel-eoi" role="tabpanel" aria-labelledby="pursuit-tab-eoi" className="pursuit-workspace-panel">
      <div className="pursuit-panel-heading"><div><span className="ds-eyebrow">{t('workspace.eoiEyebrow')}</span><h2 id="pursuit-eoi-title">{t('workspace.eoi')}</h2><p>{t('workspace.eoiHelp')}</p></div></div>
      <PursuitEoi pursuitId={pursuitId} headers={headers} runId={eoiRunId(analysis, lastReviewableAnalysis)} onOpenRequirements={() => selectTab('requirements')} />
    </section>}

    {activeTab === 'team' && <section id="pursuit-panel-team" role="tabpanel" aria-labelledby="pursuit-tab-team" className="pursuit-workspace-panel">
      <div className="pursuit-panel-heading"><div><span className="ds-eyebrow">{t('workspace.teamEyebrow')}</span><h2 id="pursuit-team-title">{t('workspace.team')}</h2><p>{t('workspace.teamHelp')}</p></div></div>
      <PursuitTeam pursuitId={pursuitId} headers={headers} onScenariosChange={setScenarios} />
    </section>}

    {activeTab === 'documents' && <section id="pursuit-panel-documents" role="tabpanel" aria-labelledby="pursuit-tab-documents" className="pursuit-workspace-panel">
      <div className="pursuit-panel-heading"><div><span className="ds-eyebrow">{t('workspace.documentsEyebrow')}</span><h2 id="pursuit-documents-title">{t('workspace.documents')}</h2><p>{t('workspace.documentsHelp')}</p></div></div>
      <section className="pursuit-document-group" aria-labelledby="official-documents-title"><header><div><h3 id="official-documents-title">{t('documents.official')}</h3><p>{t('documents.officialHelp')}</p></div></header>
        {documentCandidateLoading ? <p className="ds-muted">{t('documents.loading')}</p> : documentCandidate?.source_documents.length ? <div className="private-document-list">{documentCandidate.source_documents.map((document) => <Surface className="private-document-row" key={document.tender_document_id}>
          <FileCheck2 aria-hidden /><div className="private-document-summary"><h4><BidiText>{document.role === 'OFFICIAL_NOTICE' ? t('roles.OFFICIAL_NOTICE') : document.display_name}</BidiText></h4><div className="ds-row ds-muted ds-text-small"><span>{documentRoleLabel(document.role)}</span><span>{document.page_count_known ? t('documents.pages', { count: document.page_count || 0 }) : t('documents.pagesUnknown')}</span><span>{t('documents.officialSource')}</span></div></div>
          <StatusBadge tone={document.parse_ready ? 'success' : 'warning'}>{document.parse_ready ? t('requirements.ready') : t('requirements.notReady')}</StatusBadge>
          {document.source_url && <ButtonLink size="sm" variant="ghost" href={document.source_url}>{t('documents.openSource')}</ButtonLink>}
        </Surface>)}</div> : <EmptyState icon={<FileText aria-hidden />} title={t('documents.noOfficial')} description={t('documents.noOfficialHelp')} />}
      </section>
      <section className="pursuit-document-group" aria-labelledby="your-documents-title"><header><div><h3 id="your-documents-title">{t('documents.yours')}</h3><p>{t('documents.yoursHelp')}</p></div></header>
        {documents.length ? <div className="private-document-list">
          {documents.map((document) => {
            const state = customerProcessingState(document.processing_state) || 'CHECKING';
            return <Surface className="private-document-row" key={document.document_id}>
              <FileCheck2 aria-hidden />
              <div className="private-document-summary"><h4><BidiText>{document.display_name}</BidiText></h4><div className="ds-row ds-muted ds-text-small">
                <select className="ds-control private-role-select" aria-label={t('upload.role')} disabled={actionBusy === document.document_id} value={document.role} onChange={(event) => void correctRole(document, event.target.value as PrivateDocumentRole)}>
                  {DOCUMENT_ROLES.map((role) => <option value={role} key={role}>{t(`roles.${role}`)}</option>)}
                </select><span>{t('documents.version', { version: document.version_number })}</span><span>{formatFileSize(document.byte_size, locale)}</span>
              </div>{document.page_count_known ? <small>{t('documents.pages', { count: document.page_count || 0 })}</small> : <small>{t('documents.pagesUnknown')}</small>}
                <details className="pursuit-technical-details"><summary>{t('requirements.technicalDetails')}</summary><TechnicalText>{document.sha256}</TechnicalText></details>
              </div>
              <StatusBadge tone={state === 'FAILED' ? 'danger' : state === 'PARTIAL' ? 'warning' : state === 'READY' ? 'success' : 'info'}>{t(`processing.${state}`)}</StatusBadge>
              <div className="private-document-actions">
                {state === 'READY' || state === 'PARTIAL' ? <Button type="button" size="sm" variant="ghost" loading={actionBusy === document.document_id} onClick={() => void download(document)} leadingIcon={<Download aria-hidden />}>{t('documents.download')}</Button> : null}
                {document.retry_allowed && <Button type="button" size="sm" variant="secondary" loading={actionBusy === document.document_id} onClick={() => void retry(document)} leadingIcon={<RefreshCw aria-hidden />}>{t('documents.retry')}</Button>}
                <label className="ds-button ds-button-ghost ds-button-sm"><Replace aria-hidden />{t('documents.replace')}<input className="sr-only" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => { const file = event.target.files?.[0]; if (file) void replace(document, file); event.target.value = ''; }} /></label>
              </div>
            </Surface>;
          })}
        </div> : <EmptyState icon={<FileText aria-hidden />} title={t('documents.empty')} description={t('documents.emptyHelp')} action={<ButtonLink href="/dashboard/uploaded-tenders/upload">{t('workspace.addDocuments')}</ButtonLink>} />}
      </section>
    </section>}

    {activeTab === 'proposal' && <section id="pursuit-panel-proposal" role="tabpanel" aria-labelledby="pursuit-tab-proposal" className="pursuit-workspace-panel">
      <div className="pursuit-panel-heading"><div><span className="ds-eyebrow">{t('workspace.proposalEyebrow')}</span><h2 id="pursuit-proposal-title">{t('workspace.proposal')}</h2><p>{t('workspace.proposalHelp')}</p></div></div>
      <PursuitProposal pursuitId={pursuitId} headers={headers} />
    </section>}
  </main>;
}

export default function PursuitWorkspacePage({ params }: { params: Promise<{ pursuitId: string }> }) {
  const { pursuitId } = use(params);
  return <Suspense fallback={null}><PursuitWorkspace pursuitId={pursuitId} /></Suspense>;
}
