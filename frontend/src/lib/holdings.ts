import type { RowError } from "../types";

export const ageLabel = (days: number | null): string =>
  days === null ? "No data" : days === 0 ? "today" : days === 1 ? "1 day" : `${days} days`;

/** A file-level error (no row) shows its message alone; a missing column also names the header the file should have. */
export const rowErrorText = (e: RowError): string => {
  if (e.row === null) return e.message === "missing required column" && e.column ? `${e.message}: ${e.column}` : e.message;
  return `Row ${e.row}${e.column ? ` (${e.column})` : ""}: ${e.message}`;
};

/** `errorFor` renders a failure as "NNN: <detail>"; an intake 422 carries {message, errors} as that detail. */
export function parseIntakeError(err: Error): { message: string; errors: RowError[] } {
  try {
    const body = JSON.parse(err.message.replace(/^\d{3}: /, ""));
    if (typeof body?.message === "string") return { message: body.message, errors: Array.isArray(body.errors) ? body.errors : [] };
  } catch {
    /* not JSON */
  }
  return { message: err.message, errors: [] };
}

/** A 409 that asks for an override reason (a file over an API month), not a lost revision race. */
export const needsOverrideReason = (err: Error): boolean => err.message.startsWith("409") && /override/i.test(err.message);

/** "YYYY-MM" of the month before `today` (local time): the month a monthly run usually covers. */
export function previousMonth(today: Date): string {
  const d = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** The empty row of Security Master's unmatched table. Without a master nothing was matched at all: saying
 * "every held security is matched" would read as a result. */
export const unmatchedEmptyText = (masterIssuers: number): string =>
  masterIssuers === 0 ? "No holdings have been loaded through Holdings Intake yet." : "Every held security is matched.";
