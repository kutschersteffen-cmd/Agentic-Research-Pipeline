// Taxonomy Library → Universe builder wording (spec showcase-themes-fixes, sections 3 and 11).

/** What the fund list says when it is empty: before a search, after a search with search down, after an empty search. */
export function fundSearchEmptyText(searched: { search_unreachable: boolean } | null): string | undefined {
  if (!searched) return undefined;
  return searched.search_unreachable
    ? "The web search could not be reached. Download the fund's holdings file from the provider's website and upload it in step 2 below."
    : "No candidates found. Try another name.";
}

/** The success line after building a universe from holdings: its file name, never the server path. */
export function builtUniverseLine(result: { path: string; company_count: number }): string {
  const name = result.path.split(/[\\/]/).pop();
  return `Built ${result.company_count} companies and saved them as the universe "${name}". Pick it under "Or pick a saved universe" on the Thematic Universe page.`;
}
