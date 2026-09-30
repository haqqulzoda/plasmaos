/**
 * Customer navigation (D1-07): one product, six destinations.
 *
 * Dashboard · Opportunities (Explorer) · Pursuits · Partners & Experts ·
 * Company & Experience · Notifications. Bid Preparation and Readiness Vault are no
 * longer menu items; their routes keep working and map onto the item they belong to,
 * so the active state and the top-bar context stay truthful on every page.
 */

export type CustomerNavigationKey =
    | 'dashboard'
    | 'opportunities'
    | 'pursuits'
    | 'partnersExperts'
    | 'companyExperience'
    | 'notifications';

export type CustomerNavigationItem = {
    nameKey: CustomerNavigationKey;
    href: string;
    /** Other route prefixes that belong to this destination. */
    also: readonly string[];
};

export const CUSTOMER_NAVIGATION: readonly CustomerNavigationItem[] = [
    {nameKey: 'dashboard', href: '/dashboard', also: []},
    {nameKey: 'opportunities', href: '/dashboard/tenders', also: []},
    {
        nameKey: 'pursuits',
        href: '/dashboard/my-tenders',
        also: ['/dashboard/pursuits', '/dashboard/uploaded-tenders', '/dashboard/bid-preparation'],
    },
    {nameKey: 'partnersExperts', href: '/dashboard/partners-experts', also: []},
    {nameKey: 'companyExperience', href: '/dashboard/settings', also: ['/dashboard/readiness-vault']},
    {nameKey: 'notifications', href: '/dashboard/notifications', also: []},
];

const under = (path: string, prefix: string) => path === prefix || path.startsWith(`${prefix}/`);

export function activeNavigationKey(path: string): CustomerNavigationKey | null {
    const clean = (path.split(/[?#]/, 1)[0] || '/').replace(/\/+$/, '') || '/';
    if (clean === '/dashboard') return 'dashboard';
    for (const item of CUSTOMER_NAVIGATION) {
        if (item.href === '/dashboard') continue;
        if (under(clean, item.href) || item.also.some((prefix) => under(clean, prefix))) return item.nameKey;
    }
    return null;
}
