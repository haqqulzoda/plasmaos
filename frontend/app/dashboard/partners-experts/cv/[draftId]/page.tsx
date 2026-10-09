'use client';

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, CheckCircle2, Plus, Quote, Trash2 } from 'lucide-react';

import { useLibraryT } from '@/components/library/useLibraryT';
import { BidiText } from '@/components/i18n/BidiText';
import { Button, ButtonLink } from '@/components/ui/Button';
import { PageHeader, PageSkeleton, StatusBadge, Surface } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Input, Textarea } from '@/components/ui/Forms';
import {
    cvConfirmPayload,
    cvDraftConfirmable,
    cvDraftPending,
    emptyAssignment,
    emptyCertification,
    emptyEducation,
    emptyLanguage,
    reviewDraftErrors,
    reviewDraftFromProposal,
    type FieldError,
    type ReviewDraft,
} from '@/lib/library';
import { confirmCvDraft, getCvDraft, requestFailure, type CvDraftReview } from '@/lib/libraryApi';

type Section = keyof ReviewDraft;
const SECTION_FIELDS: Record<Section, string[]> = {
    assignments: ['role', 'client', 'country', 'sector', 'start', 'end', 'description'],
    education: ['degree', 'institution', 'year'],
    languages: ['language', 'level'],
    certifications: ['name', 'issuer', 'year'],
};
const EMPTY: Record<Section, () => Record<string, string>> = {
    education: emptyEducation, assignments: emptyAssignment, languages: emptyLanguage, certifications: emptyCertification,
};

