'use client';

import { useRef, useState } from 'react';
import { Building2, FileUp, Pencil, Plus, UserRound } from 'lucide-react';
import { useLibraryT } from './useLibraryT';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { EmptyState, Surface } from '@/components/ui/Display';
import {
    emptyReferenceDraft,
    ensureSelfFirm,
    expertFields,
    expertPayload,
    firmFields,
    joinList,
    newestFirst,
    partnerFirmPayload,
    referenceChanges,
    referenceDraft,
    referencePayload,
    cvPayload,
    type FirmDraft,
    type ImportKind,
} from '@/lib/library';
import {
    archiveReference,
    createCvVersion,
    createExpert,
    createFirm,
    createReference,
    getSelfFirm,
    requestFailure,
    saveSelfFirm,
    updateExpert,
    updateFirm,
    updateReference,
} from '@/lib/libraryApi';
import type { CandidateExpert, CandidateFirm, CandidateProjectReference } from '@/types/pursuit';

import { CvVersionForm, ExpertForm, FirmForm, ReferenceForm } from './LibraryForms';
import { CsvImportDialog, EvidenceBadge, ReferenceList, ReviewAction } from './LibraryParts';

type Common = { organizationId: string; reload: () => void };
type ReferenceTarget = { firmId: string | null; reference: CandidateProjectReference | null };
type ImportTarget = { kind: ImportKind; firmId: string | null; name: string };

/** Run an action; null on success, a customer-safe reason otherwise. */
async function attempt(action: () => Promise<unknown>, after: () => void): Promise<string | null> {
    try {
        await action();
        after();
        return null;
    } catch (error) {
        return requestFailure(error);
    }
}

function firmDraft(firm: CandidateFirm | null, fallbackName = ''): FirmDraft {
    return {
        display_name: firm?.display_name ?? fallbackName, legal_name: firm?.legal_name ?? '', country: firm?.country ?? '',
        services: joinList(firm?.services), sectors: joinList(firm?.sectors), capabilities: joinList(firm?.capabilities),
        regions: joinList(firm?.regions),
    };
}

function FirmFacts({ firm }: { firm: CandidateFirm }) {
    const t = useLibraryT();
    const facts = [firm.country, ...firm.sectors.map(String), ...firm.services.map(String)].filter(Boolean);
    return <p className="ds-muted">{facts.length ? <BidiText>{facts.join(' · ')}</BidiText> : t('notRecorded')}</p>;
}

/** Reference add/edit for one firm; the own firm is created on the first save. */
function useReferenceEditor({ organizationId, reload, resolveFirmId }: Common & { resolveFirmId: (known: string | null) => Promise<string> }) {
    const [target, setTarget] = useState<ReferenceTarget | null>(null);
    const form = target && <ReferenceForm
        key={target.reference?.reference_id ?? `new-${target.firmId}`}
        open onClose={() => setTarget(null)} editing={Boolean(target.reference)}
        initial={target.reference ? referenceDraft(target.reference) : emptyReferenceDraft()}
        storedEvidence={target.reference?.evidence_state}
        onSubmit={(draft) => attempt(async () => {
            const firmId = await resolveFirmId(target.firmId);
            if (target.reference) {
                const changes = referenceChanges(target.reference, draft);
                if (Object.keys(changes).length) await updateReference(organizationId, firmId, target.reference.reference_id, changes);
            } else {
                await createReference(organizationId, firmId, referencePayload(draft));
            }
        }, () => { setTarget(null); reload(); })}
    />;
    return { open: setTarget, form };
}

function referenceHandlers(organizationId: string, firmId: string, reload: () => void) {
    return {
        onArchive: (reference: CandidateProjectReference) => attempt(
            () => archiveReference(organizationId, firmId, reference.reference_id), reload,
        ),
        onReview: (reference: CandidateProjectReference) => attempt(
            () => updateReference(organizationId, firmId, reference.reference_id, { evidence_state: 'REVIEWED' }), reload,
        ),
    };
}

// ---- Our experience ---------------------------------------------------------------------------------

