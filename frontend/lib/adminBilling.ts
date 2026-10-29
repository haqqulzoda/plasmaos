/** Admin → Billing: what each detail action sends. Deploy 5.1: the organization actions carry the organization id
 *  taken when the action starts (the detail dialog closes while an action is open, so the page must not read the
 *  id from the detail state at save time: that sent /organizations/undefined/… and a 422). */

export type AdminBillingAction =
  | { kind: 'paid'; invoice: { id: string; number: string } }
  | { kind: 'refund'; order: { id: string } }
  | { kind: 'confirmCancel'; order: { id: string } }
  | { kind: 'override'; organizationId: string }
  | { kind: 'offer'; organizationId: string }
  | { kind: 'invoice'; organizationId: string };

export type AdminBillingForm = {
  text: string; note: string; plan: string; status: string; downgrade: boolean; startsOn: string; endsOn: string;
};

export const emptyAdminBillingForm = (): AdminBillingForm =>
  ({ text: '', note: '', plan: '', status: '', downgrade: true, startsOn: '', endsOn: '' });

const organizationPath = (organizationId: string, tail: string) => {
  if (!/^[0-9a-f-]{36}$/i.test(organizationId)) throw new Error('No organization is open: open it again from the list.');
  return `/admin/billing/organizations/${organizationId}/${tail}`;
};

export function adminBillingRequest(action: AdminBillingAction, form: AdminBillingForm): { path: string; body: Record<string, unknown> } {
  switch (action.kind) {
    case 'paid':
      return { path: `/admin/billing/invoices/${action.invoice.id}/mark-paid`, body: { reference: form.text.trim(), note: form.note.trim() || null } };
    case 'refund':
      return { path: `/admin/billing/orders/${action.order.id}/refund`, body: { note: form.note.trim(), downgrade: form.downgrade } };
    case 'confirmCancel':
      return { path: `/admin/billing/orders/${action.order.id}/confirm-cancel`, body: {} };
    case 'offer':
      return { path: organizationPath(action.organizationId, 'offers'), body: { product: 'per_tender', note: form.note.trim() || null } };
    case 'invoice':
      return { path: organizationPath(action.organizationId, 'invoices'), body: { product: 'per_tender', signed_note: form.note.trim() } };
    case 'override':
      return {
        path: organizationPath(action.organizationId, 'override'),
        body: {
          plan: form.plan || null, billing_status: form.status || null, reason: form.note.trim(),
          plan_started_on: form.startsOn || null, plan_ends_on: form.endsOn || null,
        },
      };
  }
}

export type WebhookHealth = {
  first_card_checkout_at: string | null; last_order_paid_at: string | null; pending_card_orders: number;
  events: { event_type: string; count: number; last_received_at: string | null }[]; warning: boolean;
};
