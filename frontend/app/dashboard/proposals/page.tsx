import { redirect } from 'next/navigation';

export default function LegacyProposalsRedirect() {
    redirect('/dashboard/bid-preparation');
}
