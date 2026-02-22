/**
 * Plasma AI — Sovereign Compliance Engine
 *
 * TypeScript interfaces for the Gap Analysis data contract
 * between the backend AI analyzer and the frontend Strategy Panel.
 */

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

export interface AnalyzeTenderResponse {
    analysis_id: string;
    analysis: GapAnalysis;
}
