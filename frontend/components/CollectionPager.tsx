'use client';

import {useTranslations} from 'next-intl';
import {Button} from '@/components/ui/Button';

export function CollectionPager({offset, hasMore, onChange, busy = false}: {
  offset: number; hasMore: boolean; onChange: (offset: number) => void; busy?: boolean;
}) {
  const t = useTranslations('common');
  return <div className="flex flex-wrap items-center gap-3 py-3">
    <Button variant="secondary" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - 25))}
      >{t('actions.previous')}</Button>
    <Button variant="secondary" disabled={busy || !hasMore} onClick={() => onChange(offset + 25)}
      >{t('actions.next')}</Button>
  </div>;
}
