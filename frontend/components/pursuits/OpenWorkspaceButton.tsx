"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { OrganizationContextPicker } from "@/components/pursuits/OrganizationContextPicker";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { resolveWorkspace, type WorkspaceDeps, type WorkspaceOrganization } from "@/lib/openWorkspace";

const deps: WorkspaceDeps = {
  listOrganizations: async () => (await api.get<WorkspaceOrganization[]>("/organizations")).data,
  // Idempotent: 201 creates the SOURCE pursuit, 200 returns the existing one.
  createOrResolveSourcePursuit: async (tenderId, organizationId) =>
    (
      await api.post<{ pursuit_id: string }>(
        "/pursuits/source",
        { tender_id: tenderId },
        { headers: { "X-Organization-ID": organizationId } },
      )
    ).data,
};

/**
 * One door (D1-06): the single way from a source tender into the pursuit workspace.
 * Nothing is requested on render. The click resolves the organization (one ACTIVE
 * membership is automatic, several show the picker), creates or resolves the SOURCE
 * pursuit, and navigates to it.
 */
export function OpenWorkspaceButton({
  tenderId,
  variant = "primary",
  size = "sm",
  disabled = false,
  className,
}: {
  tenderId: string;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  disabled?: boolean;
  className?: string;
}) {
  const t = useTranslations("pursuits.oneDoor");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  // The guard lives in a ref so `open` keeps one identity: the organization picker
  // refetches whenever its onChange changes.
  const busyRef = useRef(false);
  const [choosing, setChoosing] = useState(false);
  const [organizationId, setOrganizationId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const open = useCallback(
    async (chosenOrganizationId?: string) => {
      if (busyRef.current || disabled) return;
      busyRef.current = true;
      setBusy(true);
      setError(null);
      try {
        const resolution = await resolveWorkspace(tenderId, deps, chosenOrganizationId);
        if (resolution.kind === "navigate") router.push(resolution.href);
        else if (resolution.kind === "choose") setChoosing(true);
        else setError(t("noOrganization"));
      } catch {
        setError(t("failed"));
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [disabled, router, t, tenderId],
  );

  const choose = useCallback(
    (value: string) => {
      setOrganizationId(value);
      if (value) void open(value);
    },
    [open],
  );

  return (
    <div className="open-workspace" data-open-workspace={tenderId}>
      <Button
        variant={variant}
        size={size}
        className={className}
        loading={busy}
        disabled={disabled}
        onClick={() => void open(organizationId || undefined)}
        trailingIcon={<ArrowRight className="rtl-mirror" aria-hidden />}
      >
        {busy ? t("opening") : t("openWorkspace")}
      </Button>
      {choosing && (
        <div className="open-workspace-organization">
          <p className="ds-muted ds-text-small">{t("chooseOrganization")}</p>
          <OrganizationContextPicker value={organizationId} onChange={choose} />
        </div>
      )}
      {error && (
        <p role="alert" className="ds-text-danger ds-text-small">
          {error}
        </p>
      )}
    </div>
  );
}
