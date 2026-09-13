'use client';
// Copied into an ISOLATED test build by s10-1-browser-acceptance.py. Never a runtime route.
import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { NextIntlClientProvider } from 'next-intl';
import { CustomerShell } from '@/components/shell/CustomerShell';
import { AdminShell } from '@/components/shell/AdminShell';
import { Button } from '@/components/ui/Button';
import {
  Input,
  Textarea,
  SearchField,
  Select,
  Checkbox,
  Radio,
  Combobox,
} from '@/components/ui/Forms';
import {
  Tabs,
  SegmentedControl,
  Pagination,
  Breadcrumbs,
} from '@/components/ui/Navigation';
import {
  Badge,
  StatusBadge,
  Surface,
  Metric,
  Skeleton,
  EmptyState,
  PageHeader,
  SectionHeader,
  DataTable,
} from '@/components/ui/Display';
import { Dialog, Drawer, Dropdown } from '@/components/ui/Overlay';
import { Alert, Tooltip } from '@/components/ui/Feedback';
import { TechnicalText, BidiText } from '@/components/i18n/BidiText';
import en from '@/messages/en/navigation.json';
import uz from '@/messages/uz/navigation.json';
import ru from '@/messages/ru/navigation.json';
import ar from '@/messages/ar/navigation.json';
export default function FoundationFixture() {
  const params = useSearchParams();
  const requestedLocale = params.get('locale');
  const locale =
    requestedLocale === 'ar' ||
    requestedLocale === 'ru' ||
    requestedLocale === 'uz'
      ? requestedLocale
      : 'en';
  const admin = params.get('admin') === '1';
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState('first');
  const [segment, setSegment] = useState('all');
  const [dialog, setDialog] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [count, setCount] = useState(0);
  const [alert, setAlert] = useState(true);
  const content = (
    <div
      className={`ds-theme ds-stack ${admin ? 'ds-admin' : ''}`}
      data-fixture-content
    >
      <Breadcrumbs
        label="Breadcrumbs"
        items={[
          { label: 'Foundation', href: '/s101-fixture' },
          { label: 'Components' },
        ]}
      />
      <PageHeader
        eyebrow="DESIGN FOUNDATION"
        title={
          locale === 'ar'
            ? 'أساس التصميم ومكوّنات الواجهة'
            : 'Application foundation'
        }
        description="Deterministic component acceptance fixture"
        primaryAction={
          <Button onClick={() => setCount(count + 1)}>Primary action</Button>
        }
        metadata={<span data-count>{count}</span>}
      />
      <Surface>
        <SectionHeader title="Controls" />
        <div className="ds-row">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button disabled>Disabled</Button>
          <Button loading>Saving</Button>
          <Tooltip content="Additional context">
            <Button variant="secondary">Tooltip control</Button>
          </Tooltip>
        </div>
      </Surface>
      <Surface className="ds-stack">
        <Input label="Company name" helper="Legal name" />
        <Input
          label="Email"
          type="email"
          defaultValue="pilot@example.invalid"
          readOnly
        />
        <Input label="Invalid field" error="This field is required" />
        <Input label="Disabled field" disabled />
        <SearchField
          label="Search"
          clearLabel="Clear search"
          value={query}
          onValueChange={setQuery}
          shortcut="⌘ K"
        />
        <Textarea label="Notes" helper="Optional information" count="0 / 500" />
        <Select label="Status">
          <option>All</option>
          <option>Active</option>
        </Select>
        <Combobox label="Country" options={['Uzbekistan', 'Kazakhstan']} />
        <Checkbox label="Include archived" />
        <Radio name="mode" label="First mode" defaultChecked />
        <Radio name="mode" label="Second mode" />
      </Surface>
      <SegmentedControl
        label="Filter"
        value={segment}
        onChange={setSegment}
        options={[
          { value: 'all', label: 'All' },
          { value: 'recommended', label: 'Recommended' },
          { value: 'dismissed', label: 'Dismissed' },
        ]}
      />
      <Tabs
        label="View"
        value={tab}
        onChange={setTab}
        items={[
          { value: 'first', label: 'First tab', content: 'First panel' },
          { value: 'second', label: 'Second tab', content: 'Second panel' },
          {
            value: 'disabled',
            label: 'Disabled tab',
            disabled: true,
            content: 'Unavailable',
          },
        ]}
      />
      <Surface>
        <div className="ds-row">
          {(
            [
              'neutral',
              'info',
              'success',
              'warning',
              'danger',
              'accent',
            ] as const
          ).map((tone) => (
            <StatusBadge key={tone} tone={tone}>
              {tone}
            </StatusBadge>
          ))}
          <Badge>Neutral badge</Badge>
        </div>
        <Metric
          label="Count"
          value="1,024"
          supporting="Fixture value"
          state={<Badge tone="success">Ready</Badge>}
        />
        <BidiText>English — العربية — Русский</BidiText>
        <TechnicalText>WB-2026-00123 · pilot@example.invalid</TechnicalText>
      </Surface>
      {alert && (
        <Alert
          tone="warning"
          title="Review required"
          dismissLabel="Dismiss alert"
          onDismiss={() => setAlert(false)}
        >
          A visible status description.
        </Alert>
      )}
      <Surface>
        <Skeleton />
        <EmptyState
          title="No items"
          description="Change the filters to continue."
          action={<Button variant="secondary">Reset filters</Button>}
        />
      </Surface>
      <DataTable
        caption="Fixture records"
        columns={[
          {
            key: 'name',
            heading: 'Name',
            cell: (r: { id: string; name: string; amount: number }) => (
              <BidiText>{r.name}</BidiText>
            ),
          },
          {
            key: 'amount',
            heading: 'Amount',
            numeric: true,
            cell: (r) => r.amount,
          },
        ]}
        rows={[{ id: '1', name: 'Reference — مرجع', amount: 12345 }]}
        rowKey={(r) => r.id}
        loadingLabel="Loading records"
        empty="No records"
        pagination={
          <Pagination
            label="Pagination"
            previousLabel="Previous"
            nextLabel="Next"
            hasPrevious={count > 0}
            hasNext
            onPrevious={() => setCount(Math.max(0, count - 1))}
            onNext={() => setCount(count + 1)}
          />
        }
      />
      <div className="ds-row">
        <Button onClick={() => setDialog(true)}>Open dialog</Button>
        <Button onClick={() => setDrawer(true)}>Open drawer</Button>
        <Dropdown label="Actions" trigger="Actions">
          <Button
            variant="ghost"
            role="menuitem"
            onClick={() => setCount(count + 1)}
          >
            Increase count
          </Button>
          <Button variant="ghost" role="menuitem">
            Second action
          </Button>
        </Dropdown>
      </div>
      <Dialog
        open={dialog}
        onClose={() => setDialog(false)}
        title="Confirm action"
        description="Dialog description"
        closeLabel="Close dialog"
        footer={<Button onClick={() => setDialog(false)}>Confirm</Button>}
      >
        <Input label="Dialog input" />
      </Dialog>
      <Drawer
        open={drawer}
        onClose={() => setDrawer(false)}
        title="Details"
        closeLabel="Close drawer"
      >
        <Input label="Drawer input" />
      </Drawer>
    </div>
  );
  return (
    <NextIntlClientProvider
      locale={locale}
      messages={{
        navigation: ({ en, uz, ru, ar } as Record<string, typeof en>)[locale],
      }}
    >
      <div dir={locale === 'ar' ? 'rtl' : 'ltr'} lang={locale}>
        {admin ? (
          <AdminShell
            isEffectiveAdmin
            name="Synthetic Admin"
            email="admin@example.invalid"
            onLogout={() => setCount(count + 1)}
          >
            {content}
          </AdminShell>
        ) : (
          <CustomerShell
            canAdmin
            name="Synthetic Pilot"
            email="pilot@example.invalid"
            company="Fixture Company"
            onLogout={() => setCount(count + 1)}
          >
            {content}
          </CustomerShell>
        )}
      </div>
    </NextIntlClientProvider>
  );
}
