"use client";

import { Pagination } from "@/components/ui/Navigation";
import {
  PageHeader,
  Surface,
  StatusBadge,
  PageSkeleton,
  EmptyState,
} from "@/components/ui/Display";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Forms";
import { Drawer, Dialog } from "@/components/ui/Overlay";
import { Alert } from "@/components/ui/Feedback";
import { useCollectionOffset } from "@/lib/useCollectionOffset";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { Archive, Plus, Edit3, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import {
  DOCUMENT_STATUS_OPTIONS,
  DOCUMENT_TYPE_OPTIONS,
  expiryState,
  documentStatusMessageKey,
  documentTypeMessageKey,
  expiryMessageKey,
} from "@/lib/readiness";
import { formatDate } from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { translateServiceLabel } from "@/i18n/taxonomy";
import {
  labelForService,
  serviceValueSet,
  useServiceMeta,
} from "@/lib/services";
import { BidiText, TechnicalText } from "@/components/i18n/BidiText";

type ReadinessDocument = {
  id: string;
  company_profile_id: string;
  document_type: string;
  document_name: string;
  document_number?: string | null;
  issuer?: string | null;
  issue_date?: string | null;
  expiry_date?: string | null;
  status: string;
  related_service?: string | null;
  notes?: string | null;
  optional_file_url?: string | null;
};

type FormState = {
  document_type: string;
  document_name: string;
  document_number: string;
  issuer: string;
  issue_date: string;
  expiry_date: string;
  status: string;
  related_service: string;
  notes: string;
  optional_file_url: string;
};

type Filters = {
  document_type: string;
  status: string;
  related_service: string;
};

type ReadinessTranslator = (
  key: string,
  values?: Record<string, string | number>,
) => string;

const emptyForm: FormState = {
  document_type: "license",
  document_name: "",
  document_number: "",
  issuer: "",
  issue_date: "",
  expiry_date: "",
  status: "unknown",
  related_service: "",
  notes: "",
  optional_file_url: "",
};

const emptyFilters: Filters = {
  document_type: "",
  status: "",
  related_service: "",
};

function toForm(document: ReadinessDocument): FormState {
  return {
    document_type: document.document_type,
    document_name: document.document_name,
    document_number: document.document_number ?? "",
    issuer: document.issuer ?? "",
    issue_date: document.issue_date ?? "",
    expiry_date: document.expiry_date ?? "",
    status: document.status,
    related_service: document.related_service ?? "",
    notes: document.notes ?? "",
    optional_file_url: document.optional_file_url ?? "",
  };
}

function toPayload(form: FormState) {
  return {
    document_type: form.document_type,
    document_name: form.document_name,
    document_number: form.document_number || null,
    issuer: form.issuer || null,
    issue_date: form.issue_date || null,
    expiry_date: form.expiry_date || null,
    status: form.status,
    related_service: form.related_service || null,
    notes: form.notes || null,
    optional_file_url: form.optional_file_url || null,
  };
}

function apiStatus(error: unknown): number | undefined {
  if (
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    typeof (error as { response?: { status?: unknown } }).response?.status ===
      "number"
  ) {
    return (error as { response: { status: number } }).response.status;
  }
  return undefined;
}

export default function ReadinessVaultPage() {
  const translate = useTranslations("readiness");
  const t = translate as ReadinessTranslator;
  const tCommon = useTranslations("common");
  const locale = useLocale() as CustomerSelectableLocale;
  const translateRef = useRef(t);
  useEffect(() => {
    translateRef.current = t;
  }, [t]);
  const services = useServiceMeta();
  const [documents, setDocuments] = useState<ReadinessDocument[]>([]);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ReadinessDocument | null>(
    null,
  );
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profileRequired, setProfileRequired] = useState(false);
  const [offset, setOffset] = useCollectionOffset();
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<Filters>(emptyFilters);

  const editingDocument = useMemo(
    () => documents.find((document) => document.id === editingId) ?? null,
    [documents, editingId],
  );
  const serviceValues = useMemo(() => serviceValueSet(services), [services]);
  const filteredDocuments = useMemo(
    () =>
      documents.filter((document) => {
        if (
          filters.document_type &&
          document.document_type !== filters.document_type
        ) {
          return false;
        }
        if (filters.status && document.status !== filters.status) {
          return false;
        }
        if (
          filters.related_service &&
          document.related_service !== filters.related_service
        ) {
          return false;
        }
        return true;
      }),
    [documents, filters],
  );

  const loadSequence = useRef(0);
  const loadDocuments = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError(null);
    setProfileRequired(false);
    try {
      const response = await api.get<ReadinessDocument[]>("/vault/readiness", {
        params: { limit: 25, offset, ...filters },
      });
      if (sequence !== loadSequence.current) return;
      setDocuments(response.data ?? []);
      setHasMore(response.headers["x-has-more"] === "true");
      setTotal(
        Number(response.headers["x-total-count"] ?? response.data.length),
      );
    } catch (err) {
      if (sequence !== loadSequence.current) return;
      if (apiStatus(err) === 404) {
        setDocuments([]);
        setProfileRequired(true);
        return;
      }
      setError("loadFailed");
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [offset, filters]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const openCreateForm = () => {
    if (profileRequired) {
      setError("profileRequiredAdd");
      return;
    }
    setEditingId(null);
    setForm(emptyForm);
    setFormOpen(true);
    setSaved(false);
    setError(null);
  };

  const openEditForm = (document: ReadinessDocument) => {
    const nextForm = toForm(document);
    if (
      nextForm.related_service &&
      !serviceValues.has(nextForm.related_service)
    ) {
      nextForm.related_service = "";
    }

    setEditingId(document.id);
    setForm(nextForm);
    setFormOpen(true);
    setSaved(false);
    setError(null);
  };

  const closeForm = () => {
    setFormOpen(false);
    setEditingId(null);
    setForm(emptyForm);
  };

  const updateField = (field: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const updateFilter = (field: keyof Filters, value: string) => {
    setOffset(0);
    setFilters((current) => ({ ...current, [field]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.document_name.trim()) {
      setError("nameRequired");
      return;
    }

    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      if (editingId) {
        const response = await api.put<ReadinessDocument>(
          `/vault/readiness/${editingId}`,
          toPayload(form),
        );
        setDocuments((current) =>
          current.map((document) =>
            document.id === editingId ? response.data : document,
          ),
        );
      } else {
        const response = await api.post<ReadinessDocument>(
          "/vault/readiness",
          toPayload(form),
        );
        setDocuments((current) => [...current, response.data]);
      }
      setSaved(true);
      closeForm();
      await loadDocuments();
      window.setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      if (apiStatus(err) === 404) {
        setProfileRequired(true);
        setError("profileRequiredSave");
        return;
      }
      setError("saveFailed");
    } finally {
      setSaving(false);
    }
  };

  const deleteDocument = async (document: ReadinessDocument) => {
    setDeletingId(document.id);
    setError(null);
    try {
      await api.delete(`/vault/readiness/${document.id}`);
      setDocuments((current) =>
        current.filter((item) => item.id !== document.id),
      );
      setDeleteTarget(null);
      await loadDocuments();
      if (editingId === document.id) {
        closeForm();
      }
    } catch (err) {
      if (apiStatus(err) === 404) {
        setError("notFound");
        return;
      }
      setError("deleteFailed");
    } finally {
      setDeletingId(null);
    }
  };

  const statusTone = (status: string) =>
    status === "available"
      ? ("success" as const)
      : status === "expired"
        ? ("danger" as const)
        : status === "missing"
          ? ("warning" as const)
          : ("neutral" as const);
  const expiryTone = (state: string) =>
    state === "expired"
      ? ("danger" as const)
      : state === "expiring_soon"
        ? ("warning" as const)
        : ("neutral" as const);
  const activeFilters = Object.values(filters).some(Boolean);
  const field = (key: keyof FormState, label: string, type = "text") => (
    <Input
      label={t(label)}
      type={type}
      dir={
        [
          "document_number",
          "optional_file_url",
          "issue_date",
          "expiry_date",
        ].includes(key)
          ? "ltr"
          : "auto"
      }
      value={form[key]}
      disabled={saving}
      onChange={(event) => updateField(key, event.target.value)}
      required={key === "document_name"}
      error={
        key === "document_name" && error === "nameRequired"
          ? t(error)
          : undefined
      }
    />
  );
  return (
    <div className="customer-page readiness-page">
      <PageHeader
        eyebrow={t("redesign.context")}
        title={t("title")}
        description={t("redesign.description")}
        primaryAction={
          <Button onClick={openCreateForm} disabled={profileRequired}>
            <Plus aria-hidden />
            {t("addRecord")}
          </Button>
        }
      />
      <p className="ds-muted" role="status">
        {t("recordCount", { shown: filteredDocuments.length, total })}
      </p>
      {error && !formOpen && (
        <Alert
          tone="danger"
          title={t(error)}
          action={
            error === "loadFailed" ? (
              <Button onClick={loadDocuments}>{t("redesign.retry")}</Button>
            ) : undefined
          }
        />
      )}
      {profileRequired && (
        <Alert tone="warning" title={t("profileRequiredView")} />
      )}
      {saved && <Alert tone="success" title={t("saved")} />}
      <Surface className="readiness-filters">
        <Select
          label={t("documentType")}
          value={filters.document_type}
          onChange={(event) =>
            updateFilter("document_type", event.target.value)
          }
        >
          <option value="">{t("allTypes")}</option>
          {DOCUMENT_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.messageKey)}
            </option>
          ))}
        </Select>
        <Select
          label={t("status")}
          value={filters.status}
          onChange={(event) => updateFilter("status", event.target.value)}
        >
          <option value="">{t("allStatuses")}</option>
          {DOCUMENT_STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.messageKey)}
            </option>
          ))}
        </Select>
        <Select
          label={t("relatedService")}
          value={filters.related_service}
          onChange={(event) =>
            updateFilter("related_service", event.target.value)
          }
        >
          <option value="">{t("allServices")}</option>
          {services.map((option) => (
            <option key={option.value} value={option.value}>
              {translateServiceLabel(
                option.value,
                tCommon,
                labelForService(option.value, services),
              )}
            </option>
          ))}
        </Select>
        <Button
          variant="secondary"
          disabled={!activeFilters}
          onClick={() => {
            setOffset(0);
            setFilters(emptyFilters);
          }}
        >
          {t("resetFilters")}
        </Button>
      </Surface>
      {loading ? (
        <PageSkeleton label={t("loading")} />
      ) : !error && !profileRequired && filteredDocuments.length === 0 ? (
        <EmptyState
          icon={<Archive aria-hidden />}
          title={
            activeFilters
              ? t("noMatches")
              : offset > 0
                ? t("redesign.pageEmpty")
                : t("empty")
          }
          action={
            !activeFilters && offset === 0 ? (
              <Button onClick={openCreateForm}>{t("addRecord")}</Button>
            ) : undefined
          }
        />
      ) : (
        <div className="readiness-grid">
          {filteredDocuments.map((record) => {
            const expiry = expiryState(record.expiry_date);
            const url =
              record.optional_file_url &&
              /^https?:\/\//i.test(record.optional_file_url)
                ? record.optional_file_url
                : null;
            return (
              <Surface key={record.id} className="readiness-record">
                <div className="ds-row">
                  <StatusBadge tone={statusTone(record.status)}>
                    {t(documentStatusMessageKey(record.status))}
                  </StatusBadge>
                  <StatusBadge>
                    {t(documentTypeMessageKey(record.document_type))}
                  </StatusBadge>
                </div>
                <h2>
                  <BidiText>{record.document_name}</BidiText>
                </h2>
                {record.document_number && (
                  <p className="ds-muted">
                    <TechnicalText>{record.document_number}</TechnicalText>
                  </p>
                )}
                {record.issuer && (
                  <p>
                    <BidiText>{record.issuer}</BidiText>
                  </p>
                )}
                <dl className="readiness-facts">
                  <div>
                    <dt>{t("issueDate")}</dt>
                    <dd>
                      {record.issue_date
                        ? formatDate(record.issue_date, locale)
                        : t("none")}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("expiryDate")}</dt>
                    <dd>
                      {record.expiry_date
                        ? formatDate(record.expiry_date, locale)
                        : t("none")}
                    </dd>
                  </div>
                </dl>
                {record.expiry_date && (
                  <div>
                    <StatusBadge tone={expiryTone(expiry)}>
                      {t(expiryMessageKey(expiry))}
                    </StatusBadge>
                  </div>
                )}
                {record.related_service && (
                  <div>
                    <StatusBadge>
                      {translateServiceLabel(
                        record.related_service,
                        tCommon,
                        labelForService(record.related_service, services),
                      )}
                    </StatusBadge>
                  </div>
                )}
                {record.notes && (
                  <p>
                    <BidiText>{record.notes}</BidiText>
                  </p>
                )}
                <footer className="ds-row">
                  {url ? (
                    <ButtonLink
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      variant="ghost"
                    >
                      {t("redesign.viewFile")}
                    </ButtonLink>
                  ) : (
                    <span className="ds-muted">
                      {record.optional_file_url ? (
                        <TechnicalText>
                          {record.optional_file_url}
                        </TechnicalText>
                      ) : (
                        t("redesign.noFile")
                      )}
                    </span>
                  )}
                  <Button
                    variant="icon"
                    aria-label={t("editNamed", { name: record.document_name })}
                    onClick={() => openEditForm(record)}
                  >
                    <Edit3 aria-hidden />
                  </Button>
                  <Button
                    variant="icon"
                    aria-label={t("deleteNamed", {
                      name: record.document_name,
                    })}
                    onClick={() => setDeleteTarget(record)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </footer>
              </Surface>
            );
          })}
        </div>
      )}
      <Pagination
        label={t("title")}
        hasPrevious={offset > 0}
        hasNext={hasMore}
        busy={loading}
        onPrevious={() => setOffset(Math.max(0, offset - 25))}
        onNext={() => setOffset(offset + 25)}
        previousLabel={tCommon("actions.previous")}
        nextLabel={tCommon("actions.next")}
      />
      <Drawer
        open={formOpen}
        onClose={() => {
          if (!saving) closeForm();
        }}
        title={editingDocument ? t("editRecord") : t("addRecordTitle")}
        closeLabel={t("closeForm")}
      >
        <form className="readiness-form" onSubmit={handleSubmit}>
          {error && <Alert tone="danger" title={t(error)} />}
          <Select
            label={t("documentType")}
            value={form.document_type}
            disabled={saving}
            onChange={(event) =>
              updateField("document_type", event.target.value)
            }
          >
            {DOCUMENT_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.messageKey)}
              </option>
            ))}
          </Select>
          {field("document_name", "documentName")}
          {field("document_number", "documentNumber")}
          {field("issuer", "issuer")}
          <div className="profile-fields">
            {field("issue_date", "issueDate", "date")}
            {field("expiry_date", "expiryDate", "date")}
          </div>
          <Select
            label={t("status")}
            value={form.status}
            disabled={saving}
            onChange={(event) => updateField("status", event.target.value)}
          >
            {DOCUMENT_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.messageKey)}
              </option>
            ))}
          </Select>
          <Select
            label={t("relatedService")}
            value={form.related_service}
            disabled={saving}
            onChange={(event) =>
              updateField("related_service", event.target.value)
            }
          >
            <option value="">{t("none")}</option>
            {services.map((option) => (
              <option key={option.value} value={option.value}>
                {translateServiceLabel(
                  option.value,
                  tCommon,
                  labelForService(option.value, services),
                )}
              </option>
            ))}
          </Select>
          {field("optional_file_url", "fileReference")}
          <p className="ds-muted">{t("redesign.fileHelp")}</p>
          <Textarea
            label={t("notes")}
            dir="auto"
            value={form.notes}
            disabled={saving}
            onChange={(event) => updateField("notes", event.target.value)}
          />
          <div className="ds-row">
            <Button variant="secondary" disabled={saving} onClick={closeForm}>
              {t("redesign.cancel")}
            </Button>
            <Button type="submit" loading={saving} disabled={saving}>
              {saving ? t("saving") : t("saveRecord")}
            </Button>
          </div>
        </form>
      </Drawer>
      <Dialog
        open={deleteTarget !== null}
        onClose={() => {
          if (!deletingId) setDeleteTarget(null);
        }}
        title={t("deleteConfirm", { name: deleteTarget?.document_name || "" })}
        closeLabel={t("closeForm")}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={!!deletingId}
              onClick={() => setDeleteTarget(null)}
            >
              {t("redesign.cancel")}
            </Button>
            <Button
              variant="danger"
              loading={!!deletingId}
              disabled={!!deletingId}
              onClick={() => {
                if (deleteTarget) void deleteDocument(deleteTarget);
              }}
            >
              {t("redesign.delete")}
            </Button>
          </>
        }
      >
        {error && <Alert tone="danger" title={t(error)} />}
      </Dialog>
    </div>
  );
}
