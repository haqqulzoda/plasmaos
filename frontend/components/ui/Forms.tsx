'use client';
import {
  useId,
  useRef,
  type InputHTMLAttributes,
  type TextareaHTMLAttributes,
  type SelectHTMLAttributes,
  type ReactNode,
} from 'react';
import { Search, X } from 'lucide-react';
import { Button } from './Button';
type FieldProps = { label: ReactNode; helper?: ReactNode; error?: ReactNode };
function description(
  id: string,
  helper: ReactNode,
  error: ReactNode,
  extra?: string,
) {
  return (
    [extra, helper ? `${id}-help` : '', error ? `${id}-error` : '']
      .filter(Boolean)
      .join(' ') || undefined
  );
}
function Field({
  id,
  label,
  helper,
  error,
  children,
  count,
}: FieldProps & { id: string; children: ReactNode; count?: ReactNode }) {
  return (
    <div className="ds-field">
      <label className="ds-field-label" htmlFor={id}>
        {label}
      </label>
      {children}
      {helper && (
        <p id={`${id}-help`} className="ds-field-help">
          {helper}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="ds-field-error">
          {error}
        </p>
      )}
      {count && <span className="ds-field-help ds-numeric">{count}</span>}
    </div>
  );
}
export function Input({
  label,
  helper,
  error,
  id: supplied,
  className = '',
  ...props
}: InputHTMLAttributes<HTMLInputElement> & FieldProps) {
  const generated = useId();
  const id = supplied || generated;
  return (
    <Field {...{ id, label, helper, error }}>
      <input
        {...props}
        id={id}
        className={`ds-control ${className}`}
        aria-invalid={error ? true : props['aria-invalid']}
        aria-describedby={description(
          id,
          helper,
          error,
          props['aria-describedby'],
        )}
      />
    </Field>
  );
}
export function Textarea({
  label,
  helper,
  error,
  count,
  id: supplied,
  className = '',
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> &
  FieldProps & { count?: ReactNode }) {
  const generated = useId();
  const id = supplied || generated;
  return (
    <Field {...{ id, label, helper, error, count }}>
      <textarea
        {...props}
        id={id}
        className={`ds-control ${className}`}
        aria-invalid={error ? true : props['aria-invalid']}
        aria-describedby={description(
          id,
          helper,
          error,
          props['aria-describedby'],
        )}
      />
    </Field>
  );
}
/** Native select retains platform keyboard, touch, and assistive-technology behavior. */
export function Select({
  label,
  helper,
  error,
  id: supplied,
  className = '',
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & FieldProps) {
  const generated = useId();
  const id = supplied || generated;
  return (
    <Field {...{ id, label, helper, error }}>
      <select
        {...props}
        id={id}
        className={`ds-control ${className}`}
        aria-invalid={error ? true : props['aria-invalid']}
        aria-describedby={description(
          id,
          helper,
          error,
          props['aria-describedby'],
        )}
      />
    </Field>
  );
}
export function SearchField({
  label,
  clearLabel,
  value,
  onValueChange,
  shortcut,
  ...props
}: Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange' | 'type'
> & {
  label: string;
  clearLabel: string;
  value: string;
  onValueChange: (value: string) => void;
  shortcut?: ReactNode;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="ds-search">
      <Search aria-hidden />
      <input
        {...props}
        ref={inputRef}
        aria-label={label}
        type="search"
        className="ds-control"
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      />
      {shortcut && <kbd>{shortcut}</kbd>}
      {value && (
        <Button
          variant="icon"
          aria-label={clearLabel}
          disabled={props.disabled}
          onClick={() => {
            onValueChange('');
            inputRef.current?.focus();
          }}
        >
          <X aria-hidden />
        </Button>
      )}
    </div>
  );
}
export function Checkbox({
  label,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: ReactNode }) {
  return (
    <label className="ds-choice">
      <input {...props} type="checkbox" />
      {label}
    </label>
  );
}
export function Radio({
  label,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: ReactNode }) {
  return (
    <label className="ds-choice">
      <input {...props} type="radio" />
      {label}
    </label>
  );
}
/** Browser-native datalist offers lightweight suggestions without inventing form state. */
export function Combobox({
  options,
  ...props
}: Parameters<typeof Input>[0] & { options: readonly string[] }) {
  const id = useId();
  return (
    <>
      <Input {...props} list={id} />
      <datalist id={id}>
        {options.map((option) => (
          <option key={option} value={option} />
        ))}
      </datalist>
    </>
  );
}
