'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export const REGION_OPTIONS = [
    'Central Asia',
    'Asia',
    'Europe',
    'Africa',
    'North America',
    'Latin America',
] as const;

export const CENTRAL_ASIA_REGION = 'Central Asia';

export const CENTRAL_ASIA_COUNTRIES = [
    'Uzbekistan',
    'Kazakhstan',
    'Kyrgyzstan',
    'Tajikistan',
    'Turkmenistan',
] as const;

export type GeographyMeta = {
    regions: string[];
    countries_by_region: Record<string, string[]>;
    central_asia_countries: string[];
};

export const DEFAULT_GEOGRAPHY_META: GeographyMeta = {
    regions: [...REGION_OPTIONS],
    countries_by_region: {
        [CENTRAL_ASIA_REGION]: [...CENTRAL_ASIA_COUNTRIES],
        Asia: [],
        Europe: [],
        Africa: [],
        'North America': [],
        'Latin America': [],
    },
    central_asia_countries: [...CENTRAL_ASIA_COUNTRIES],
};

function normalizeList(values: unknown, fallback: string[]): string[] {
    if (!Array.isArray(values)) {
        return fallback;
    }

    const normalized: string[] = [];
    const seen = new Set<string>();

    values.forEach((value) => {
        if (typeof value !== 'string') {
            return;
        }
        const cleaned = value.trim();
        const key = cleaned.toLowerCase();
        if (cleaned && !seen.has(key)) {
            normalized.push(cleaned);
            seen.add(key);
        }
    });

    return normalized.length > 0 ? normalized : fallback;
}

function normalizeCountriesByRegion(
    value: unknown,
    regions: string[],
): Record<string, string[]> {
    const fallback = DEFAULT_GEOGRAPHY_META.countries_by_region;
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return fallback;
    }

    return regions.reduce<Record<string, string[]>>((current, region) => {
        current[region] = normalizeList(
            (value as Record<string, unknown>)[region],
            fallback[region] ?? [],
        );
        return current;
    }, {});
}

export function normalizeGeographyMeta(data: Partial<GeographyMeta> | null | undefined): GeographyMeta {
    const regions = normalizeList(data?.regions, DEFAULT_GEOGRAPHY_META.regions);
    const centralAsiaCountries = normalizeList(
        data?.central_asia_countries,
        DEFAULT_GEOGRAPHY_META.central_asia_countries,
    );
    const countriesByRegion = normalizeCountriesByRegion(data?.countries_by_region, regions);

    countriesByRegion[CENTRAL_ASIA_REGION] = centralAsiaCountries;

    return {
        regions,
        countries_by_region: countriesByRegion,
        central_asia_countries: centralAsiaCountries,
    };
}

export function useGeographyMeta(): GeographyMeta {
    const [geography, setGeography] = useState<GeographyMeta>(DEFAULT_GEOGRAPHY_META);

    useEffect(() => {
        let mounted = true;

        api.get<Partial<GeographyMeta>>('/meta/geography')
            .then((response) => {
                if (mounted) {
                    setGeography(normalizeGeographyMeta(response.data));
                }
            })
            .catch(() => {
                if (mounted) {
                    setGeography(DEFAULT_GEOGRAPHY_META);
                }
            });

        return () => {
            mounted = false;
        };
    }, []);

    return geography;
}
