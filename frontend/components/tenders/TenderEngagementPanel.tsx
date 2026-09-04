"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bookmark, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { PrepareBidButton } from "@/components/bid-preparation/PrepareBidButton";
import { EngagementWorkflowActions } from "@/components/tenders/EngagementWorkflowActions";
import { api } from "@/lib/api";
import {
  engagementStatusClasses,
  type SaveToMyTendersResponse,
  type TenderEngagementActionContext,
  type TenderScopedEngagementResponse,
} from "@/types/engagement";

interface TenderEngagementPanelProps {
  tenderId: string;
  proposalContext?: boolean;
  engagementData?: TenderEngagementActionContext | null;
  proposalIdData?: string | null;
  loadingData?: boolean;
  canStartNew?: boolean;
  onRefresh?: () => void | Promise<void>;
}

export function TenderEngagementPanel({
  tenderId,
  proposalContext = false,
  engagementData,
  proposalIdData,
  loadingData = false,
  canStartNew = true,
  onRefresh,
}: TenderEngagementPanelProps) {
  const t = useTranslations("myTenders");
  const controlled = engagementData !== undefined;
  const [engagement, setEngagement] =
    useState<TenderEngagementActionContext | null>(engagementData ?? null);
  const [proposalId, setProposalId] = useState<string | null>(
    proposalIdData ?? null,
  );
  const [loading, setLoading] = useState(!controlled);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (controlled) {
      await onRefresh?.();
      return;
    }
    try {
      const response = await api.get<TenderScopedEngagementResponse>(
        `/tenders/${tenderId}/engagement`,
      );
      setEngagement(response.data.engagement);
      setProposalId(response.data.proposal_id);
      setError(null);
    } catch {
      setError(t("panel.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [controlled, onRefresh, t, tenderId]);

  useEffect(() => {
    if (controlled) {
      setEngagement(engagementData ?? null);
      setProposalId(proposalIdData ?? null);
      setLoading(loadingData);
      return;
    }
    void load();
  }, [controlled, engagementData, load, loadingData, proposalIdData]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const response = await api.post<SaveToMyTendersResponse>(
        `/tenders/${tenderId}/engagement`,
      );
      setEngagement(response.data.engagement);
      await onRefresh?.();
    } catch (requestError: unknown) {
      const status = (requestError as { response?: { status?: number } })
        .response?.status;
      if (status === 409) {
        setError(t("panel.changed"));
        await load();
      } else {
        setError(t("panel.saveFailed"));
      }
    } finally {
      setSaving(false);
    }
  };
  const engagementLabel =
    engagement?.engagement_status === "SAVED"
      ? t("statuses.saved")
      : engagement?.engagement_status === "EVALUATING"
        ? t("statuses.evaluating")
        : engagement?.engagement_status === "PREPARING"
          ? t("statuses.preparing")
          : engagement?.engagement_status === "SUBMITTED"
            ? t("statuses.submitted")
            : engagement?.engagement_status === "WON"
              ? t("statuses.won")
              : engagement?.engagement_status === "LOST"
                ? t("statuses.lost")
                : t("statuses.dismissed");

  return (
    <section
      aria-labelledby="pursuit-status-heading"
      className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
    >
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
        <div>
          <h2
            id="pursuit-status-heading"
            className="text-sm font-semibold text-white"
          >
            {t("panel.title")}
          </h2>
          {loading ? (
            <p
              role="status"
              className="mt-2 flex items-center gap-2 text-sm text-zinc-400"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("panel.loading")}
            </p>
          ) : engagement ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span
                className={`rounded-md border px-2 py-1 text-xs font-semibold ${engagementStatusClasses(engagement.engagement_status)}`}
              >
                {t("panel.status", { status: engagementLabel })}
              </span>
            </div>
          ) : (
            <p className="mt-2 text-sm text-zinc-400">{t("panel.none")}</p>
          )}
        </div>
        {!loading && engagement ? (
          <EngagementWorkflowActions
            engagement={engagement}
            tenderId={tenderId}
            proposalId={proposalId}
            onChanged={setEngagement}
            onRefresh={load}
          />
        ) : !loading && proposalContext && proposalId ? (
          <PrepareBidButton proposalId={proposalId} />
        ) : !loading && canStartNew ? (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs font-semibold text-sky-100 hover:bg-sky-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Bookmark className="h-4 w-4" />
              )}
              {saving ? t("panel.saving") : t("panel.save")}
            </button>
            <PrepareBidButton tenderId={tenderId} />
          </div>
        ) : !loading ? (
          <p className="text-xs text-zinc-500">{t("panel.noAction")}</p>
        ) : null}
      </div>
      <div className="mt-3 flex gap-4 text-xs">
        <Link
          href="/dashboard/my-tenders"
          className="text-sky-300 hover:text-sky-200"
        >
          {t("panel.openMy")}
        </Link>
        {proposalId ? (
          <Link
            href={`/dashboard/bid-preparation/${proposalId}`}
            className="text-indigo-300 hover:text-indigo-200"
          >
            {t("panel.openBid")}
          </Link>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-red-300">
          {error}
        </p>
      ) : null}
    </section>
  );
}
