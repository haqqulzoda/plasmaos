'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export type ServiceOption = {
    value: string;
    label: string;
};

export const DEFAULT_SERVICE_OPTIONS: ServiceOption[] = [
    { value: 'construction', label: 'Construction' },
    { value: 'medical', label: 'Medical' },
    { value: 'IT', label: 'IT' },
    { value: 'industrial services', label: 'Industrial Services' },
    { value: 'consulting', label: 'Consulting' },
    { value: 'equipment supply', label: 'Equipment Supply' },
    { value: 'other', label: 'Other' },
];

function normalizeServiceOptions(values: unknown): ServiceOption[] {
    if (!Array.isArray(values)) {
        return DEFAULT_SERVICE_OPTIONS;
    }

    const normalized: ServiceOption[] = [];
    const seen = new Set<string>();

    values.forEach((item) => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
            return;
        }

        const value = (item as { value?: unknown }).value;
        const label = (item as { label?: unknown }).label;
        if (typeof value !== 'string' || typeof label !== 'string') {
            return;
        }

        const cleanedValue = value.trim();
        const cleanedLabel = label.trim();
        const key = cleanedValue.toLowerCase();
        if (cleanedValue && cleanedLabel && !seen.has(key)) {
            normalized.push({ value: cleanedValue, label: cleanedLabel });
            seen.add(key);
        }
    });

    return normalized.length > 0 ? normalized : DEFAULT_SERVICE_OPTIONS;
}

export function serviceValueSet(options: ServiceOption[]): Set<string> {
    return new Set(options.map((option) => option.value));
}

export function labelForService(
    value: string | null | undefined,
    options: ServiceOption[],
): string {
    if (!value) {
        return '';
    }

    return options.find((option) => option.value === value)?.label ?? value;
}

export function useServiceMeta(): ServiceOption[] {
    const [services, setServices] = useState<ServiceOption[]>(DEFAULT_SERVICE_OPTIONS);

    useEffect(() => {
        let mounted = true;

        api.get<ServiceOption[]>('/meta/services')
            .then((response) => {
                if (mounted) {
                    setServices(normalizeServiceOptions(response.data));
                }
            })
            .catch(() => {
                if (mounted) {
                    setServices(DEFAULT_SERVICE_OPTIONS);
                }
            });

        return () => {
            mounted = false;
        };
    }, []);

    return services;
}
