"use client";

import { useState } from "react";
import { Bookmark } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import type { PursuitSummary } from "@/types/explorer";
import type {
  SaveToMyTendersResponse,
  TenderEngagementActionResponse,
} from "@/types/engagement";

function toPursuit(
  engagement:
    | SaveToMyTendersResponse["engagement"]
    | TenderEngagementActionResponse["engagement"],
): PursuitSummary {
  return {
    engagement_id: engagement.engagement_id,
    status: engagement.engagement_status,
    allowed_actions: engagement.allowed_actions,
  };
}

export function DashboardBookmarkButton({
  tenderId,
  pursuit,
  onChanged,
  disabled = false,
}: {
  tenderId: string;
  pursuit: PursuitSummary | null;
  onChanged: (pursuit: PursuitSummary) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("dashboard.bookmark");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const isDismissed = pursuit?.status === "DISMISSED";
  const isSaved = Boolean(pursuit && !isDismissed);
  const canRemove =
    pursuit?.status === "SAVED" && pursuit.allowed_actions.includes("DISMISS");
  const canToggle = !isSaved || canRemove;
  const label = isSaved
    ? canRemove
      ? t("remove")
      : t("inMyTenders")
    : t("save");

  const toggle = async () => {
    if (pending || !canToggle) return;
    setPending(true);
    setError(false);
    try {
      if (canRemove && pursuit) {
        const response = await api.post<TenderEngagementActionResponse>(
          `/my-tenders/${pursuit.engagement_id}/actions/dismiss`,
          { expected_status: pursuit.status },
        );
        onChanged(toPursuit(response.data.engagement));
      } else {
        const response = await api.post<SaveToMyTendersResponse>(
          `/tenders/${tenderId}/engagement`,
        );
        onChanged(toPursuit(response.data.engagement));
      }
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  };

  return (
    <span className="dashboard-bookmark-wrap">
      <Button
        variant="icon"
        className="dashboard-bookmark"
        aria-label={label}
        aria-pressed={isSaved}
        title={label}
        data-saved={isSaved || undefined}
        disabled={!canToggle || (!isSaved && disabled)}
        loading={pending}
        onClick={() => void toggle()}
      >
        {!pending && <Bookmark aria-hidden />}
      </Button>
      {error && (
        <span role="alert" className="dashboard-bookmark-error">
          {t("failed")}
        </span>
      )}
    </span>
  );
}
