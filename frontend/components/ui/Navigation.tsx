'use client';
import { useId, type ReactNode } from 'react';
import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { BidiText } from '@/components/i18n/BidiText';
import { Radio } from './Forms';
import { Button } from './Button';
type Option = { value: string; label: ReactNode; disabled?: boolean };
export function SegmentedControl({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Option[];
}) {
  const name = useId();
  return (
    <fieldset className="ds-segments">
      <legend className="sr-only">{label}</legend>
      {options.map((option) => (
        <Radio
          key={option.value}
          name={name}
          value={option.value}
          label={option.label}
          checked={value === option.value}
          disabled={option.disabled}
          onChange={() => onChange(option.value)}
        />
      ))}
    </fieldset>
  );
}
export function Tabs({
  label,
  value,
  onChange,
  items,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  items: (Option & { content: ReactNode })[];
}) {
  const id = useId();
  return (
    <div className="ds-stack">
      <div
        className="ds-tabs"
        role="tablist"
        aria-label={label}
        onKeyDown={(e) => {
          const rtl = getComputedStyle(e.currentTarget).direction === 'rtl';
          const enabled = items.filter((item) => !item.disabled);
          const index = enabled.findIndex((item) => item.value === value);
          let next = index;
          if (e.key === 'ArrowRight') next += rtl ? -1 : 1;
          else if (e.key === 'ArrowLeft') next += rtl ? 1 : -1;
          else if (e.key === 'Home') next = 0;
          else if (e.key === 'End') next = enabled.length - 1;
          else return;
          e.preventDefault();
          const item = enabled[(next + enabled.length) % enabled.length];
          if (item) {
            onChange(item.value);
            document.getElementById(`${id}-tab-${item.value}`)?.focus();
          }
        }}
      >
        {items.map((item) => (
          <Button
            key={item.value}
            variant="ghost"
            className="ds-tab"
            role="tab"
            id={`${id}-tab-${item.value}`}
            aria-controls={`${id}-panel-${item.value}`}
            aria-selected={item.value === value}
            tabIndex={item.value === value ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.value)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      {items.map((item) => (
        <div
          key={item.value}
          role="tabpanel"
          id={`${id}-panel-${item.value}`}
          aria-labelledby={`${id}-tab-${item.value}`}
          hidden={value !== item.value}
          tabIndex={0}
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
export function Breadcrumbs({
  label,
  items,
}: {
  label: string;
  items: { label: ReactNode; href?: string }[];
}) {
  return (
    <nav aria-label={label}>
      <ol className="ds-breadcrumbs">
        {items.map((item, i) => (
          <li key={i}>
            {i > 0 && <ChevronRight className="rtl-mirror" aria-hidden />}
            {item.href ? (
              <Link href={item.href} prefetch={false}>
                <BidiText>{item.label}</BidiText>
              </Link>
            ) : (
              <span aria-current="page">
                <BidiText>{item.label}</BidiText>
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
export function Pagination({
  label,
  previousLabel,
  nextLabel,
  hasPrevious,
  hasNext,
  busy,
  onPrevious,
  onNext,
  children,
}: {
  label: string;
  previousLabel: string;
  nextLabel: string;
  hasPrevious: boolean;
  hasNext: boolean;
  busy?: boolean;
  onPrevious: () => void;
  onNext: () => void;
  children?: ReactNode;
}) {
  return (
    <nav className="ds-row" aria-label={label}>
      <Button
        variant="secondary"
        disabled={busy || !hasPrevious}
        onClick={onPrevious}
      >
        {previousLabel}
      </Button>
      {children}
      <Button variant="secondary" disabled={busy || !hasNext} onClick={onNext}>
        {nextLabel}
      </Button>
    </nav>
  );
}
