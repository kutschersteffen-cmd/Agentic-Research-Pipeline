import type { Citation, ExtractionRecord, FlowFile, FlowProgress, FlowRow, PriorRun, RepeatRow, ReviewItem } from "../types";
import { valueLabel } from "./fieldValue.ts";
import { fieldItemKey } from "./reviewKeys.ts";

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

const two = (n: number) => String(n).padStart(2, "0");

/** Step 4's header line; until a company has finished there is nothing to estimate the time left from. */
export function progressHeader(p: Pick<FlowProgress, "started_at" | "done" | "total" | "minutes_left" | "cost_usd" | "status">): string {
  const at = new Date(p.started_at);
  const active = p.status === "pending" || p.status === "running";
  const left = !active ? "" : p.minutes_left == null ? " · estimating time left" : ` · about ${p.minutes_left} ${p.minutes_left === 1 ? "minute" : "minutes"} left`;
  return `Started ${two(at.getHours())}:${two(at.getMinutes())} · ${p.done} of ${p.total} done${left} · $${p.cost_usd.toFixed(2)} so far`;
}

export interface ResultRow {
  key: string;
  companyId: string;
  company: string;
  field: string;
  value: string;
  citation: Citation | null;
  notFound: boolean;
  /** The open review item for this value; set means it needs a person. */
  item: ReviewItem | null;
  /** A whole company waits (a step before extraction stopped it), not one value. */
  companyLevel?: boolean;
}

/** Step 5: one row per extracted value, the ones with an open review item first (in their order), then the rest.
 * An open item that is no value's (a company a pre-step stopped for review) gets a row of its own. */
export function resultRows(results: ExtractionRecord[], items: ReviewItem[]): ResultRow[] {
  const open = new Map(items.map((i) => [i.item_key, i]));
  const rows = results.flatMap((r) =>
    r.fields.map((f): ResultRow => {
      const key = fieldItemKey(r, f);
      return {
        key, companyId: r.company_id, company: r.name, field: r.field_names?.[f.field_id] ?? f.field_name, value: valueLabel(f),
        citation: f.citations.find((c) => c.grounded) ?? f.citations[0] ?? null, notFound: f.value_state === "not_found",
        item: open.get(key) ?? null,
      };
    }),
  );
  const used = new Set(rows.map((r) => r.key));
  const companies = items.filter((i) => !used.has(i.item_key)).map((i): ResultRow => {
    const p = i.payload as { company_id?: string; name?: string; failed_step_label?: string; error?: string };
    const cid = p.company_id ?? i.item_key;
    return { key: i.item_key, companyId: cid, company: p.name ?? cid, field: p.failed_step_label ?? "Whole company",
      value: p.error ?? "Stopped for review", citation: null, notFound: false, item: i, companyLevel: true };
  });
  return [...companies, ...rows.filter((r) => r.item), ...rows.filter((r) => !r.item)];
}

export const onlyNeedsYou = (rows: ResultRow[]) => rows.filter((r) => r.item);
