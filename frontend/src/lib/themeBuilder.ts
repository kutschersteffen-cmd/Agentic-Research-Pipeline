// Thematic Universe wording and citation links (spec showcase-themes-fixes, sections 5 and 6).

/** Shown after "Save as taxonomy draft". */
export const savedDraftLine = (name: string) =>
  `Saved as draft "${name}". Ratify it and release its schema in the Taxonomy Library, then come back and run it.`;

/** A citation without a stored file links to its web address, but only an http(s) one. */
export function webSourceUrl(c: { source_filename?: string | null; source_url?: string | null }): string | null {
  if (c.source_filename || !c.source_url) return null;
  return /^https?:\/\//i.test(c.source_url) ? c.source_url : null;
}

/** "1 company", "2 companies". */
export const companies = (n: number) => `${n} ${n === 1 ? "company" : "companies"}`;

/** The "Filter by activity" choices: the theme's activities, else those found in the results. */
export function activityOptions(
  theme: { activities: { activity_id: string; name: string }[] } | null,
  results: { activity_id: string; activity_name: string }[],
): { id: string; name: string }[] {
  if (theme) return theme.activities.map((a) => ({ id: a.activity_id, name: a.name }));
  const seen = new Map<string, string>();
  for (const r of results) if (!seen.has(r.activity_id)) seen.set(r.activity_id, r.activity_name);
  return [...seen].map(([id, name]) => ({ id, name }));
}
