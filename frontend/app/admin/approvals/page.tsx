'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Check, ChevronLeft, ChevronRight, Eye, RefreshCw, RotateCcw, Search, ShieldAlert, UserRound, X } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { api } from '@/lib/api';
import { Alert } from '@/components/ui/Feedback';
import { Button } from '@/components/ui/Button';
import { Dialog, Drawer } from '@/components/ui/Overlay';
import { Input, Select, Textarea } from '@/components/ui/Forms';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { ACCOUNT_ROLES, ACCOUNT_STATUSES, type AccountStatus, type AdminAccount, type AdminAccountsPage, type LifecycleAction, actionConsequence, actionLabel, adminActionError, roleLabel, statusLabel } from '@/lib/adminOperations';

const PAGE_SIZE = 25;
type CompanyAction = 'approve' | 'reject' | 'disable';
type PendingAction = { rowKey: string; resource: 'account' | 'company'; resourceId: string; action: LifecycleAction | CompanyAction; targetLabel: string; restoreTargetStatus?: AccountStatus | null };

export default function AdminAccountsPageView() {
  const router = useRouter();
  const { data: session } = useSession();
  const [page, setPage] = useState<AdminAccountsPage>({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [actingId, setActingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [searchDraft, setSearchDraft] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AdminAccount | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [reason, setReason] = useState('');
  const confirmButtonRef = useRef<HTMLButtonElement>(null);

  const canManageAccounts = session?.approval_status === 'approved' && (session?.is_admin === true || session?.platform_role === 'admin');
  const loadAccounts = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const response = await api.get<AdminAccountsPage>('/admin/accounts', { params: { limit: PAGE_SIZE, offset, approval_status: statusFilter || undefined, role: roleFilter || undefined, query: searchQuery || undefined } });
      setPage(response.data);
      setSelected((current) => current ? response.data.items.find((item) => item.id === current.id) || current : null);
    } catch (caught) {
      const result = adminActionError(caught);
      setError(result.authorityLost ? result.message : 'Accounts could not be loaded. Try again.');
      if (result.authorityLost) router.replace('/dashboard');
    } finally { setLoading(false); }
  }, [offset, roleFilter, router, searchQuery, statusFilter]);

  useEffect(() => { void loadAccounts(); }, [loadAccounts]);
  const beginAction = (action: PendingAction) => { setReason(''); setError(null); setSuccess(null); setPendingAction(action); };
  const submitAction = async () => {
    if (!pendingAction || !canManageAccounts) return;
    setActingId(pendingAction.rowKey); setError(null); setSuccess(null);
    const url = pendingAction.resource === 'account' ? `/admin/users/${pendingAction.resourceId}/${pendingAction.action}` : `/admin/companies/${pendingAction.resourceId}/${pendingAction.action}`;
    try {
      const response = await api.post(url, { reason: reason.trim() || null });
      const resultStatus = response.data?.approval_status;
      setSuccess(`${pendingAction.targetLabel} is now ${typeof resultStatus === 'string' ? statusLabel(resultStatus) : 'updated'}. Existing credentials remain invalid and the backend confirmed the transition.`);
      setPendingAction(null); await loadAccounts();
    } catch (caught) {
      const result = adminActionError(caught); setPendingAction(null);
      if (result.refresh) await loadAccounts();
      setError(result.message);
      if (result.authorityLost) router.replace('/dashboard');
    } finally { setActingId(null); }
  };
  const applySearch = (event: FormEvent) => { event.preventDefault(); setOffset(0); setSearchQuery(searchDraft.trim()); };
  const pageNumber = Math.floor(page.offset / page.limit) + 1;
  const pageCount = Math.max(1, Math.ceil(page.total / page.limit));

  return (
    <div className="admin-page accounts-page ds-container-data ds-stack">
      <header className="admin-page-header"><div><span className="ds-eyebrow">Identity operations</span><h1>Accounts &amp; approvals</h1><p className="ds-muted">Canonical lifecycle state, access decisions and immutable audit entry points.</p></div><Button variant="secondary" loading={loading} onClick={() => loadAccounts()} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button></header>
      <Alert tone="info" title="Account state is authoritative.">Every completed lifecycle transition changes the account security version. Existing sessions and credentials stop working immediately; the next privileged action requires fresh authentication.</Alert>
      {!canManageAccounts && <Alert tone="warning" title="Read-only administrator view"><ShieldAlert aria-hidden /> Current effective-admin authority is required for actions that change account or company state.</Alert>}
      {error && <Alert tone="danger" title={error} />}
      {success && <Alert tone="success" title={success} />}

      <form onSubmit={applySearch} className="ds-surface admin-filter-bar">
        <Input label="Account" placeholder="Name or email" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} />
        <Select label="Status" value={statusFilter} onChange={(event) => { setOffset(0); setStatusFilter(event.target.value); }}><option value="">All statuses</option>{ACCOUNT_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</Select>
        <Select label="Role" value={roleFilter} onChange={(event) => { setOffset(0); setRoleFilter(event.target.value); }}><option value="">All roles</option>{ACCOUNT_ROLES.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}</Select>
        <Button type="submit" leadingIcon={<Search aria-hidden />}>Apply filters</Button>
      </form>

      <section className="ds-surface admin-table-surface" aria-busy={loading}>
        <div className="admin-section-heading"><div><h2>Account directory</h2><p className="ds-muted">{page.total} matching accounts · Page {pageNumber} of {pageCount}</p></div></div>
        {loading ? <div className="admin-loading" role="status"><RefreshCw className="ds-spin" aria-hidden />Loading accounts…</div> : page.items.length === 0 ? <div className="admin-empty"><UserRound aria-hidden /><strong>No accounts match these filters.</strong></div> : (
          <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th scope="col">Account</th><th scope="col">Status</th><th scope="col">Role</th><th scope="col">Company</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Details</span></th></tr></thead><tbody>{page.items.map((account) => <tr key={account.id}><td><strong><BidiText>{account.name}</BidiText></strong><TechnicalText>{account.email}</TechnicalText>{account.is_current_actor && <span className="ds-badge ds-tone-info">You</span>}</td><td><StatusBadge status={account.approval_status} /></td><td>{roleLabel(account.role)}</td><td>{account.company ? <><BidiText>{account.company.company_name || 'Unnamed company'}</BidiText><small className="ds-muted">{statusLabel(account.company.approval_status)}</small></> : '—'}</td><td><time dateTime={account.created_at || undefined}>{formatDate(account.created_at)}</time></td><td><Button size="sm" variant="ghost" onClick={() => setSelected(account)} leadingIcon={<Eye aria-hidden />}>View</Button></td></tr>)}</tbody></table></div>
        )}
      </section>
      <nav className="admin-pagination" aria-label="Account pages"><span>{page.total} accounts</span><div><Button variant="secondary" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} leadingIcon={<ChevronLeft aria-hidden />}>Previous</Button><Button variant="secondary" disabled={loading || offset + page.limit >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)} trailingIcon={<ChevronRight aria-hidden />}>Next</Button></div></nav>

      <Drawer open={Boolean(selected)} onClose={() => setSelected(null)} title="Account detail" description="Canonical account and company state." closeLabel="Close account detail" side="end">{selected && <AccountDetail account={selected} canManage={canManageAccounts} busy={actingId === selected.id} onAction={beginAction} />}</Drawer>
      <Dialog open={Boolean(pendingAction)} onClose={() => !actingId && setPendingAction(null)} title={`${pendingAction ? actionLabel(pendingAction.action as LifecycleAction) : 'Update'} ${pendingAction?.targetLabel || ''}?`} description="This administrative decision is audited and cannot preserve old credentials." closeLabel="Close confirmation" initialFocusRef={confirmButtonRef} footer={<><Button variant="secondary" onClick={() => setPendingAction(null)} disabled={Boolean(actingId)}>Cancel</Button><Button ref={confirmButtonRef} variant={pendingAction?.action === 'approve' || pendingAction?.action === 'restore' ? 'primary' : 'danger'} onClick={() => void submitAction()} loading={Boolean(actingId)}>Confirm {pendingAction ? actionLabel(pendingAction.action as LifecycleAction) : 'action'}</Button></>}>
        {pendingAction && <div className="account-confirm"><Alert tone={pendingAction.action === 'approve' || pendingAction.action === 'restore' ? 'warning' : 'danger'} title="Immediate session invalidation">{pendingAction.resource === 'account' ? actionConsequence(pendingAction.action as LifecycleAction, pendingAction.restoreTargetStatus) : companyConsequence(pendingAction.action as CompanyAction)}</Alert>{(pendingAction.action === 'reject' || pendingAction.action === 'disable') && <Textarea label="Reason (optional)" maxLength={500} rows={3} value={reason} onChange={(event) => setReason(event.target.value)} />}</div>}
      </Dialog>
    </div>
  );
}

