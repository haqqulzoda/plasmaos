'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Eye, Loader2, Megaphone, Plus, RefreshCw, Search, Send, ShieldAlert, Users, X } from 'lucide-react';
import { api } from '@/lib/api';
import { Alert } from '@/components/ui/Feedback';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Overlay';
import { Input, Radio, SearchField, Textarea } from '@/components/ui/Forms';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import type { AdminAccount, AdminAccountsPage } from '@/lib/adminOperations';
import {
  communicationsError,
  mutableBroadcast,
  terminalBroadcast,
  type BroadcastAudience,
  type BroadcastDetail,
  type BroadcastMessageType,
  type BroadcastPage,
  type BroadcastStatus,
  type BroadcastSummary,
} from '@/lib/communications';

type Composer = {
  id: string | null;
  status?: BroadcastStatus;
  subject: string;
  body: string;
  messageType: BroadcastMessageType;
  audienceMode: BroadcastAudience;
  selectedIds: string[] | null;
  selectedCount: number;
};

const emptyComposer = (): Composer => ({ id: null, subject: '', body: '', messageType: 'ANNOUNCEMENT', audienceMode: 'ALL_ELIGIBLE_USERS', selectedIds: [], selectedCount: 0 });
const STATUSES: Array<'' | BroadcastStatus> = ['', 'DRAFT', 'QUEUED', 'SENDING', 'SENT', 'PARTIAL', 'FAILED'];

