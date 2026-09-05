"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { PrepareBidButton } from "@/components/bid-preparation/PrepareBidButton";
import { api } from "@/lib/api";
import type {
  EngagementAction,
  SaveToMyTendersResponse,
  TenderEngagementActionContext,
  TenderEngagementActionResponse,
  TenderEngagementSummary,
} from "@/types/engagement";

type CommandAction = Exclude<EngagementAction, "SAVE" | "PREPARE_BID">;

interface ActionDefinition {
  action: CommandAction;
  path: string;
  tone?: "primary" | "danger" | "secondary";
}

const ACTIONS: Record<CommandAction, ActionDefinition> = {
  EVALUATE: { action: "EVALUATE", path: "evaluate", tone: "primary" },
  MARK_SUBMITTED: {
    action: "MARK_SUBMITTED",
    path: "mark-submitted",
    tone: "primary",
  },
  RECORD_WON: {
    action: "RECORD_WON",
    path: "mark-won",
    tone: "primary",
  },
  RECORD_LOST: {
    action: "RECORD_LOST",
    path: "mark-lost",
    tone: "secondary",
  },
  DISMISS: {
    action: "DISMISS",
    path: "dismiss",
    tone: "danger",
  },
  CORRECT_TO_PREPARING: {
    action: "CORRECT_TO_PREPARING",
    path: "correct-to-preparing",
    tone: "secondary",
  },
  CORRECT_TO_SUBMITTED: {
    action: "CORRECT_TO_SUBMITTED",
    path: "correct-to-submitted",
    tone: "secondary",
  },
  CORRECT_TO_WON: {
    action: "CORRECT_TO_WON",
    path: "correct-to-won",
    tone: "secondary",
  },
  CORRECT_TO_LOST: {
    action: "CORRECT_TO_LOST",
    path: "correct-to-lost",
    tone: "secondary",
  },
};

const buttonClasses = (tone: ActionDefinition["tone"]) => {
  if (tone === "danger")
    return "border-red-500/40 text-red-200 hover:bg-red-500/10";
  if (tone === "primary")
    return "border-indigo-500 bg-indigo-600 text-white hover:bg-indigo-500";
  return "border-zinc-700 text-zinc-200 hover:border-indigo-500 hover:text-indigo-200";
};

