/**
 * D2-05 EOI builder state, pure so it is testable without React.
 *
 * Experience rows are numbered exactly as the backend numbers them: the selected own
 * references in suggestion-rank order, then each selected partner's references in
 * the order listed. "Addressed by #…" is computed from the matched ids the
 * suggestions already carry; nothing here calls the network.
 */
import type {
  EoiCriterion,
  EoiDefaults,
  EoiDraftCreateRequest,
  EoiLetter,
  EoiPartnerRole,
  EoiReference,
  EoiSuggestions,
} from '../types/eoi';

export const MAX_OWN_REFERENCES = 30;
export const MAX_PARTNERS = 5;
export const MAX_PARTNER_REFERENCES = 15;
export const GENERATION_BUDGET_SECONDS = 45;
export const EOI_STEPS = ['experience', 'partners', 'letter'] as const;
export type EoiStep = (typeof EOI_STEPS)[number];

export type PartnerSelection = { role: EoiPartnerRole; referenceIds: string[] };

export type BuilderState = {
  own: string[]; // selected own reference ids
  partners: Record<string, PartnerSelection>; // firm id -> selection
  letter: EoiLetter;
  language: 'en' | 'ru';
  includeNotes: boolean;
};

type Profile = {
  company_name?: string | null;
  director_name?: string | null;
  phone_contact?: string | null;
  address?: string | null;
} | null | undefined;

export function emptyLetter(): EoiLetter {
  return {
    addressee_organization: '', addressee_name: null, signatory_name: '', signatory_title: '',
    contact_email: '', contact_phone: null, contact_address: null,
  };
}

/** Prefilled from the suggestions' defaults and the company profile; the user can change everything. */
export function initialBuilderState(
  suggestions: EoiSuggestions,
  { profile, email, uiLocale }: { profile?: Profile; email?: string | null; uiLocale?: string } = {},
): BuilderState {
  const own = [...suggestions.own_references]
    .sort((a, b) => a.rank - b.rank)
    .filter((item) => item.suggested)
    .slice(0, MAX_OWN_REFERENCES)
    .map((item) => item.reference_id);
  return {
    own,
    partners: {},
    language: uiLocale === 'ru' ? 'ru' : 'en',
    includeNotes: true,
    letter: letterDefaults(suggestions.defaults, profile, email),
  };
}

export function letterDefaults(defaults: EoiDefaults, profile?: Profile, email?: string | null): EoiLetter {
  return {
    addressee_organization: defaults.addressee_organization || '',
    addressee_name: defaults.addressee_name || null,
    signatory_name: profile?.director_name?.trim() || '',
    signatory_title: '',
    contact_email: email?.trim() || '',
    contact_phone: profile?.phone_contact?.trim() || null,
    contact_address: profile?.address?.trim() || null,
  };
}

export function toggleOwn(state: BuilderState, referenceId: string, selected: boolean): BuilderState {
  const own = selected
    ? (state.own.includes(referenceId) ? state.own : [...state.own, referenceId])
    : state.own.filter((value) => value !== referenceId);
  return { ...state, own };
}

export function togglePartner(state: BuilderState, firmId: string, selected: boolean): BuilderState {
  const partners = { ...state.partners };
  if (selected) partners[firmId] = partners[firmId] ?? { role: 'JV_MEMBER', referenceIds: [] };
  else delete partners[firmId];
  return { ...state, partners };
}

export function setPartnerRole(state: BuilderState, firmId: string, role: EoiPartnerRole): BuilderState {
  const current = state.partners[firmId];
  return current ? { ...state, partners: { ...state.partners, [firmId]: { ...current, role } } } : state;
}

export function togglePartnerReference(state: BuilderState, firmId: string, referenceId: string, selected: boolean): BuilderState {
  const current = state.partners[firmId];
  if (!current) return state;
  const referenceIds = selected
    ? (current.referenceIds.includes(referenceId) ? current.referenceIds : [...current.referenceIds, referenceId])
    : current.referenceIds.filter((value) => value !== referenceId);
  return { ...state, partners: { ...state.partners, [firmId]: { ...current, referenceIds } } };
}

export type ExperienceRow = { no: number; reference: EoiReference; firmId: string | null };

/** The rows of the experience table in the order the backend will number them. */
export function experienceRows(suggestions: EoiSuggestions, state: BuilderState): ExperienceRow[] {
  const selectedOwn = new Set(state.own);
  const rows: ExperienceRow[] = [...suggestions.own_references]
    .sort((a, b) => a.rank - b.rank)
    .filter((item) => selectedOwn.has(item.reference_id))
    .map((reference) => ({ no: 0, reference, firmId: null }));
  for (const firm of suggestions.partner_firms) {
    const selection = state.partners[firm.firm_id];
    if (!selection) continue;
    const chosen = new Set(selection.referenceIds);
    for (const reference of firm.references) {
      if (chosen.has(reference.reference_id)) rows.push({ no: 0, reference, firmId: firm.firm_id });
    }
  }
  return rows.map((row, index) => ({ ...row, no: index + 1 }));
}