/** The document text with the focused row's quote marked (first occurrence, whitespace-tolerant). */
function DocumentText({ text, quote }: { text: string; quote: string | null }) {
    const parts = useMemo(() => {
        if (!quote) return [text];
        const pattern = quote.trim().split(/\s+/).map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
        const match = pattern ? new RegExp(pattern).exec(text) : null;
        return match ? [text.slice(0, match.index), match[0], text.slice(match.index + match[0].length)] : [text];
    }, [text, quote]);
    useEffect(() => {
        if (parts.length === 3) document.getElementById('cv-quote-mark')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, [parts]);
    return <pre className="cv-review-text" dir="auto" data-cv-document-text>
        {parts.length === 3 ? <>{parts[0]}<mark id="cv-quote-mark">{parts[1]}</mark>{parts[2]}</> : parts[0]}
    </pre>;
}

function CvReview() {
    const t = useLibraryT();
    const router = useRouter();
    const { draftId } = useParams<{ draftId: string }>();
    const organizationId = useSearchParams().get('organization') ?? '';
    const [review, setReview] = useState<CvDraftReview | null>(null);
    const [draft, setDraft] = useState<ReviewDraft | null>(null);
    const [expertName, setExpertName] = useState('');
    const [focusQuote, setFocusQuote] = useState<string | null>(null);
    const [errors, setErrors] = useState<FieldError[]>([]);
    const [loadFailed, setLoadFailed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    const [saved, setSaved] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const data = await getCvDraft(organizationId, draftId);
            setReview(data);
            setLoadFailed(false);
            // The editable form is filled once, when the proposal (or the failure) arrives.
            if (!cvDraftPending(data.state)) {
                setDraft((current) => current ?? reviewDraftFromProposal(data.proposal));
                setExpertName((current) => current || data.proposal?.full_name?.value || '');
            }
        } catch {
            setLoadFailed(true);
        }
    }, [draftId, organizationId]);

    useEffect(() => { void load(); }, [load]);
    useEffect(() => {
        if (!review || !cvDraftPending(review.state)) return;
        const timer = window.setInterval(() => void load(), 3_000);
        return () => window.clearInterval(timer);
    }, [review, load]);

    const needsName = review?.expert_id ? null : expertName;
    const back = '/dashboard/partners-experts?tab=experts';
    const error = (key: string) => {
        const found = errors.find((item) => item.field === key);
        return found ? t(`errors.${found.code}`) : undefined;
    };
    const update = (section: Section, index: number, field: string, value: string) => setDraft((current) => current && ({
        ...current,
        [section]: (current[section] as Record<string, string>[]).map((row, position) => position === index ? { ...row, [field]: value } : row),
    }));
    const add = (section: Section) => setDraft((current) => current && ({ ...current, [section]: [...current[section], EMPTY[section]()] }));
    const remove = (section: Section, index: number) => setDraft((current) => current && ({
        ...current, [section]: (current[section] as Record<string, string>[]).filter((_, position) => position !== index),
    }));
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!draft || !review) return;
        const found = reviewDraftErrors(draft, needsName);
        setErrors(found);
        if (found.length) return;
        setBusy(true);
        setFailure(null);
        try {
            const result = await confirmCvDraft(organizationId, review.cv_draft_id, cvConfirmPayload(draft, needsName));
            setSaved(t('cvReview.saved', { name: result.expert_name, version: result.cv_version.version_number }));
            await load();
        } catch (problem) {
            setFailure(requestFailure(problem));
        } finally {
            setBusy(false);
        }
    };

    if (!organizationId || loadFailed) return <main className="customer-page ds-container-content">
        <Alert tone="danger" title={t('cvReview.loadFailed')} action={<ButtonLink href={back} variant="secondary">{t('cvReview.back')}</ButtonLink>} />
    </main>;
    if (!review) return <PageSkeleton label={t('cvReview.loading')} />;
    const pending = cvDraftPending(review.state);
    const confirmable = cvDraftConfirmable(review.state, review.failure_code);
    const summary = review.extraction_summary as { verified_rows?: number; dropped_unverified_rows?: number };

    return <main className="customer-page cv-review-page ds-container-content" data-cv-review={review.state}>
        <PageHeader eyebrow={t('cvReview.eyebrow')} title={t('cvReview.title')}
            description={t('cvReview.description')}
            primaryAction={<ButtonLink href={back} variant="secondary"><ArrowLeft className="rtl-mirror" aria-hidden />{t('cvReview.back')}</ButtonLink>} />
        <div className="ds-row cv-review-meta">
            <StatusBadge tone={review.state === 'READY' || review.state === 'CONFIRMED' ? 'success' : review.state === 'FAILED' ? 'warning' : 'info'}>
                {t(`cvDrafts.states.${review.state}`)}
            </StatusBadge>
            <BidiText>{review.display_filename}</BidiText>
            {review.expert_name && <span className="ds-muted"><BidiText>{review.expert_name}</BidiText></span>}
        </div>
        {pending && <Alert tone="info" title={t('cvReview.reading')}>{t('cvReview.readingHelp')}</Alert>}
        {review.state === 'READY' && <Alert tone="info" title={t('cvReview.proposed', { count: summary.verified_rows ?? 0 })}>
            {summary.dropped_unverified_rows ? t('cvReview.dropped', { count: summary.dropped_unverified_rows }) : t('cvReview.checkEverything')}
        </Alert>}
        {review.state === 'FAILED' && (review.failure_code === 'DOCUMENT_REJECTED'
            ? <Alert tone="danger" title={t('cvReview.rejected')} />
            : <Alert tone="warning" title={t('cvReview.failed')}>{t('cvReview.manualHelp')}</Alert>)}
        {saved && <Alert tone="success" title={saved} action={<Button variant="secondary" onClick={() => router.push(back)}>{t('cvReview.back')}</Button>} />}
        {review.state === 'CONFIRMED' && !saved && <Alert tone="success" title={t('cvReview.alreadySaved')} />}

        <div className="cv-review-layout">
            <Surface className="cv-review-document" aria-label={t('cvReview.documentLabel')}>
                <h2>{t('cvReview.document')}</h2>
                {review.document_text ? <DocumentText text={review.document_text} quote={focusQuote} />
                    : <p className="ds-muted">{t('cvReview.noText')}</p>}
                {review.document_text_truncated && <p className="ds-muted ds-text-small">{t('cvReview.truncated')}</p>}
            </Surface>
            <Surface className="cv-review-form">
                <h2>{t('cvReview.fields')}</h2>
                {draft && confirmable ? <form className="ds-stack" onSubmit={submit} data-cv-review-form>
                    {needsName !== null && <Input label={t('cvReview.expertName')} value={expertName} required maxLength={500}
                        onChange={(event) => setExpertName(event.target.value)} error={error('expert_name')} />}
                    {error('cv') && <Alert tone="warning" title={error('cv') ?? ''} />}
                    {(Object.keys(SECTION_FIELDS) as Section[]).map((section) => <fieldset className="library-fieldset" key={section} data-cv-section={section}>
                        <legend>{t(`cv.sections.${section}`)}</legend>
                        {(draft[section] as (Record<string, string> & { quote?: string })[]).map((row, index) => <div
                            className="library-cv-row" key={index} onFocus={() => setFocusQuote(row.quote ?? null)}>
                            {row.quote ? <button type="button" className="cv-review-quote" onClick={() => setFocusQuote(row.quote ?? null)}>
                                <Quote aria-hidden /><span><BidiText>{row.quote}</BidiText></span>
                            </button> : <p className="ds-muted ds-text-small">{t('cvReview.noQuote')}</p>}
                            <div className="library-form-grid">
                                {SECTION_FIELDS[section].map((name) => {
                                    const key = `${section}.${index}.${name}`;
                                    const common = {
                                        label: t(`cv.fields.${section}.${name}`), value: row[name] ?? '', name: key, error: error(key),
                                        onChange: (event: { target: { value: string } }) => update(section, index, name, event.target.value),
                                    };
                                    return name === 'description' ? <Textarea key={name} {...common} rows={2} />
                                        : <Input key={name} {...common} placeholder={name === 'start' || name === 'end' ? 'YYYY-MM' : name === 'year' ? 'YYYY' : undefined} />;
                                })}
                            </div>
                            <Button variant="ghost" size="sm" onClick={() => remove(section, index)} leadingIcon={<Trash2 aria-hidden />}>{t('cv.removeRow')}</Button>
                        </div>)}
                        <Button variant="secondary" size="sm" onClick={() => add(section)} leadingIcon={<Plus aria-hidden />}>{t(`cv.add.${section}`)}</Button>
                    </fieldset>)}
                    <p className="ds-muted ds-text-small">{t('cvReview.unverifiedNote')}</p>
                    {failure && <Alert tone="danger" title={t('cvReview.saveFailed')}>{failure}</Alert>}
                    <div className="ds-row"><Button type="submit" loading={busy} leadingIcon={<CheckCircle2 aria-hidden />}>{t('cvReview.confirm')}</Button></div>
                </form> : pending ? <p className="ds-muted" role="status">{t('cvReview.readingHelp')}</p> : null}
            </Surface>
        </div>
    </main>;
}

export default function CvReviewPage() {
    return <Suspense fallback={<PageSkeleton label="" />}><CvReview /></Suspense>;
}
