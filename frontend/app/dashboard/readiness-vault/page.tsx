import { permanentRedirect } from 'next/navigation';

// S1: the Readiness Vault lives under Company & Experience.
export default function LegacyReadinessVaultRedirect() {
    permanentRedirect('/dashboard/settings/readiness');
}
