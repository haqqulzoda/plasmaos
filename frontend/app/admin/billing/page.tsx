'use client';

import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, CreditCard, Download, RefreshCw } from 'lucide-react';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox, Input, Select, Textarea } from '@/components/ui/Forms';
import { Dialog } from '@/components/ui/Overlay';
import { api } from '@/lib/api';
import { formatTimestamp } from '@/lib/adminPanels';
import type { BillingInvoice, BillingOrder, BillingOverview, BillingPayment } from '@/lib/billing';

type Customer = {
  organization_id: string; organization_name: string; legal_name: string | null; country: string | null;
  resident: boolean | null; plan: string; access_state: string; billing_status: string | null;
  plan_started_on: string | null; plan_ends_on: string | null; last_order: BillingOrder | null;
  open_invoices: number; onboarding_open: boolean; last_activity_at: string | null;
};
type Task = {
  id: string; organization_id: string; organization_name: string; product: string; method: string;
  order_status: string; status: 'open' | 'done'; note: string | null; created_at: string; done_at: string | null;
};
type Detail = BillingOverview & {
  organization_name: string; access_state: string; billing_status: string | null;
  terms_acceptances: { id: string; terms_version: string; text_sha256: string; user_email: string | null; ip_address: string | null; accepted_at: string }[];
  events: { id: string; event_type: string; provider_event_id: string; outcome: string | null; processing_error: string | null; received_at: string; processed_at: string | null }[];
  onboarding: { id: string; status: string; note: string | null; created_at: string }[];
  audit: { id: string; action: string; actor: string | null; reason: string | null; created_at: string }[];
};
type Action =
  | { kind: 'paid'; invoice: BillingInvoice }
  | { kind: 'refund'; order: BillingOrder }
  | { kind: 'override' }
  | { kind: 'onboarding'; task: Task };

const PRODUCT: Record<string, string> = { pilot: 'Pilot', pursuit_desk: 'Pursuit Desk', extra_pursuit: 'Extra pursuit' };
const PLANS = ['explore', 'pilot', 'pursuit_desk', 'agent', 'enterprise', 'per_tender'];
const STATUSES = ['none', 'paid', 'awaiting_payment', 'suspended', 'refunded', 'canceled'];
const TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral' | 'info'> = {
  paid: 'success', awaiting_payment: 'warning', suspended: 'danger', refunded: 'neutral', canceled: 'neutral',
  issued: 'warning', overdue: 'danger', void: 'neutral', pending: 'info', lapsed: 'danger',
};
const usd = (cents: number) => `$${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: cents % 100 ? 2 : 0 })}`;
const uzs = (value: string | null) => `${Number(value ?? 0).toLocaleString('en-US', { maximumFractionDigits: 2 })} UZS`;
const label = (value: string | null | undefined) => (value ?? 'none').replace(/_/g, ' ');
const failure = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message);
  return typeof detail === 'string' ? detail : fallback;
};

/** B1: the billing console. Customers, plans and billing status, orders, invoices, payments, webhook events,
 *  onboarding tasks; mark a bank transfer paid, record a refund, override the plan. Every change is audited. */
