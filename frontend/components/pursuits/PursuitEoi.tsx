'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, FileText, Plus, RefreshCw, Users } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { useLocale, useTranslations } from 'next-intl';

import { BidiText } from '@/components/i18n/BidiText';
import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState, StatusBadge, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox, Input, Select } from '@/components/ui/Forms';
import { formatDateTime } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';
import {
  EOI_STEPS,
  GENERATION_BUDGET_SECONDS,
  addressedBy,
  builderErrors,
  draftRequest,
  experienceRows,
  initialBuilderState,
  partnerCoversUncovered,
  setPartnerRole,
  staleReasonKey,
  toggleOwn,
  togglePartner,
  togglePartnerReference,
  type BuilderState,
  type EoiStep,
} from '@/lib/eoiBuilder';
import { requestFailure } from '@/lib/libraryApi';
import type { EoiCriterion, EoiDraft, EoiPartnerRole, EoiReference, EoiSuggestions } from '@/types/eoi';

type Loose = (key: string, values?: Record<string, string | number>) => string;
type Props = { pursuitId: string; headers: Record<string, string | undefined>; runId: string | null; onOpenRequirements: () => void };

function locatorText(criterion: EoiCriterion, t: Loose) {
  if (criterion.locator.page_number) return t('locatorPage', { page: criterion.locator.page_number });
  if (criterion.locator.paragraph_number) return t('locatorParagraph', { paragraph: criterion.locator.paragraph_number });
  return t('locatorNotice');
}

function ReferenceFacts({ reference }: { reference: EoiReference }) {
  const period = [reference.start_date?.slice(0, 7), reference.completion_date?.slice(0, 7)].filter(Boolean).join(' – ');
  return <small className="ds-muted">
    <BidiText>{[reference.client_name, reference.country, reference.sector].filter(Boolean).join(' · ')}</BidiText>
    {period && <span dir="ltr"> · {period}</span>}
  </small>;
}

