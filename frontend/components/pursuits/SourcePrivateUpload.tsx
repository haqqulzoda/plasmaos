'use client';

import { useCallback, useState } from 'react';
import { FilePlus2, LockKeyhole, Upload } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { OrganizationContextPicker } from '@/components/pursuits/OrganizationContextPicker';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Select } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import type { PrivateDocumentRole, PrivateUploadResponse } from '@/types/pursuit';

const ROLES: PrivateDocumentRole[] = [
  'RFP', 'TOR', 'NOTICE', 'ADDENDUM', 'CLARIFICATION', 'FORM', 'ANNEX', 'OTHER',
];

export function SourcePrivateUpload({ tenderId }: { tenderId: string }) {
  const t = useTranslations('pursuits');
  const [open, setOpen] = useState(false);
  const [organizationId, setOrganizationId] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [roles, setRoles] = useState<PrivateDocumentRole[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PrivateUploadResponse | null>(null);
  const chooseOrganization = useCallback((value: string) => setOrganizationId(value), []);

  const submit = async () => {
    if (!files.length || !organizationId || busy) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    form.append('roles', JSON.stringify(roles));
    try {
      const response = await api.post<PrivateUploadResponse>(
        `/pursuits/source/${encodeURIComponent(tenderId)}/documents`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data', 'X-Organization-ID': organizationId } },
      );
      setResult(response.data);
      setFiles([]);
      setRoles([]);
    } catch (caught: unknown) {
      const detail = (caught as { response?: { data?: { detail?: { message?: string } | string } } }).response?.data?.detail;
      setError(typeof detail === 'string' ? detail : detail?.message || t('upload.failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="private-upload-block" data-private-upload>
      <div className="private-upload-heading">
        <div>
          <span className="ds-eyebrow"><LockKeyhole aria-hidden />{t('sourceUpload.privateLabel')}</span>
          <h3>{t('sourceUpload.title')}</h3>
          <p className="ds-muted">{t('sourceUpload.help')}</p>
        </div>
        {!open && <Button type="button" variant="secondary" onClick={() => setOpen(true)} leadingIcon={<FilePlus2 aria-hidden />}>
          {t('sourceUpload.action')}
        </Button>}
      </div>
      {open && <div className="private-upload-form">
        <OrganizationContextPicker value={organizationId} onChange={chooseOrganization} />
        <label className="ds-field">
          <span className="ds-field-label">{t('upload.files')}</span>
          <input
            className="ds-control"
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            multiple
            onChange={(event) => {
              const selected = Array.from(event.target.files || []);
              setFiles(selected);
              setRoles(selected.map(() => 'OTHER'));
              setResult(null);
              setError(null);
            }}
          />
          <span className="ds-field-help">{t('upload.limits')}</span>
        </label>
        {files.map((file, index) => <div className="private-upload-file" key={`${file.name}-${file.lastModified}`}>
          <span>{file.name}</span>
          <Select
            label={t('upload.role')}
            value={roles[index] || 'OTHER'}
            onChange={(event) => setRoles((current) => current.map((role, roleIndex) => roleIndex === index ? event.target.value as PrivateDocumentRole : role))}
          >
            {ROLES.map((role) => <option key={role} value={role}>{t(`roles.${role}`)}</option>)}
          </Select>
        </div>)}
        {error && <p role="alert" className="ds-field-error">{error}</p>}
        <div className="ds-row">
          <Button type="button" onClick={() => void submit()} loading={busy} disabled={!files.length || !organizationId} leadingIcon={<Upload aria-hidden />}>
            {t('upload.submit')}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t('actions.cancel')}</Button>
        </div>
      </div>}
      {result && <div className="private-upload-success" role="status">
        <p>{t('sourceUpload.accepted', { count: result.document_ids.length })}</p>
        {result.duplicate_document_ids.length > 0 && <p>{t('upload.duplicateWarning')}</p>}
        <ButtonLink href={`/dashboard/pursuits/${result.pursuit.pursuit_id}?organization_id=${encodeURIComponent(organizationId)}`} variant="secondary">
          {t('actions.openWorkspace')}
        </ButtonLink>
      </div>}
    </div>
  );
}