export function OwnExperienceTab({ organizationId, reload, selfFirm, organizationName }: Common & {
    selfFirm: CandidateFirm | null; organizationName: string;
}) {
    const t = useLibraryT();
    const [editingFirm, setEditingFirm] = useState(false);
    const [importing, setImporting] = useState<ImportTarget | null>(null);
    // Resolved once per session of this tab: an import creates the own firm at most once.
    const resolved = useRef<CandidateFirm | null>(null);
    const ensure = async () => {
        resolved.current = await ensureSelfFirm(resolved.current ?? selfFirm, {
            getSelfFirm: () => getSelfFirm(organizationId),
            createSelfFirm: () => saveSelfFirm(organizationId, {}),
        });
        return resolved.current.firm_id;
    };
    const editor = useReferenceEditor({ organizationId, reload, resolveFirmId: async (known) => known ?? ensure() });
    const references = selfFirm?.project_references ?? [];
    const actions = <div className="library-actions">
        <Button leadingIcon={<Plus aria-hidden />} onClick={() => editor.open({ firmId: selfFirm?.firm_id ?? null, reference: null })}
            data-add-reference="own">{selfFirm && references.length ? t('reference.add') : t('own.addFirst')}</Button>
        <Button variant="secondary" leadingIcon={<FileUp aria-hidden />}
            onClick={() => setImporting({ kind: 'references', firmId: selfFirm?.firm_id ?? null, name: selfFirm?.display_name ?? organizationName })}>
            {t('import.open')}
        </Button>
    </div>;
    return <section className="library-tab ds-stack" data-library-tab="own">
        <header className="library-tab-header">
            <div><h2>{t('own.title')}</h2><p className="ds-muted">{t('own.help')}</p></div>
        </header>
        {!selfFirm ? <EmptyState icon={<Building2 aria-hidden />} title={t('own.emptyTitle')}
            description={t('own.emptyHelp')} action={actions} /> : <>
            <Surface className="library-card library-self-firm" variant="raised" data-self-firm={selfFirm.firm_id}>
                <header>
                    <div><h3><BidiText>{selfFirm.display_name}</BidiText></h3><FirmFacts firm={selfFirm} /></div>
                    <EvidenceBadge state={selfFirm.evidence_state} />
                </header>
                <div className="library-actions">
                    <Button variant="ghost" size="sm" leadingIcon={<Pencil aria-hidden />} onClick={() => setEditingFirm(true)}>
                        {t('own.editFirm')}
                    </Button>
                    <ReviewAction state={selfFirm.evidence_state} subject={selfFirm.display_name}
                        onConfirm={() => attempt(() => saveSelfFirm(organizationId, { evidence_state: 'REVIEWED' }), reload)} />
                </div>
            </Surface>
            {actions}
            <ReferenceList references={references} onEdit={(reference) => editor.open({ firmId: selfFirm.firm_id, reference })}
                {...referenceHandlers(organizationId, selfFirm.firm_id, reload)} />
        </>}
        {editor.form}
        {editingFirm && <FirmForm open onClose={() => setEditingFirm(false)} initial={firmDraft(selfFirm, organizationName)}
            title={t('own.editFirm')} description={t('own.firmHelp')} submitLabel={t('saveChanges')}
            onSubmit={(draft) => attempt(() => saveSelfFirm(organizationId, firmFields(draft)), () => { setEditingFirm(false); reload(); })} />}
        {importing && <CsvImportDialog kind="references" targetName={importing.name} onClose={() => setImporting(null)}
            onFinished={reload}
            post={(async (payload: Parameters<typeof createReference>[2]) => {
                const firmId = await ensure();
                return createReference(organizationId, firmId, payload);
            }) as (payload: never) => Promise<unknown>} />}
    </section>;
}

// ---- Partner firms ----------------------------------------------------------------------------------

