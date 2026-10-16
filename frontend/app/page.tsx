'use client';

import { SignInPanel } from '@/components/auth/SignInPanel';
import { PlasmaLogo } from '@/components/brand/PlasmaLogo';
import { LanguageSelector } from '@/components/i18n/LanguageSelector';
import { getSession } from 'next-auth/react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle2 } from 'lucide-react';

/** Only same-origin paths may follow sign-in (the proxy adds ?next=<path>). */
function safeNext(value: string | null): string {
  return value && value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') ? value : '/dashboard';
}

export default function LoginPage() {
  return <Suspense fallback={null}><LoginContent /></Suspense>;
}

function LoginContent() {
  const t = useTranslations('auth');
  const router = useRouter();
  const callbackUrl = safeNext(useSearchParams().get('next'));

  useEffect(() => {
    const hydrate = async () => {
      const session = await getSession();
      if (session) {
        router.replace(callbackUrl);
      }
    };
    hydrate().catch(() => undefined);
  }, [callbackUrl, router]);

  return (
    <main className="ds-theme auth-page">
      <header className="auth-header">
        <PlasmaLogo />
        <LanguageSelector surface="auth" />
      </header>
      <section className="auth-layout" aria-labelledby="auth-title">
        <div className="auth-copy">
          <span className="ds-eyebrow">{t('platformLabel')}</span>
          <h1 id="auth-title">{t('welcomeBack')}</h1>
          <p className="ds-muted">{t('workspaceHelp')}</p>
          <ul className="auth-benefits">
            <li><CheckCircle2 aria-hidden />{t('benefitExplorer')}</li>
            <li><CheckCircle2 aria-hidden />{t('benefitReadiness')}</li>
            <li><CheckCircle2 aria-hidden />{t('benefitCompliance')}</li>
          </ul>
        </div>
        <div className="ds-surface auth-card">
          <h2>{t('signInTitle')}</h2>
          <p className="ds-muted">{t('signInHelp')}</p>
          <SignInPanel callbackUrl={callbackUrl} />
          <p className="auth-privacy ds-muted">{t('privacyNote')}</p>
        </div>
      </section>
      <footer className="auth-footer ds-muted">© {new Date().getFullYear()} Plasma AI</footer>
    </main>
  );
}
