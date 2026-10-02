import type { ExplorerItem, ExplorerTenderSummary } from "@/types/explorer";
import { matchesProfile } from "./factChips.ts";
import { isTenderOpen } from "./tenderTruth.ts";
import type { SourceRefreshStatusItem } from "@/types/source-refresh";

export const DASHBOARD_OPPORTUNITY_LIMIT = 3;
/** The dashboard top list leaves out tenders closing sooner than this (Explorer still shows them). */
export const DASHBOARD_MIN_DAYS_LEFT = 3;
const DAY_MS = 24 * 60 * 60 * 1000;

type ProfileMatch = { country?: string | null; services?: (string | null)[] | null } | null | undefined;

/**
 * "Matches your profile" tier (D2-02), the same rule as the backend ranking:
 * 1 country and service, 2 country only, 3 service only, 4 no match.
 */
export function profileMatchTier(profileMatch: ProfileMatch): 1 | 2 | 3 | 4 {
  const country = Boolean(profileMatch?.country?.trim());
  const service = (profileMatch?.services ?? []).some((value) => value?.trim());
  if (country && service) return 1;
  if (country) return 2;
  if (service) return 3;
  return 4;
}

export type ProfilePromptVariant = "all" | "targeting" | "details";

type DashboardProfile = {
  company_profile_id?: string | null;
  onboarding_required?: boolean;
  company_name?: string | null;
  director_name?: string | null;
  phone_contact?: string | null;
  inn?: string | null;
  industry?: string | null;
  target_regions?: string[] | null;
  target_countries?: string[] | null;
  target_services?: string[] | null;
};

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

export function isCurrentTender(
  tender: ExplorerTenderSummary,
  now = Date.now(),
): boolean {
  // Derived status and the conservative effective deadline (D1-05b/c); sorting
  // below still uses the stored deadline.
  return isTenderOpen(tender, now);
}

function stableTenderIdentity(tender: ExplorerTenderSummary): string {
  const canonical = tender.canonical_source_key?.trim();
  return canonical || `${tender.source_system}:${tender.external_id}`;
}

// No score: profile-match tier, then the soonest deadline, then a stable identity order.
export function compareOpportunities(a: ExplorerItem, b: ExplorerItem): number {
  const tierDifference = profileMatchTier(a.profile_match) - profileMatchTier(b.profile_match);
  if (tierDifference) return tierDifference;
  const aDeadline = timestamp(a.tender.deadline);
  const bDeadline = timestamp(b.tender.deadline);
  if (aDeadline !== null && bDeadline === null) return -1;
  if (aDeadline === null && bDeadline !== null) return 1;
  if (aDeadline !== null && bDeadline !== null && aDeadline !== bDeadline) {
    return aDeadline - bDeadline;
  }

  const aIdentity = stableTenderIdentity(a.tender);
  const bIdentity = stableTenderIdentity(b.tender);
  if (aIdentity < bIdentity) return -1;
  if (aIdentity > bIdentity) return 1;
  return a.tender.id < b.tender.id ? -1 : a.tender.id > b.tender.id ? 1 : 0;
}

/**
 * Select the passive Dashboard shortlist: current tenders that match the company
 * profile on at least one country or service fact (D1-08), ranked by tier and then
 * deadline (D2-02), leaving out tenders with fewer than DASHBOARD_MIN_DAYS_LEFT days
 * left. No generation or domain write is performed here.
 */
export function activeOpportunityShortlist(
  items: readonly ExplorerItem[],
  now = Date.now(),
): ExplorerItem[] {
  const byIdentity = new Map<string, ExplorerItem>();
  for (const item of items) {
    if (!matchesProfile(item.profile_match) || !isCurrentTender(item.tender, now)) continue;
    const deadline = timestamp(item.tender.deadline);
    if (deadline !== null && deadline - now < DASHBOARD_MIN_DAYS_LEFT * DAY_MS) continue;
    const identity = stableTenderIdentity(item.tender);
    const current = byIdentity.get(identity);
    if (!current || compareOpportunities(item, current) < 0) {
      byIdentity.set(identity, item);
    }
  }
  return [...byIdentity.values()]
    .sort(compareOpportunities)
    .slice(0, DASHBOARD_OPPORTUNITY_LIMIT);
}

export function profilePromptVariant(
  profile: DashboardProfile | null,
): ProfilePromptVariant | null {
  if (
    !profile?.company_profile_id ||
    profile.onboarding_required
  ) {
    return "all";
  }

  const detailsMissing = [
    profile.company_name,
    profile.director_name,
    profile.phone_contact,
    profile.inn,
    profile.industry,
  ].some((value) => !value?.trim());
  const geographyMissing =
    !(profile.target_regions?.length || profile.target_countries?.length);
  const servicesMissing = !profile.target_services?.length;
  const targetingMissing = geographyMissing || servicesMissing;

  if (detailsMissing && targetingMissing) return "all";
  if (targetingMissing) return "targeting";
  if (detailsMissing) return "details";
  return null;
}

export function lastAuthoritativeRefresh(
  items: readonly SourceRefreshStatusItem[],
): string | null {
  let latest: { value: string; time: number } | null = null;
  for (const item of items) {
    const value = item.last_clean_completed?.completed_at;
    const time = timestamp(value);
    if (value && time !== null && (!latest || time > latest.time)) {
      latest = { value, time };
    }
  }
  return latest?.value ?? null;
}
