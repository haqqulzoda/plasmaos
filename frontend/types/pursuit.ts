export type PursuitOrigin = 'SOURCE' | 'UPLOAD';
export type PursuitStage =
  | 'SAVED'
  | 'EVALUATING'
  | 'PREPARING'
  | 'SUBMITTED'
  | 'WON'
  | 'LOST'
  | 'DISMISSED';
export type DocumentProcessingState =
  | 'UPLOADING'
  | 'QUEUED'
  | 'CHECKING'
  | 'EXTRACTING'
  | 'READY'
  | 'PARTIAL'
  | 'FAILED';
export type PrivateDocumentRole =
  | 'RFP'
  | 'TOR'
  | 'NOTICE'
  | 'ADDENDUM'
  | 'CLARIFICATION'
  | 'FORM'
  | 'ANNEX'
  | 'OTHER';

export type OrganizationSummary = {
  organization_id: string;
  legacy_company_profile_id: string;
  display_name: string | null;
  membership_id: string;
  membership_role: 'OWNER' | 'MEMBER';
  membership_state: 'INVITED' | 'ACTIVE' | 'REVOKED';
};

export type Pursuit = {
  pursuit_id: string;
  organization_id: string;
  source_tender_id: string | null;
  origin: PursuitOrigin;
  owner_membership_id: string | null;
  stage: PursuitStage;
  created_at: string;
  updated_at: string;
  stage_changed_at: string;
  tender_title: string | null;
  title: string | null;
  buyer: string | null;
  declared_funder: string | null;
  country: string | null;
  reference: string | null;
  source_deadline: string | null;
  external_deadline: string | null;
  deadline_timezone: string | null;
  source_url: string | null;
  confirmed_fields: string[];
  processing_state: DocumentProcessingState | null;
  file_count: number;
  processed_count: number;
  failed_count: number;
  owner_name: string | null;
  /** D2-05: display name of the first uploaded document (title fallback). */
  first_document_name?: string | null;
};

export type PursuitListResponse = {
  items: Pursuit[];
  total: number;
  limit: number;
  offset: number;
};

