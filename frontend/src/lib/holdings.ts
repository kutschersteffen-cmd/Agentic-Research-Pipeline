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