export default function AdminBillingPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [form, setForm] = useState({ text: '', note: '', plan: '', status: '', downgrade: true });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, queue] = await Promise.all([
        api.get<Customer[]>('/admin/billing/customers'), api.get<Task[]>('/admin/billing/onboarding'),
      ]);
      setCustomers(list.data);
      setTasks(queue.data);
    } catch {
      setError('Billing could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const open = async (organizationId: string) => {
    setFormError(null);
    try {
      setDetail((await api.get<Detail>(`/admin/billing/organizations/${organizationId}`)).data);
    } catch {
      setError('The organization could not be loaded.');
    }
  };

  const start = (next: Action) => {
    setAction(next);
    setForm({ text: '', note: '', plan: '', status: '', downgrade: true });
    setFormError(null);
  };

  const pdf = async (invoice: BillingInvoice) => {
    const response = await api.get(`/admin/billing/invoices/${invoice.id}/pdf`, { responseType: 'blob' });
    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
    window.open(url, '_blank', 'noopener');
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const save = async () => {
    if (!action) return;
    setSaving(true);
    setFormError(null);
    try {
      if (action.kind === 'onboarding') {
        setTasks((await api.post<Task[]>(`/admin/billing/onboarding/${action.task.id}/done`, { note: form.note.trim() || null })).data);
        setSuccess(`Onboarding of ${action.task.organization_name} marked done.`);
      } else {
        const path = action.kind === 'paid' ? `/admin/billing/invoices/${action.invoice.id}/mark-paid`
          : action.kind === 'refund' ? `/admin/billing/orders/${action.order.id}/refund`
          : `/admin/billing/organizations/${detail?.organization_id}/override`;
        const body = action.kind === 'paid' ? { reference: form.text.trim(), note: form.note.trim() || null }
          : action.kind === 'refund' ? { note: form.note.trim(), downgrade: form.downgrade }
          : { plan: form.plan || null, billing_status: form.status || null, reason: form.note.trim() };
        setDetail((await api.post<Detail>(path, body)).data);
        setSuccess(action.kind === 'paid' ? `Invoice ${action.invoice.number} marked paid.`
          : action.kind === 'refund' ? 'Refund recorded.' : 'Plan and billing status saved.');
      }
      setAction(null);
      await load();
    } catch (problem) {
      setFormError(failure(problem, 'The change could not be saved.'));
    } finally {
      setSaving(false);
    }
  };

  const openTasks = tasks.filter((task) => task.status === 'open');

  return <div className="admin-page ds-container-data ds-stack" data-admin-billing>
    <header className="admin-page-header">
      <div className="admin-heading-with-icon">
        <CreditCard aria-hidden />
        <div>
          <span className="ds-eyebrow">Operations</span>
          <h1>Billing</h1>
          <p className="ds-muted">
            Customers who bought in the app: card payments through Polar, bank transfers by invoice (PL-YYYY-NNN). Mark a
            transfer paid with its bank reference, record refunds, override a plan. Every change is audited.
          </p>
        </div>
      </div>
      <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
    </header>
    {error && <Alert tone="danger" title={error} />}
    {success && <Alert tone="success" title={success} />}

    <section className="ds-stack" aria-labelledby="admin-onboarding-title" data-admin-onboarding>
      <h2 id="admin-onboarding-title">Onboarding queue ({openTasks.length} open)</h2>
      <DataTable<Task>
        caption="Onboarding tasks"
        loading={loading}
        loadingLabel="Loading onboarding tasks…"
        empty={<span className="ds-muted">No onboarding tasks.</span>}
        rows={tasks.slice(0, 20)}
        rowKey={(task) => task.id}
        columns={[
          { key: 'created', heading: 'Activated', cell: (task) => formatTimestamp(task.created_at) },
          { key: 'organization', heading: 'Organization', cell: (task) => <BidiText>{task.organization_name}</BidiText> },
          { key: 'product', heading: 'Bought', cell: (task) => `${PRODUCT[task.product] ?? task.product} · ${label(task.method)}` },
          { key: 'payment', heading: 'Payment', cell: (task) => <StatusBadge tone={TONE[task.order_status] ?? 'neutral'}>{label(task.order_status)}</StatusBadge> },
          { key: 'status', heading: 'Kickoff', cell: (task) => task.status === 'done'
            ? <span className="ds-muted ds-text-small">Done {formatTimestamp(task.done_at)}{task.note ? ` · ${task.note}` : ''}</span>
            : <Button size="sm" leadingIcon={<CheckCircle2 aria-hidden />} onClick={() => start({ kind: 'onboarding', task })}>Mark done</Button> },
        ]}
      />
    </section>

    <section className="ds-stack" aria-labelledby="admin-customers-title">
      <h2 id="admin-customers-title">Customers</h2>
      <DataTable<Customer>
        caption="Billing customers"
        loading={loading}
        loadingLabel="Loading customers…"
        empty={<span className="ds-muted">No organization has billing details or orders yet.</span>}
        rows={customers}
        rowKey={(row) => row.organization_id}
        columns={[
          { key: 'organization', heading: 'Organization', cell: (row) => <span className="admin-partner-cell">
            <strong><BidiText>{row.organization_name}</BidiText></strong>
            <span className="ds-muted ds-text-small"><BidiText>{row.legal_name ?? 'no billing details'}</BidiText>{row.country ? ` · ${row.country}` : ''}{row.resident ? ' · resident (UZS)' : ''}</span>
          </span> },
          { key: 'plan', heading: 'Plan', cell: (row) => <span className="admin-partner-cell">
            <strong>{label(row.plan)}</strong>
            <span className="ds-muted ds-text-small">{row.plan_started_on ?? ''}{row.plan_ends_on ? ` → ${row.plan_ends_on}` : ''}</span>
          </span> },
          { key: 'status', heading: 'Billing status', cell: (row) => <StatusBadge tone={TONE[row.billing_status ?? ''] ?? 'neutral'}>{label(row.billing_status)}</StatusBadge> },
          { key: 'order', heading: 'Last order', cell: (row) => row.last_order
            ? <span className="admin-partner-cell"><span>{PRODUCT[row.last_order.product]} · {label(row.last_order.method)} · {usd(row.last_order.amount_cents)}</span>
              <span className="ds-muted ds-text-small">{label(row.last_order.status)} · {formatTimestamp(row.last_order.created_at)}</span></span>
            : '—' },
          { key: 'open', heading: 'Open invoices', cell: (row) => row.open_invoices || '—' },
          { key: 'actions', heading: '', cell: (row) => <Button size="sm" variant="secondary" onClick={() => void open(row.organization_id)}>Open</Button> },
        ]}
      />
    </section>

    <Dialog
      open={Boolean(detail) && !action}
      onClose={() => setDetail(null)}
      title={detail ? `Billing: ${detail.organization_name}` : ''}
      description={detail ? `Plan ${label(detail.plan)} (${detail.access_state}) · billing status ${label(detail.billing_status)}` : ''}
      closeLabel="Close billing detail"
      footer={<>
        <Button variant="secondary" onClick={() => setDetail(null)}>Close</Button>
        <Button onClick={() => start({ kind: 'override' })}>Override plan or status</Button>
      </>}
    >
      {detail && <div className="ds-stack admin-billing-detail" data-admin-billing-detail>
        <h3>Invoices</h3>
        {detail.invoices.length === 0 ? <p className="ds-muted">None.</p> : <ul className="admin-plan-list">{detail.invoices.map((invoice) => <li key={invoice.id}>
          <TechnicalText>{invoice.number}</TechnicalText> · {invoice.currency === 'UZS' ? `${uzs(invoice.total_uzs)} (${usd(invoice.total_usd_cents)} at CBU ${Number(invoice.fx_rate).toLocaleString('en-US')})` : usd(invoice.total_usd_cents)}
          {' · '}issued {invoice.issued_on} · due {invoice.due_on} · <StatusBadge tone={TONE[invoice.status] ?? 'neutral'}>{invoice.status}</StatusBadge>
          {invoice.reminders_sent > 0 && <span className="ds-muted ds-text-small"> · reminder day {invoice.reminders_sent} sent</span>}
          <span className="ds-row">
            <Button size="sm" variant="ghost" leadingIcon={<Download aria-hidden />} onClick={() => void pdf(invoice)}>PDF</Button>
            {(invoice.status === 'issued' || invoice.status === 'overdue') && <Button size="sm" onClick={() => start({ kind: 'paid', invoice })}>Mark paid</Button>}
          </span>
        </li>)}</ul>}
        <h3>Orders</h3>
        {detail.orders.length === 0 ? <p className="ds-muted">None.</p> : <ul className="admin-plan-list">{detail.orders.map((order) => <li key={order.id}>
          {formatTimestamp(order.created_at)} · {PRODUCT[order.product]}{order.renewal ? ' (renewal)' : ''} · {label(order.method)} · {usd(order.amount_cents)}
          {order.credit_cents > 0 && ` (pilot credit ${usd(order.credit_cents)})`} · <StatusBadge tone={TONE[order.status] ?? 'neutral'}>{label(order.status)}</StatusBadge>
          {order.refund_note && <span className="ds-muted ds-text-small"> · {order.refund_note}</span>}
          {['paid', 'awaiting_payment', 'lapsed'].includes(order.status)
            && <Button size="sm" variant="ghost" onClick={() => start({ kind: 'refund', order })}>Record refund</Button>}
        </li>)}</ul>}
        <h3>Payments</h3>
        {detail.payments.length === 0 ? <p className="ds-muted">None.</p> : <ul className="admin-plan-list">{detail.payments.map((payment: BillingPayment) => <li key={payment.id}>
          {formatTimestamp(payment.paid_at)} · {label(payment.method)} · {usd(payment.amount_cents)} · {payment.status}
          {payment.reference && <> · ref <TechnicalText>{payment.reference}</TechnicalText></>}
          {payment.provider_payment_id && <> · Polar <TechnicalText>{payment.provider_payment_id}</TechnicalText></>}
        </li>)}</ul>}
        <h3>Terms accepted</h3>
        {detail.terms_acceptances.length === 0 ? <p className="ds-muted">None.</p> : <ul className="admin-plan-list">{detail.terms_acceptances.map((row) => <li key={row.id}>
          {formatTimestamp(row.accepted_at)} · {row.terms_version} · <TechnicalText>{row.text_sha256.slice(0, 12)}…</TechnicalText> · {row.user_email ?? '—'} · IP {row.ip_address ?? '—'}
        </li>)}</ul>}
        <h3>Polar webhook events</h3>
        {detail.events.length === 0 ? <p className="ds-muted">None.</p> : <ul className="admin-plan-list">{detail.events.map((event) => <li key={event.id}>
          {formatTimestamp(event.received_at)} · {event.event_type} · {event.outcome ?? (event.processing_error ? `error ${event.processing_error}` : 'unprocessed')}
          <span className="ds-muted ds-text-small"> · <TechnicalText>{event.provider_event_id}</TechnicalText></span>
        </li>)}</ul>}
        <h3>Audit</h3>
        <ul className="admin-plan-list">{detail.audit.slice(0, 20).map((row) => <li key={row.id}>
          {formatTimestamp(row.created_at)} · {row.action} · {row.actor ?? '—'}{row.reason ? ` · ${row.reason}` : ''}
        </li>)}</ul>
      </div>}
    </Dialog>

    <Dialog
      open={Boolean(action)}
      onClose={() => !saving && setAction(null)}
      title={action?.kind === 'paid' ? `Mark ${action.invoice.number} paid` : action?.kind === 'refund' ? 'Record a refund'
        : action?.kind === 'onboarding' ? `Onboarding done: ${action.task.organization_name}` : 'Override plan or billing status'}
      description={action?.kind === 'paid' ? 'The bank transfer arrived. A suspended plan comes back with its original dates. Audited.'
        : action?.kind === 'refund' ? 'For a refund made in the Polar dashboard or by bank. Audited; the customer is alerted by the team.'
        : action?.kind === 'onboarding' ? 'The kickoff call is booked or done.' : 'A manual change, with a reason. Audited.'}
      closeLabel="Close"
      footer={<>
        <Button variant="secondary" onClick={() => setAction(null)} disabled={saving}>Cancel</Button>
        <Button onClick={() => void save()} loading={saving} variant={action?.kind === 'refund' ? 'danger' : 'primary'}>Save</Button>
      </>}
    >
      <div className="ds-stack">
        {action?.kind === 'paid' && <Input label="Bank reference" required maxLength={200} value={form.text}
          onChange={(event) => setForm({ ...form, text: event.target.value })} />}
        {action?.kind === 'override' && <>
          <Select label="Plan" value={form.plan} onChange={(event) => setForm({ ...form, plan: event.target.value })}>
            <option value="">Keep {label(detail?.plan)}</option>
            {PLANS.map((plan) => <option key={plan} value={plan}>{label(plan)}</option>)}
          </Select>
          <Select label="Billing status" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
            <option value="">Keep {label(detail?.billing_status)}</option>
            {STATUSES.map((status) => <option key={status} value={status}>{label(status)}</option>)}
          </Select>
        </>}
        {action?.kind === 'refund' && <Checkbox label="Return the organization to Explore (when this order is its current plan)"
          checked={form.downgrade} onChange={(event) => setForm({ ...form, downgrade: event.target.checked })} />}
        <Textarea label={action?.kind === 'paid' || action?.kind === 'onboarding' ? 'Note (optional)' : 'Reason'} rows={3} maxLength={1000}
          value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} />
        {formError && <Alert tone="danger" title={formError} />}
      </div>
    </Dialog>
  </div>;
}
