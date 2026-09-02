import axios from 'axios';

import { api } from '@/lib/api';
import type {
    SourceCatalogItem,
    SourceRefreshActivityPage,
    SourceRefreshCommandResponse,
    SourceRefreshStatusItem,
} from '@/types/source-refresh';
import { ACTIVITY_PAGE_SIZE } from '@/lib/sourceRefreshPolicy';

export * from '@/lib/sourceRefreshPolicy';

export const listSourceCatalog = (signal?: AbortSignal) =>
    api.get<SourceCatalogItem[]>('/tenders/sources/catalog', { signal });

export const listSourceRefreshStatus = (signal?: AbortSignal) =>
    api.get<SourceRefreshStatusItem[]>('/tenders/sources/refresh-status', { signal });

export const listSourceRefreshActivity = (cursor: string, signal?: AbortSignal) =>
    api.get<SourceRefreshActivityPage>('/tenders/sources/refresh-activity', {
        params: { cursor, limit: ACTIVITY_PAGE_SIZE },
        signal,
    });

export const requestSourceRefresh = (sourceSystem: string) =>
    api.post<SourceRefreshCommandResponse>(
        `/tenders/sources/${encodeURIComponent(sourceSystem)}/refresh`,
    );

export const isInvalidActivityCursorError = (error: unknown): boolean =>
    axios.isAxiosError(error) && error.response?.status === 422;
