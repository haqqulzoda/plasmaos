/**
 * Plasma AI — Hunter Feed
 *
 * TypeScript interfaces for the Hunter recommendation feed.
 */

export interface HunterTender {
    id: string;
    title: string;
    budget: number;
    currency: string;
    deadline: string | null;
}

export interface HunterRecommendation {
    id: string;
    match_score: number;
    strategic_rationale: string;
    created_at: string;
    tender: HunterTender;
}
