"use client";

import { use, useCallback, useEffect, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowLeft, Building2, Calendar, ChartNoAxesColumnIncreasing,
  CircleDollarSign, Download, ExternalLink, FileText, Globe2, Landmark,
  Loader2, MapPin, RefreshCw, ShieldCheck, UserRound, UsersRound,
} from "lucide-react";

import { OpenWorkspaceButton } from "@/components/pursuits/OpenWorkspaceButton";
import { FactChips } from "@/components/tenders/FactChips";
import { SourcePrivateUpload } from "@/components/pursuits/SourcePrivateUpload";
import { TenderEngagementPanel } from "@/components/tenders/TenderEngagementPanel";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Skeleton, StatusBadge } from "@/components/ui/Display";
import { BidiText } from "@/components/i18n/BidiText";
import { api } from "@/lib/api";
import { safeSourceUrl } from "@/lib/sourceUrl";
import { formatCurrency, formatDate, formatDateTime, formatFileSize, formatNumber } from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { EXPLORER_PATH, readExplorerReturnState } from "@/lib/explorerReturnState";
import { leadershipListPresentation } from "@/lib/projectLeadership";
import type {
  DetailsSectionState, TenderDetailsCompetitor, TenderDetailsDocumentItem,
  TenderDetailsResponse, TenderDocumentAcquisitionState,
} from "@/types/tender-details";
import type { Tender } from "@/types/tender";
import { isTenderActionable } from "@/types/tender";

const activeAcquisitionState = (state?: TenderDocumentAcquisitionState) =>
  state === "QUEUED" || state === "DOWNLOADING" || state === "PROCESSING";

const sourceNameFallbacks: Record<string, string> = {
  world_bank: "World Bank",
  adb: "Asian Development Bank",
  giz: "GIZ",
  ebrd: "EBRD",
  uzex: "UZEX",
};

type DocumentSyncStatus = {
  state: string;
  acquisition_state: TenderDocumentAcquisitionState;
  documents_total: number;
  documents_ready: number;
  documents_failed: number;
  documents_processing: number;
  job_id: string | null;
};
type DocumentSyncAccepted = { job_id: string; status: string; progress: number };

