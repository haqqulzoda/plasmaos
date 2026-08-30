import { api } from '@/lib/api';
import type {
    ExplorerListParams,
    ExplorerResponse,
    RecommendationCommandResponse,
} from '@/types/explorer';

export const listExplorer = (
    params: ExplorerListParams,
    signal?: AbortSignal,
) => api.get<ExplorerResponse>('/explorer/tenders', { params, signal });

export const dismissRecommendation = (recommendationId: string) =>
    api.post<RecommendationCommandResponse>(
        `/recommendations/${recommendationId}/dismiss`,
    );

export const restoreRecommendation = (recommendationId: string) =>
    api.post<RecommendationCommandResponse>(
        `/recommendations/${recommendationId}/restore`,
    );
