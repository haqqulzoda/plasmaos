/** P2 partner finder types (moved out of pursuit.ts in P3; the requester's own note lives here). */
import type { CandidateMatch } from './pursuit';

// P2 partner finder: firms that won similar development-bank contracts (public award records,
// unverified), introduction requests worked by the Plasma team, prospective JV members.
export type PartnerGapBasis = 'PARTNER_FIRM_RULE' | 'LOCAL_PRESENCE' | 'EXPERIENCE' | 'EXPERT';
export type PartnerRequestStatus = 'REQUESTED' | 'CONTACTED' | 'ACCEPTED' | 'DECLINED' | 'INTRODUCED';
export type PartnerRequestKind = 'INTRODUCTION' | 'EXPERT_SOURCING';

export type PartnerGapFeatures = {
  category: 'PARTNER_FIRM' | 'EXPERT';
  basis: PartnerGapBasis;
  summary: string;
  keywords: string[];
  sectors: string[];
  country: string | null;
  procurement_group: string;
  presence: 'LOCAL' | 'FOREIGN' | 'ANY';
};

export type PartnerGap = {
  gap_id: string;
  requirement_id: string | null;
  position_id: string | null;
  coverage_state: string;
  review_state: string;
  resolution_category: string;
  distinction: string | null;
  missing_contribution: string;
  features: PartnerGapFeatures;
};

export type PublicAward = {
  title: string;
  project_name: string | null;
  lender: string;
  lender_label: string;
  country: string | null;
  year: number | null;
  notice_id: string;
  notice_url: string;
  procurement_group: string | null;
  joint_venture: boolean;
};

export type PartnerSuggestion = {
  rank: number;
  firm_key: string;
  firm_name: string;
  firm_country: string | null;
  presence: 'LOCAL' | 'FOREIGN' | 'UNKNOWN';
  presence_matches_gap: boolean;
  match_strength: 'STRONG' | 'MODERATE';
  in_procurement_category: boolean;
  same_country: boolean;
  matched_terms: string[];
  matched_sectors: string[];
  similar_award_count: number;
  latest_award_year: number | null;
  best_relevance: number;
  awards: PublicAward[];
  source_label: string;
  request: { request_id: string; status: PartnerRequestStatus } | null;
};

export type PartnerSuggestions = {
  analysis_run_id: string;
  gap_id: string;
  gap: PartnerGapFeatures;
  ranking_version: string;
  source_label: string;
  jv_rule_check: boolean;
  awards_considered: number;
  suggestions: PartnerSuggestion[];
};

export type ExpertSuggestion = {
  rank: number;
  expert_id: string;
  display_name: string;
  scope: 'ORGANIZATION_PRIVATE' | 'NETWORK_SHARED';
  qualification_state: CandidateMatch['qualification_state'];
  rationale: string;
  missing_or_weak_evidence: string[];
};

export type ExpertSuggestions = {
  analysis_run_id: string;
  gap_id: string;
  gap: PartnerGapFeatures;
  experts: ExpertSuggestion[];
  sourcing_request: { request_id: string; status: PartnerRequestStatus } | null;
};

export type PartnerRequest = {
  request_id: string;
  pursuit_id: string;
  analysis_run_id: string;
  gap_id: string;
  kind: PartnerRequestKind;
  gap_category: string;
  gap_summary: string;
  firm_key: string | null;
  firm_name: string | null;
  firm_country: string | null;
  awards: PublicAward[];
  source_label: string | null;
  note: string | null;
  status: PartnerRequestStatus;
  status_changed_at: string;
  created_at: string;
  requester_membership_id: string;
  history: { from_status: PartnerRequestStatus | null; to_status: PartnerRequestStatus; message: string | null; at: string }[];
};

export type PartnerFinderOverview = {
  analysis_run_id: string | null;
  inputs_changed: boolean;
  gaps: PartnerGap[];
  requests: PartnerRequest[];
};

export type ProspectiveMember = {
  prospective_member_id: string;
  partner_request_id: string;
  display_name: string;
  firm_country: string | null;
  request_status: PartnerRequestStatus;
  confirmation: 'NOT_YET_CONFIRMED';
  targets: { gap_id: string; analysis_run_id: string; gap_summary: string }[];
  would_close_gap_ids: string[];
  awards: PublicAward[];
  source_label: string;
  added_at: string;
};
