import type { RowError } from "../types";

export const ageLabel = (days: number | null): string =>
  days === null ? "No data" : days === 0 ? "today" : days === 1 ? "1 day" : `${days} days`;

export const rowErrorText = (e: RowError): string =>
  e.row === null ? e.message : `Row ${e.row}${e.column ? ` (${e.column})` : ""}: ${e.message}`;

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
