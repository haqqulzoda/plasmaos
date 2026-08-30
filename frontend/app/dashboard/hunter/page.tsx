import { redirect } from 'next/navigation';

/**
 * Passive compatibility route for historical customer bookmarks.
 *
 * Legacy Hunter query parameters had no supported filter contract, so they
 * are intentionally not mapped into Tender Explorer filters.
 */
export default function HunterCompatibilityRedirect() {
    redirect('/dashboard/tenders?view=recommended');
}
