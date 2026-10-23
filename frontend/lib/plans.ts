/**
 * P3: the organization's plan, this period's usage and what the plan includes (GET /organizations/plan).
 * Import-free for the node test runner.
 */

import type { BillingSummary } from './billing';

export type PlanCode = 'explore' | 'pilot' | 'pursuit_desk' | 'agent' | 'enterprise' | 'per_tender';
export type PlanNoticeLevel = 'none' | 'near_limit' | 'limit_reached';

export type PlanCounter = {
  used: number;
  limit: number | null;
  extra_granted: number;
  override: number | null;
  remaining: number | null;
  notice: PlanNoticeLevel;
};

export type PlanStatus = {
  organization_id: string;
  plan: PlanCode;
  access_state: string;
  period_kind: 'calendar_month' | 'plan_term' | 'plan_year' | 'lifetime';
  period_start: string;
  period_end: string | null;
  plan_started_on: string | null;
  plan_ends_on: string | null;
  pursuits: PlanCounter;
  introductions: PlanCounter;
  users: { used: number; limit: number | null };
  features: {
    tender_check: boolean;
    eoi: boolean;
    own_evidence: boolean;
    partner_search: boolean;
    competitor_intelligence: boolean;
  };
  intelligence: string;
  /** B1: the payment status, an open invoice and the annual offer. */
  billing?: BillingSummary | null;
};

export const PLAN_CODES: PlanCode[] = ['explore', 'pilot', 'pursuit_desk', 'agent', 'enterprise', 'per_tender'];

/** The pursuit workspace tabs a plan opens: Explore checks requirements only. */
export function planTabs<T extends string>(tabs: readonly T[], plan: PlanStatus | null): T[] {
  if (!plan) return [...tabs];
  return tabs.filter((tab) => {
    if (tab === 'eoi') return plan.features.eoi;
    if (tab === 'team' || tab === 'proposal') return plan.features.own_evidence;
    if (tab === 'documents') return plan.plan !== 'explore';
    return true;
  });
}

/** A plan error from the API (402 limit, 403 feature): its code, else null. */
export function planErrorCode(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === 'string' && code.startsWith('PLAN_') ? code : null;
  }
  return null;
}

export const PLAN_STATUS_EVENT = 'plasma:plan-status-changed';
