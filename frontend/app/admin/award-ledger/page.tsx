'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, ExternalLink, Landmark, RefreshCw } from 'lucide-react';
import { useSession } from 'next-auth/react';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, Metric, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { SearchField, Select } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import {
    LEDGER_STATUSES,
    bidLabel,
    filenameFrom,
    formatCount,
    ledgerQuery,
    saveDownload,
    statusLabel,
    statusTone,
    type AwardOutcomeItem,
    type AwardOutcomePage,
    type LedgerFilters,
    type LedgerStatus,
    type LedgerSummary,
} from '@/lib/adminAnalytics';
import { formatTimestamp } from '@/lib/adminPanels';

const PAGE_SIZE = 50;
const GROUPS = ['Consultant Services', 'Goods', 'Works', 'Non-consulting Services'];

/** Sprint 1: public award outcomes per bidder (World Bank contract awards). Firm and market exports are admin-only. */
export default function AdminAwardLedgerPage() {
    const { data: session } = useSession();
    const isAdmin = session?.is_admin === true || session?.platform_role === 'admin';
    const [summary, setSummary] = useState<LedgerSummary | null>(null);
    const [page, setPage] = useState<AwardOutcomePage | null>(null);
    const [filters, setFilters] = useState<LedgerFilters>({ procurement_group: 'Consultant Services' });
    const [search, setSearch] = useState('');
    const [offset, setOffset] = useState(0);
    const [loading, setLoading] = useState(true);
    const [downloading, setDownloading] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [summaryResponse, pageResponse] = await Promise.all([
                api.get<LedgerSummary>('/admin/award-ledger/summary'),
                api.get<AwardOutcomePage>(`/admin/award-ledger/outcomes?${ledgerQuery(filters, { limit: PAGE_SIZE, offset })}`),
            ]);
            setSummary(summaryResponse.data);
            setPage(pageResponse.data);
        } catch {
            setError('The award ledger could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, [filters, offset]);
    useEffect(() => { void load(); }, [load]);

    useEffect(() => {
        const timer = setTimeout(() => {
            setOffset(0);
            setFilters((current) => (current.q ?? '') === search ? current : { ...current, q: search });
        }, 350);
        return () => clearTimeout(timer);
    }, [search]);

    const setFilter = (key: keyof LedgerFilters, value: string) => {
        setOffset(0);
        setFilters((current) => ({ ...current, [key]: value }));
    };

    const download = async (key: string, path: string, fallback: string, type: string) => {
        setDownloading(key);
        setError(null);
        try {
            const response = await api.get<string>(path, { responseType: 'text' });
            saveDownload(response.data, filenameFrom(response.headers['content-disposition'], fallback), type);
        } catch {
            setError('The download failed.');
        } finally {
            setDownloading(null);
        }
    };

    const totals = useMemo(() => {
        const rows: Record<string, number> = {};
        for (const country of summary?.countries ?? []) {
            for (const [status, count] of Object.entries(country.rows)) rows[status] = (rows[status] ?? 0) + (count ?? 0);
        }
        return rows;
    }, [summary]);

    const total = page?.total ?? 0;
    return <div className="admin-page ds-container-data ds-stack" data-admin-award-ledger>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Landmark aria-hidden />
                <div>
                    <span className="ds-eyebrow">Market data</span>
                    <h1>Award ledger</h1>
                    <p className="ds-muted">Every bidder in published World Bank contract-award notices for Uzbekistan, Kazakhstan, the Kyrgyz Republic and Tajikistan. Reasons are verbatim; public data only.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        {error && <Alert tone="danger" title={error} />}

        <section className="admin-metric-grid" aria-label="Ledger totals">
            <Metric label="Notices" value={formatCount(summary?.notice_count)}
                supporting={summary?.first_notice_date ? `${summary.first_notice_date} to ${summary.last_notice_date}` : undefined} />
            <Metric label="Bidder rows" value={formatCount(summary?.row_count)} />
            {LEDGER_STATUSES.filter((status) => status !== 'NOT_EVALUATED' || totals[status]).map((status) =>
                <Metric key={status} label={statusLabel(status)} value={formatCount(totals[status] ?? 0)} />)}
        </section>
        {summary?.last_retrieved_at && <p className="ds-muted">
            Last retrieved {formatTimestamp(summary.last_retrieved_at)} · {formatCount(summary.stored_snapshot_count)} stored notice snapshots (append-only).
        </p>}

        <DataTable
            caption="Bidder rows by country and status"
            loading={loading && !summary}
            loadingLabel="Loading totals…"
            empty={<span className="ds-muted">The ledger is empty. Run scripts/ingest_award_ledger.py.</span>}
            rows={summary?.countries ?? []}
            rowKey={(item) => item.country}
            columns={[
                { key: 'country', heading: 'Country', cell: (item) => item.country || '—' },
                { key: 'notices', heading: 'Notices', numeric: true, cell: (item) => formatCount(item.notices) },
                ...LEDGER_STATUSES.filter((status) => status !== 'NOT_EVALUATED' || totals[status]).map((status) => ({
                    key: status, heading: statusLabel(status), numeric: true, cell: (item: LedgerSummary['countries'][number]) => formatCount(item.rows[status] ?? 0),
                })),
                { key: 'empty', heading: 'Without bidders', numeric: true, cell: (item) => formatCount(item.notices_without_bidders) },
            ]}
        />

        <section className="ds-stack" aria-label="Exports">
            <div className="ds-row admin-export-row">
                <Button variant="secondary" leadingIcon={<Download aria-hidden />} loading={downloading === 'ledger'} disabled={downloading !== null}
                    onClick={() => void download('ledger', `/admin/award-ledger/outcomes.csv?${ledgerQuery(filters)}`, 'award-ledger.csv', 'text/csv;charset=utf-8')}>
                    Ledger CSV (filtered)
                </Button>
                {isAdmin && <>
                    <Button variant="secondary" leadingIcon={<Download aria-hidden />} loading={downloading === 'firms'} disabled={downloading !== null}
                        onClick={() => void download('firms', '/admin/award-ledger/firms.csv', 'award-ledger-firms.csv', 'text/csv;charset=utf-8')}>
                        Firm export CSV
                    </Button>
                    <Button variant="secondary" leadingIcon={<Download aria-hidden />} loading={downloading === 'market-csv'} disabled={downloading !== null}
                        onClick={() => void download('market-csv', '/admin/award-ledger/market-sizing.csv', 'market-sizing.csv', 'text/csv;charset=utf-8')}>
                        Market sizing CSV
                    </Button>
                    <Button variant="secondary" leadingIcon={<Download aria-hidden />} loading={downloading === 'market-md'} disabled={downloading !== null}
                        onClick={() => void download('market-md', '/admin/award-ledger/market-sizing.md', 'market-sizing.md', 'text/markdown;charset=utf-8')}>
                        Market sizing summary
                    </Button>
                </>}
            </div>
            {!isAdmin && <p className="ds-muted">The firm export and market sizing are available to administrators.</p>}
        </section>

        <fieldset className="admin-ledger-filters ds-row">
            <legend className="sr-only">Filter bidder rows</legend>
            <Select label="Country" value={filters.country ?? ''} onChange={(event) => setFilter('country', event.target.value)}>
                <option value="">All countries</option>
                {(summary?.countries ?? []).map((item) => <option key={item.country} value={item.country}>{item.country}</option>)}
            </Select>
            <Select label="Status" value={filters.status ?? ''} onChange={(event) => setFilter('status', event.target.value as LedgerStatus | '')}>
                <option value="">All statuses</option>
                {LEDGER_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
            </Select>
            <Select label="Procurement group" value={filters.procurement_group ?? ''} onChange={(event) => setFilter('procurement_group', event.target.value)}>
                <option value="">All groups</option>
                {GROUPS.map((group) => <option key={group} value={group}>{group}</option>)}
            </Select>
            <SearchField label="Search bidder, package, notice or reason" clearLabel="Clear search" placeholder="Search bidder, package, notice, reason"
                value={search} onValueChange={setSearch} />
        </fieldset>

        <DataTable<AwardOutcomeItem>
            caption="Bidder rows"
            loading={loading}
            loadingLabel="Loading bidder rows…"
            empty={<span className="ds-muted">No bidder rows match these filters.</span>}
            rows={page?.items ?? []}
            rowKey={(item) => item.id}
            columns={[
                { key: 'notice', heading: 'Notice', cell: (item) => <span>
                    <a href={item.notice_url} target="_blank" rel="noreferrer noopener" className="ds-link">
                        <TechnicalText>{item.notice_id}</TechnicalText> <ExternalLink aria-hidden size={14} />
                    </a><br /><small className="ds-muted">{item.notice_date ?? '—'} · {item.country ?? '—'}</small>
                </span> },
                { key: 'package', heading: 'Package', cell: (item) => <span>
                    <BidiText>{item.package_title ?? '—'}</BidiText><br />
                    <small className="ds-muted">{item.procurement_method ?? '—'}{item.package_reference ? <> · <TechnicalText>{item.package_reference}</TechnicalText></> : null}</small>
                </span> },
                { key: 'bidder', heading: 'Bidder', cell: (item) => <span>
                    <strong><BidiText>{item.bidder_name}</BidiText></strong><br />
                    <small className="ds-muted">{item.bidder_country ?? 'Country not published'} · {bidLabel(item)}</small>
                </span> },
                { key: 'status', heading: 'Status', cell: (item) => <StatusBadge tone={statusTone(item.status)}>{statusLabel(item.status)}</StatusBadge> },
                { key: 'price', heading: 'Evaluated price', cell: (item) => item.evaluated_price_text ? <TechnicalText>{item.evaluated_price_text}</TechnicalText> : '—' },
                { key: 'reason', heading: 'Reason (verbatim)', cell: (item) => item.rejection_reason ? <BidiText>{item.rejection_reason}</BidiText> : '—' },
            ]}
            pagination={total > PAGE_SIZE ? <div className="ds-row admin-pagination">
                <Button size="sm" variant="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
                <span className="ds-muted">{formatCount(offset + 1)}–{formatCount(Math.min(offset + PAGE_SIZE, total))} of {formatCount(total)}</span>
                <Button size="sm" variant="secondary" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
            </div> : undefined}
        />
    </div>;
}