export function PartnerFirmsTab({ organizationId, reload, firms }: Common & { firms: CandidateFirm[] }) {
    const t = useLibraryT();
    const [firmForm, setFirmForm] = useState<{ firm: CandidateFirm | null } | null>(null);
    const [importing, setImporting] = useState<ImportTarget | null>(null);
    const editor = useReferenceEditor({
        organizationId, reload,
        resolveFirmId: async (known) => { if (!known) throw new Error('firm required'); return known; },
    });
    return <section className="library-tab ds-stack" data-library-tab="partners">
        <header className="library-tab-header">
            <div><h2>{t('partners.title')}</h2><p className="ds-muted">{t('partners.help')}</p></div>
            <Button leadingIcon={<Plus aria-hidden />} onClick={() => setFirmForm({ firm: null })} data-add-firm>{t('partners.add')}</Button>
        </header>
        {!firms.length ? <EmptyState icon={<Building2 aria-hidden />} title={t('partners.emptyTitle')} description={t('partners.emptyHelp')} />
            : <div className="library-stack">{firms.map((firm) => {
                const editable = firm.scope === 'ORGANIZATION_PRIVATE';
                return <Surface className="library-card" variant="raised" key={firm.firm_id} data-firm-id={firm.firm_id}>
                    <header>
                        <div><h3><BidiText>{firm.display_name}</BidiText></h3><FirmFacts firm={firm} />
                            <small className="ds-muted">{t(`scopes.${firm.scope}`)}</small></div>
                        <EvidenceBadge state={firm.evidence_state} />
                    </header>
                    {editable && <div className="library-actions">
                        <Button variant="ghost" size="sm" leadingIcon={<Pencil aria-hidden />} onClick={() => setFirmForm({ firm })}>{t('edit')}</Button>
                        <ReviewAction state={firm.evidence_state} subject={firm.display_name}
                            onConfirm={() => attempt(() => updateFirm(organizationId, firm.firm_id, { evidence_state: 'REVIEWED' }), reload)} />
                        <Button variant="secondary" size="sm" leadingIcon={<Plus aria-hidden />}
                            onClick={() => editor.open({ firmId: firm.firm_id, reference: null })}>{t('reference.add')}</Button>
                        <Button variant="secondary" size="sm" leadingIcon={<FileUp aria-hidden />}
                            onClick={() => setImporting({ kind: 'references', firmId: firm.firm_id, name: firm.display_name })}>{t('import.open')}</Button>
                    </div>}
                    <h4>{t('referenceHistory')}</h4>
                    <ReferenceList references={firm.project_references} readOnly={!editable}
                        onEdit={(reference) => editor.open({ firmId: firm.firm_id, reference })}
                        {...referenceHandlers(organizationId, firm.firm_id, reload)} />
                </Surface>;
            })}</div>}
        {editor.form}
        {firmForm && <FirmForm open onClose={() => setFirmForm(null)} initial={firmDraft(firmForm.firm)}
            title={firmForm.firm ? t('partners.editTitle') : t('partners.addTitle')} description={t('partners.privacyHelp')}
            submitLabel={firmForm.firm ? t('saveChanges') : t('partners.save')}
            onSubmit={(draft) => attempt(
                () => (firmForm.firm
                    ? updateFirm(organizationId, firmForm.firm.firm_id, { ...firmFields(draft), canonical_name: firmFields(draft).display_name })
                    : createFirm(organizationId, partnerFirmPayload(draft))),
                () => { setFirmForm(null); reload(); },
            )} />}
        {importing?.firmId && <CsvImportDialog kind="references" targetName={importing.name} onClose={() => setImporting(null)}
            onFinished={reload}
            post={((payload: Parameters<typeof createReference>[2]) => createReference(organizationId, importing.firmId as string, payload)) as (payload: never) => Promise<unknown>} />}
    </section>;
}

// ---- Experts ------------------------------------------------------------------------------------------

function CvHistory({ expert }: { expert: CandidateExpert }) {
    const t = useLibraryT();
    const versions = newestFirst(expert.cv_versions);
    if (!versions.length) return <p className="ds-muted">{t('noCvVersions')}</p>;
    return <ol className="library-cv-history" data-cv-history>
        {versions.map((cv) => <li key={cv.cv_version_id} data-cv-version={cv.version_number}>
            <details>
                <summary>
                    <strong>{t('cvVersion', { version: cv.version_number })}</strong>
                    <span className="ds-muted">{t('cv.counts', {
                        education: cv.education.length, assignments: cv.assignments.length,
                        languages: cv.languages.length, certifications: cv.certifications.length,
                    })}</span>
                    <EvidenceBadge state={cv.evidence_state} />
                    <TechnicalText>{cv.structured_sha256.slice(0, 12)}</TechnicalText>
                </summary>
                {(['assignments', 'education', 'languages', 'certifications'] as const).map((section) => (
                    cv[section].length ? <div key={section}>
                        <h5>{t(`cv.sections.${section}`)}</h5>
                        <ul>{cv[section].map((row, index) => <li key={index}><BidiText>
                            {Object.values((row ?? {}) as Record<string, unknown>).filter(Boolean).map(String).join(' · ')}
                        </BidiText></li>)}</ul>
                    </div> : null
                ))}
            </details>
        </li>)}
    </ol>;
}

