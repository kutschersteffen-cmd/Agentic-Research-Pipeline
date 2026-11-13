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
