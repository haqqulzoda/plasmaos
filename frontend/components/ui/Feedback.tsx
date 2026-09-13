'use client';
import {
  useId,
  useState,
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from 'react';
import { AlertTriangle, Info, CheckCircle2, X } from 'lucide-react';
import { Button } from './Button';
export function Alert({
  tone = 'info',
  title,
  children,
  action,
  onDismiss,
  dismissLabel,
}: {
  tone?: 'info' | 'success' | 'warning' | 'danger';
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
}) {
  const Icon =
    tone === 'success' ? CheckCircle2 : tone === 'info' ? Info : AlertTriangle;
  return (
    <div
      className={`ds-alert ds-tone-${tone}`}
      role={tone === 'danger' ? 'alert' : 'status'}
    >
      <Icon aria-hidden />
      <div className="ds-alert-body">
        <strong>{title}</strong>
        {children && <p>{children}</p>}
        {action}
      </div>
      {onDismiss && dismissLabel && (
        <Button variant="icon" aria-label={dismissLabel} onClick={onDismiss}>
          <X aria-hidden />
        </Button>
      )}
    </div>
  );
}
/** Tooltip complements visible/accessible control labels; Escape dismisses it. */
export function Tooltip({
  content,
  children,
}: {
  content: string;
  children: ReactNode;
}) {
  const id = useId();
  const [dismissed, setDismissed] = useState(false);
  return (
    <span
      className="ds-tooltip-wrap"
      onMouseEnter={() => setDismissed(false)}
      onFocus={() => setDismissed(false)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setDismissed(true);
      }}
    >
      {isValidElement(children)
        ? cloneElement(
            children as ReactElement<{ 'aria-describedby'?: string }>,
            { 'aria-describedby': dismissed ? undefined : id },
          )
        : children}
      {!dismissed && (
        <span id={id} className="ds-tooltip" role="tooltip">
          {content}
        </span>
      )}
    </span>
  );
}
