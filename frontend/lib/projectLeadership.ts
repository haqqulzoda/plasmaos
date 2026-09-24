/** Presentation rules for source-backed project leadership names. */
export function leadershipListPresentation<T>(items: readonly T[], expanded: boolean) {
  return {
    columns: items.length >= 4 ? "two" as const : "one" as const,
    visibleItems: expanded || items.length <= 6 ? items : items.slice(0, 6),
    hasToggle: items.length > 6,
  };
}
