"use client";

import { useState, useEffect } from "react";
import {
  FileText,
  Globe2,
  CalendarDays,
  MapPin,
  ArrowRight,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useCollectionOffset } from "@/lib/useCollectionOffset";
import { formatCurrency, formatDate } from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import type { BidPreparationArtifact } from "@/types/bid-preparation";
import { PrepareBidButton } from "@/components/bid-preparation/PrepareBidButton";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { BidiText } from "@/components/i18n/BidiText";
import {
  EmptyState,
  PageHeader,
  PageSkeleton,
  Surface,
  StatusBadge,
} from "@/components/ui/Display";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Pagination } from "@/components/ui/Navigation";
import { Alert } from "@/components/ui/Feedback";

export default function BidPreparationPage() {
  const t = useTranslations("bidPreparation");
  const copy = useTranslations("bidPreparation.redesign");
  const tExplorer = useTranslations("explorer");
  const tMy = useTranslations("myTenders");
  const locale = useLocale() as CustomerSelectableLocale;
  const { displayNameForSource } = useSourceRefresh();
  const [offset, setOffset] = useCollectionOffset();
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [proposals, setProposals] = useState<BidPreparationArtifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<"denied" | "failed" | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const fetchProposals = () => {
      setIsLoading(true);
      setError(null);
      api
        .get("/proposals", { params: { limit: 25, offset } })
        .then((response) => {
          if (cancelled) return;
          setHasMore(response.headers["x-has-more"] === "true");
          setTotal(
            Number(response.headers["x-total-count"] ?? response.data.length),
          );
          setProposals(response.data);
        })
        .catch((requestError: { response?: { status?: number } }) => {
          if (!cancelled)
            setError(
              [401, 403].includes(requestError.response?.status ?? 0)
                ? "denied"
                : "failed",
            );
        })
        .finally(() => {
          if (!cancelled) setIsLoading(false);
        });
    };
    fetchProposals();
    return () => {
      cancelled = true;
    };
  }, [offset, retry]);

  const proposalStatus = (status: string) =>
    status === "DRAFT"
      ? t("status.draft")
      : status === "GENERATING"
        ? t("status.generating")
        : status === "COMPLETED"
          ? t("status.completed")
          : status === "SUBMITTED"
            ? t("status.submitted")
            : t("status.unknown");
  const tenderStatus = (status: string) =>
    status === "OPEN"
      ? tExplorer("status.open")
      : status === "CLOSED"
        ? tExplorer("status.closed")
        : status === "CANCELLED"
          ? tExplorer("status.cancelled")
          : tExplorer("status.unknown");
  const engagementStatus = (status: string) =>
    status === "SAVED"
      ? tMy("statuses.saved")
      : status === "EVALUATING"
        ? tMy("statuses.evaluating")
        : status === "PREPARING"
          ? tMy("statuses.preparing")
          : status === "SUBMITTED"
            ? tMy("statuses.submitted")
            : status === "WON"
              ? tMy("statuses.won")
              : status === "LOST"
                ? tMy("statuses.lost")
                : tMy("statuses.dismissed");
  const money = (value: number, currency: string) =>
    formatCurrency(value, currency, locale, { maximumFractionDigits: 1 });
  return (
    <div className="customer-page ds-stack">
      <PageHeader
        eyebrow={t("proposal")}
        title={t("title")}
        description={copy("description")}
        status={
          !isLoading && !error ? (
            <StatusBadge>{copy("total", { count: total })}</StatusBadge>
          ) : undefined
        }
        primaryAction={
          <ButtonLink href="/dashboard/tenders">
            {t("browse")}
            <ArrowRight className="rtl-mirror" aria-hidden />
          </ButtonLink>
        }
      />
      {isLoading ? (
        <PageSkeleton label={t("loading")} />
      ) : error ? (
        <Alert
          tone="danger"
          title={error === "denied" ? copy("denied") : t("loadFailed")}
          action={
            <Button variant="secondary" onClick={() => setRetry((v) => v + 1)}>
              {copy("retry")}
            </Button>
          }
        />
      ) : !proposals.length ? (
        <EmptyState
          icon={<FileText aria-hidden />}
          title={offset > 0 && total > 0 ? copy("pageEmpty") : t("emptyTitle")}
          description={t("emptyHelp")}
          action={
            <ButtonLink href="/dashboard/tenders">{t("browse")}</ButtonLink>
          }
        />
      ) : (
        <div className="ds-stack" aria-label={t("title")}>
          {proposals.map((proposal) => (
            <Surface
              key={proposal.id}
              className="pipeline-row proposal-row"
              role="article"
              aria-label={proposal.tender_title}
              data-proposal-id={proposal.id}
            >
              <div className="pipeline-source" aria-hidden>
                <Globe2 />
              </div>
              <div className="pipeline-summary ds-stack">
                <div className="ds-row">
                  <StatusBadge
                    tone={
                      proposal.status === "COMPLETED"
                        ? "success"
                        : proposal.status === "GENERATING"
                          ? "info"
                          : "neutral"
                    }
                  >
                    {t("preparationStatus", {
                      status: proposalStatus(proposal.status),
                    })}
                  </StatusBadge>
                  <StatusBadge
                    tone={
                      proposal.tender_status === "OPEN" ? "success" : "neutral"
                    }
                  >
                    {t("tenderStatus", {
                      status: tenderStatus(proposal.tender_status),
                    })}
                  </StatusBadge>
                  {proposal.engagement_status && (
                    <StatusBadge>
                      {t("engagement", {
                        status: engagementStatus(proposal.engagement_status),
                      })}
                    </StatusBadge>
                  )}
                </div>
                <h2>
                  <BidiText>{proposal.tender_title}</BidiText>
                </h2>
                <div className="ds-row ds-muted ds-text-small">
                  <BidiText>
                    {displayNameForSource(proposal.tender_source_system)}
                  </BidiText>
                  {proposal.tender_region && (
                    <>
                      <MapPin aria-hidden />
                      <BidiText>{proposal.tender_region}</BidiText>
                    </>
                  )}
                </div>
                <span className="ds-muted ds-text-small">
                  {t("created", {
                    date: formatDate(proposal.created_at, locale),
                  })}
                </span>
              </div>
              <dl className="pipeline-facts">
                <div>
                  <dt>{t("value")}</dt>
                  <dd className="ds-numeric">
                    {money(proposal.tender_budget, proposal.tender_currency)}
                  </dd>
                </div>
                <div>
                  <dt>{copy("price")}</dt>
                  <dd className="ds-numeric">
                    {typeof proposal.structured_data?.our_price === "number" &&
                    Number.isFinite(proposal.structured_data.our_price)
                      ? money(
                          proposal.structured_data.our_price,
                          proposal.currency,
                        )
                      : copy("notSet")}
                  </dd>
                </div>
                <div>
                  <dt>{t("aiConfidence")}</dt>
                  <dd className="ds-numeric">
                    {Number.isFinite(proposal.ai_confidence_score)
                      ? `${proposal.ai_confidence_score}%`
                      : copy("notSet")}
                  </dd>
                </div>
                <div>
                  <dt>
                    <CalendarDays aria-hidden />
                    {copy("deadline")}
                  </dt>
                  <dd>
                    {proposal.tender_deadline
                      ? formatDate(proposal.tender_deadline, locale)
                      : copy("notSet")}
                  </dd>
                </div>
              </dl>
              <div className="pipeline-actions">
                <ButtonLink
                  size="sm"
                  href={`/dashboard/bid-preparation/${proposal.id}`}
                >
                  {proposal.status === "DRAFT" ? t("continue") : t("open")}
                  <ArrowRight className="rtl-mirror" aria-hidden />
                </ButtonLink>
                <ButtonLink
                  variant="secondary"
                  size="sm"
                  href={`/dashboard/tenders/${proposal.tender_id}`}
                >
                  {tMy("openTender")}
                </ButtonLink>
                {!proposal.engagement_status && (
                  <PrepareBidButton foundation proposalId={proposal.id} />
                )}
              </div>
              {proposal.status === "GENERATING" && (
                <div className="pipeline-progress">
                  <Alert title={t("status.generating")}>
                    {copy("generating")}
                  </Alert>
                </div>
              )}
            </Surface>
          ))}
        </div>
      )}
      {!isLoading && !error && (total > 0 || offset > 0) && (
        <Pagination
          label={copy("pagination")}
          previousLabel={tMy("previous")}
          nextLabel={tMy("next")}
          hasPrevious={offset > 0}
          hasNext={hasMore}
          onPrevious={() => setOffset(Math.max(0, offset - 25))}
          onNext={() => setOffset(offset + 25)}
        >
          <span role="status">
            {copy("page", { page: Math.floor(offset / 25) + 1, count: total })}
          </span>
        </Pagination>
      )}
    </div>
  );
}
