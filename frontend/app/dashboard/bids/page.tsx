import { permanentRedirect } from 'next/navigation';

export default function LegacyBidsRedirect() {
    permanentRedirect('/dashboard/my-tenders');
}
