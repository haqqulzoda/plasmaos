'use client';

import { PlasmaLogo } from '@/components/brand/PlasmaLogo';
import { LanguageSelector } from '@/components/i18n/LanguageSelector';
import { Button } from '@/components/ui/Button';
import { getSession, signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle2 } from 'lucide-react';

/* ── SVG: Google "G" icon ─────────────────────────────────────────────── */
function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23Z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09A6.97 6.97 0 0 1 5.47 12c0-.72.13-1.43.37-2.09V7.07H2.18A11.96 11.96 0 0 0 0 12c0 1.94.46 3.77 1.28 5.4l3.56-2.77.01-.54Z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 1.99 14.97.96 12 .96 7.7.96 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53Z"
        fill="#EA4335"
      />
    </svg>
  );
}

export default function LoginPage() {
  const t = useTranslations('auth');
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const hydrate = async () => {
      const session = await getSession();
      if (session) {
        router.replace('/dashboard');
      }
    };
    hydrate().catch(() => undefined);
  }, [router]);

  const handleSignIn = () => {
    setIsLoading(true);
    signIn('google', { callbackUrl: '/dashboard' });
  };

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
          <Button
            type="button"
            size="lg"
            loading={isLoading}
            disabled={isLoading}
            onClick={handleSignIn}
            leadingIcon={!isLoading ? <GoogleIcon /> : undefined}
          >
            {isLoading ? t('connecting') : t('continueWithGoogle')}
          </Button>
          <p className="auth-privacy ds-muted">{t('privacyNote')}</p>
        </div>
      </section>
      <footer className="auth-footer ds-muted">© {new Date().getFullYear()} Plasma AI</footer>
    </main>
  );
}
