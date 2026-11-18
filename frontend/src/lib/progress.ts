// The status line of an action that can take minutes (plan drafting, RFP library import).

/** Seconds as m:ss; minutes keep counting past the hour (3600 -> "60:00"). */
export function elapsedLabel(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

const KEEP_OPEN = "This can take a few minutes; keep this page open.";

export function draftingLine(outputFormat: string, seconds: number): string {
  const what = outputFormat === "house_deck" ? "storyline" : "content plan";
  return `Drafting the ${what}… ${elapsedLabel(seconds)} elapsed. ${KEEP_OPEN}`;
}

export function importingLine(fileCount: number, seconds: number): string {
  return `Importing ${fileCount} file${fileCount === 1 ? "" : "s"}… ${elapsedLabel(seconds)} elapsed. ${KEEP_OPEN}`;
}

/** What an import did, as shown on the page and read to a screen reader. */
export function importResultLine(result: { imported: number; dropped: string[] }): string {
  return `Imported ${result.imported} entries, dropped ${result.dropped.length}${result.dropped.length ? `: ${result.dropped.join("; ")}` : ""}`;
}
