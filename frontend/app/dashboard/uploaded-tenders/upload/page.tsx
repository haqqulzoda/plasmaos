'use client';

import { FormEvent, useCallback, useState } from 'react';
import { ArrowLeft, FileUp, LockKeyhole, Upload } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Forms';
import { PageHeader, Surface } from '@/components/ui/Display';
import { api } from '@/lib/api';
import type { PrivateDocumentRole, PrivateUploadResponse } from '@/types/pursuit';

const ROLES: PrivateDocumentRole[] = [
  'RFP', 'TOR', 'NOTICE', 'ADDENDUM', 'CLARIFICATION', 'FORM', 'ANNEX', 'OTHER',
];
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const MAX_PACK_BYTES = 150 * 1024 * 1024;

export default function UploadTenderPage() {
  const t = useTranslations('pursuits');
  const router = useRouter();
  const [organizationId, setOrganizationId] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [roles, setRoles] = useState<PrivateDocumentRole[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chooseOrganization = useCallback((value: string) => setOrganizationId(value), []);
  const setField = (field: string, value: string) => setValues((current) => ({ ...current, [field]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!files.length || !organizationId || busy) return;
    if (files.some((file) => file.size > MAX_FILE_BYTES) || files.reduce((sum, file) => sum + file.size, 0) > MAX_PACK_BYTES) {
      setError(t('upload.sizeError'));
      return;
    }
    setBusy(true);
    setError(null);
    const context: Record<string, string | string[]> = {};
    const confirmed: string[] = [];
    for (const [key, value] of Object.entries(values)) {
      if (!value.trim()) continue;
      context[key] = key === 'external_deadline' ? new Date(value).toISOString() : value.trim();
      confirmed.push(key);
    }
    context.confirmed_fields = confirmed;
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    form.append('roles', JSON.stringify(roles));
    form.append('context_json', JSON.stringify(context));
    try {
      const response = await api.post<PrivateUploadResponse>('/pursuits/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data', 'X-Organization-ID': organizationId },
      });
      router.push(`/dashboard/pursuits/${response.data.pursuit.pursuit_id}?organization_id=${encodeURIComponent(organizationId)}${response.data.duplicate_document_ids.length ? '&duplicates=1' : ''}`);
    } catch (caught: unknown) {
      const detail = (caught as { response?: { data?: { detail?: { message?: string } | string } } }).response?.data?.detail;
      setError(typeof detail === 'string' ? detail : detail?.message || t('upload.failed'));
    } finally {
      setBusy(false);
    }
  };

  return <main className="customer-page pursuit-upload-page ds-container-narrow">
    <ButtonLink href="/dashboard/uploaded-tenders" variant="ghost" size="sm">
      <ArrowLeft className="rtl-mirror" aria-hidden />{t('actions.backToUploads')}
    </ButtonLink>
    <PageHeader eyebrow={t('upload.eyebrow')} title={t('upload.title')} description={t('upload.description')} />
    <form className="pursuit-upload-form" onSubmit={submit}>
      <Surface className="pursuit-upload-step">
        <header><span>1</span><div><h2>{t('upload.stepFiles')}</h2><p>{t('upload.stepFilesHelp')}</p></div></header>
        <div className="private-ownership-note"><LockKeyhole aria-hidden /><p>{t('upload.privateOwnership')}</p></div>
        <OrganizationContextPicker value={organizationId} onChange={chooseOrganization} />
        <label className="ds-field">
          <span className="ds-field-label">{t('upload.files')}</span>
          <input
            className="ds-control"
            type="file"
            required
            multiple
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(event) => {
              const selected = Array.from(event.target.files || []);
              setFiles(selected);
              setRoles(selected.map(() => 'OTHER'));
              setError(null);
            }}
          />
          <span className="ds-field-help">{t('upload.limits')}</span>
        </label>
        {files.map((file, index) => <div className="private-upload-file" key={`${file.name}-${file.lastModified}`}>
          <div><FileUp aria-hidden /><span>{file.name}</span><small>{Math.ceil(file.size / 1024)} KB</small></div>
          <Select label={t('upload.role')} value={roles[index] || 'OTHER'} onChange={(event) => setRoles((current) => current.map((role, roleIndex) => roleIndex === index ? event.target.value as PrivateDocumentRole : role))}>
            {ROLES.map((role) => <option value={role} key={role}>{t(`roles.${role}`)}</option>)}
          </Select>
        </div>)}
      </Surface>

      <Surface className="pursuit-upload-step">
        <header><span>2</span><div><h2>{t('upload.stepContext')}</h2><p>{t('upload.stepContextHelp')}</p></div></header>
        <div className="pursuit-context-grid">
          <Input label={t('fields.title')} value={values.title || ''} onChange={(event) => setField('title', event.target.value)} />
          <Input label={t('fields.buyer')} value={values.buyer || ''} onChange={(event) => setField('buyer', event.target.value)} />
          <Input label={t('fields.funder')} helper={t('upload.funderHelp')} value={values.declared_funder || ''} onChange={(event) => setField('declared_funder', event.target.value)} />
          <Input label={t('fields.country')} value={values.country || ''} onChange={(event) => setField('country', event.target.value)} />
          <Input label={t('fields.reference')} value={values.reference || ''} onChange={(event) => setField('reference', event.target.value)} />
          <Input label={t('fields.procurementStage')} value={values.procurement_stage || ''} onChange={(event) => setField('procurement_stage', event.target.value)} />
          <Input type="datetime-local" label={t('fields.deadline')} helper={t('upload.deadlineHelp')} value={values.external_deadline || ''} onChange={(event) => setField('external_deadline', event.target.value)} />
          <Input label={t('fields.timezone')} placeholder="Asia/Tashkent" value={values.deadline_timezone || ''} onChange={(event) => setField('deadline_timezone', event.target.value)} />
          <Input type="url" label={t('fields.sourceUrl')} value={values.source_url || ''} onChange={(event) => setField('source_url', event.target.value)} />
        </div>
      </Surface>
      {error && <p role="alert" className="pursuit-upload-error">{error}</p>}
      <div className="pursuit-upload-actions">
        <Button type="submit" loading={busy} disabled={!files.length || !organizationId} leadingIcon={<Upload aria-hidden />}>
          {t('upload.submit')}
        </Button>
        <p className="ds-muted">{t('upload.nextAction')}</p>
      </div>
    </form>
  </main>;
}
