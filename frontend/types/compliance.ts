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