export default function BroadcastsPage() {
  const [history, setHistory] = useState<BroadcastSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<'' | BroadcastStatus>('');
  const [composer, setComposer] = useState<Composer>(emptyComposer);
  const [detail, setDetail] = useState<BroadcastDetail | null>(null);
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [userQuery, setUserQuery] = useState('');
  const [userResults, setUserResults] = useState<AdminAccount[]>([]);
  const [userSearchBusy, setUserSearchBusy] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const testRequestIds = useRef(new Map<string, string>());

  const loadHistory = useCallback(async (append = false, cursor?: string | null) => {
    if (append) setBusy('history-more');
    else setLoading(true);
    setError(null);
    try {
      const response = await api.get<BroadcastPage>('/admin/broadcasts', { params: { limit: 25, cursor: cursor || undefined, status: statusFilter || undefined } });
      setHistory((current) => append ? [...current, ...response.data.items] : response.data.items);
      setNextCursor(response.data.next_cursor);
    } catch (caught) {
      setError(communicationsError(caught));
    } finally {
      setLoading(false);
      setBusy((current) => current === 'history-more' ? null : current);
    }
  }, [statusFilter]);

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  useEffect(() => {
    if (!detail || !['QUEUED', 'SENDING'].includes(detail.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.get<BroadcastDetail>(`/admin/broadcasts/${encodeURIComponent(detail.id)}`);
        setDetail(response.data);
        setComposer((current) => ({ ...current, status: response.data.status }));
        void loadHistory();
      } catch {
        // Keep the last confirmed aggregate; manual refresh remains available.
      }
    }, 10_000);
    return () => window.clearTimeout(timer);
  }, [detail, loadHistory]);

  const selectHistory = async (item: BroadcastSummary) => {
    setBusy(`detail-${item.id}`);
    setError(null);
    try {
      const response = await api.get<BroadcastDetail>(`/admin/broadcasts/${encodeURIComponent(item.id)}`);
      const value = response.data;
      setDetail(value);
      setPreviewCount(value.status === 'DRAFT' ? null : value.recipient_count);
      setComposer({ id: value.id, status: value.status, subject: value.subject, body: value.body, messageType: value.message_type, audienceMode: value.audience_mode, selectedIds: value.audience_mode === 'SELECTED_USERS' ? null : [], selectedCount: value.selected_user_count });
      setSuccess(null);
    } catch (caught) {
      setError(communicationsError(caught));
    } finally {
      setBusy(null);
    }
  };

  const saveDraft = async () => {
    if (!composer.subject.trim() || !composer.body.trim()) {
      setError('Subject and body are required.');
      return null;
    }
    setBusy('save'); setError(null); setSuccess(null);
    const common = { subject: composer.subject, body: composer.body, message_type: composer.messageType, audience_mode: composer.audienceMode };
    try {
      const response = composer.id
        ? await api.patch<BroadcastDetail>(`/admin/broadcasts/${encodeURIComponent(composer.id)}`, { ...common, ...(composer.selectedIds !== null ? { selected_user_ids: composer.audienceMode === 'SELECTED_USERS' ? composer.selectedIds : [] } : {}) })
        : await api.post<BroadcastDetail>('/admin/broadcasts', { ...common, selected_user_ids: composer.audienceMode === 'SELECTED_USERS' ? composer.selectedIds || [] : [] });
      const value = response.data;
      setDetail(value);
      setComposer((current) => ({ ...current, id: value.id, status: value.status, selectedCount: value.selected_user_count }));
      setSuccess('Draft saved. The backend confirmed the content and audience definition.');
      await loadHistory();
      return value;
    } catch (caught) {
      setError(communicationsError(caught));
      return null;
    } finally { setBusy(null); }
  };

  const previewAudience = async () => {
    const saved = await saveDraft();
    const id = saved?.id || composer.id;
    if (!id) return;
    setBusy('preview');
    try {
      const response = await api.post<{ eligible_recipient_count: number; frozen_recipient_count?: number }>(`/admin/broadcasts/${encodeURIComponent(id)}/audience-preview`);
      const count = response.data.frozen_recipient_count ?? response.data.eligible_recipient_count;
      setPreviewCount(count);
      setSuccess(`Audience preview confirmed ${count} eligible recipient${count === 1 ? '' : 's'}.`);
    } catch (caught) { setError(communicationsError(caught)); }
    finally { setBusy(null); }
  };

  const sendTest = async () => {
    const saved = await saveDraft();
    const id = saved?.id || composer.id;
    if (!id) return;
    const requestId = testRequestIds.current.get(id) || crypto.randomUUID();
    testRequestIds.current.set(id, requestId);
    setBusy('test'); setError(null);
    try {
      await api.post(`/admin/broadcasts/${encodeURIComponent(id)}/send-test`, { request_id: requestId });
      setSuccess('Test delivered only to your administrator inbox.');
    } catch (caught) { setError(communicationsError(caught)); }
    finally { setBusy(null); }
  };

  const openConfirmation = async () => {
    const saved = await saveDraft();
    if (!saved) return;
    try {
      const response = await api.post<{ eligible_recipient_count: number }>(`/admin/broadcasts/${encodeURIComponent(saved.id)}/audience-preview`);
      const count = response.data.eligible_recipient_count;
      setPreviewCount(count);
      if (count === 0) {
        setError('No eligible recipients are in this audience. Final send remains unavailable.');
        return;
      }
      setConfirmOpen(true);
    } catch (caught) { setError(communicationsError(caught)); }
  };

  const sendFinal = async () => {
    if (!composer.id) return;
    setBusy('send'); setError(null);
    try {
      const response = await api.post<BroadcastDetail>(`/admin/broadcasts/${encodeURIComponent(composer.id)}/send`);
      setDetail(response.data);
      setComposer((current) => ({ ...current, status: response.data.status }));
      setConfirmOpen(false);
      setSuccess(`Broadcast accepted with ${response.data.recipient_count} frozen recipients. Delivery is asynchronous.`);
      await loadHistory();
    } catch (caught) { setConfirmOpen(false); setError(communicationsError(caught)); }
    finally { setBusy(null); }
  };

  const searchUsers = async (event: FormEvent) => {
    event.preventDefault();
    if (!userQuery.trim()) return;
    setUserSearchBusy(true); setError(null);
    try {
      const response = await api.get<AdminAccountsPage>('/admin/accounts', { params: { query: userQuery.trim(), approval_status: 'approved', limit: 20, offset: 0 } });
      setUserResults(response.data.items);
    } catch (caught) { setError(communicationsError(caught)); }
    finally { setUserSearchBusy(false); }
  };

  const selection = composer.selectedIds || [];
  const editable = mutableBroadcast(composer.status);
  const liveDetail = detail && detail.id === composer.id ? detail : null;
  const audienceLabel = composer.audienceMode === 'ALL_ELIGIBLE_USERS' ? 'All eligible users' : 'Selected users';
  const preview = useMemo(() => ({ subject: composer.subject || 'Your subject appears here', body: composer.body || 'Your message preview appears here.' }), [composer.body, composer.subject]);

  return (
    <div className="admin-page broadcasts-page ds-container-split ds-stack">
      <header className="admin-page-header">
        <div><span className="ds-eyebrow">Communications</span><h1>Broadcasts &amp; announcements</h1><p className="ds-muted">Compose, verify and monitor administrator-authored inbox messages.</p></div>
        <Button variant="secondary" onClick={() => { setComposer(emptyComposer()); setDetail(null); setPreviewCount(null); setSuccess(null); }} leadingIcon={<Plus aria-hidden />}>New broadcast</Button>
      </header>
      {error && <Alert tone="danger" title={error} />}
      {success && <Alert tone="success" title={success} />}

      <div className="broadcast-layout">
        <section className="ds-surface broadcast-history" aria-busy={loading}>
          <div className="admin-section-heading"><div><h2>Broadcast history</h2><p className="ds-muted">Newest first, with backend delivery totals.</p></div><Button variant="icon" aria-label="Refresh broadcast history" onClick={() => loadHistory()}><RefreshCw className={loading ? 'ds-spin' : ''} aria-hidden /></Button></div>
          <label className="ds-field"><span className="ds-field-label">Status</span><select className="ds-control" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as '' | BroadcastStatus)}>{STATUSES.map((status) => <option key={status || 'ALL'} value={status}>{status || 'ALL'}</option>)}</select></label>
          {loading ? <div className="admin-loading" role="status"><Loader2 className="ds-spin" aria-hidden />Loading history…</div> : history.length === 0 ? <div className="admin-empty">No broadcasts match this filter.</div> : (
            <ol className="broadcast-history-list">{history.map((item) => <li key={item.id}><button type="button" className="broadcast-history-item" data-active={composer.id === item.id} onClick={() => void selectHistory(item)} disabled={busy === `detail-${item.id}`}><span className={`ds-badge broadcast-status status-${item.status.toLowerCase()}`}>{item.status}</span><strong><BidiText>{item.subject}</BidiText></strong><span className="ds-muted ds-numeric">{item.delivered_count}/{item.recipient_count} delivered</span><time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time></button></li>)}</ol>
          )}
          {nextCursor && <Button variant="ghost" loading={busy === 'history-more'} onClick={() => loadHistory(true, nextCursor)} trailingIcon={<ChevronDown aria-hidden />}>Load more</Button>}
        </section>

        <main className="broadcast-workspace">
          <section className="ds-surface broadcast-composer">
            <div className="admin-section-heading"><div><h2>{composer.id ? 'Broadcast detail' : 'New broadcast'}</h2><p className="ds-muted">{editable ? 'Draft changes remain private until an explicit final send.' : 'Queued and sent content is immutable.'}</p></div>{composer.status && <span className={`ds-badge broadcast-status status-${composer.status.toLowerCase()}`}>{composer.status}</span>}</div>
            <fieldset disabled={!editable || Boolean(busy)} className="broadcast-fields">
              <legend className="sr-only">Broadcast content</legend>
              <div className="broadcast-type"><Radio name="message-type" checked={composer.messageType === 'ANNOUNCEMENT'} onChange={() => setComposer((value) => ({ ...value, messageType: 'ANNOUNCEMENT' }))} label="Announcement" /><Radio name="message-type" checked={composer.messageType === 'SYSTEM_ALERT'} onChange={() => setComposer((value) => ({ ...value, messageType: 'SYSTEM_ALERT' }))} label="System alert" /></div>
              <Input label="Subject" maxLength={200} value={composer.subject} onChange={(event) => setComposer((value) => ({ ...value, subject: event.target.value }))} />
              <Textarea label="Body" helper="Plain text is delivered verbatim. HTML is never executed." rows={8} maxLength={5000} count={`${composer.body.length}/5000`} value={composer.body} onChange={(event) => setComposer((value) => ({ ...value, body: event.target.value }))} />
              <fieldset className="broadcast-audience"><legend>Audience</legend><Radio name="audience" checked={composer.audienceMode === 'ALL_ELIGIBLE_USERS'} onChange={() => { setComposer((value) => ({ ...value, audienceMode: 'ALL_ELIGIBLE_USERS', selectedIds: [] })); setPreviewCount(null); }} label="All eligible users" /><Radio name="audience" checked={composer.audienceMode === 'SELECTED_USERS'} onChange={() => { setComposer((value) => ({ ...value, audienceMode: 'SELECTED_USERS', selectedIds: value.selectedIds ?? null })); setPreviewCount(null); }} label="Selected users" /></fieldset>
              {composer.audienceMode === 'SELECTED_USERS' && <RecipientPicker query={userQuery} setQuery={setUserQuery} results={userResults} selected={selection} preservedCount={composer.selectedIds === null ? composer.selectedCount : null} busy={userSearchBusy} onSearch={searchUsers} onToggle={(id) => setComposer((value) => ({ ...value, selectedIds: selection.includes(id) ? selection.filter((item) => item !== id) : [...selection, id] }))} />}
            </fieldset>
            <div className="broadcast-command-bar">
              <Button variant="secondary" loading={busy === 'save'} disabled={!editable || Boolean(busy)} onClick={() => void saveDraft()}>Save draft</Button>
              <Button variant="secondary" loading={busy === 'preview'} disabled={!editable || Boolean(busy)} onClick={() => void previewAudience()} leadingIcon={<Users aria-hidden />}>Preview audience</Button>
              <Button variant="secondary" loading={busy === 'test'} disabled={!editable || Boolean(busy)} onClick={() => void sendTest()} leadingIcon={<Send aria-hidden />}>Send test</Button>
              <Button loading={busy === 'send'} disabled={!editable || Boolean(busy)} onClick={() => void openConfirmation()} leadingIcon={<Megaphone aria-hidden />}>Broadcast now</Button>
            </div>
          </section>

          <aside className="ds-surface broadcast-preview" aria-label="Inbox live preview">
            <div className="admin-section-heading"><div><h2>Inbox preview</h2><p className="ds-muted">Read-only plain-text rendering.</p></div><Eye aria-hidden /></div>
            <article className="notification-row" data-read="false"><span className="notification-state"><AlertTriangle aria-hidden /></span><div className="notification-content"><div className="notification-meta"><span className="ds-badge">{composer.messageType === 'SYSTEM_ALERT' ? 'System alert' : 'Announcement'}</span></div><h3><BidiText>{preview.subject}</BidiText></h3><BidiText className="notification-body">{preview.body}</BidiText></div></article>
            <dl className="broadcast-metrics"><div><dt>Audience</dt><dd>{audienceLabel}</dd></div><div><dt>{composer.status && composer.status !== 'DRAFT' ? 'Frozen recipients' : 'Eligible preview'}</dt><dd className="ds-numeric">{composer.status && composer.status !== 'DRAFT' ? liveDetail?.recipient_count ?? '—' : previewCount ?? 'Not checked'}</dd></div>{liveDetail && <><div><dt>Delivered</dt><dd className="ds-numeric">{liveDetail.delivered_count}</dd></div><div><dt>Failed</dt><dd className="ds-numeric">{liveDetail.failed_count}</dd></div></>}</dl>
            {liveDetail && terminalBroadcast(liveDetail.status) && liveDetail.status !== 'SENT' && <Alert tone="warning" title={liveDetail.status === 'PARTIAL' ? 'Delivery completed partially.' : 'Delivery failed.'}>Counts are authoritative. Internal worker exceptions are not exposed.</Alert>}
          </aside>
        </main>
      </div>

      <Dialog open={confirmOpen} onClose={() => !busy && setConfirmOpen(false)} title="Confirm final broadcast" description="This freezes the audience and makes the message read-only." closeLabel="Close confirmation" initialFocusRef={confirmRef} footer={<><Button variant="secondary" onClick={() => setConfirmOpen(false)} disabled={Boolean(busy)}>Cancel</Button><Button ref={confirmRef} onClick={() => void sendFinal()} loading={busy === 'send'} leadingIcon={<Send aria-hidden />}>Send to {previewCount ?? 0} recipients</Button></>}>
        <div className="broadcast-confirm"><ShieldAlert aria-hidden /><dl><div><dt>Message type</dt><dd>{composer.messageType === 'SYSTEM_ALERT' ? 'System alert' : 'Announcement'}</dd></div><div><dt>Audience</dt><dd>{audienceLabel}</dd></div><div><dt>Authoritative eligible count</dt><dd className="ds-numeric">{previewCount ?? 0}</dd></div></dl><p>Delivery begins asynchronously after confirmation. Repeated requests resolve to the same backend send.</p></div>
      </Dialog>
    </div>
  );
}

