import type { FlowFile, FlowRow, PriorRun, RepeatRow } from "../types";

// An Argus flow (#/argus/<flow_id>/<step>): step 1's text, as the spec writes it.

export const flowHref = (flowId: string, step: number) => `#/argus/${flowId}/${step}`;

export const extractedBeforeText = (p: PriorRun | null) =>
  p ? `${p.label} · ${p.date} · ${p.approved} approved · ${p.waiting} waiting` : "Never";

export const documentsText = (count: number, types: string[]) => (count ? `${count} (${types.join(", ")})` : "None");

export const continueLabel = (n: number) => `Continue with ${n} ${n === 1 ? "company" : "companies"}`;

/** The company's own identifiers first, then the security master's that it doesn't already show. */
export function identifierList(r: FlowRow): string[] {
  const own = Object.entries(r.identifiers).flatMap(([s, vs]) => vs.map((v) => `${s} ${v}`));
  const master = Object.entries(r.master_identifiers).flatMap(([s, vs]) => vs.map((v) => `${s} ${v}`));
  return [...own, ...master.filter((x) => !own.includes(x))];
}

/** Step 2's continue button: the kept files and how many companies they cover; nothing kept, nothing to continue with. */
export function continueFilesLabel(files: Pick<FlowFile, "company_id" | "state">[]): { text: string; disabled: boolean } {
  const kept = files.filter((f) => f.state === "kept");
  const m = new Set(kept.map((f) => f.company_id)).size;
  return { text: `Continue with ${kept.length} ${kept.length === 1 ? "file" : "files"} for ${m} ${m === 1 ? "company" : "companies"}`, disabled: kept.length === 0 };
}

export const previousYear = (today: Date) => today.getFullYear() - 1;

/** Step 3's start button: a released schema (or fixed profile) runs on every company; a draft is tried on one. */
export function startLabel(name: string, version: number | null, released: boolean, companies: number): string {
  if (!released) return `Try ${name} on 1 company`;
  return `Extract ${name}${version ? ` v${version}` : ""} for ${companies} ${companies === 1 ? "company" : "companies"}`;
}

export const newDocsLine = (added: number) =>
  added > 0 ? `${added} new ${added === 1 ? "document" : "documents"} since the last run` : null;

/** Every company the repeat warning lists needs Skip or Run again before the run can start. */
export const canStart = (rows: Pick<RepeatRow, "company_id" | "kind">[], repeat: Record<string, string>) =>
  rows.every((r) => r.kind !== "same" || r.company_id in repeat);

/** One entry per schema, its newest version: a run saves its schema, so an older version would be stored again as a new one. */
export function newestVersions<T extends { schema_id: string; version: number; name: string }>(all: T[]): T[] {
  const newest = new Map<string, T>();
  for (const s of all) if ((newest.get(s.schema_id)?.version ?? 0) < s.version) newest.set(s.schema_id, s);
  return [...newest.values()].sort((a, b) => a.name.localeCompare(b.name));
}
