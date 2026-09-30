"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

/**
 * Pursuits (D1-07): one list, two origins. "From sources" is the pipeline of
 * source-tender pursuits; "Uploaded" is the organization-private uploaded tenders.
 */
export function PursuitSegments({ active }: { active: "sources" | "uploaded" }) {
  const t = useTranslations("pursuits.segments");
  return (
    <nav className="pursuit-segments" aria-label={t("label")}>
      <Link
        prefetch={false}
        href="/dashboard/my-tenders"
        aria-current={active === "sources" ? "page" : undefined}
      >
        {t("fromSources")}
      </Link>
      <Link
        prefetch={false}
        href="/dashboard/uploaded-tenders"
        aria-current={active === "uploaded" ? "page" : undefined}
      >
        {t("uploaded")}
      </Link>
    </nav>
  );
}
