import Image from 'next/image';

/** Exact supplied artwork. Empty alt in lockups avoids repeating the wordmark. */
export function PlasmaMark({
  decorative = false,
  size = 'md',
}: {
  decorative?: boolean;
  size?: 'sm' | 'md' | 'lg';
}) {
  return (
    <Image
      src="/brand/plasma-mark.svg"
      width={36}
      height={39}
      alt={decorative ? '' : 'Plasma AI'}
      className={`plasma-mark plasma-mark-${size}`}
      unoptimized
    />
  );
}
export function PlasmaLogo({ admin = false }: { admin?: boolean }) {
  return (
    <span className="plasma-logo">
      <PlasmaMark decorative />
      <span className="plasma-wordmark">
        {admin ? 'Admin Console' : 'Plasma AI'}
        {admin && <small>Plasma AI</small>}
      </span>
    </span>
  );
}
