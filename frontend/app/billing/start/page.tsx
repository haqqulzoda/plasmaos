import { redirect } from 'next/navigation';

/** B1: the public checkout link (/billing/start?plan=…) opens the checkout inside the signed-in app. */
export default async function BillingStartRedirect({ searchParams }: { searchParams: Promise<{ plan?: string | string[] }> }) {
  const { plan } = await searchParams;
  const value = Array.isArray(plan) ? plan[0] : plan;
  redirect(value ? `/dashboard/billing/start?plan=${encodeURIComponent(value)}` : '/dashboard/billing');
}
