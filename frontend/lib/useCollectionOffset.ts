'use client';
import {usePathname, useRouter, useSearchParams} from 'next/navigation';

export function useCollectionOffset(key = 'page') {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const page = Math.min(1000000, Math.max(1, Math.floor(Number(params.get(key)) || 1)));
  const setOffset = (offset: number) => {
    const next = new URLSearchParams(params.toString());
    if (offset === 0) next.delete(key);
    else next.set(key, String(Math.floor(offset / 25) + 1));
    router.replace(`${pathname}${next.size ? `?${next}` : ''}`, {scroll: false});
  };
  return [25 * (page - 1), setOffset] as const;
}
