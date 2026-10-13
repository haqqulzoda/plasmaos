import { permanentRedirect } from 'next/navigation';

// S1: bids are prepared in Pursuits. Proposal pages (/dashboard/bid-preparation/<id>) still open.
export default function LegacyBidPreparationRedirect() {
    permanentRedirect('/dashboard/my-tenders');
}