/** requirement id -> experience row numbers addressing it. */
export function addressedBy(suggestions: EoiSuggestions, state: BuilderState): Map<string, number[]> {
  const result = new Map<string, number[]>(suggestions.criteria.map((item) => [item.requirement_id, []]));
  for (const row of experienceRows(suggestions, state)) {
    for (const requirementId of row.reference.matched_requirement_ids) {
      result.get(requirementId)?.push(row.no);
    }
  }
  return result;
}

/** Criteria no selected own reference addresses (partners are offered against these). */
export function uncoveredByOwn(suggestions: EoiSuggestions, state: BuilderState): EoiCriterion[] {
  const covered = new Set(
    suggestions.own_references
      .filter((item) => state.own.includes(item.reference_id))
      .flatMap((item) => item.matched_requirement_ids),
  );
  return suggestions.criteria.filter((item) => !covered.has(item.requirement_id));
}

export function partnerCoversUncovered(suggestions: EoiSuggestions, state: BuilderState, firmId: string): string[] {
  const firm = suggestions.partner_firms.find((item) => item.firm_id === firmId);
  if (!firm) return [];
  const uncovered = new Set(uncoveredByOwn(suggestions, state).map((item) => item.requirement_id));
  return firm.covers_requirement_ids.filter((value) => uncovered.has(value));
}

export type BuilderError = { field: string; code: string };
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** The same limits the backend enforces, checked before Generate is enabled. */
export function builderErrors(state: BuilderState): BuilderError[] {
  const errors: BuilderError[] = [];
  if (!state.own.length) errors.push({ field: 'own', code: 'ownRequired' });
  if (state.own.length > MAX_OWN_REFERENCES) errors.push({ field: 'own', code: 'ownTooMany' });
  const partners = Object.values(state.partners);
  if (partners.length > MAX_PARTNERS) errors.push({ field: 'partners', code: 'partnersTooMany' });
  if (partners.some((item) => item.referenceIds.length > MAX_PARTNER_REFERENCES)) {
    errors.push({ field: 'partners', code: 'partnerReferencesTooMany' });
  }
  const letter = state.letter;
  if (letter.addressee_organization.trim().length < 2) errors.push({ field: 'addressee_organization', code: 'required' });
  if (letter.signatory_name.trim().length < 2) errors.push({ field: 'signatory_name', code: 'required' });
  if (letter.signatory_title.trim().length < 2) errors.push({ field: 'signatory_title', code: 'required' });
  if (!EMAIL.test(letter.contact_email.trim())) errors.push({ field: 'contact_email', code: 'email' });
  return errors;
}

const optional = (value: string | null) => (value && value.trim() ? value.trim() : null);

export function draftRequest(suggestions: EoiSuggestions, state: BuilderState): EoiDraftCreateRequest {
  const rows = experienceRows(suggestions, state);
  return {
    analysis_run_id: suggestions.analysis_run_id,
    language: state.language,
    own_reference_ids: rows.filter((row) => row.firmId === null).map((row) => row.reference.reference_id),
    partners: suggestions.partner_firms
      .filter((firm) => state.partners[firm.firm_id])
      .map((firm) => ({
        firm_id: firm.firm_id,
        role: state.partners[firm.firm_id].role,
        reference_ids: rows.filter((row) => row.firmId === firm.firm_id).map((row) => row.reference.reference_id),
      })),
    letter: {
      addressee_organization: state.letter.addressee_organization.trim(),
      addressee_name: optional(state.letter.addressee_name),
      signatory_name: state.letter.signatory_name.trim(),
      signatory_title: state.letter.signatory_title.trim(),
      contact_email: state.letter.contact_email.trim(),
      contact_phone: optional(state.letter.contact_phone),
      contact_address: optional(state.letter.contact_address),
    },
    include_relevance_notes: state.includeNotes,
  };
}

/** The workspace's latest COMPLETED run (any quality), else none. */
export function eoiRunId(...runs: ({ analysis_run_id: string; status: string } | null | undefined)[]): string | null {
  return runs.find((run) => run?.status === 'COMPLETED')?.analysis_run_id ?? null;
}

export const STALE_REASONS = [
  'NEWER_ANALYSIS_RUN', 'ANALYSIS_INPUTS_CHANGED', 'REFERENCE_SUPERSEDED', 'REFERENCE_ARCHIVED',
] as const;

export function staleReasonKey(reason: string): string {
  return (STALE_REASONS as readonly string[]).includes(reason) ? reason : 'OTHER';
}
