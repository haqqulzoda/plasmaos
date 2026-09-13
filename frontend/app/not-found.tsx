'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { PlasmaLogo } from '@/components/brand/PlasmaLogo';

export default function NotFound() {
  const t = useTranslations('common.notFound');
  return (
    <main className="ds-theme standalone-state">
      <section className="ds-surface standalone-state-card">
        <PlasmaLogo />
        <p className="ds-eyebrow">404</p>
        <h1>{t('title')}</h1>
        <p className="ds-muted">{t('help')}</p>
        <Link href="/dashboard" className="ds-button ds-button-primary">
          {t('back')}
        </Link>
      </section>
    </main>
  );
}
