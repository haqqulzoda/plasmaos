import type { HTMLAttributes, ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, AlertTriangle } from "lucide-react";
import { BidiText } from "@/components/i18n/BidiText";
export type Tone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "accent";
export function Badge({
  tone = "neutral",
  children,
  icon,
}: {
  tone?: Tone;
  children: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <span className={`ds-badge ds-tone-${tone}`}>
      {icon}
      {children}
    </span>
  );
}
export function StatusBadge({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  const Icon =
    tone === "success"
      ? CheckCircle2
      : tone === "warning"
        ? AlertTriangle
        : tone === "danger"
          ? AlertCircle
          : Info;
  return (
    <Badge tone={tone} icon={<Icon aria-hidden />}>
      {children}
    </Badge>
  );
}
export function Surface({
  variant = "default",
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "subtle" | "raised" | "interactive";
}) {
  return (
    <div
      {...props}
      className={`ds-surface ds-surface-${variant} ${className}`}
    />
  );
}
export const Card = Surface;
export function Metric({
  label,
  value,
  supporting,
  state,
}: {
  label: ReactNode;
  value: ReactNode;
  supporting?: ReactNode;
  state?: ReactNode;
}) {
  return (
    <dl className="ds-metric">
      <dt>{label}</dt>
      <dd className="ds-metric-value">{value}</dd>
      {supporting && <dd className="ds-muted">{supporting}</dd>}
      {state && <dd>{state}</dd>}
    </dl>
  );
}
export function Skeleton({
  className = "",
  ...props
}: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      {...props}
      aria-hidden="true"
      className={`ds-skeleton ${className}`}
    />
  );
}
export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  secondaryAction?: ReactNode;
}) {
  return (
    <div className="ds-empty">
      {icon}
      <h3>{title}</h3>
      {description && <p className="ds-muted">{description}</p>}
      <div className="ds-row">
        {action}
        {secondaryAction}
      </div>
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  status,
  primaryAction,
  secondaryAction,
  metadata,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  metadata?: ReactNode;
}) {
  return (
    <header className="ds-page-header">
      <div>
        {eyebrow && <span className="ds-eyebrow">{eyebrow}</span>}
        <div className="ds-row">
          <h1>
            <BidiText>{title}</BidiText>
          </h1>
          {status}
        </div>
        {description && <p>{description}</p>}
        {metadata && <div className="ds-row ds-muted">{metadata}</div>}
      </div>
      <div className="ds-row">
        {secondaryAction}
        {primaryAction}
      </div>
    </header>
  );
}
export function SectionHeader({
  title,
  action,
  description,
  icon,
  titleId,
}: {
  title: ReactNode;
  action?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  titleId?: string;
}) {
  return (
    <header className="ds-section-header">
      <div className="ds-row">
        {icon}
        <div>
          <h2 id={titleId}>{title}</h2>
          {description && <p className="ds-muted">{description}</p>}
        </div>
      </div>
      {action}
    </header>
  );
}

export function PageSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="ds-stack ds-page-skeleton">
      <span className="sr-only">{label}</span>
      <Skeleton />
      <Skeleton />
      <div className="ds-grid-three">
        {[0, 1, 2].map((i) => (
          <Surface key={i} className="ds-stack ds-pad">
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </Surface>
        ))}
      </div>
    </div>
  );
}
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  loading,
  loadingLabel,
  empty,
  pagination,
}: {
  caption: string;
  columns: {
    key: string;
    heading: ReactNode;
    cell: (row: T) => ReactNode;
    numeric?: boolean;
  }[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  loadingLabel: string;
  empty: ReactNode;
  pagination?: ReactNode;
}) {
  return (
    <div className="ds-stack">
      <div
        className="ds-table-scroll"
        role="region"
        aria-label={caption}
        tabIndex={0}
      >
        <table className="ds-table" aria-busy={loading || undefined}>
          <caption>{caption}</caption>
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  scope="col"
                  key={col.key}
                  className={col.numeric ? "ds-numeric" : undefined}
                >
                  {col.heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length}>
                  <span role="status">{loadingLabel}</span>
                  <Skeleton />
                </td>
              </tr>
            ) : !rows.length ? (
              <tr>
                <td colSpan={columns.length}>{empty}</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={rowKey(row)}>
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={col.numeric ? "ds-numeric" : undefined}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {pagination}
    </div>
  );
}