function Section({ id, title, icon, description, action, children, className = "" }: {
  id: string; title: string; icon: ReactNode; description?: string;
  action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section id={id} className={`s143-section ${className}`} aria-labelledby={`${id}-title`}>
      <div className="s143-section-heading">
        <div className="s143-heading-main">
          <h2 id={`${id}-title`}>{icon}{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action && <div className="s143-section-action">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function SectionPlaceholder({ title }: { title: string }) {
  return <section className="s143-section s143-placeholder" aria-label={title}>
    <Skeleton className="s143-skeleton-title" /><Skeleton className="s143-skeleton-line" />
    <Skeleton className="s143-skeleton-line" /><Skeleton className="s143-skeleton-line" />
  </section>;
}

function StateMessage({ state, empty, unavailable }: {
  state: DetailsSectionState; empty: string; unavailable: string;
}) {
  return <p className="s143-state" role="status">
    {state === "UNAVAILABLE" ? unavailable : empty}
  </p>;
}

function ProjectLeadershipNames({ items, viewAllLabel, showLessLabel }: {
  items: { role_id: string; display_name: string }[];
  viewAllLabel: string;
  showLessLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const { columns, visibleItems, hasToggle } = leadershipListPresentation(items, expanded);
  return <>
    <ul className="s143-leadership-list" data-columns={columns}>
      {visibleItems.map((role) => <li key={role.role_id}><BidiText>{role.display_name}</BidiText></li>)}
    </ul>
    {hasToggle && <button className="s143-leadership-toggle" type="button" aria-expanded={expanded}
      onClick={() => setExpanded((current) => !current)}>
      {expanded ? showLessLabel : viewAllLabel}
    </button>}
  </>;
}

function competitorOutcome(item: TenderDetailsCompetitor, t: ReturnType<typeof useTranslations<"tenderDetails">>) {
  return item.participation_type === "winner"
    ? t("competitorParticipation.winner")
    : item.participation_type === "participant"
      ? t("competitorParticipation.participant")
      : t("competitorParticipation.similar");
}

export default function TenderDetailPage({ params }: { params: Promise<{ tenderId: string }> }) {
  const { tenderId } = use(params);
  const t = useTranslations("tenderDetails");
  const tExplorer = useTranslations("explorer");
  const tFacts = useTranslations("explorer.facts");
  const copy = useTranslations("tenderDetails.redesign");
  const locale = useLocale() as CustomerSelectableLocale;
  const { displayNameForSource } = useSourceRefresh();
  const displaySource = (source: string) => {
    const catalogName = displayNameForSource(source);
    return catalogName === source ? sourceNameFallbacks[source] ?? source : catalogName;
  };
  const [returnHref, setReturnHref] = useState(EXPLORER_PATH);
  const [tender, setTender] = useState<Tender | null>(null);
  const [details, setDetails] = useState<TenderDetailsResponse | null>(null);
  const [isLoadingTender, setIsLoadingTender] = useState(true);
  const [isLoadingDetails, setIsLoadingDetails] = useState(true);
  const [tenderError, setTenderError] = useState<string | null>(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [openingDocumentId, setOpeningDocumentId] = useState<string | null>(null);
  const [documentActionError, setDocumentActionError] = useState<string | null>(null);
  const [acquisitionBusy, setAcquisitionBusy] = useState(false);

  useEffect(() => {
    const restored = readExplorerReturnState();
    if (restored) setReturnHref(restored.explorerUrl);
  }, []);

  const loadTender = useCallback(async () => {
    setIsLoadingTender(true);
    setTenderError(null);
    try {
      const response = await api.get<Tender>(`/tenders/${tenderId}`);
      setTender(response.data);
    } catch (error: unknown) {
      setTender(null);
      const status = (error as { response?: { status?: number } }).response?.status;
      setTenderError(status === 404 ? "notFound" : status === 401 || status === 403 ? "denied" : "loadFailed");
    } finally { setIsLoadingTender(false); }
  }, [tenderId]);

  const loadDetails = useCallback(async () => {
    setIsLoadingDetails(true);
    setDetailsError(null);
    try {
      const response = await api.get<TenderDetailsResponse>(`/tenders/${tenderId}/details`);
      setDetails(response.data);
    } catch {
      // Retain a previously successful composed projection on a refresh failure.
      setDetailsError("detailsFailed");
    } finally { setIsLoadingDetails(false); }
  }, [tenderId]);

  useEffect(() => { void loadTender(); }, [loadTender]);
  useEffect(() => { void loadDetails(); }, [loadDetails]);

  const acquisitionState = details?.documents.data?.acquisition_state;
  const acquisitionJobId = details?.documents.data?.job_id;
  useEffect(() => {
    if (!activeAcquisitionState(acquisitionState) || !acquisitionJobId) return;
    let cancelled = false;
    let timer: number | null = null;
    let attempts = 0;
    const poll = async () => {
      if (cancelled) return;
      attempts += 1;
      try {
        const response = await api.get<DocumentSyncStatus>(`/tenders/${tenderId}/sync-status`);
        if (cancelled) return;
        if (response.data.job_id !== acquisitionJobId) {
          await loadDetails();
          return;
        }
        setDetails((current) => {
          const data = current?.documents.data;
          if (!current || !data) return current;
          const total = Math.max(data.visible_total_count, response.data.documents_total);
          return { ...current, documents: { ...current.documents, data: {
            ...data, acquisition_state: response.data.acquisition_state,
            job_state: response.data.state,
            ready_count: response.data.documents_ready,
            failed_count: response.data.documents_failed,
            processing_count: response.data.documents_processing,
            remote_count: Math.max(total - response.data.documents_ready - response.data.documents_failed - response.data.documents_processing, 0),
          } } };
        });
        if (!activeAcquisitionState(response.data.acquisition_state)) {
          await loadDetails();
          return;
        }
      } catch { /* A bounded retry may recover a transient read failure. */ }
      if (!cancelled && attempts < 150) timer = window.setTimeout(() => void poll(), 2_000);
    };
    timer = window.setTimeout(() => void poll(), 2_000);
    return () => { cancelled = true; if (timer !== null) window.clearTimeout(timer); };
  }, [acquisitionJobId, acquisitionState, loadDetails, tenderId]);

  const openDocument = useCallback(async (item: TenderDetailsDocumentItem) => {
    if (item.availability !== "AVAILABLE" || item.acquisition_state !== "READY" || openingDocumentId) return;
    setOpeningDocumentId(item.document_id);
    setDocumentActionError(null);
    try {
      const response = await api.get(`/tenders/documents/${item.document_id}/download`, { responseType: "blob" });
      const contentType = (typeof response.headers["content-type"] === "string" ? response.headers["content-type"] : undefined) || item.content_type || "application/octet-stream";
      const url = URL.createObjectURL(new Blob([response.data], { type: contentType }));
      const link = document.createElement("a");
      link.href = url;
      if (contentType.includes("pdf")) { link.target = "_blank"; link.rel = "noreferrer"; }
      else link.download = item.display_name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch { setDocumentActionError(t("documentOpenFailed")); }
    finally { setOpeningDocumentId(null); }
  }, [openingDocumentId, t]);

  const acquireDocuments = useCallback(async () => {
    if (acquisitionBusy) return;
    setAcquisitionBusy(true);
    setDocumentActionError(null);
    try {
      const response = await api.post<DocumentSyncAccepted>(`/tenders/${tenderId}/sync-docs`);
      setDetails((current) => {
        const data = current?.documents.data;
        if (!current || !data) return current;
        return { ...current, documents: { ...current.documents, data: {
          ...data,
          acquisition_state: response.data.status === "IN_PROGRESS"
            ? response.data.progress >= 60 ? "PROCESSING" : "DOWNLOADING" : "QUEUED",
          job_id: response.data.job_id, job_state: response.data.status,
        } } };
      });
    } catch { setDocumentActionError(t("documentAcquisitionFailed")); }
    finally { setAcquisitionBusy(false); }
  }, [acquisitionBusy, t, tenderId]);

  const presentDate = (value: string | null | undefined, includeTime = false) =>
    includeTime ? formatDateTime(value, locale) : formatDate(value, locale);
  const presentFileSize = (value: number | null) =>
    value === null || value < 0 ? t("sizeMissing") : formatFileSize(value, locale);
  const actionable = isTenderActionable(tender);
  const project = details?.project_context.data;
  const leadership = details?.project_leadership.data;
  const projectLeadership = leadership?.items ?? [];
  const documents = details?.documents.data;
  const competitors = details?.competitor_intelligence.data?.groups.flatMap((group) => group.competitors) ?? [];
  const contacts = details?.procurement_contacts.data;
  const compliance = details?.compliance.data;
  const readiness = details?.company_readiness.data;
  const pursuit = details?.pursuit.data;
  const bidPreparation = details?.bid_preparation.data;
  const requirements = details?.requirements.data;
  const canAcquireDocuments = Boolean(documents?.acquisition_supported && actionable &&
    ["AVAILABLE_REMOTE", "PARTIAL", "FAILED"].includes(documents.acquisition_state));

  if (isLoadingTender) return <div className="customer-page s143-page" data-page="tender-details"><SectionPlaceholder title={t("loading")} /></div>;
  if (tenderError || !tender) return <div className="customer-page s143-page" data-page="tender-details">
    <ButtonLink prefetch={false} href={returnHref}><ArrowLeft className="rtl-mirror" aria-hidden="true" />{t("back")}</ButtonLink>
    <p role="alert" className="s143-state s143-error">{tenderError === "notFound" ? copy("notFound") : tenderError === "denied" ? copy("denied") : t("loadFailed")}</p>
  </div>;

  const sourceUrl = safeSourceUrl(tender.source_url);
  const tenderStatus = tender.status === "OPEN" ? tExplorer("status.open")
    : tender.status === "CLOSED" ? tExplorer("status.closed")
    : tender.status === "CANCELLED" ? tExplorer("status.cancelled") : tExplorer("status.unknown");
  const presentMoney = tender.price_display || (tender.budget > 0
    ? formatCurrency(tender.budget, tender.currency, locale, { maximumFractionDigits: 2 })
    : t("notSpecified"));
  const documentStatus = documents?.acquisition_state === "QUEUED" ? t("documentAcquisition.queued")
    : documents?.acquisition_state === "DOWNLOADING" ? t("documentAcquisition.downloading")
    : documents?.acquisition_state === "PROCESSING" ? t("documentAcquisition.processing")
    : documents?.acquisition_state === "READY" ? t("documentAcquisition.ready", { count: formatNumber(documents.ready_count, locale) })
    : documents?.acquisition_state === "PARTIAL" ? t("documentAcquisition.partial", { ready: formatNumber(documents.ready_count, locale), total: formatNumber(documents.visible_total_count, locale), failed: formatNumber(documents.failed_count, locale) })
    : documents?.acquisition_state === "FAILED" ? t("documentAcquisition.failed")
    : documents?.visible_total_count ? t("documentAcquisition.available", { count: formatNumber(documents.visible_total_count, locale) })
    : t("documentAcquisition.availableUnknown");

  return <main className="customer-page s143-page" data-page="tender-details">
    <div className="s143-utility">
      <ButtonLink prefetch={false} href={returnHref} variant="ghost" size="sm">
        <ArrowLeft className="rtl-mirror" aria-hidden="true" />{t("back")}
      </ButtonLink>
      <div className="s143-utility-actions">
        {sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="ds-button ds-button-secondary ds-button-sm">
          <ExternalLink aria-hidden="true" />{t("openSource")}
        </a>}
        <OpenWorkspaceButton tenderId={tender.id} disabled={!pursuit && !actionable} />
      </div>
    </div>

    <header className="s143-identity">
      <div className="s143-kicker">
        <span><Globe2 aria-hidden="true" />{t("source", { source: displaySource(tender.source_system) })}</span>
        <StatusBadge tone={tender.status === "OPEN" ? "success" : "neutral"}>{tenderStatus}</StatusBadge>
        <span dir="ltr" className="technical-ltr">{t("reference", { reference: tender.external_id })}</span>
      </div>
      <h1><BidiText>{tender.title}</BidiText></h1>
      <dl className="s143-facts">
        {[
          { icon: <Building2 aria-hidden="true" />, label: t("procuringEntity"), value: tender.buyer?.trim() || t("notSpecified") },
          { icon: <Calendar aria-hidden="true" />, label: t("deadline"), value: presentDate(tender.deadline) },
          { icon: <CircleDollarSign aria-hidden="true" />, label: t("estimatedValue"), value: presentMoney },
          { icon: <MapPin aria-hidden="true" />, label: t("location"), value: [tender.country, tender.region].filter(Boolean).join(" / ") || t("notSpecified") },
        ].map((fact) => <div key={fact.label}>
          <dt>{fact.icon}<span>{fact.label}</span></dt>
          <dd><BidiText>{fact.value}</BidiText></dd>
        </div>)}
      </dl>
    </header>

    {detailsError && <div role="alert" className="s143-error s143-retry">
      <span>{t("detailsFailed")}</span>
      <Button variant="secondary" size="sm" type="button" onClick={() => void loadDetails()}>
        <RefreshCw aria-hidden="true" />{t("retryDetails")}
      </Button>
    </div>}

    {!details && isLoadingDetails ? <>
      <div className="s143-decision-grid" aria-label={t("detailsLoading")}>
        <SectionPlaceholder title={t("sections.pursuit")} />
        <SectionPlaceholder title={t("complianceTitle")} />
        <SectionPlaceholder title={tFacts("label")} />
      </div>
      <div className="s143-project-grid">
        <SectionPlaceholder title={t("projectTitle")} />
        <SectionPlaceholder title={t("leadership")} />
      </div>
      <SectionPlaceholder title={t("tenderDocuments")} />
      <SectionPlaceholder title={t("competitorsTitle")} />
      <SectionPlaceholder title={t("contactsTitle")} />
      <SectionPlaceholder title={t("bidTitle")} />
    </> : null}

    {details && <>
      <div className="s143-decision-grid">
        <TenderEngagementPanel
          decisionCard tenderId={tender.id} proposalContext workspaceEntry
          engagementData={pursuit} proposalIdData={bidPreparation?.proposal_id ?? null}
          loadingData={false} canStartNew={actionable} onRefresh={loadDetails}
        />

        <section className="s143-decision-card" aria-labelledby="s143-compliance-title">
          <h2 id="s143-compliance-title"><ShieldCheck aria-hidden="true" />{t("complianceTitle")}</h2>
          <dl className="s143-decision-list">
            <div><dt>{t("compliance")}</dt><dd>
              {compliance ? <><span>{compliance.execution_state === "FAILED" ? t("complianceFailed") : compliance.compliance_completeness === "PARTIAL" ? t("compliancePartial") : compliance.version_origin === "LEGACY_BACKFILL" ? t("complianceLegacy") : compliance.decision_label || t("complianceAvailable")}</span>
                {compliance.key_issue_count !== null && <small>{t("keyIssues")}: {formatNumber(compliance.key_issue_count, locale)}</small>}</>
                : details.compliance.state === "UNAVAILABLE" ? t("complianceUnavailable") : t("complianceEmpty")}
            </dd></div>
            <div><dt>{t("readiness")}</dt><dd>{readiness
              ? <>{t("availableCount", { count: readiness.readiness_documents_available })} / {t("totalCount", { count: readiness.readiness_documents_total })}</>
              : details.company_readiness.state === "UNAVAILABLE" ? t("readinessUnavailable") : t("readinessEmpty")}</dd></div>
            {readiness && <div><dt>{t("missingEvidence")}</dt><dd>{formatNumber(readiness.readiness_documents_missing, locale)}</dd></div>}
          </dl>
          <div className="s143-decision-links">
            <ButtonLink prefetch={false} href="/dashboard/readiness-vault" size="sm">{t("openReadiness")}</ButtonLink>
          </div>
        </section>

        <section className="s143-decision-card" aria-labelledby="s143-recommendation-title">
          <h2 id="s143-recommendation-title"><ChartNoAxesColumnIncreasing aria-hidden="true" />{tFacts("label")}</h2>
          <FactChips tender={tender} profileMatch={details.profile_match} />
          <dl className="s143-classification">
            <div><dt>{t("category")}</dt><dd><BidiText>{tender.procurement_category || tender.category || t("notSpecified")}</BidiText></dd></div>
            <div><dt>{t("method")}</dt><dd><BidiText>{tender.procurement_method || t("notSpecified")}</BidiText></dd></div>
            <div><dt>{t("noticeType")}</dt><dd><BidiText>{tender.notice_type || t("notSpecified")}</BidiText></dd></div>
          </dl>
        </section>
      </div>

      <div className="s143-project-grid"
        data-balanced={projectLeadership.length <= 6 ? "true" : "false"}>
        <Section id="project-context" title={t("projectTitle")} icon={<FileText aria-hidden="true" />}>
          {project ? <>
            {details.project_context.state === "UNAVAILABLE" && <p className="s143-state">{t("projectUnavailable")}</p>}
            {["queued", "running", "never_attempted"].includes(project.enrichment_state) && <p className="s143-state">{t("projectPreparing")}</p>}
            <dl className="s143-label-value">
              <div><dt>{t("s143.projectName")}</dt><dd><BidiText>{project.name || t("projectName", { source: displaySource(project.source_system) })}</BidiText></dd></div>
              <div><dt>{t("countryRegion")}</dt><dd><BidiText>{[project.country, project.region].filter(Boolean).join(" / ") || t("notReported")}</BidiText></dd></div>
              {project.project_status && <div><dt>{t("s143.projectStatus")}</dt><dd><BidiText>{project.project_status}</BidiText></dd></div>}
              {project.approval_date && <div><dt>{t("projectApproval")}</dt><dd>{presentDate(project.approval_date)}</dd></div>}
              {project.closing_date && <div><dt>{t("projectClosing")}</dt><dd>{presentDate(project.closing_date)}</dd></div>}
            </dl>
          </> : <StateMessage state={details.project_context.state} empty={t("projectLinkedEmpty")} unavailable={t("projectUnavailable")} />}
        </Section>

        <Section id="project-leadership" title={t("leadership")} icon={<UsersRound aria-hidden="true" />}
          description={t("s143.leadershipSource")}>
          {projectLeadership.length ? <ProjectLeadershipNames key={tender.id} items={projectLeadership}
            viewAllLabel={t("s143.leadershipViewAll", { count: formatNumber(projectLeadership.length, locale) })}
            showLessLabel={t("s143.leadershipShowLess")} />
            : <StateMessage state={details.project_leadership.state} empty={t("leadershipEmpty")} unavailable={t("projectUnavailable")} />}
          {leadership?.truncated && <p className="s143-note">{t("s143.leadershipTruncated", { count: formatNumber(leadership.returned_count, locale), total: formatNumber(leadership.total_count, locale) })}</p>}
        </Section>
      </div>

      <Section id="tender-documents" title={t("officialSourceDocuments")} icon={<FileText aria-hidden="true" />}
        action={canAcquireDocuments ? <Button variant="secondary" size="sm" type="button" loading={acquisitionBusy} onClick={() => void acquireDocuments()}>
          <Download aria-hidden="true" />{documents?.acquisition_state === "AVAILABLE_REMOTE" ? t("documentAcquisition.download") : t("documentAcquisition.retry")}
        </Button> : undefined}>
        {documents?.acquisition_supported && <p role="status" className="s143-document-status">{documentStatus}</p>}
        {documentActionError && <p role="alert" className="s143-state s143-error">{documentActionError}</p>}
        {documents?.official_notice && <div className="s143-official-notice">
          <FileText aria-hidden="true" />
          <div><strong>{t("officialNotice.title")}</strong><p className="s143-note">{t("officialNotice.help")}</p></div>
          {safeSourceUrl(documents.official_notice.source_url) && <a href={safeSourceUrl(documents.official_notice.source_url) ?? undefined} target="_blank" rel="noopener noreferrer" className="ds-button ds-button-ghost ds-button-sm" aria-label={`${t("officialNotice.openAtSource")}: ${t("officialNotice.title")}`}>
            <ExternalLink aria-hidden="true" />{t("officialNotice.openAtSource")}
          </a>}
        </div>}
        {documents?.items.length ? <div className="s143-table-wrap">
          <table className="s143-table s143-document-table">
            <thead><tr><th scope="col">{t("s143.name")}</th><th scope="col">{t("s143.type")}</th><th scope="col">{t("s143.size")}</th><th scope="col">{t("s143.download")}</th></tr></thead>
            <tbody>{documents.items.map((item) => {
              const ready = item.availability === "AVAILABLE" && item.acquisition_state === "READY";
              return <tr key={item.document_id}>
                <td data-label={t("s143.name")}><BidiText>{item.display_name}</BidiText></td>
                <td data-label={t("s143.type")}><BidiText>{item.document_type}</BidiText></td>
                <td data-label={t("s143.size")}>{presentFileSize(item.file_size)}</td>
                <td data-label={t("s143.download")}>
                  {ready ? <Button variant="ghost" size="sm" type="button" disabled={openingDocumentId !== null} onClick={() => void openDocument(item)} aria-label={`${t("openDocument")}: ${item.display_name}`}>
                    {openingDocumentId === item.document_id ? <Loader2 aria-hidden="true" className="animate-spin" /> : <Download aria-hidden="true" />}
                    {openingDocumentId === item.document_id ? t("opening") : t("s143.download")}
                  </Button> : <span className="s143-document-state">{t(`documentAcquisition.states.${item.acquisition_state}`)}</span>}
                </td>
              </tr>;
            })}</tbody>
          </table>
        </div> : documents?.official_notice ? null : <StateMessage state={details.documents.state} empty={t("documentsEmpty")} unavailable={t("documentsUnavailable")} />}
        {documents?.truncated && <p className="s143-note">{t("documentsTruncated", { count: documents.visible_total_count - documents.returned_count })}</p>}
        <SourcePrivateUpload tenderId={tender.id} />
        <details className="s143-disclosure">
          <summary>{t("importantRequirements")}</summary>
          {requirements?.items.length ? <ul>{requirements.items.map((item, index) => <li key={`${item.label}-${index}`}>
            <BidiText>{item.label}</BidiText>
            <small>{t("aiRequirement")}</small>
            {(item.document_name || item.section || item.page) && <small><BidiText>{[item.document_name, item.section, item.page].filter(Boolean).join(" · ")}</BidiText></small>}
          </li>)}</ul> : <StateMessage state={details.requirements.state} empty={t("requirementsEmpty")} unavailable={t("requirementsUnavailable")} />}
          {requirements?.truncated && <p className="s143-note">{t("requirementsTruncated", { returned: formatNumber(requirements.returned_count, locale), total: formatNumber(requirements.total_count, locale) })}</p>}
        </details>
      </Section>

      <Section id="competitors" title={t("competitorsTitle")} icon={<ChartNoAxesColumnIncreasing aria-hidden="true" />} description={t("competitorsHelp")}>
        {competitors.length ? <div className="s143-table-wrap">
          <table className="s143-table s143-competitor-table">
            <thead><tr><th scope="col">{t("s143.company")}</th><th scope="col">{t("s143.historicalOutcome")}</th><th scope="col">{t("s143.whyRelevant")}</th><th scope="col">{t("s143.source")}</th><th scope="col">{t("s143.regionCountry")}</th><th scope="col">{t("competitorEvidence")}</th></tr></thead>
            <tbody>{competitors.map((item) => {
              const evidenceUrl = safeSourceUrl(item.evidence_source);
              return <tr key={`${item.service_category}-${item.company_name}-${item.related_tender_id || item.source}`}>
                <td data-label={t("s143.company")}><BidiText>{item.company_name}</BidiText></td>
                <td data-label={t("s143.historicalOutcome")}>{competitorOutcome(item, t)}</td>
                <td data-label={t("s143.whyRelevant")}><BidiText>{item.reason}</BidiText></td>
                <td data-label={t("s143.source")}><BidiText>{displaySource(item.source)}</BidiText></td>
                <td data-label={t("s143.regionCountry")}><BidiText>{item.country || t("notReported")}</BidiText></td>
                <td data-label={t("competitorEvidence")}>{evidenceUrl ? <a href={evidenceUrl} target="_blank" rel="noopener noreferrer" className="ds-button ds-button-secondary ds-button-sm" aria-label={`${t("competitorEvidence")}: ${item.company_name}`}><ExternalLink aria-hidden="true" />{t("competitorEvidence")}</a> : t("competitorEvidenceUnavailable")}</td>
              </tr>;
            })}</tbody>
          </table>
        </div> : <StateMessage state={details.competitor_intelligence.state} empty={t("competitorsEmpty")} unavailable={t("competitorsUnavailable")} />}
      </Section>

      <Section id="contacts" title={t("contactsTitle")} icon={<UserRound aria-hidden="true" />}>
        {contacts ? <div className="s143-contact-grid">
          <dl className="s143-label-value">
            <div><dt>{t("procurementContact")}</dt><dd><BidiText>{contacts.contact_person || t("notProvided")}</BidiText></dd></div>
            <div><dt>{t("email")}</dt><dd dir="ltr" className="technical-ltr">{contacts.email || t("notProvided")}</dd></div>
            <div><dt>{t("phone")}</dt><dd dir="ltr" className="technical-ltr">{contacts.phone || t("notProvided")}</dd></div>
            <div><dt>{t("s143.address")}</dt><dd><BidiText>{contacts.address || t("notProvided")}</BidiText></dd></div>
          </dl>
          <dl className="s143-label-value">
            <div><dt>{t("submissionMethod")}</dt><dd><BidiText>{contacts.submission_method || t("notProvided")}</BidiText></dd></div>
            <div><dt>{t("submissionDeadline")}</dt><dd>{presentDate(contacts.submission_deadline)}</dd></div>
            <div><dt>{t("questionDeadline")}</dt><dd>{presentDate(contacts.question_deadline)}</dd></div>
            <div><dt>{t("procedure")}</dt><dd><BidiText>{contacts.procedure_type || t("notProvided")}</BidiText></dd></div>
          </dl>
        </div> : <StateMessage state={details.procurement_contacts.state} empty={t("contactsEmpty")} unavailable={t("contactsUnavailable")} />}
      </Section>

      <Section id="bid-preparation" title={t("bidTitle")} icon={<Landmark aria-hidden="true" />} className="s143-bid-strip"
        action={<OpenWorkspaceButton tenderId={tender.id} variant="secondary" disabled={!pursuit && !actionable} />}>
        <p>{bidPreparation ? t("preparationStatus", { status: bidPreparation.proposal_status }) : t("bidNotStartedHelp")}</p>
      </Section>
    </>}
  </main>;
}
