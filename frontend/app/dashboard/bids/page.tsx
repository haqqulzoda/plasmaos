import { redirect } from 'next/navigation';

export default function LegacyBidsRedirect() {
    redirect('/dashboard/bid-preparation');
}