export function PursuitEoi({ pursuitId, headers, runId, onOpenRequirements }: Props) {
  const t = useTranslations('pursuits.eoi') as unknown as Loose;
  const locale = useLocale() as CustomerSelectableLocale;
  const { data: session } = useSession();
  const [suggestions, setSuggestions] = useState<EoiSuggestions | null>(null);
  const [state, setState] = useState<BuilderState | null>(null);
  const [drafts, setDrafts] = useState<EoiDraft[]>([]);
  const [step, setStep] = useState<EoiStep>('experience');
  const [loading, setLoading] = useState(Boolean(runId));
  const [loadError, setLoadError] = useState<'unavailable' | 'failed' | null>(null);
  const [generating, setGenerating] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [created, setCreated] = useState<EoiDraft | null>(null);
  const base = `/pursuits/${encodeURIComponent(pursuitId)}`;

  const loadDrafts = useCallback(async () => {
    const response = await api.get<EoiDraft[]>(`${base}/eoi-drafts`, { headers });
    setDrafts(response.data);
  }, [base, headers]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    // Passive reads only: suggestions, the company profile for the letter, existing versions.
    Promise.all([
      api.get<EoiSuggestions>(`${base}/eoi/suggestions`, { headers, params: { analysis_run_id: runId } }),
      api.get<Record<string, string | null>>('/users/me/company').catch(() => ({ data: null })),
      api.get<EoiDraft[]>(`${base}/eoi-drafts`, { headers }).catch(() => ({ data: [] as EoiDraft[] })),
    ]).then(([suggested, profile, versions]) => {
      if (cancelled) return;
      setSuggestions(suggested.data);
      setState(initialBuilderState(suggested.data, { profile: profile.data, email: session?.user?.email, uiLocale: locale }));
      setDrafts(versions.data);
    }).catch((error) => {
      if (cancelled) return;
      const status = (error as { response?: { status?: number } })?.response?.status;
      setLoadError(status === 404 || status === 405 ? 'unavailable' : 'failed');
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // The session email only seeds the letter once; later session refreshes must not reset the builder.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, headers, runId]);

  useEffect(() => {
    if (!generating) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [generating]);

  const rows = useMemo(() => (suggestions && state ? experienceRows(suggestions, state) : []), [state, suggestions]);
  const addressed = useMemo(() => (suggestions && state ? addressedBy(suggestions, state) : new Map<string, number[]>()), [state, suggestions]);
  const errors = useMemo(() => (state ? builderErrors(state) : []), [state]);
  const rowNumber = (referenceId: string) => rows.find((row) => row.reference.reference_id === referenceId)?.no;

  const generate = async () => {
    if (!suggestions || !state || errors.length) return;
    setGenerating(true);
    setElapsed(0);
    setGenerateError(null);
    setCreated(null);
    try {
      const response = await api.post<EoiDraft>(`${base}/eoi-drafts`, draftRequest(suggestions, state), { headers });
      setCreated(response.data);
      await loadDrafts();
    } catch (error) {
      setGenerateError(requestFailure(error));
    } finally {
      setGenerating(false);
    }
  };

  const download = async (draft: EoiDraft, format: 'DOCX' | 'PDF') => {
    const artifact = draft.artifacts.find((item) => item.format === format);
    if (!artifact) return;
    const response = await api.get(`${base}/eoi-artifacts/${artifact.artifact_id}/download`, { headers, responseType: 'blob' });
    const url = URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.download = `expression-of-interest-v${draft.version}-${draft.language}.${format.toLowerCase()}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  if (!runId) return <EmptyState icon={<FileText aria-hidden />} title={t('noAnalysisTitle')} description={t('noAnalysisHelp')}
    action={<Button variant="secondary" onClick={onOpenRequirements}>{t('openRequirements')}</Button>} />;
  if (loading) return <p className="ds-muted" role="status">{t('loading')}</p>;
  if (loadError || !suggestions || !state) return <Alert tone={loadError === 'unavailable' ? 'info' : 'danger'}
    title={loadError === 'unavailable' ? t('unavailableTitle') : t('loadFailed')}>{loadError === 'unavailable' ? t('unavailableHelp') : ''}</Alert>;

  const setLetter = (field: keyof BuilderState['letter']) => (event: { target: { value: string } }) =>
    setState((current) => current && ({ ...current, letter: { ...current.letter, [field]: event.target.value } }));
  const errorFor = (field: string) => {
    const error = errors.find((item) => item.field === field);
    return error ? t(`errors.${error.code}`) : undefined;
  };

  return <div className="pursuit-eoi ds-stack" data-eoi-builder>
    {!suggestions.run_current && <Alert tone="warning" title={t('runNotCurrentTitle')}>{t('runNotCurrentHelp')}</Alert>}
    <nav className="eoi-steps" aria-label={t('stepsLabel')}>
      <ol>{EOI_STEPS.map((value, index) => <li key={value}>
        <button type="button" aria-current={step === value ? 'step' : undefined} onClick={() => setStep(value)} data-eoi-step={value}>
          <span className="eoi-step-number">{index + 1}</span>{t(`steps.${value}`)}
        </button>
      </li>)}</ol>
    </nav>

    {step === 'experience' && <section className="eoi-panel" aria-labelledby="eoi-experience-title" data-eoi-panel="experience">
      <header className="eoi-panel-header"><div><h3 id="eoi-experience-title">{t('steps.experience')}</h3><p className="ds-muted">{t('experienceHelp')}</p></div>
        <ButtonLink variant="ghost" size="sm" href="/dashboard/partners-experts?tab=own"><Plus aria-hidden />{t('addExperience')}</ButtonLink></header>
      <div className="eoi-experience-grid">
        <div className="eoi-criteria">
          <h4>{t('criteriaTitle', { count: suggestions.criteria.length })}</h4>
          {suggestions.criteria.length ? <ul>{suggestions.criteria.map((criterion) => {
            const numbers = addressed.get(criterion.requirement_id) ?? [];
            return <li key={criterion.requirement_id} data-criterion-id={criterion.requirement_id} data-addressed={numbers.length > 0}>
              <strong><BidiText>{criterion.statement}</BidiText></strong>
              <blockquote><BidiText>{criterion.original_quote}</BidiText></blockquote>
              <small className="ds-muted">{locatorText(criterion, t)}</small>
              <StatusBadge tone={numbers.length ? 'success' : 'neutral'}>
                {numbers.length ? t('addressedBy', { rows: numbers.map((value) => `#${value}`).join(', ') }) : t('notAddressed')}
              </StatusBadge>
            </li>;
          })}</ul> : <p className="ds-muted">{t('noCriteria')}</p>}
        </div>
        <div className="eoi-references">
          <h4>{t('ownTitle')}</h4>
          {suggestions.own_references.length ? <ul>{suggestions.own_references.map((reference) => {
            const checked = state.own.includes(reference.reference_id);
            const number = rowNumber(reference.reference_id);
            return <li key={reference.reference_id} data-reference-id={reference.reference_id} data-selected={checked}>
              <Checkbox label={<span className="eoi-reference-label">
                {number && <span className="eoi-row-number">#{number}</span>}
                <BidiText>{reference.project_name}</BidiText>
              </span>} checked={checked}
                onChange={(event) => setState((current) => current && toggleOwn(current, reference.reference_id, event.target.checked))} />
              <ReferenceFacts reference={reference} />
              <div className="eoi-badges">
                <StatusBadge tone={reference.matched_requirement_ids.length ? 'info' : 'neutral'}>
                  {t('matchesCriteria', { count: reference.matched_requirement_ids.length })}
                </StatusBadge>
                {reference.suggested && <StatusBadge tone="success">{t('suggested')}</StatusBadge>}
              </div>
            </li>;
          })}</ul> : <EmptyState icon={<FileText aria-hidden />} title={t('noOwnTitle')} description={t('noOwnHelp')}
            action={<ButtonLink href="/dashboard/partners-experts?tab=own">{t('addExperience')}</ButtonLink>} />}
        </div>
      </div>
      <div className="eoi-nav"><Button onClick={() => setStep('partners')}>{t('next')}</Button></div>
    </section>}

    {step === 'partners' && <section className="eoi-panel" aria-labelledby="eoi-partners-title" data-eoi-panel="partners">
      <header className="eoi-panel-header"><div><h3 id="eoi-partners-title">{t('steps.partners')}</h3><p className="ds-muted">{t('partnersHelp')}</p></div></header>
      {suggestions.partner_firms.length ? <ul className="eoi-partners">{suggestions.partner_firms.map((firm) => {
        const selection = state.partners[firm.firm_id];
        const covers = partnerCoversUncovered(suggestions, state, firm.firm_id);
        return <li key={firm.firm_id} data-partner-id={firm.firm_id}>
          <Surface className="eoi-partner-card">
            <Checkbox label={<strong><BidiText>{firm.display_name}</BidiText></strong>} checked={Boolean(selection)}
              onChange={(event) => setState((current) => current && togglePartner(current, firm.firm_id, event.target.checked))} />
            {firm.country && <small className="ds-muted"><BidiText>{firm.country}</BidiText></small>}
            <p className="ds-text-small">{covers.length ? t('coversUncovered', { count: covers.length }) : t('coversNone')}</p>
            {covers.length > 0 && <ul className="eoi-covers">{covers.map((id) => <li key={id}><BidiText>
              {suggestions.criteria.find((item) => item.requirement_id === id)?.statement ?? ''}
            </BidiText></li>)}</ul>}
            {selection && <div className="ds-stack">
              <Select label={t('partnerRole')} value={selection.role} name={`role-${firm.firm_id}`}
                onChange={(event) => setState((current) => current && setPartnerRole(current, firm.firm_id, event.target.value as EoiPartnerRole))}>
                <option value="JV_MEMBER">{t('roles.JV_MEMBER')}</option>
                <option value="SUBCONSULTANT">{t('roles.SUBCONSULTANT')}</option>
              </Select>
              {firm.references.length ? <ul className="eoi-partner-references">{firm.references.map((reference) => {
                const number = rowNumber(reference.reference_id);
                return <li key={reference.reference_id}>
                  <Checkbox label={<span className="eoi-reference-label">{number && <span className="eoi-row-number">#{number}</span>}<BidiText>{reference.project_name}</BidiText></span>}
                    checked={selection.referenceIds.includes(reference.reference_id)}
                    onChange={(event) => setState((current) => current && togglePartnerReference(current, firm.firm_id, reference.reference_id, event.target.checked))} />
                  <ReferenceFacts reference={reference} />
                  <StatusBadge tone={reference.matched_requirement_ids.length ? 'info' : 'neutral'}>{t('matchesCriteria', { count: reference.matched_requirement_ids.length })}</StatusBadge>
                </li>;
              })}</ul> : <p className="ds-muted">{t('partnerNoReferences')}</p>}
            </div>}
          </Surface>
        </li>;
      })}</ul> : <EmptyState icon={<Users aria-hidden />} title={t('noPartnersTitle')} description={t('noPartnersHelp')}
        action={<ButtonLink variant="secondary" href="/dashboard/partners-experts?tab=partners">{t('addPartner')}</ButtonLink>} />}
      <div className="eoi-nav"><Button variant="secondary" onClick={() => setStep('experience')}>{t('back')}</Button><Button onClick={() => setStep('letter')}>{t('next')}</Button></div>
    </section>}

    {step === 'letter' && <section className="eoi-panel" aria-labelledby="eoi-letter-title" data-eoi-panel="letter">
      <header className="eoi-panel-header"><div><h3 id="eoi-letter-title">{t('steps.letter')}</h3>
        <p className="ds-muted">{t('letterHelp', { title: suggestions.defaults.assignment_title || '—', reference: suggestions.defaults.reference_no || '—' })}</p></div></header>
      <div className="eoi-letter-grid">
        <Input label={t('fields.addressee_organization')} value={state.letter.addressee_organization} onChange={setLetter('addressee_organization')} error={errorFor('addressee_organization')} name="addressee_organization" required />
        <Input label={t('fields.addressee_name')} value={state.letter.addressee_name ?? ''} onChange={setLetter('addressee_name')} name="addressee_name" />
        <Input label={t('fields.signatory_name')} value={state.letter.signatory_name} onChange={setLetter('signatory_name')} error={errorFor('signatory_name')} name="signatory_name" required />
        <Input label={t('fields.signatory_title')} value={state.letter.signatory_title} onChange={setLetter('signatory_title')} error={errorFor('signatory_title')} name="signatory_title" required />
        <Input label={t('fields.contact_email')} type="email" value={state.letter.contact_email} onChange={setLetter('contact_email')} error={errorFor('contact_email')} name="contact_email" required />
        <Input label={t('fields.contact_phone')} value={state.letter.contact_phone ?? ''} onChange={setLetter('contact_phone')} name="contact_phone" />
        <Input label={t('fields.contact_address')} value={state.letter.contact_address ?? ''} onChange={setLetter('contact_address')} name="contact_address" />
        <Select label={t('fields.language')} value={state.language} name="language"
          onChange={(event) => setState((current) => current && ({ ...current, language: event.target.value === 'ru' ? 'ru' : 'en' }))}>
          <option value="en">English</option><option value="ru">Русский</option>
        </Select>
      </div>
      <Checkbox label={t('includeNotes')} checked={state.includeNotes} name="include_relevance_notes"
        onChange={(event) => setState((current) => current && ({ ...current, includeNotes: event.target.checked }))} />
      <p className="ds-muted ds-text-small">{t('includeNotesHelp')}</p>
      {errors.some((item) => item.field === 'own' || item.field === 'partners') && <Alert tone="warning" title={t('selectionIncomplete')}>
        {errors.filter((item) => item.field === 'own' || item.field === 'partners').map((item) => t(`errors.${item.code}`)).join(' ')}
      </Alert>}
      <p className="ds-text-small">{t('generateSummary', { rows: rows.length, criteria: [...addressed.values()].filter((value) => value.length).length, total: suggestions.criteria.length })}</p>
      <div className="eoi-nav">
        <Button variant="secondary" onClick={() => setStep('partners')} disabled={generating}>{t('back')}</Button>
        <Button onClick={() => void generate()} loading={generating} disabled={errors.length > 0} data-eoi-generate>{t('generate')}</Button>
      </div>
      {generating && <p role="status" data-eoi-progress>{t('generating', { seconds: elapsed, budget: GENERATION_BUDGET_SECONDS })}</p>}
      {generateError && <Alert tone="danger" title={t('generateFailed')}>{generateError}</Alert>}
      {created && <Alert tone="success" title={t('generated', { version: created.version })} />}
    </section>}

    <section className="eoi-versions" aria-labelledby="eoi-versions-title" data-eoi-versions>
      <header className="eoi-panel-header"><h3 id="eoi-versions-title">{t('versionsTitle')}</h3>
        <Button variant="ghost" size="sm" leadingIcon={<RefreshCw aria-hidden />} onClick={() => void loadDrafts()}>{t('refresh')}</Button></header>
      {drafts.length ? <ul>{drafts.map((draft) => <li key={draft.draft_id} data-eoi-version={draft.version} data-current={draft.current}>
        <Surface className="eoi-version-card">
          <div className="eoi-version-main">
            <strong>{t('version', { version: draft.version })}</strong>
            <span className="ds-muted">{formatDateTime(draft.created_at, locale)} · {draft.language.toUpperCase()}</span>
            {draft.current ? <StatusBadge tone="success">{t('current')}</StatusBadge>
              : <StatusBadge tone="warning">{t('stale')}</StatusBadge>}
          </div>
          {!draft.current && <ul className="eoi-stale-reasons">{draft.stale_reasons.map((reason) => <li key={reason}>{t(`staleReasons.${staleReasonKey(reason)}`)}</li>)}</ul>}
          <p className="ds-text-small">{t('versionSummary', {
            references: draft.summary.own_reference_count, partners: draft.summary.partner_count,
            addressed: draft.summary.criteria_with_references, total: draft.summary.criteria_total,
            notes: draft.summary.relevance_notes_generated, dropped: draft.summary.relevance_notes_dropped,
          })}</p>
          <div className="eoi-actions">
            {(['DOCX', 'PDF'] as const).map((format) => draft.artifacts.some((item) => item.format === format) && <Button key={format}
              size="sm" variant="secondary" leadingIcon={<Download aria-hidden />} onClick={() => void download(draft, format)}>{format}</Button>)}
          </div>
        </Surface>
      </li>)}</ul> : <p className="ds-muted">{t('noVersions')}</p>}
    </section>
  </div>;
}