export type PrivateDocument = {
  document_id: string;
  current_version_id: string;
  role: PrivateDocumentRole;
  display_name: string;
  version_number: number;
  media_type: string;
  byte_size: number;
  sha256: string;
  processing_state: DocumentProcessingState;
  page_count: number | null;
  page_count_known: boolean;
  retry_allowed: boolean;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type PrivateUploadResponse = {
  pursuit: Pursuit;
  batch_id: string;
  document_ids: string[];
  processing_state: DocumentProcessingState;
  duplicate_document_ids: string[];
};

export type PursuitContextSuggestion = {
  suggestion_id: string;
  field_name: string;
  suggested_value: string;
  document_version_id: string;
  page_number: number | null;
  evidence_span: string | null;
  confidence: number | null;
  review_state: 'PROVISIONAL' | 'ACCEPTED' | 'REJECTED';
  provenance_state: ContextProvenanceState;
  user_confirmed_value: string | null;
};

export type ContextProvenanceState =
  | 'SOURCE_DETECTED'
  | 'USER_CONFIRMED'
  | 'USER_OVERRIDE_CONFLICTS_WITH_SOURCE'
  | 'UNKNOWN';

export type PursuitContextFieldProvenance = {
  field_name: string;
  provenance_state: ContextProvenanceState;
  source_value: string | null;
  user_confirmed_value: string | null;
};

export type PursuitContext = {
  pursuit_id: string;
  title: string | null;
  buyer: string | null;
  declared_funder: string | null;
  country: string | null;
  reference: string | null;
  procurement_stage: string | null;
  external_deadline: string | null;
  deadline_timezone: string | null;
  source_url: string | null;
  confirmed_fields: string[];
  suggestions: PursuitContextSuggestion[];
  field_provenance: PursuitContextFieldProvenance[];
};

export const customerProcessingState = (state: DocumentProcessingState | null) =>
  state === 'QUEUED' ? 'CHECKING' : state;

export type CoverageState =
  | 'SUPPORTED'
  | 'PARTIAL'
  | 'GAP'
  | 'EVIDENCE_MISSING'
  | 'NEEDS_INTERPRETATION'
  | 'NOT_APPLICABLE'
  | 'LATER_STAGE_OBLIGATION';

export type AnalysisSourceCandidate = {
  tender_document_id: string;
  display_name: string;
  role: string;
  snapshot_sha256: string;
  content_sha256: string;
  analyzed_text_sha256: string;
  extracted_character_count: number;
  file_type: string;
  parse_ready: boolean;
  page_count: number | null;
  page_count_known: boolean;
  source_url: string | null;
  duplicate_warning: string | null;
  provenance: 'SHARED_SOURCE';
};

export type AnalysisPrivateCandidate = {
  private_document_id: string;
  document_version_id: string;
  display_name: string;
  version_number: number;
  role: PrivateDocumentRole;
  content_sha256: string;
  processing_result_id: string | null;
  processing_result_sha256: string | null;
  extracted_character_count: number;
  processing_state: DocumentProcessingState;
  parse_ready: boolean;
  page_count: number | null;
  page_count_known: boolean;
  malware_scan_status: string | null;
  duplicate_warning: string | null;
  provenance: 'ORGANIZATION_PRIVATE_UPLOAD';
};

export type AnalysisPackCandidate = {
  schema_version: string;
  candidate_sha256: string;
  organization_id: string;
  pursuit_id: string;
  pursuit_origin: PursuitOrigin;
  source_tender_id: string | null;
  parse_ready: boolean;
  page_count_total: number | null;
  source_documents: AnalysisSourceCandidate[];
  private_versions: AnalysisPrivateCandidate[];
  generated_at: string;
};

export type AnalysisPackItem = {
  pack_item_id: string;
  item_kind: 'SOURCE' | 'PRIVATE';
  provenance: 'SHARED_SOURCE' | 'ORGANIZATION_PRIVATE_UPLOAD';
  display_name: string;
  role: string;
  version_number: number | null;
  page_count: number | null;
  page_count_known: boolean;
  content_sha256: string;
  source_url: string | null;
};

export type PursuitRequirement = {
  requirement_id: string;
  pack_item_id: string;
  original_quote: string;
  source_context: string | null;
  normalized_requirement: string;
  effective_normalized_requirement: string;
  category: string;
  requirement_type: string;
  stage_scope: string;
  distinction: 'MANDATORY' | 'SCORED' | 'INFORMATIONAL';
  predicate: Record<string, unknown> | null;
  contribution_rule: string | null;
  coverage_state: CoverageState;
  effective_coverage_state: CoverageState;
  review_state: string;
  effective_review_state: string;
  source_locator: Record<string, unknown>;
  generated_interpretation: string | null;
  /** D2-01: own-firm references the deterministic own-experience match named. */
  matched_reference_ids?: string[];
};

/** D2-01: an informational statement or submission instruction (no Gap, no evidence expected). */
export type PursuitSubmissionNote = PursuitRequirement & {
  note_kind: 'INFORMATIONAL' | 'SUBMISSION_INSTRUCTION';
};

export type PursuitPosition = {
  position_id: string;
  pack_item_id: string;
  title: string;
  effective_title: string;
  quantity: number | null;
  distinction: 'MANDATORY' | 'SCORED';
  education_qualification: string | null;
  general_experience: string | null;
  specific_experience: string | null;
  relevant_assignments: string | null;
  languages: unknown[];
  certifications: unknown[];
  location_travel: string | null;
  expected_effort: string | null;
  assignment_dates: string | null;
  qualification_criteria: Array<{
    normalized_text: string;
    distinction: 'MANDATORY' | 'PREFERRED' | 'DESIRED';
  }>;
  original_quote: string;
  source_context: string | null;
  coverage_state: CoverageState;
  effective_coverage_state: CoverageState;
  review_state: string;
  effective_review_state: string;
  source_locator: Record<string, unknown>;
  generated_interpretation: string | null;
};

export type PursuitGap = {
  gap_id: string;
  requirement_id: string | null;
  position_id: string | null;
  source_pack_item_id: string;
  missing_contribution: string;
  coverage_state: CoverageState;
  effective_coverage_state: CoverageState;
  resolution_category: 'COMPANY_EVIDENCE' | 'PARTNER_FIRM' | 'EXPERT' | 'CLARIFICATION' | 'HUMAN_INTERPRETATION';
  effective_resolution_category: 'COMPANY_EVIDENCE' | 'PARTNER_FIRM' | 'EXPERT' | 'CLARIFICATION' | 'HUMAN_INTERPRETATION';
  review_state: string;
  effective_review_state: string;
  rationale: string;
  matched_reference_ids?: string[];
};

export type PursuitAnalysis = {
  analysis_run_id: string;
  analysis_pack_id: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  result_completeness: 'FULL' | null;
  quality_state: 'READY_FOR_REVIEW' | 'NEEDS_ATTENTION' | 'FAILED';
  quality_summary: string;
  analysis_language: 'en' | 'uz' | 'ru';
  model_provider: string;
  model_name: string;
  prompt_version: string;
  schema_version: string;
  pipeline_version: string;
  created_at: string;
  completed_at: string | null;
  failure_stage: string | null;
  failure_reason: string | null;
  inputs_changed: boolean;
  stale_reason: string | null;
  page_count_known: boolean;
  limit_disclosure: string;
  pack_items: AnalysisPackItem[];
  requirements: PursuitRequirement[];
  positions: PursuitPosition[];
  gaps: PursuitGap[];
  /** D2-01: kept out of requirements and every evidence count. Absent before D2-01. */
  submission_and_notes?: PursuitSubmissionNote[];
};

export type CandidateQualificationState =
  | 'SUPPORTED_BY_EVIDENCE'
  | 'PARTIAL'
  | 'EVIDENCE_MISSING'
  | 'NEEDS_REVIEW'
  | 'NOT_RELEVANT';

export type CandidateEvidenceState =
  | 'VERIFIED'
  | 'REVIEWED'
  | 'UNVERIFIED'
  | 'EVIDENCE_MISSING';

export type CandidateReviewDecision =
  | 'SHORTLISTED'
  | 'REJECTED'
  | 'MORE_EVIDENCE_REQUESTED'
  | 'IRRELEVANT'
  | 'CONTRIBUTION_CORRECTED';

export type CandidateReview = {
  decision_id: string;
  candidate_search_run_id: string;
  candidate_match_id: string;
  decision: CandidateReviewDecision;
  corrected_contribution: string | null;
  reason: string;
  actor_membership_id: string;
  created_at: string;
};

export type CandidateMatch = {
  candidate_match_id: string;
  gap_id: string;
  candidate_kind: 'FIRM' | 'EXPERT';
  candidate_id: string;
  candidate_name: string;
  candidate_scope: 'ORGANIZATION_PRIVATE' | 'NETWORK_SHARED';
  candidate_evidence_state: CandidateEvidenceState;
  proposed_contribution: string;
  strongest_evidence: unknown[];
  relevant_evidence: unknown[];
  missing_or_weak_evidence: unknown[];
  qualification_state: CandidateQualificationState;
  rationale: string;
  provenance: Record<string, unknown>;
  retrieval_rank: number;
  latest_review: CandidateReview | null;
};

export type CandidateSearchRun = {
  candidate_search_run_id: string;
  organization_id: string;
  pursuit_id: string;
  analysis_run_id: string;
  gap_id: string;
  target_kind: 'FIRM' | 'EXPERT';
  requirement_id: string | null;
  position_id: string | null;
  review_assertion_id: string;
  effective_coverage_state: CoverageState;
  effective_review_state: 'CONFIRMED' | 'CORRECTED';
  resolution_category: 'PARTNER_FIRM' | 'EXPERT';
  contribution_rule: string;
  search_version: string;
  search_parameters: Record<string, unknown>;
  result_limit: number;
  status: 'COMPLETED';
  created_at: string;
  completed_at: string;
  is_stale: boolean;
  stale_reason: string | null;
  matches: CandidateMatch[];
};

export type CandidateProjectReference = {
  reference_id: string;
  firm_id: string;
  project_name: string;
  client_name: string | null;
  country: string | null;
  service: string | null;
  sector: string | null;
  role: string;
  contract_share_percent: string | null;
  contract_value: string | null;
  contract_currency: string | null;
  value_basis: string;
  start_date: string | null;
  completion_date: string | null;
  completion_state: string;
  relevant_scope: string | null;
  evidence_provenance: Record<string, unknown>;
  evidence_state: CandidateEvidenceState;
  /** D2-01: METADATA_ONLY is a recorded claim; FILE_BACKED names a document (not verified). */
  evidence_basis?: 'METADATA_ONLY' | 'FILE_BACKED';
  /** D2-01: set when this row replaced an edited reference (the old row is archived). */
  supersedes_reference_id?: string | null;
  archived_at?: string | null;
  created_at: string;
};

export type CandidateFirm = {
  firm_id: string;
  /** D2-01: true only for the organization's own firm. */
  is_self_firm?: boolean;
  scope: 'ORGANIZATION_PRIVATE' | 'NETWORK_SHARED';
  canonical_name: string;
  display_name: string;
  legal_name: string | null;
  country: string | null;
  regions: unknown[];
  services: unknown[];
  capabilities: unknown[];
  sectors: unknown[];
  source_type: string;
  source_provenance: Record<string, unknown>;
  evidence_state: CandidateEvidenceState;
  project_references: CandidateProjectReference[];
  created_at: string;
  updated_at: string;
};

export type CandidateCVVersion = {
  cv_version_id: string;
  expert_id: string;
  version_number: number;
  education: unknown[];
  qualifications: unknown[];
  certifications: unknown[];
  assignments: unknown[];
  languages: unknown[];
  evidence_provenance: Record<string, unknown>;
  evidence_state: CandidateEvidenceState;
  structured_sha256: string;
  created_at: string;
};

export type CandidateExpert = {
  expert_id: string;
  scope: 'ORGANIZATION_PRIVATE' | 'NETWORK_SHARED';
  display_name: string;
  qualifications: unknown[];
  languages: unknown[];
  specializations: unknown[];
  consent_state: string;
  evidence_state: CandidateEvidenceState;
  source_provenance: Record<string, unknown>;
  cv_versions: CandidateCVVersion[];
  created_at: string;
  updated_at: string;
};

export type CandidateLibrary = {
  /** D2-01: the organization's own firm; never listed in ``firms``. Absent before D2-01. */
  self_firm?: CandidateFirm | null;
  firms: CandidateFirm[];
  experts: CandidateExpert[];
};

export type ParticipationConfirmationSource =
  | 'DIRECT_EMAIL'
  | 'CALL'
  | 'MEETING'
  | 'SIGNED_DOCUMENT'
  | 'OPERATOR_RECORDED'
  | 'CUSTOMER_RECORDED'
  | 'OTHER';

export type CandidateAvailabilityStatus =
  | 'UNKNOWN'
  | 'TENTATIVE'
  | 'AVAILABLE'
  | 'PARTIALLY_AVAILABLE'
  | 'UNAVAILABLE';

export type CandidateInterestStatus =
  | 'UNKNOWN'
  | 'INTERESTED'
  | 'CONDITIONAL'
  | 'DECLINED';

export type CandidateParticipationState =
  | 'UNCONFIRMED'
  | 'TENTATIVE'
  | 'CONFIRMED'
  | 'DECLINED'
  | 'WITHDRAWN';

export type CandidateAvailabilityFact = {
  fact_id: string;
  status: CandidateAvailabilityStatus;
  effective_status: CandidateAvailabilityStatus | 'EXPIRED';
  is_expired: boolean;
  window_start: string | null;
  window_end: string | null;
  effort_percent: string | null;
  capacity_description: string | null;
  location_travel_constraints: string | null;
  confirmation_source: ParticipationConfirmationSource;
  observed_at: string;
  valid_until: string | null;
  supporting_document_version_id: string | null;
  supersedes_fact_id: string | null;
  actor_membership_id: string;
  created_at: string;
};

export type CandidateInterestFact = {
  fact_id: string;
  status: CandidateInterestStatus;
  effective_status: CandidateInterestStatus | 'EXPIRED';
  is_expired: boolean;
  confirmation_source: ParticipationConfirmationSource;
  observed_at: string;
  valid_until: string | null;
  conditions: string | null;
  supporting_document_version_id: string | null;
  supersedes_fact_id: string | null;
  actor_membership_id: string;
  created_at: string;
};

export type CandidateParticipationDecision = {
  decision_id: string;
  state: CandidateParticipationState;
  effective_state: CandidateParticipationState | 'NEEDS_RECONFIRMATION';
  needs_reconfirmation: boolean;
  confirmation_source: ParticipationConfirmationSource;
  observed_at: string;
  reconfirm_by: string | null;
  conditions_summary: string | null;
  reason: string | null;
  supporting_document_version_id: string | null;
  supersedes_decision_id: string | null;
  actor_membership_id: string;
  created_at: string;
};

export type ParticipationHistoryEvent = {
  event_kind: 'AVAILABILITY' | 'INTEREST' | 'PARTICIPATION';
  event_id: string;
  recorded_state: string;
  confirmation_source: ParticipationConfirmationSource;
  observed_at: string;
  actor_membership_id: string;
  supersedes_id: string | null;
  created_at: string;
};

export type CandidateParticipationRecord = {
  participation_record_id: string;
  organization_id: string;
  pursuit_id: string;
  candidate_match_id: string;
  shortlist_decision_id: string;
  effective_shortlist_decision_id: string | null;
  effective_shortlist_state: CandidateReviewDecision | null;
  candidate_search_run_id: string;
  analysis_run_id: string;
  gap_id: string;
  candidate_kind: 'FIRM' | 'EXPERT';
  candidate_id: string;
  candidate_name: string;
  proposed_contribution: string;
  w5_qualification_state: CandidateQualificationState;
  w5_candidate_evidence_state: CandidateEvidenceState;
  w5_strongest_evidence: unknown[];
  w5_missing_or_weak_evidence: unknown[];
  assignment_dates: string | null;
  assignment_window_coverage: 'FULL_WINDOW' | 'PARTIAL_WINDOW' | 'NO_OVERLAP' | 'UNKNOWN_DATES';
  latest_availability: CandidateAvailabilityFact | null;
  latest_interest: CandidateInterestFact | null;
  latest_participation: CandidateParticipationDecision | null;
  upstream_stale: boolean;
  upstream_stale_reason: string | null;
  same_candidate_record_ids: string[];
  history: ParticipationHistoryEvent[];
  created_by_membership_id: string;
  created_at: string;
};

export type ScenarioAssessmentState = 'DRAFT' | 'NEEDS_REVIEW' | 'BLOCKED' | 'VIABLE';
export type ScenarioGapState = 'COVERED' | 'PARTIAL' | 'UNRESOLVED' | 'BLOCKED' | 'NEEDS_REVIEW';
export type ScenarioDecision = 'PREFERRED' | 'REJECTED' | 'APPROVED_FOR_PROPOSAL';
export type ScenarioIssueCode =
  | 'UPSTREAM_STALE'
  | 'PARTIAL_CANDIDATE_EVIDENCE'
  | 'UNCONFIRMED_AVAILABILITY'
  | 'EXPIRED_AVAILABILITY'
  | 'UNAVAILABLE_PARTICIPANT'
  | 'DECLINED_INTEREST'
  | 'UNCONFIRMED_PARTICIPANT'
  | 'NEEDS_RECONFIRMATION'
  | 'PARTICIPATION_UNAVAILABLE'
  | 'NO_WINDOW_OVERLAP'
  | 'PARTIAL_WINDOW'
  | 'UNKNOWN_ASSIGNMENT_WINDOW'
  | 'CONTRIBUTION_RULE_UNCLEAR'
  | 'CONFLICTING_PARTICIPATION_FACTS'
  | 'UNKNOWN_EFFORT'
  | 'CONCURRENT_FULL_TIME_CONFLICT'
  | 'EXPERT_DOUBLE_COUNT'
  | 'UNREVIEWED_GAP'
  | 'UNRESOLVED_GAP';

export type TeamScenarioContribution = {
  contribution_id: string;
  candidate_match_id: string;
  participation_record_id: string;
  gap_id: string;
  requirement_id: string | null;
  position_id: string | null;
  shortlist_decision_id: string;
  shortlist_decision_state: string;
  proposed_contribution: string;
  contribution_rule: string;
  qualification_state: CandidateQualificationState;
  candidate_evidence_state: CandidateEvidenceState;
  evidence_identities: Array<Record<string, string>>;
  strongest_evidence: unknown[];
  availability_fact_id: string | null;
  availability_recorded_state: string | null;
  availability_effective_state: string | null;
  availability_window_start: string | null;
  availability_window_end: string | null;
  availability_effort_percent: string | null;
  availability_capacity: string | null;
  availability_valid_until: string | null;
  interest_fact_id: string | null;
  interest_recorded_state: string | null;
  interest_effective_state: string | null;
  interest_conditions: string | null;
  participation_decision_id: string | null;
  participation_recorded_state: string | null;
  participation_effective_state: string | null;
  confirmation_source: string | null;
  confirmation_observed_at: string | null;
  reconfirm_by: string | null;
  confirmation_conditions: string | null;
  assignment_dates: string | null;
  assignment_window_result: 'FULL_WINDOW' | 'PARTIAL_WINDOW' | 'NO_OVERLAP' | 'UNKNOWN_DATES';
  upstream_stale: boolean;
};

export type TeamScenarioParticipant = {
  participant_id: string;
  participant_type: 'PARTNER_FIRM' | 'EXPERT';
  candidate_id: string;
  display_name: string;
  contributions: TeamScenarioContribution[];
};

export type TeamScenarioGapAssessment = {
  gap_assessment_id: string;
  gap_id: string;
  requirement_id: string | null;
  position_id: string | null;
  review_assertion_id: string | null;
  w4_coverage_state: CoverageState;
  w4_review_state: string;
  resolution_category: string;
  state: ScenarioGapState;
  is_current_stage: boolean;
  is_blocking: boolean;
  rationale_code: string;
};

export type TeamScenarioIssue = {
  issue_id: string;
  issue_code: ScenarioIssueCode;
  severity: 'REVIEW' | 'BLOCKING';
  gap_id: string | null;
  participant_id: string | null;
  contribution_id: string | null;
  details: Record<string, unknown>;
};

export type TeamScenarioDecisionRecord = {
  decision_id: string;
  revision_id: string;
  decision: ScenarioDecision;
  reason: string;
  explicit_confirmation: boolean;
  actor_membership_id: string;
  created_at: string;
};

export type TeamScenarioRevision = {
  revision_id: string;
  version_number: number;
  analysis_run_id: string;
  analysis_pack_id: string;
  selection_sha256: string;
  assessment_schema_version: string;
  assessment_state: ScenarioAssessmentState;
  current_assessment_state: ScenarioAssessmentState;
  scenario_current: boolean;
  stale_reasons: string[];
  gap_count: number;
  covered_gap_count: number;
  unresolved_gap_count: number;
  participant_count: number;
  confirmed_participant_count: number;
  issue_count: number;
  blocking_issue_count: number;
  unresolved_later_stage_count: number;
  source_provenance_count: number;
  private_provenance_count: number;
  participants: TeamScenarioParticipant[];
  gap_assessments: TeamScenarioGapAssessment[];
  issues: TeamScenarioIssue[];
  decisions: TeamScenarioDecisionRecord[];
  created_by_membership_id: string;
  created_at: string;
};

export type TeamScenario = {
  scenario_id: string;
  organization_id: string;
  pursuit_id: string;
  lead_organization_id: string;
  title: string;
  archived_at: string | null;
  latest_revision: TeamScenarioRevision | null;
  revisions: TeamScenarioRevision[];
  created_by_membership_id: string;
  created_at: string;
};

export type ProposalEvidenceItemCategory =
  | 'PURSUIT_CONTEXT' | 'REQUIREMENT' | 'GAP_ASSESSMENT' | 'FIRM'
  | 'PROJECT_REFERENCE' | 'EXPERT' | 'CV_FACTS' | 'PARTICIPATION_CONFIRMATION'
  | 'SOURCE_DOCUMENT' | 'PRIVATE_DOCUMENT' | 'LATER_STAGE_OBLIGATION'
  | 'FORM_OR_REQUIRED_ARTIFACT' | 'OTHER';

export type ProposalEvidencePackItem = {
  item_id: string;
  ordinal: number;
  category: ProposalEvidenceItemCategory;
  source_authority_type: string;
  source_identity: string;
  provenance: string;
  review_state: string | null;
  evidence_state: string | null;
  purpose: string;
  requirement_id: string | null;
  position_id: string | null;
  gap_id: string | null;
  source_sha256: string | null;
  source_version: string | null;
  payload: Record<string, unknown>;
};

export type ProposalEvidenceArtifact = {
  artifact_id: string;
  pack_id: string;
  artifact_type: 'PDF' | 'DOCX' | 'JSON';
  historical_snapshot: boolean;
  content_sha256: string;
  byte_size: number;
  media_type: string;
  generator_version: string;
  created_by_membership_id: string;
  created_at: string;
};

export type ProposalEvidencePack = {
  pack_id: string;
  workspace_id: string;
  organization_id: string;
  pursuit_id: string;
  pack_version: number;
  scenario_id: string;
  scenario_revision_id: string;
  approval_decision_id: string;
  analysis_run_id: string;
  analysis_pack_id: string;
  schema_version: string;
  manifest_sha256: string;
  pack_state: 'SEALED';
  scenario_title: string;
  pursuit_title: string;
  item_count: number;
  matrix_row_count: number;
  participant_count: number;
  later_stage_count: number;
  checklist_count: number;
  pack_current: boolean;
  stale_reasons: string[];
  items: ProposalEvidencePackItem[];
  artifacts: ProposalEvidenceArtifact[];
  sealed_by_membership_id: string;
  created_at: string;
};

export type PursuitProposalWorkspace = {
  workspace_id: string | null;
  organization_id: string;
  pursuit_id: string;
  created_by_membership_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  legacy_proposal_id: string | null;
  packs: ProposalEvidencePack[];
};