export function EngagementWorkflowActions({
  engagement,
  tenderId,
  proposalId,
  onChanged,
  onRefresh,
}: {
  engagement: TenderEngagementActionContext;
  tenderId: string;
  proposalId?: string | null;
  onChanged?: (engagement: TenderEngagementSummary) => void;
  onRefresh?: () => void | Promise<void>;
}) {
  const t = useTranslations("myTenders.actions");
  const [pending, setPending] = useState<ActionDefinition | null>(null);
  const [submitting, setSubmitting] = useState<CommandAction | "SAVE" | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!pending) return;
    cancelRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) setPending(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [pending, submitting]);

  const invoke = async (definition: ActionDefinition) => {
    setSubmitting(definition.action);
    setError(null);
    try {
      const response = await api.post<TenderEngagementActionResponse>(
        `/my-tenders/${engagement.engagement_id}/actions/${definition.path}`,
        { expected_status: engagement.engagement_status },
      );
      setPending(null);
      onChanged?.(response.data.engagement);
      await onRefresh?.();
    } catch (requestError: unknown) {
      const response = (
        requestError as {
          response?: { status?: number; data?: { detail?: string } };
        }
      ).response;
      if (response?.status === 409) {
        setPending(null);
        setError(t("statusChanged"));
        await onRefresh?.();
      } else if (response?.status === 404) {
        setPending(null);
        setError(t("missing"));
        await onRefresh?.();
      } else {
        setError(t("updateFailed"));
      }
    } finally {
      setSubmitting(null);
    }
  };

  const saveAgain = async () => {
    setSubmitting("SAVE");
    setError(null);
    try {
      const response = await api.post<SaveToMyTendersResponse>(
        `/tenders/${tenderId}/engagement`,
      );
      onChanged?.(response.data.engagement);
      await onRefresh?.();
    } catch (requestError: unknown) {
      const response = (requestError as { response?: { status?: number } })
        .response;
      if (response?.status === 409) {
        setError(t("statusChanged"));
        await onRefresh?.();
      } else {
        setError(t("resumeFailed"));
      }
    } finally {
      setSubmitting(null);
    }
  };

  const request = (definition: ActionDefinition) => {
    const needsPreparingDismissConfirmation =
      definition.action === "DISMISS" &&
      engagement.engagement_status === "PREPARING";
    if (
      needsPreparingDismissConfirmation ||
      [
        "MARK_SUBMITTED",
        "RECORD_WON",
        "RECORD_LOST",
        "CORRECT_TO_PREPARING",
        "CORRECT_TO_SUBMITTED",
        "CORRECT_TO_WON",
        "CORRECT_TO_LOST",
      ].includes(definition.action)
    ) {
      setPending(definition);
    } else {
      void invoke(definition);
    }
  };

  const available = engagement.allowed_actions;
  const normal = (
    [
      "EVALUATE",
      "MARK_SUBMITTED",
      "RECORD_WON",
      "RECORD_LOST",
    ] as CommandAction[]
  ).filter((action) => available.includes(action));
  const secondary = (
    [
      "DISMISS",
      "CORRECT_TO_PREPARING",
      "CORRECT_TO_SUBMITTED",
      "CORRECT_TO_WON",
      "CORRECT_TO_LOST",
    ] as CommandAction[]
  ).filter((action) => available.includes(action));
  const actionLabel = (action: CommandAction) =>
    action === "EVALUATE"
      ? t("evaluate")
      : action === "MARK_SUBMITTED"
        ? t("markSubmitted")
        : action === "RECORD_WON"
          ? t("recordWon")
          : action === "RECORD_LOST"
            ? t("recordLost")
            : action === "DISMISS"
              ? t("dismiss")
              : action === "CORRECT_TO_PREPARING"
                ? t("correctPreparing")
                : action === "CORRECT_TO_SUBMITTED"
                  ? t("correctSubmitted")
                  : action === "CORRECT_TO_WON"
                    ? t("correctWon")
                    : t("correctLost");
  const confirmationTitle = (action: CommandAction) =>
    action === "MARK_SUBMITTED"
      ? t("submittedTitle")
      : action === "RECORD_WON"
        ? t("wonTitle")
        : action === "RECORD_LOST"
          ? t("lostTitle")
          : action === "DISMISS"
            ? t("dismissPreparingTitle")
            : action === "CORRECT_TO_PREPARING"
              ? t("correctSubmissionTitle")
              : action === "CORRECT_TO_SUBMITTED"
                ? t("correctOutcomeTitle")
                : action === "CORRECT_TO_WON"
                  ? t("correctWonTitle")
                  : t("correctLostTitle");
  const confirmationCopy = (action: CommandAction) =>
    action === "MARK_SUBMITTED"
      ? t("submittedConfirm")
      : action === "RECORD_WON"
        ? t("wonConfirm")
        : action === "RECORD_LOST"
          ? t("lostConfirm")
          : action === "DISMISS"
            ? t("dismissPreparingConfirm")
            : action === "CORRECT_TO_PREPARING"
              ? t("correctSubmissionConfirm")
              : action === "CORRECT_TO_SUBMITTED"
                ? t("correctOutcomeConfirm")
                : action === "CORRECT_TO_WON"
                  ? t("correctWonConfirm")
                  : t("correctLostConfirm");

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {available.includes("SAVE") ? (
          <button
            type="button"
            onClick={() => void saveAgain()}
            disabled={submitting !== null}
            className="inline-flex items-center gap-2 rounded-lg border border-sky-500 bg-sky-600 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : null}
            {t("saveAgain")}
          </button>
        ) : null}
        {normal.map((action) => {
          const definition = ACTIONS[action];
          return (
            <button
              key={action}
              type="button"
              onClick={() => request(definition)}
              disabled={submitting !== null}
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:opacity-60 ${buttonClasses(definition.tone)}`}
            >
              {submitting === action ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : null}
              {actionLabel(definition.action)}
            </button>
          );
        })}
        {available.includes("PREPARE_BID") ||
        engagement.engagement_status === "PREPARING" ? (
          proposalId ? (
            <a
              href={`/dashboard/bid-preparation/${proposalId}`}
              className="inline-flex items-center rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              {t("openBid")}
            </a>
          ) : (
            <PrepareBidButton
              tenderId={tenderId}
              label={
                engagement.engagement_status === "PREPARING"
                  ? t("openBid")
                  : undefined
              }
            />
          )
        ) : null}
        {secondary.length ? (
          <details className="relative">
            <summary className="cursor-pointer list-none rounded-lg border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-300 hover:border-zinc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">
              {engagement.engagement_status === "DISMISSED"
                ? t("resume")
                : secondary.some((action) => action.startsWith("CORRECT_"))
                  ? t("correctStatus")
                  : t("more")}
            </summary>
            <div className="absolute end-0 z-20 mt-2 flex min-w-56 flex-col gap-1 rounded-lg border border-zinc-700 bg-zinc-950 p-2 shadow-xl">
              {secondary.map((action) => (
                <button
                  key={action}
                  type="button"
                  onClick={() => request(ACTIONS[action])}
                  disabled={submitting !== null}
                  className="rounded-md px-3 py-2 text-start text-xs font-medium text-zinc-200 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:opacity-60"
                >
                  {actionLabel(action)}
                </button>
              ))}
            </div>
          </details>
        ) : null}
      </div>
      {error ? (
        <p
          role="alert"
          className="flex items-center gap-2 text-xs text-red-300"
        >
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          {error}
        </p>
      ) : null}
      {pending ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !submitting)
              setPending(null);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="engagement-confirm-title"
            aria-describedby="engagement-confirm-description"
            className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-950 p-5 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2
                  id="engagement-confirm-title"
                  className="text-lg font-semibold text-white"
                >
                  {confirmationTitle(pending.action)}
                </h2>
                <p
                  id="engagement-confirm-description"
                  className="mt-2 text-sm leading-6 text-zinc-300"
                >
                  {confirmationCopy(pending.action)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPending(null)}
                disabled={submitting !== null}
                aria-label={t("closeConfirmation")}
                className="rounded-md p-1 text-zinc-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                ref={cancelRef}
                type="button"
                onClick={() => setPending(null)}
                disabled={submitting !== null}
                className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-semibold text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={() => void invoke(pending)}
                disabled={submitting !== null}
                className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:opacity-60 ${buttonClasses(pending.tone)}`}
              >
                {submitting ? (
                  <Loader2
                    className="h-4 w-4 animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                {actionLabel(pending.action)}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
