/**
 * Plasma AI — Sovereign Compliance Engine
 *
 * TypeScript interfaces for the dynamic compliance data contract
 * between the backend evaluator and the frontend UI.
 */

// ── Dynamic Compliance Ontology Types ──────────────────────────

export interface MetRequirement {
    uuid: string;
    name: string;
}

export interface MissingRequirement {
    uuid: string;
    name: string;
    impact_weight: number;
    is_fatal: boolean;
}

export interface DynamicRequirements {
    mapped_requirement_uuids: string[];
    unmapped_custom_requirements: string[];
}

export interface DynamicEvaluation {
    is_compliant: boolean;
    met_requirements: MetRequirement[];
    missing_requirements: MissingRequirement[];
    unmapped_requirements: string[];
    status_message: string;
}

export interface AnalyzeTenderResponse {
    analysis_id: string;
    requirements: DynamicRequirements;
    evaluation: DynamicEvaluation;
    content_hash: string;
    override_seal: string | null;
}

// ── Legacy backward-compatible aliases ──────────────────────────
// These exist solely so that unreferenced legacy components
// (StrategyPanel, TenderWorkspace) still compile. They should be
// removed once those files are migrated.

export type Severity = 'High' | 'Medium' | 'Low';

export interface RiskItem {
    risk_type: string;
    description: string;
    severity: Severity;
    source_quote?: string;
}

export interface GapAnalysis {
    is_fully_compliant: boolean;
    missing_requirements: string[];
    identified_risks: RiskItem[];
    recommended_mitigation_strategy: string;
}

// Legacy aliases pointing to the new types so old import paths still resolve
export type Requirements = DynamicRequirements;
export type Evaluation = DynamicEvaluation;

// ── Hybrid Compliance Engine Types ──────────────────────────────
// These types mirror the backend's services/compliance_engine.py
// output (ComplianceResult). They are ADDITIVE — no existing type
// above is modified or removed.

export type MatchVerdict = 'SATISFIED' | 'FAILED' | 'NEEDS_MANUAL_REVIEW';
export type MatchMethod = 'UUID_TAXONOMY' | 'TOKEN_OVERLAP' | 'VAULT_DETERMINISTIC' | 'SKIPPED';
export type ComplianceVerdictStatus =
    | 'NOT_ELIGIBLE'
    | 'NEEDS_REVIEW'
    | 'ELIGIBLE_WITH_REVIEW'
    | 'COMPLIANT';

export interface RequirementMatchDetail {
    category: 'DQ' | 'NICE_TO_HAVE' | 'COMPLIANT' | string;
    headline: string;
    source_filename: string;
    source_page: number;
    exact_quote: string;
    raw_text_snippet: string;
    requirement_type: string;
    is_dealbreaker: boolean;
    confidence_score: number;
    verdict: MatchVerdict;
    match_method: MatchMethod;
    matched_credential: string | null;
    taxonomy_node_id: string | null;
    vault_match_type?: string | null;
    vault_match_source?: string | null;
    vault_evidence_id?: string | null;
    vault_match_confidence?: number | null;
    vault_missing_reason?: string | null;
    reason: string;
    parent_section_header: string | null;
}

export interface HybridCompliancePayload {
    is_eligible: boolean;
    total_requirements: number;
    satisfied_count: number;
    failed_count: number;
    manual_review_count: number;
    skipped_optional_count: number;
    recorded_obligations_count?: number;
    skipped_non_bid_obligations_count?: number;
    uuid_match_count: number;
    token_match_count: number;
    verdict_status?: ComplianceVerdictStatus;
    failed_dealbreakers: RequirementMatchDetail[];
    manual_reviews_required: RequirementMatchDetail[];
    satisfied_requirements: RequirementMatchDetail[];
    recorded_obligations?: RequirementMatchDetail[];
    status_message: string;
}

/**
 * Extended response type that includes the optional hybrid compliance
 * payload. The backend already ships this field — the legacy
 * AnalyzeTenderResponse just didn't declare it.
 */
export interface AnalyzeTenderResponseV2 extends AnalyzeTenderResponse {
    hybrid_compliance?: HybridCompliancePayload | null;
}

export interface TenderAnalysisPayloadBase {
    analysis_id: string | null;
    requirements: DynamicRequirements | null;
    evaluation: DynamicEvaluation | null;
    hybrid_compliance?: HybridCompliancePayload | null;
    content_hash: string | null;
    override_seal: string | null;
}

// ── Immutable Override Types ────────────────────────────────────
// Response from POST /tenders/{id}/override after the backend
// recomputes the cryptographic override seal.

export interface OverrideResponse {
    state_hash: string;
    override_seal: string | null;
    overridden_node_ids: string[];
}
