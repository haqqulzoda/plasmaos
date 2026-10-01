/**
 * D2-03 minimal Requirements screen: one grouped list (each requirement once), bulk
 * confirmation plans, and the pursuit display title. Pure; tested without React.
 */
import type { PursuitAnalysis, PursuitGap, PursuitRequirement, PursuitSubmissionNote } from '../types/pursuit';

export const REQUIREMENT_GROUPS = ['attention', 'partial', 'notes', 'later', 'settled'] as const;
export type RequirementGroup = (typeof REQUIREMENT_GROUPS)[number];
export type GroupedRequirements = Record<RequirementGroup, PursuitRequirement[]>;

const ATTENTION = new Set(['GAP', 'EVIDENCE_MISSING', 'NEEDS_INTERPRETATION']);

export function requirementGroup(item: PursuitRequirement): RequirementGroup {
  const state = item.effective_coverage_state;
  if (ATTENTION.has(state)) return 'attention';
  if (state === 'PARTIAL') return 'partial';
  if (state === 'LATER_STAGE_OBLIGATION') return 'later';
  return 'settled'; // SUPPORTED or NOT_APPLICABLE stated by a reviewer
}

/**
 * Every requirement appears once. Submission instructions and informational notes come
 * from ``submission_and_notes`` and never from ``requirements`` (older runs that put them
 * in ``requirements`` keep them there).
 */
export function groupRequirements(analysis: Pick<PursuitAnalysis, 'requirements' | 'submission_and_notes'> | null): GroupedRequirements {
  const groups: GroupedRequirements = { attention: [], partial: [], notes: [], later: [], settled: [] };
  if (!analysis) return groups;
  const seen = new Set<string>();
  for (const note of analysis.submission_and_notes ?? []) {
    if (seen.has(note.requirement_id)) continue;
    seen.add(note.requirement_id);
    groups.notes.push(note);
  }
  for (const item of analysis.requirements) {
    if (seen.has(item.requirement_id)) continue;
    seen.add(item.requirement_id);
    groups[requirementGroup(item)].push(item);
  }
  return groups;
}

export function gapsByRequirement(gaps: readonly PursuitGap[]): Map<string, PursuitGap> {
  return new Map(gaps.filter((gap) => gap.requirement_id).map((gap) => [gap.requirement_id as string, gap]));
}

export type ReviewPost = {
  target_kind: 'REQUIREMENT' | 'GAP';
  target_id: string;
  new_coverage_state: string;
  new_review_state: 'CONFIRMED';
  corrected_fields: Record<string, never>;
  reason: string;
};

/**
 * "Confirm all in this group": the requirement and, when it has one, its Gap, each
 * confirmed at its current coverage. Notes have no Gap. Per-item reasons override the
 * group reason.
 */
export function bulkConfirmPlan(
  items: readonly PursuitRequirement[],
  gaps: Map<string, PursuitGap>,
  reason: string,
  overrides: Record<string, string> = {},
): { requirementId: string; posts: ReviewPost[] }[] {
  return items.map((item) => {
    const why = (overrides[item.requirement_id] ?? '').trim() || reason.trim();
    const posts: ReviewPost[] = [{
      target_kind: 'REQUIREMENT', target_id: item.requirement_id, new_coverage_state: item.effective_coverage_state,
      new_review_state: 'CONFIRMED', corrected_fields: {}, reason: why,
    }];
    const gap = gaps.get(item.requirement_id);
    if (gap) {
      posts.push({
        target_kind: 'GAP', target_id: gap.gap_id, new_coverage_state: gap.effective_coverage_state,
        new_review_state: 'CONFIRMED', corrected_fields: {}, reason: why,
      });
    }
    return { requirementId: item.requirement_id, posts };
  });
}

export function defaultBulkReason(template: string, name: string | null | undefined): string {
  return template.replace('{name}', name?.trim() || '—');
}

export type SequentialReport = { done: number; failed: { id: string; message: string }[] };

/** Runs tasks one at a time, in order, reporting progress and every failure. */
export async function runSequential<T>(
  items: readonly T[],
  id: (item: T) => string,
  task: (item: T) => Promise<unknown>,
  onProgress?: (done: number, total: number) => void,
  describe: (error: unknown) => string = (error) => (error instanceof Error ? error.message : String(error)),
): Promise<SequentialReport> {
  const report: SequentialReport = { done: 0, failed: [] };
  onProgress?.(0, items.length);
  for (const item of items) {
    try {
      await task(item);
    } catch (error) {
      report.failed.push({ id: id(item), message: describe(error) });
    }
    report.done += 1;
    onProgress?.(report.done, items.length);
  }
  return report;
}

/** Names of matched references, resolved from the library; unknown ids are counted, not invented. */
export function referenceNames(
  ids: readonly string[] | undefined,
  library: Map<string, string>,
): { names: string[]; unresolved: number } {
  const names: string[] = [];
  let unresolved = 0;
  for (const value of ids ?? []) {
    const name = library.get(value);
    if (name) names.push(name);
    else unresolved += 1;
  }
  return { names, unresolved };
}

type TitledPursuit = {
  title?: string | null;
  tender_title?: string | null;
  first_document_name?: string | null;
  created_at: string;
};

/** Never "Untitled": context title, tender title, first uploaded document, else "Uploaded tender · date". */
export function pursuitDisplayTitle(
  pursuit: TitledPursuit,
  fallback: (date: string) => string,
): string {
  const value = [pursuit.title, pursuit.tender_title, pursuit.first_document_name]
    .map((item) => item?.trim())
    .find(Boolean);
  return value || fallback(pursuit.created_at);
}

export type { PursuitSubmissionNote };
