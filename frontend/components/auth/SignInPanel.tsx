'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { signIn } from 'next-auth/react';
import { useTranslations } from 'next-intl';
import { ArrowLeft, Mail } from 'lucide-react';

import { TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Feedback';
import { Input } from '@/components/ui/Forms';

/* ── SVG: Google "G" icon ─────────────────────────────────────────────── */
export function GoogleIcon({ className }: { className?: string }) {
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

type CodeError = 'invalid_code' | 'code_expired' | 'rate_limited' | 'account_unavailable' | 'unavailable' | 'invalid_email';
const CODE_ERRORS: readonly CodeError[] = ['invalid_code', 'code_expired', 'rate_limited', 'account_unavailable', 'unavailable', 'invalid_email'];

function asCodeError(value: unknown): CodeError {
  return CODE_ERRORS.includes(value as CodeError) ? (value as CodeError) : 'invalid_code';
}

/**
 * P1 sign-in: Google, or a 6-digit code sent by e-mail. Both reach the same account for the
 * same verified address; an open invitation for that address is accepted either way.
 */
export function SignInPanel({ callbackUrl, googleLabel }: { callbackUrl: string; googleLabel?: string }) {
  const t = useTranslations('auth');
  const [googleLoading, setGoogleLoading] = useState(false);
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CodeError | null>(null);
  const [resendIn, setResendIn] = useState(0);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setTimeout(() => setResendIn((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  const requestCode = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch('/api/v1/auth/email/request-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
        cache: 'no-store',
      });
      if (response.status === 429) {
        const retryAfter = Number(response.headers.get('Retry-After') ?? '60');
        setResendIn(Number.isFinite(retryAfter) ? Math.min(retryAfter, 3600) : 60);
        setError('rate_limited');
        return;
      }
      if (response.status === 422) {
        setError('invalid_email');
        return;
      }
      if (!response.ok) {
        setError('unavailable');
        return;
      }
      const body = (await response.json()) as { resend_after_seconds?: number };
      setResendIn(body.resend_after_seconds ?? 60);
      setCode('');
      setStep('code');
    } catch {
      setError('unavailable');
    } finally {
      setBusy(false);
    }
  };

  const submitEmail = (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) return;
    void requestCode();
  };

  const submitCode = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await signIn('email-code', {
        email: email.trim(),
        code: code.replace(/\s+/g, ''),
        redirect: false,
        redirectTo: callbackUrl,
      });
      if (!result || result.error) {
        setError(asCodeError(result?.code));
        if (result?.code === 'code_expired') setCode('');
        return;
      }
      window.location.assign(result.url && result.url.startsWith(window.location.origin) ? result.url : callbackUrl);
    } catch {
      setError('unavailable');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-methods" data-sign-in-panel>
      <Button
        type="button"
        size="lg"
        loading={googleLoading}
        disabled={googleLoading || busy}
        onClick={() => {
          setGoogleLoading(true);
          void signIn('google', { callbackUrl });
        }}
        leadingIcon={!googleLoading ? <GoogleIcon /> : undefined}
      >
        {googleLoading ? t('connecting') : (googleLabel ?? t('continueWithGoogle'))}
      </Button>

      <div className="auth-divider" role="separator"><span>{t('emailCode.or')}</span></div>

      {step === 'email' ? (
        <form className="auth-code-form" onSubmit={submitEmail} noValidate>
          <Input
            label={t('emailCode.emailLabel')}
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            dir="ltr"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            helper={t('emailCode.emailHelp')}
          />
          {error && <Alert tone={error === 'rate_limited' ? 'warning' : 'danger'} title={t(`emailCode.errors.${error}`)} />}
          <Button type="submit" variant="secondary" size="lg" loading={busy} disabled={busy || !email.trim() || resendIn > 0}
            leadingIcon={!busy ? <Mail aria-hidden /> : undefined}>
            {resendIn > 0 ? t('emailCode.resendIn', { seconds: resendIn }) : t('emailCode.sendCode')}
          </Button>
        </form>
      ) : (
        <form className="auth-code-form" onSubmit={(event) => void submitCode(event)} noValidate>
          <p className="ds-muted auth-code-sent" role="status">
            {t('emailCode.sentTo')} <strong><TechnicalText>{email.trim()}</TechnicalText></strong>
          </p>
          <Input
            autoFocus
            label={t('emailCode.codeLabel')}
            name="code"
            autoComplete="one-time-code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            dir="ltr"
            className="auth-code-input"
            required
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            helper={t('emailCode.codeHelp')}
            data-code-input
          />
          {error && <Alert tone={error === 'rate_limited' ? 'warning' : 'danger'} title={t(`emailCode.errors.${error}`)} />}
          <Button type="submit" size="lg" loading={busy} disabled={busy || code.length !== 6}>
            {t('emailCode.signIn')}
          </Button>
          <div className="auth-code-actions">
            <Button type="button" variant="ghost" size="sm" leadingIcon={<ArrowLeft className="rtl-mirror" aria-hidden />}
              onClick={() => { setStep('email'); setError(null); setCode(''); }}>
              {t('emailCode.changeEmail')}
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={busy || resendIn > 0} onClick={() => void requestCode()}>
              {resendIn > 0 ? t('emailCode.resendIn', { seconds: resendIn }) : t('emailCode.resend')}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
