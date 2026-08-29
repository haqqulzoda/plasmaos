import { permanentRedirect } from 'next/navigation';

export default function LegacyProposalsRedirect() {
    permanentRedirect('/dashboard/bid-preparation');
}
