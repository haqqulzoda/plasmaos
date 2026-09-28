'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Download, FileArchive, FileCheck2, History, PackageCheck } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';

import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Checkbox } from '@/components/ui/Forms';
import { EmptyState, StatusBadge, Surface } from '@/components/ui/Display';
import { formatDateTime, formatFileSize } from '@/i18n/formatters';
import type { CustomerSelectableLocale } from '@/i18n/locales';
import { api } from '@/lib/api';
import type {
  ProposalEvidenceArtifact,
  ProposalEvidencePack,
  ProposalEvidencePackItem,
  PursuitProposalWorkspace,
  TeamScenario,
  TeamScenarioRevision,
} from '@/types/pursuit';

type Props = { pursuitId: string; headers: Record<string, string | undefined> };
type ApprovedRevision = { scenario: TeamScenario; revision: TeamScenarioRevision; approvalId: string };

function textValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

function friendlyState(value: unknown): string {
  return textValue(value).toLowerCase().replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

function items(pack: ProposalEvidencePack, category: ProposalEvidencePackItem['category']) {
  return pack.items.filter((item) => item.category === category);
}

function Matrix({ pack }: { pack: ProposalEvidencePack }) {
  const t = useTranslations('pursuits.proposal');
  const rows = items(pack, 'REQUIREMENT');
  if (!rows.length) return <p className="ds-muted">{t('emptyMatrix')}</p>;
  return <div className="proposal-matrix-wrap"><table className="proposal-matrix">
    <thead><tr><th>{t('requirement')}</th><th>{t('source')}</th><th>{t('reviewState')}</th><th>{t('gapOutcome')}</th><th>{t('support')}</th><th>{t('remainingCondition')}</th></tr></thead>
    <tbody>{rows.map((item) => {
      const payload = item.payload;
      const contributors = Array.isArray(payload.contributors) ? payload.contributors as Array<Record<string, unknown>> : [];
      const locator = payload.source_locator && typeof payload.source_locator === 'object' ? payload.source_locator as Record<string, unknown> : null;
      const sourceLabel = locator
        ? [typeof locator.page_number === 'number' ? t('page', { page: locator.page_number }) : null, typeof locator.paragraph_number === 'number' ? t('paragraph', { paragraph: locator.paragraph_number }) : null].filter(Boolean).join(' · ')
        : textValue(payload.source_locator);
      return <tr key={item.item_id}>
        <th data-label={t('requirement')}><BidiText>{textValue(payload.reviewed_label)}</BidiText><small><BidiText>{textValue(payload.original_language_requirement)}</BidiText></small></th>
        <td data-label={t('source')}><BidiText>{sourceLabel}</BidiText></td>
        <td data-label={t('reviewState')}>{friendlyState(payload.effective_review_state)}</td>
        <td data-label={t('gapOutcome')}><StatusBadge tone={payload.scenario_gap_outcome === 'COVERED' ? 'success' : 'warning'}>{friendlyState(payload.scenario_gap_outcome)}</StatusBadge></td>
        <td data-label={t('support')}>{contributors.length ? <ul>{contributors.map((contributor, index) => <li key={index}><BidiText>{textValue(contributor.display_name)}</BidiText><small>{friendlyState(contributor.evidence_state)} · {friendlyState(contributor.participation_state)}</small></li>)}</ul> : <span className="ds-muted">{t('noEvidence')}</span>}</td>
        <td data-label={t('remainingCondition')}><BidiText>{textValue(payload.remaining_condition)}</BidiText></td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function Roster({ pack }: { pack: ProposalEvidencePack }) {
  const t = useTranslations('pursuits.proposal');
  const roster = [...items(pack, 'FIRM'), ...items(pack, 'EXPERT')];
  return <div className="proposal-roster">{roster.map((item) => {
    const payload = item.payload;
    const contributions = Array.isArray(payload.contributions) ? payload.contributions as Array<Record<string, unknown>> : [];
    return <article key={item.item_id}>
      <span className="ds-eyebrow">{payload.role === 'LEAD_ORGANIZATION' ? t('leadOrganization') : item.category === 'FIRM' ? t('partnerFirm') : t('expert')}</span>
      <h5><BidiText>{textValue(payload.display_name)}</BidiText></h5>
      {contributions.length ? <ul>{contributions.map((value, index) => <li key={index}><BidiText>{textValue(value.proposed_contribution)}</BidiText><small>{friendlyState(value.qualification_state)} · {friendlyState(value.evidence_state)}</small></li>)}</ul> : null}
    </article>;
  })}</div>;
}

function EvidenceList({ rows, empty }: { rows: ProposalEvidencePackItem[]; empty: string }) {
  const t = useTranslations('pursuits.proposal');
  if (!rows.length) return <p className="ds-muted">{empty}</p>;
  return <ul className="proposal-evidence-list">{rows.map((item) => <li key={item.item_id}>
    <div><strong><BidiText>{textValue(item.payload.reviewed_label || item.payload.display_name || item.payload.label || item.payload.project || item.purpose)}</BidiText></strong><small>{friendlyState(item.source_authority_type)} · {friendlyState(item.provenance)}</small></div>
    <div><StatusBadge tone={item.evidence_state === 'AVAILABLE' || item.evidence_state === 'COVERED' ? 'success' : item.evidence_state === 'NEEDS_ACTION' ? 'warning' : 'neutral'}>{friendlyState(item.evidence_state || item.review_state || 'DISCLOSED')}</StatusBadge>{item.source_sha256 && <details className="proposal-item-technical"><summary>{t('technicalDetails')}</summary><TechnicalText>{item.source_sha256}</TechnicalText></details>}</div>
  </li>)}</ul>;
}

function PackCard({ pack, pursuitId, headers, refresh }: { pack: ProposalEvidencePack; pursuitId: string; headers: Props['headers']; refresh: () => Promise<void> }) {
  const t = useTranslations('pursuits.proposal');
  const locale = useLocale() as CustomerSelectableLocale;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const download = async (artifact: ProposalEvidenceArtifact) => {
    setBusy(`download-${artifact.artifact_id}`); setError(false);
    try {
      const response = await api.get(`/pursuits/${encodeURIComponent(pursuitId)}/proposal-evidence-artifacts/${artifact.artifact_id}/download`, { headers, responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([response.data], { type: artifact.media_type }));
      const link = window.document.createElement('a');
      link.href = url;
      link.download = `proposal-evidence-${pack.pack_version}${artifact.historical_snapshot ? '-historical' : ''}.${artifact.artifact_type.toLowerCase()}`;
      window.document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch { setError(true); }
    finally { setBusy(null); }
  };
  const generate = async (artifactType: ProposalEvidenceArtifact['artifact_type']) => {
    setBusy(artifactType); setError(false);
    try {
      const response = await api.post<ProposalEvidenceArtifact>(
        `/pursuits/${encodeURIComponent(pursuitId)}/proposal-evidence-packs/${pack.pack_id}/exports`,
        { artifact_type: artifactType, historical_snapshot: !pack.pack_current }, { headers },
      );
      await refresh();
      await download(response.data);
    } catch { setError(true); setBusy(null); }
  };
  const documents = [...items(pack, 'SOURCE_DOCUMENT'), ...items(pack, 'PRIVATE_DOCUMENT')];
  const later = items(pack, 'LATER_STAGE_OBLIGATION');
  const checklist = items(pack, 'FORM_OR_REQUIRED_ARTIFACT');
  const references = items(pack, 'PROJECT_REFERENCE');
  const cvFacts = items(pack, 'CV_FACTS');
  return <Surface className="proposal-pack-card" variant="raised">
    <header><div><span className="ds-eyebrow">{t('packVersion', { version: pack.pack_version })}</span><h4><BidiText>{pack.scenario_title}</BidiText></h4><p>{formatDateTime(pack.created_at, locale)}</p></div><StatusBadge tone={pack.pack_current ? 'success' : 'warning'}>{pack.pack_current ? t('current') : t('historical')}</StatusBadge></header>
    {!pack.pack_current && <div className="analysis-stale" role="status"><AlertTriangle aria-hidden /><div><strong>{t('stale')}</strong>{pack.stale_reasons.map((reason) => <p key={reason}><BidiText>{reason}</BidiText></p>)}</div></div>}
    <dl className="proposal-pack-summary">
      <div><dt>{t('matrixRows')}</dt><dd>{pack.matrix_row_count}</dd></div><div><dt>{t('participants')}</dt><dd>{pack.participant_count}</dd></div><div><dt>{t('laterStage')}</dt><dd>{pack.later_stage_count}</dd></div><div><dt>{t('checklist')}</dt><dd>{pack.checklist_count}</dd></div>
    </dl>
    <details className="proposal-manifest"><summary>{t('technicalDetails')}</summary><strong>{t('manifestHash')}</strong><TechnicalText>{pack.manifest_sha256}</TechnicalText></details>
    <details open><summary>{t('matrix')}</summary><Matrix pack={pack} /></details>
    <details><summary>{t('teamRoster')}</summary><Roster pack={pack} /></details>
    <details><summary>{t('firmReferences')} ({references.length})</summary><EvidenceList rows={references} empty={t('none')} /></details>
    <details><summary>{t('structuredCvFacts')} ({cvFacts.length})</summary><p className="ds-muted">{t('cvDisclosure')}</p><EvidenceList rows={cvFacts} empty={t('none')} /></details>
    <details open={later.length > 0}><summary>{t('laterStage')} ({later.length})</summary><EvidenceList rows={later} empty={t('none')} /></details>
    <details><summary>{t('checklist')} ({checklist.length})</summary><EvidenceList rows={checklist} empty={t('none')} /></details>
    <details><summary>{t('documents')} ({documents.length})</summary><EvidenceList rows={documents} empty={t('none')} /></details>
    <div className="proposal-export-area">
      <div><h5>{pack.pack_current ? t('exports') : t('historicalExports')}</h5><p>{pack.pack_current ? t('exportsHelp') : t('historicalHelp')}</p></div>
      <div className="proposal-export-actions">{(['PDF', 'DOCX', 'JSON'] as const).map((kind) => <Button key={kind} size="sm" variant="secondary" loading={busy === kind} onClick={() => void generate(kind)} leadingIcon={<Download aria-hidden />}>{kind === 'JSON' ? t('evidenceManifest') : t('generate', { kind })}</Button>)}</div>
    </div>
    {pack.artifacts.length ? <ul className="proposal-artifact-list">{pack.artifacts.map((artifact) => <li key={artifact.artifact_id}><span><FileCheck2 aria-hidden />{artifact.artifact_type}{artifact.historical_snapshot ? ` · ${t('historical')}` : ''} · {formatFileSize(artifact.byte_size, locale)}</span><Button size="sm" variant="ghost" loading={busy === `download-${artifact.artifact_id}`} onClick={() => void download(artifact)}>{t('download')}</Button></li>)}</ul> : null}
    {error && <p className="pursuit-upload-error" role="alert">{t('exportFailed')}</p>}
  </Surface>;
}

export function PursuitProposal({ pursuitId, headers }: Props) {
  const t = useTranslations('pursuits.proposal');
  const [workspace, setWorkspace] = useState<PursuitProposalWorkspace | null>(null);
  const [scenarios, setScenarios] = useState<TeamScenario[]>([]);
  const [selection, setSelection] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    try {
      const [workspaceResponse, scenarioResponse] = await Promise.all([
        api.get<PursuitProposalWorkspace>(`/pursuits/${encodeURIComponent(pursuitId)}/proposal-workspace`, { headers }),
        api.get<TeamScenario[]>(`/pursuits/${encodeURIComponent(pursuitId)}/team-scenarios`, { headers }),
      ]);
      setWorkspace(workspaceResponse.data); setScenarios(scenarioResponse.data); setError(false);
    } catch { setError(true); }
    finally { setLoading(false); }
  }, [headers, pursuitId]);
  useEffect(() => { void load(); }, [load]);
  const approved = useMemo<ApprovedRevision[]>(() => scenarios.flatMap((scenario) => scenario.revisions.flatMap((revision) => {
    const decision = revision.decisions.at(-1);
    return decision?.decision === 'APPROVED_FOR_PROPOSAL' && revision.scenario_current && revision.current_assessment_state === 'VIABLE'
      ? [{ scenario, revision, approvalId: decision.decision_id }] : [];
  })), [scenarios]);
  useEffect(() => {
    if (!selection && approved.length) setSelection(`${approved[0].scenario.scenario_id}:${approved[0].revision.revision_id}`);
  }, [approved, selection]);
  const createPack = async () => {
    const chosen = approved.find((item) => `${item.scenario.scenario_id}:${item.revision.revision_id}` === selection);
    if (!chosen || !confirmed) return;
    setBusy(true); setError(false);
    try {
      await api.post(`/pursuits/${encodeURIComponent(pursuitId)}/proposal-evidence-packs`, {
        scenario_id: chosen.scenario.scenario_id,
        revision_id: chosen.revision.revision_id,
        approval_decision_id: chosen.approvalId,
      }, { headers });
      setConfirmed(false); await load();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  if (loading) return <p className="ds-muted">{t('loading')}</p>;
  return <div className="pursuit-proposal">
    <div className="proposal-intro"><PackageCheck aria-hidden /><div><h3>{t('title')}</h3><p>{t('help')}</p></div></div>
    {workspace?.legacy_proposal_id && <Surface className="legacy-proposal-link"><div><History aria-hidden /><p><strong>{t('legacyTitle')}</strong><span>{t('legacyHelp')}</span></p></div><ButtonLink size="sm" variant="secondary" href={`/dashboard/bid-preparation/${workspace.legacy_proposal_id}`}>{t('openLegacy')}</ButtonLink></Surface>}
    <Surface className="proposal-seal-card">
      <header><div><span className="ds-eyebrow">{t('explicitAction')}</span><h4>{t('sealTitle')}</h4><p>{t('sealHelp')}</p></div><FileArchive aria-hidden /></header>
      {approved.length ? <><label className="ds-field"><span>{t('approvedScenario')}</span><select className="ds-control" value={selection} onChange={(event) => { setSelection(event.target.value); setConfirmed(false); }}>{approved.map((item) => <option key={`${item.scenario.scenario_id}:${item.revision.revision_id}`} value={`${item.scenario.scenario_id}:${item.revision.revision_id}`}>{item.scenario.title} · {t('revision', { version: item.revision.version_number })}</option>)}</select></label><Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} label={t('sealConfirmation')} /><Button loading={busy} disabled={!confirmed} onClick={() => void createPack()} leadingIcon={<PackageCheck aria-hidden />}>{t('seal')}</Button></> : <EmptyState icon={<FileArchive aria-hidden />} title={t('noApprovedScenarioTitle')} description={t('noApprovedScenario')} />}
      {error && <p className="pursuit-upload-error" role="alert">{t('actionFailed')}</p>}
    </Surface>
    {workspace?.packs.length ? <div className="proposal-pack-list">{workspace.packs.map((pack) => <PackCard key={pack.pack_id} {...{ pack, pursuitId, headers }} refresh={load} />)}</div> : <EmptyState icon={<FileArchive aria-hidden />} title={t('empty')} description={t('emptyHelp')} />}
  </div>;
}
