'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { signIn } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { AlertTriangle, ArrowLeft, RefreshCw } from 'lucide-react';

import { PlasmaLogo } from '@/components/brand/PlasmaLogo';
import { TechnicalText } from '@/components/i18n/BidiText';
import { LanguageSelector } from '@/components/i18n/LanguageSelector';
import { Button } from '@/components/ui/Button';
import { authErrorKind } from '@/lib/authError';

/**
 * Sign-in error page (Auth.js `pages.error`). Replaces the built-in "Server error"
 * screen with a localized explanation of what happened and what to do next.
 */
function AuthError() {
  const t = useTranslations('auth.authError');
  const code = useSearchParams().get('error');
  const kind = authErrorKind(code);
  return (
    <main className="ds-theme auth-page" data-auth-error={kind}>
      <header className="auth-header">
        <PlasmaLogo />
        <LanguageSelector surface="auth" />
      </header>
      <section className="auth-error" aria-labelledby="auth-error-title">
        <div className="ds-surface auth-card auth-error-card">
          <span className="auth-error-icon" aria-hidden><AlertTriangle /></span>
          <span className="ds-eyebrow">{t('eyebrow')}</span>
          <h1 id="auth-error-title">{t(`${kind}.title`)}</h1>
          <p>{t(`${kind}.body`)}</p>
          <p className="ds-muted">{t(`${kind}.hint`)}</p>
          <div className="auth-error-actions">
            <Button size="lg" leadingIcon={<RefreshCw aria-hidden />}
              onClick={() => signIn('google', { callbackUrl: '/dashboard' })}>
              {t('tryAgain')}
            </Button>
            <Link className="ds-button ds-button-secondary ds-button-lg" href="/" prefetch={false}>
              <ArrowLeft aria-hidden />
              {t('backToSignIn')}
            </Link>
          </div>
          {code && <p className="auth-error-code ds-muted">
            {t('errorCode')} <TechnicalText>{code.slice(0, 64)}</TechnicalText>
          </p>}
        </div>
      </section>
    </main>
  );
}

export default function AuthErrorPage() {
  return <Suspense fallback={null}><AuthError /></Suspense>;
}
