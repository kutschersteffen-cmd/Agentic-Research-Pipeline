import type { FlowFile, FlowRow, PriorRun } from "../types";

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

// Step 2: the flow's files.

/** The document sources, in the spec's order; the import folder comes with slice 9. */
export const SOURCES: [value: "upload" | "import" | "filings" | "web", label: string, enabled: boolean][] = [
  ["upload", "I upload them", true],
  ["import", "From the import folder", false],
  ["filings", "Official filings", true],
  ["web", "Filings + company websites", true],
];

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function filesLabel(files: FlowFile[]): string {
  const kept = files.filter((f) => f.state === "kept");
  return `Continue with ${plural(kept.length, "file", "files")} for ${plural(new Set(kept.map((f) => f.company_id)).size, "company", "companies")}`;
}

export const keepPassing = (files: FlowFile[]): Record<string, "kept"> =>
  Object.fromEntries(files.filter((f) => f.passed && !f.duplicate_of).map((f) => [f.key, "kept"]));

export const removeAll = (files: FlowFile[]): Record<string, "removed"> =>
  Object.fromEntries(files.filter((f) => !f.duplicate_of).map((f) => [f.key, "removed"]));

/** company_id, doc_type and file name of a file in the app's folder (its key), for api.documentRawUrl; null for a filing. */
export function filePath(f: FlowFile): [string, string, string] | null {
  if (!f.on_disk) return null;
  const [company, type, ...name] = f.key.split("/");
  return [company, type, name.join("/")];
}