function RecipientPicker({ query, setQuery, results, selected, preservedCount, busy, onSearch, onToggle }: { query: string; setQuery: (value: string) => void; results: AdminAccount[]; selected: string[]; preservedCount: number | null; busy: boolean; onSearch: (event: FormEvent) => void; onToggle: (id: string) => void }) {
  return <div className="recipient-picker"><div><strong>Selected-user search</strong><p className="ds-muted">Search returns at most 20 approved accounts. The full user corpus is never loaded.</p>{preservedCount !== null && <Alert tone="info" title={`${preservedCount} saved selections are preserved.`}>Choosing a result starts a replacement selection.</Alert>}</div><form onSubmit={onSearch} className="recipient-search"><SearchField label="Search approved accounts" clearLabel="Clear user search" placeholder="Name or email" value={query} onValueChange={setQuery} /><Button type="submit" variant="secondary" loading={busy} leadingIcon={<Search aria-hidden />}>Search</Button></form>{results.length > 0 && <ul className="recipient-results">{results.map((account) => { const checked = selected.includes(account.id); return <li key={account.id}><label><input type="checkbox" checked={checked} onChange={() => onToggle(account.id)} /><span><BidiText>{account.name}</BidiText><TechnicalText>{account.email}</TechnicalText></span>{checked ? <Check aria-label="Selected" /> : <Plus aria-hidden />}</label></li>; })}</ul>}{selected.length > 0 && <div className="recipient-selection"><strong>{selected.length} selected</strong>{selected.map((id) => <button type="button" key={id} onClick={() => onToggle(id)}><TechnicalText>{id}</TechnicalText><X aria-hidden /></button>)}</div>}</div>;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
