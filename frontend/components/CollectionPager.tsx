'use client';

import {useTranslations} from 'next-intl';

export function CollectionPager({offset, hasMore, onChange, busy = false}: {
  offset: number; hasMore: boolean; onChange: (offset: number) => void; busy?: boolean;
}) {
  const t = useTranslations('common');
  return <div className="flex flex-wrap items-center gap-3 py-3">
    <button type="button" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - 25))}
      className="rounded border px-3 py-2 disabled:opacity-40 focus-visible:ring-2">{t('actions.previous')}</button>
    <button type="button" disabled={busy || !hasMore} onClick={() => onChange(offset + 25)}
      className="rounded border px-3 py-2 disabled:opacity-40 focus-visible:ring-2">{t('actions.next')}</button>
  </div>;
}