export function ExpertsTab({ organizationId, reload, experts }: Common & { experts: CandidateExpert[] }) {
    const t = useLibraryT();
    const [expertForm, setExpertForm] = useState<{ expert: CandidateExpert | null } | null>(null);
    const [cvFor, setCvFor] = useState<CandidateExpert | null>(null);
    const [importing, setImporting] = useState(false);
    return <section className="library-tab ds-stack" data-library-tab="experts">
        <header className="library-tab-header">
            <div><h2>{t('experts')}</h2><p className="ds-muted">{t('expertsTab.help')}</p></div>
            <div className="library-actions">
                <Button leadingIcon={<Plus aria-hidden />} onClick={() => setExpertForm({ expert: null })} data-add-expert>{t('expert.add')}</Button>
                <Button variant="secondary" leadingIcon={<FileUp aria-hidden />} onClick={() => setImporting(true)}>{t('import.open')}</Button>
            </div>
        </header>
        {!experts.length ? <EmptyState icon={<UserRound aria-hidden />} title={t('expertsTab.emptyTitle')} description={t('expertsTab.emptyHelp')} />
            : <div className="library-stack">{experts.map((expert) => {
                const editable = expert.scope === 'ORGANIZATION_PRIVATE';
                return <Surface className="library-card" variant="raised" key={expert.expert_id} data-expert-id={expert.expert_id}>
                    <header>
                        <div><h3><BidiText>{expert.display_name}</BidiText></h3>
                            <p className="ds-muted">{expert.specializations.map(String).join(' · ') || t('notRecorded')}</p>
                            <p className="ds-muted">{[...expert.qualifications, ...expert.languages].map(String).join(' · ')}</p>
                            <small className="ds-muted">{t(`scopes.${expert.scope}`)}</small></div>
                        <EvidenceBadge state={expert.evidence_state} />
                    </header>
                    {editable && <div className="library-actions">
                        <Button variant="ghost" size="sm" leadingIcon={<Pencil aria-hidden />} onClick={() => setExpertForm({ expert })}>{t('edit')}</Button>
                        <ReviewAction state={expert.evidence_state} subject={expert.display_name}
                            onConfirm={() => attempt(() => updateExpert(organizationId, expert.expert_id, { evidence_state: 'REVIEWED' }), reload)} />
                        <Button variant="secondary" size="sm" leadingIcon={<Plus aria-hidden />} onClick={() => setCvFor(expert)} data-add-cv>
                            {t('cv.add.version')}
                        </Button>
                    </div>}
                    <h4>{t('cvVersions')}</h4>
                    <CvHistory expert={expert} />
                </Surface>;
            })}</div>}
        {expertForm && <ExpertForm open onClose={() => setExpertForm(null)} editing={Boolean(expertForm.expert)}
            initial={{
                display_name: expertForm.expert?.display_name ?? '', qualifications: joinList(expertForm.expert?.qualifications),
                languages: joinList(expertForm.expert?.languages), specializations: joinList(expertForm.expert?.specializations),
            }}
            onSubmit={(draft) => attempt(
                () => (expertForm.expert
                    ? updateExpert(organizationId, expertForm.expert.expert_id, expertFields(draft))
                    : createExpert(organizationId, expertPayload(draft))),
                () => { setExpertForm(null); reload(); },
            )} />}
        {cvFor && <CvVersionForm open onClose={() => setCvFor(null)} expertName={cvFor.display_name}
            nextVersion={Math.max(0, ...cvFor.cv_versions.map((cv) => cv.version_number)) + 1}
            onSubmit={(draft) => attempt(() => createCvVersion(organizationId, cvFor.expert_id, cvPayload(draft)), () => { setCvFor(null); reload(); })} />}
        {importing && <CsvImportDialog kind="experts" targetName={t('experts')} onClose={() => setImporting(false)} onFinished={reload}
            post={((payload: Record<string, unknown>) => createExpert(organizationId, payload)) as (payload: never) => Promise<unknown>} />}
    </section>;
}
