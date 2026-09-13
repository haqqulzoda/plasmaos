"use client";
import { useState } from "react";
import { Bookmark } from "lucide-react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import type { SaveToMyTendersResponse } from "@/types/engagement";

/** The existing explicit pursuit command; never creates a Proposal. */
export function SaveTenderButton({
  tenderId,
  disabled,
  onSaved,
}: {
  tenderId: string;
  disabled?: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations("myTenders.panel");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  return (
    <div className="ds-stack">
      <Button
        variant="secondary"
        size="sm"
        loading={saving}
        disabled={disabled}
        leadingIcon={<Bookmark aria-hidden />}
        onClick={async () => {
          if (saving || disabled) return;
          setSaving(true);
          setError(false);
          try {
            await api.post<SaveToMyTendersResponse>(
              `/tenders/${tenderId}/engagement`,
            );
            onSaved();
          } catch {
            setError(true);
          } finally {
            setSaving(false);
          }
        }}
      >
        {saving ? t("saving") : t("save")}
      </Button>
      {error && (
        <p role="alert" className="ds-text-danger ds-text-small">
          {t("saveFailed")}
        </p>
      )}
    </div>
  );
}
