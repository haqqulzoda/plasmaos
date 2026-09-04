'use client';

import { getSession, signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';

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

/* ── SVG: Spinner ─────────────────────────────────────────────────────── */
function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className ?? ''}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8V0C5.37 0 0 5.37 0 12h4Z"
      />
    </svg>
  );
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  LOGIN PAGE                                                          */
/* ══════════════════════════════════════════════════════════════════════ */
export default function LoginPage() {
  const t = useTranslations('auth');
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  /* ── Existing session-hydration logic (untouched) ──────────────────── */
  useEffect(() => {
    const hydrate = async () => {
      const session = await getSession();
      if (session) {
        router.replace('/dashboard');
      }
    };
    hydrate().catch(() => undefined);
  }, [router]);

  /* ── Sign-in handler ─────────────────────────────────────────────── */
  const handleSignIn = () => {
    setIsLoading(true);
    signIn('google', { callbackUrl: '/dashboard' });
  };

  return (
    <div className="min-h-screen flex">
      {/* ─── Left Panel · Auth ────────────────────────────────────────── */}
      <div className="w-full lg:w-1/2 bg-gray-950 flex items-center justify-center px-6 py-12">
        <div className="max-w-md w-full space-y-10">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
              <span className="text-white font-bold text-lg">P</span>
            </div>
            <span className="text-white text-xl font-semibold tracking-tight">
              Plasma AI
            </span>
          </div>

          {/* Headlines */}
          <div className="space-y-3">
            <h1 className="text-3xl sm:text-4xl font-bold text-white leading-tight">
              {t('welcomeBack')}
            </h1>
            <p className="text-gray-400 text-base leading-relaxed">
              Sign in to your workspace to continue managing tenders, compliance, and strategic proposals.
            </p>
          </div>

          {/* Google Button */}
          <div className="space-y-6">
            <button
              type="button"
              disabled={isLoading}
              onClick={handleSignIn}
              className="flex items-center justify-center gap-3 w-full px-4 py-3.5 border border-gray-700/80 rounded-xl bg-gray-900 text-white font-medium text-sm hover:bg-gray-800 hover:border-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <Spinner className="h-5 w-5 text-gray-400" />
              ) : (
                <GoogleIcon className="h-5 w-5" />
              )}
              {isLoading ? t('connecting') : t('continueWithGoogle')}
            </button>

            <p className="text-center text-xs text-gray-600">
              By continuing you agree to our{' '}
              <span className="text-gray-500 hover:text-gray-400 cursor-pointer transition-colors">
                Terms of Service
              </span>{' '}
              and{' '}
              <span className="text-gray-500 hover:text-gray-400 cursor-pointer transition-colors">
                Privacy Policy
              </span>
            </p>
          </div>

          {/* Footer */}
          <div className="pt-8 border-t border-gray-800/60">
            <p className="text-xs text-gray-600">
              © {new Date().getFullYear()} Plasma AI · Enterprise Tender Intelligence
            </p>
          </div>
        </div>
      </div>

      {/* ─── Right Panel · Branding ───────────────────────────────────── */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-indigo-950 via-purple-950 to-black items-center justify-center">
        {/* Decorative glows */}
        <div className="absolute -top-40 -right-40 w-[500px] h-[500px] rounded-full bg-indigo-600/20 blur-[120px]" />
        <div className="absolute -bottom-40 -left-40 w-[500px] h-[500px] rounded-full bg-purple-600/20 blur-[120px]" />

        {/* Grid pattern overlay */}
        <div
          className="absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />

        {/* Value prop content */}
        <div className="relative z-10 max-w-lg px-12 space-y-8">
          <div className="space-y-4">
            <p className="text-indigo-300 text-sm font-semibold tracking-widest uppercase">
              Enterprise Platform
            </p>
            <h2 className="text-4xl xl:text-5xl font-bold text-white leading-[1.15]">
              Tender Intelligence,{' '}
              <span className="bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
                Automated.
              </span>
            </h2>
            <p className="text-gray-400 text-lg leading-relaxed">
              From document parsing to compliance scoring — one agentic pipeline that handles the heavy lifting so your team can focus on winning.
            </p>
          </div>

          {/* Stats row */}
          <div className="grid grid-cols-3 gap-6 pt-4">
            {[
              { value: '95%', label: 'Accuracy' },
              { value: '10×', label: 'Faster' },
              { value: '24/7', label: 'Monitoring' },
            ].map((stat) => (
              <div key={stat.label} className="space-y-1">
                <p className="text-2xl font-bold text-white">{stat.value}</p>
                <p className="text-xs text-gray-500 uppercase tracking-wider">
                  {stat.label}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
