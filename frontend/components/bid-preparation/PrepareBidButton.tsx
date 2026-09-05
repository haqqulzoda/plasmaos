"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FilePenLine, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { api } from "@/lib/api";
import type { PrepareBidResponse } from "@/types/bid-preparation";

interface PrepareBidButtonProps {
  tenderId?: string;
  proposalId?: string;
  label?: string;
  className?: string;
  disabled?: boolean;
  title?: string;
}

export function PrepareBidButton({
  tenderId,
  proposalId,
  label,
  className = "",
  disabled = false,
  title,
}: PrepareBidButtonProps) {
  const router = useRouter();
  const t = useTranslations("bidPreparation");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prepare = async () => {
    if (
      disabled ||
      submitting ||
      (!tenderId && !proposalId) ||
      (tenderId && proposalId)
    )
      return;
    setSubmitting(true);
    setError(null);
    try {
      const response = proposalId
        ? await api.post<PrepareBidResponse>(
            `/proposals/${proposalId}/continue`,
          )
        : await api.post<PrepareBidResponse>("/proposals/prepare", {
            tender_id: tenderId,
          });
      router.push(`/dashboard/bid-preparation/${response.data.proposal.id}`);
    } catch (requestError: unknown) {
      console.error("Failed to start Bid Preparation:", requestError);
      setError(t("notAvailable"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="inline-flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={prepare}
        disabled={disabled || submitting}
        title={title}
        className={`inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${className}`}
      >
        {submitting ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <FilePenLine className="h-4 w-4" aria-hidden="true" />
        )}
        {submitting ? t("loading") : (label ?? t("prepare"))}
      </button>
      {error && (
        <span role="alert" className="max-w-64 text-end text-xs text-red-300">
          {error}
        </span>
      )}
    </div>
  );
}