function AccountDetail({ account, canManage, busy, onAction }: { account: AdminAccount; canManage: boolean; busy: boolean; onAction: (action: PendingAction) => void }) {
  const accountAction = (action: LifecycleAction) => onAction({ rowKey: account.id, resource: 'account', resourceId: account.id, action, targetLabel: account.email, restoreTargetStatus: account.restore_target_status });
  const companyAction = (action: CompanyAction) => account.company && onAction({ rowKey: account.id, resource: 'company', resourceId: account.company.id, action, targetLabel: account.company.company_name || account.email });
  const companyActions = account.company ? (['approve', 'reject', 'disable'] as CompanyAction[]).filter((action) => account.company?.approval_status !== ({ approve: 'approved', reject: 'rejected', disable: 'disabled' }[action])) : [];
  return <div className="account-detail"><div className="account-identity"><UserRound aria-hidden /><div><h3><BidiText>{account.name}</BidiText></h3><TechnicalText>{account.email}</TechnicalText></div></div><dl className="account-facts"><div><dt>Status</dt><dd><StatusBadge status={account.approval_status} /></dd></div><div><dt>Role</dt><dd>{roleLabel(account.role)}</dd></div><div><dt>Created</dt><dd>{formatDate(account.created_at)}</dd></div><div><dt>Company</dt><dd>{account.company ? <CompanyLink company={account.company} /> : 'None'}</dd></div></dl><Link href={`/admin/audit?target_user_id=${encodeURIComponent(account.id)}`} className="ds-button ds-button-secondary">View immutable audit history</Link><section><h3>Account actions</h3>{account.is_current_actor && <div className="ds-muted"><p>Administrators cannot reject themselves.</p><p>Administrators cannot disable themselves.</p></div>}<div className="account-actions">{account.allowed_actions.map((action) => <Button key={action} variant={action === 'approve' || action === 'restore' ? 'secondary' : 'danger'} size="sm" disabled={!canManage || busy} onClick={() => accountAction(action)} leadingIcon={action === 'approve' ? <Check aria-hidden /> : action === 'restore' ? <RotateCcw aria-hidden /> : <X aria-hidden />}>{actionLabel(action)}</Button>)}</div></section>{account.company && companyActions.length > 0 && <section><h3>Company actions</h3><p className="ds-muted">Company lifecycle is distinct from account authorization.</p><div className="account-actions">{companyActions.map((action) => <Button key={action} variant={action === 'approve' ? 'secondary' : 'danger'} size="sm" disabled={!canManage || busy} onClick={() => companyAction(action)}>{actionLabel(action)}</Button>)}</div></section>}</div>;
}

function CompanyLink({ company }: { company: NonNullable<AdminAccount['company']> }) { return <Link href={`/admin/companies/${company.id}`}><BidiText>{company.company_name || 'Unnamed company'}</BidiText></Link>; }
function StatusBadge({ status }: { status: string }) { return <span className={`ds-badge account-status status-${status}`}><span aria-hidden className="status-dot" />{statusLabel(status)}</span>; }
function companyConsequence(action: CompanyAction) { return action === 'approve' ? 'The company profile will become Approved.' : action === 'reject' ? 'The company profile will become Rejected. Account state is unchanged.' : 'The company profile will become Disabled without deleting its records.'; }
function formatDate(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat('en', { dateStyle: 'medium' }).format(date); }
