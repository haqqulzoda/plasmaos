/** D2-05 Expression of Interest contract (backend: pilot/d2-05-eoi). */

export type EoiLocator = { page_number: number | null; paragraph_number: number | null };

export type EoiDefaults = {
  assignment_title: string;
  reference_no: string;
  addressee_organization: string;
  addressee_name: string | null;
  addressee_email: string | null;
  firm_name: string;
  firm_country: string | null;
};

export type EoiCriterion = {
  requirement_id: string;
  statement: string;
  original_quote: string;
  locator: EoiLocator;
  effective_coverage_state: string;
  matched_reference_ids: string[];
};

export type EoiNote = {
  requirement_id: string;
  note_kind: 'INFORMATIONAL' | 'SUBMISSION_INSTRUCTION';
  statement: string;
  original_quote: string;
};

export type EoiReference = {
  reference_id: string;
  project_name: string;
  client_name: string | null;
  country: string | null;
  sector: string | null;
  service: string | null;
  role: string;
  contract_share_percent: string | null;
  contract_value: string | null;
  contract_currency: string | null;
  value_basis: string;
  start_date: string | null;
  completion_date: string | null;
  completion_state: string;
  relevant_scope: string | null;
  evidence_state: string;
  evidence_basis: string;
  matched_requirement_ids: string[];
  suggested: boolean;
  rank: number;
};

export type EoiPartnerFirm = {
  firm_id: string;
  display_name: string;
  country: string | null;
  references: EoiReference[];
  covers_requirement_ids: string[];
};

export type EoiSuggestions = {
  analysis_run_id: string;
  run_current: boolean;
  /** R3: recorded experience changed since the run; absent before R3. */
  company_evidence_changed?: boolean;
  company_evidence_change_reason?: string | null;
  company_evidence_changed_sections?: string[];
  defaults: EoiDefaults;
  criteria: EoiCriterion[];
  notes: EoiNote[];
  own_references: EoiReference[];
  partner_firms: EoiPartnerFirm[];
};

export type EoiPartnerRole = 'JV_MEMBER' | 'SUBCONSULTANT';

export type EoiLetter = {
  addressee_organization: string;
  addressee_name: string | null;
  signatory_name: string;
  signatory_title: string;
  contact_email: string;
  contact_phone: string | null;
  contact_address: string | null;
};

export type EoiDraftCreateRequest = {
  analysis_run_id: string;
  language: 'en' | 'ru';
  own_reference_ids: string[];
  partners: { firm_id: string; role: EoiPartnerRole; reference_ids: string[] }[];
  letter: EoiLetter;
  include_relevance_notes: boolean;
};

export type EoiArtifact = { artifact_id: string; format: 'DOCX' | 'PDF'; sha256: string; byte_size: number };

export type EoiDraftSummary = {
  criteria_total: number;
  criteria_with_references: number;
  criteria_without_references: number;
  own_reference_count: number;
  partner_count: number;
  relevance_notes_generated: number;
  relevance_notes_dropped: number;
};

export type EoiDraft = {
  draft_id: string;
  version: number;
  created_at: string;
  created_by_membership_id: string;
  analysis_run_id: string;
  language: string;
  current: boolean;
  stale_reasons: string[];
  artifacts: EoiArtifact[];
  summary: EoiDraftSummary;
};
