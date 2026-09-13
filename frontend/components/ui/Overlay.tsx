'use client';
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { X } from 'lucide-react';
import { Button } from './Button';
type OverlayProps = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  closeLabel: string;
  children: ReactNode;
  footer?: ReactNode;
  side?: 'start' | 'end';
  initialFocusRef?: RefObject<HTMLElement | null>;
};
/** Native modal supplies inert background, focus containment, Escape and restoration. */
function Overlay({
  open,
  onClose,
  title,
  description,
  closeLabel,
  children,
  footer,
  side,
  initialFocusRef,
  drawer = false,
}: OverlayProps & { drawer?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descId = useId();
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      initialFocusRef?.current?.focus();
    } else if (!open && dialog.open) dialog.close();
  }, [open, initialFocusRef]);
  useEffect(() => {
    if (!open) return;
    const old = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = old;
    };
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={`ds-overlay ${drawer ? `ds-drawer ds-drawer-${side || 'end'}` : ''}`}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onCancel={(e) => {
        e.preventDefault();
        onCloseRef.current();
      }}
      onClose={() => onCloseRef.current()}
      onKeyDown={(e) => {
        if (e.key !== 'Tab') return;
        const controls = Array.from(
          e.currentTarget.querySelectorAll<HTMLElement>(
            'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const box = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < box.left ||
            e.clientX > box.right ||
            e.clientY < box.top ||
            e.clientY > box.bottom
          )
            onCloseRef.current();
        }
      }}
    >
      <header>
        <div>
          <h2 id={titleId}>{title}</h2>
          {description && (
            <p className="ds-muted" id={descId}>
              {description}
            </p>
          )}
        </div>
        <Button variant="icon" aria-label={closeLabel} onClick={onClose}>
          <X aria-hidden />
        </Button>
      </header>
      {children}
      {footer && <footer>{footer}</footer>}
    </dialog>
  );
}
export function Dialog(props: OverlayProps) {
  return <Overlay {...props} />;
}
export function Drawer(props: OverlayProps) {
  return <Overlay {...props} drawer />;
}
export function Popover({
  label,
  trigger,
  children,
  menu = false,
}: {
  label: string;
  trigger: ReactNode;
  children: ReactNode;
  menu?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    if (menu) {
      panel.current?.querySelectorAll<HTMLElement>('a, button').forEach(item => item.setAttribute('role', 'menuitem'));
      panel.current?.querySelector<HTMLElement>('a, button:not(:disabled)')?.focus();
    }
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [open, menu]);
  return (
    <div
      className="ds-popover-wrap"
      ref={root}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={button}
        className="ds-button ds-button-ghost"
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        aria-haspopup={menu ? 'menu' : undefined}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        {trigger}
      </button>
      {open && (
        <div
          id={id}
          ref={panel}
          className="ds-popover"
          role={menu ? 'menu' : undefined}
          aria-label={menu ? label : undefined}
          onClick={(e) => {
            if ((e.target as HTMLElement).closest('a,button')) {
              button.current?.focus();
              setOpen(false);
            }
          }}
          onKeyDown={(e) => {
            if (
              !menu ||
              !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)
            )
              return;
            const controls = Array.from(
              e.currentTarget.querySelectorAll<HTMLElement>(
                'a,button:not(:disabled)',
              ),
            );
            const i = controls.indexOf(document.activeElement as HTMLElement);
            const next =
              e.key === 'Home'
                ? 0
                : e.key === 'End'
                  ? controls.length - 1
                  : (i + (e.key === 'ArrowDown' ? 1 : -1) + controls.length) %
                    controls.length;
            e.preventDefault();
            controls[next]?.focus();
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}
export function Dropdown(props: Omit<Parameters<typeof Popover>[0], 'menu'>) {
  return <Popover {...props} menu />;
}
