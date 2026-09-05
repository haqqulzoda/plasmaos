import type {ComponentPropsWithoutRef, ReactNode} from 'react';

type BidiTextProps = Readonly<{
  children: ReactNode;
  className?: string;
  direction?: 'auto' | 'ltr' | 'rtl';
}> & Omit<ComponentPropsWithoutRef<'bdi'>, 'children' | 'dir'>;

/** Smallest-possible isolation for source and user-owned natural text. */
export function BidiText({children, className = '', direction = 'auto', ...props}: BidiTextProps) {
  return (
    <bdi
      {...props}
      dir={direction}
      className={`${direction === 'auto' ? 'bidi-auto' : 'bidi-isolate'} ${className}`.trim()}
    >
      {children}
    </bdi>
  );
}

/** Explicit LTR/isolate wrapper for identifiers, URLs, email, and phone values. */
export function TechnicalText({children, className = '', ...props}: Omit<BidiTextProps, 'direction'>) {
  return <BidiText {...props} direction="ltr" className={`technical-ltr ${className}`.trim()}>{children}</BidiText>;
}
