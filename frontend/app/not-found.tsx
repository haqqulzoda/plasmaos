'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';

export default function NotFound() {
  const t = useTranslations('common.notFound');
  return (
    <main className="grid min-h-screen place-items-center bg-gray-950 p-6 text-white">
      <section className="w-full max-w-lg rounded-xl border border-gray-800 bg-gray-900 p-8 text-center">
        <p className="text-sm font-semibold text-cyan-300">404</p>
        <h1 className="mt-2 text-2xl font-semibold">{t('title')}</h1>
        <p className="mt-3 text-sm text-gray-400">{t('help')}</p>
        <Link href="/dashboard" className="mt-6 inline-flex min-h-11 items-center rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold hover:bg-cyan-500">
          {t('back')}
        </Link>
      </section>
    </main>
  );
}
