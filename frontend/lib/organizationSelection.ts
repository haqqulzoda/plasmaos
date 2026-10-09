/**
 * R3 Task 6: the organization the customer works in.
 *
 * Every request carries it as X-Organization-ID (unless a page names one itself), so the
 * backend resolves the same organization's company profile for Explorer, Dashboard,
 * Readiness and Pursuits. Kept per browser; validated against the user's organizations.
 * Import-free for the node test runner.
 */

export const SELECTED_ORGANIZATION_KEY = 'plasma.selectedOrganization';
export const SELECTED_ORGANIZATION_EVENT = 'plasma:organization-selected';

export function readSelectedOrganization(): string | null {
    try {
        return typeof window === 'undefined' ? null : window.localStorage.getItem(SELECTED_ORGANIZATION_KEY);
    } catch {
        return null;
    }
}

export function writeSelectedOrganization(organizationId: string | null): void {
    try {
        if (typeof window === 'undefined') return;
        if (organizationId) window.localStorage.setItem(SELECTED_ORGANIZATION_KEY, organizationId);
        else window.localStorage.removeItem(SELECTED_ORGANIZATION_KEY);
        window.dispatchEvent(new CustomEvent(SELECTED_ORGANIZATION_EVENT, { detail: organizationId }));
    } catch {
        // Storage can be unavailable (private mode); the backend default organization applies.
    }
}

/** The stored choice when the user is still an ACTIVE member of it, else null. */
export function validSelection(
    organizations: readonly { organization_id: string; membership_state?: string | null }[],
    stored: string | null,
): string | null {
    if (!stored) return null;
    return organizations.some((item) => item.organization_id === stored && (item.membership_state ?? 'ACTIVE') === 'ACTIVE')
        ? stored
        : null;
}

/** Which organization a page should use: the valid stored choice, else the only one, else none. */
export function pageOrganization(
    organizations: readonly { organization_id: string; membership_state?: string | null }[],
    stored: string | null,
): string | null {
    const selected = validSelection(organizations, stored);
    if (selected) return selected;
    const active = organizations.filter((item) => (item.membership_state ?? 'ACTIVE') === 'ACTIVE');
    return active.length === 1 ? active[0].organization_id : null;
}

/** The header the API client adds when a request does not name an organization itself. */
export function organizationHeader(existing: string | null | undefined, stored: string | null): string | null {
    if (existing) return null;
    return stored || null;
}
