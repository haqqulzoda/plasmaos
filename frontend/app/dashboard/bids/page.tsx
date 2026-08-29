import { permanentRedirect } from 'next/navigation';

export default function LegacyBidsRedirect() {
    permanentRedirect('/dashboard/bid-preparation');
}
