import type { Citation, ExtractedField, ExtractionRecord, FieldDefinition, FlowFile, FlowProgress, FlowRow, PriorRun, RepeatRow, ReviewItem, RunManifest } from "../types";
import { valueLabel } from "./fieldValue.ts";

/** The accepted side of a conflict, written like the new value (with its unit); an object value as JSON, never "[object Object]". */
export const acceptedLabel = (v: unknown, unit?: string | null): string =>
  v == null ? "—" : valueLabel({ value: typeof v === "object" ? JSON.stringify(v) : (v as string | number | boolean), value_state: "found", unit: unit ?? null });
import { fieldItemKey } from "./reviewKeys.ts";

// An Argus flow (#/argus/<flow_id>/<step>): step 1's text, as the spec writes it.

export const flowHref = (flowId: string, step: number) => `#/argus/${flowId}/${step}`;

export const extractedBeforeText = (p: PriorRun | null) =>
  p ? `${p.label} · ${p.date} · ${p.approved} approved · ${p.waiting} waiting` : "Never";

export const documentsText = (count: number, types: string[]) => (count ? `${count} (${types.join(", ")})` : "None");

export const continueLabel = (n: number) => `Continue with ${n} ${n === 1 ? "company" : "companies"}`;

/** The company's own identifiers first, then the security master's that it doesn't already show. */
const SEARCH_ENDED = ["completed", "partially_completed", "failed", "cancelled"];

/** Step 2's line under "Find documents". A search that ended with nothing found says so and what to try. */
export function searchStatusText(status: string, files: number): string {
  if (!SEARCH_ENDED.includes(status)) return files > 0 ? `${files} found so far, still checking other sources…` : "Searching…";
  if (status === "completed" && files === 0)
    return "The search found no documents. Add an ISIN, LEI or CIK in step 1, try the other source, or upload the report.";
  return `Search ${status.replace("_", " ")}.`;
}

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

/** Step 3's start button: a released schema (or fixed profile) runs on every company; a draft is tried on one.
 * `name` is null while the chosen schema is still loading, when whether it is a draft is not known yet. */
export function startLabel(name: string | null, version: number | null, released: boolean, companies: number): string {
  if (name === null) return "Loading schema…";
  if (!released) return `Try ${name} on 1 company`;
  return `Extract ${name}${version ? ` v${version}` : ""} for ${companies} ${companies === 1 ? "company" : "companies"}`;
}

/** Under step 3's start button for a draft: a trial covers one company, and Release is what makes it the full run. */
export function draftHint(released: boolean, companies: number, canRelease: boolean): string | null {
  if (released || companies < 2) return null;
  return `A draft runs on one company only. ${canRelease ? "Release it" : "An approver releases it"} to extract all ${companies} companies.`;
}

/** Step 5: the flow's companies this run has no values for; `earlier` is the run a "Skip, keep earlier results" kept. */
export function notInRun(
  companies: { company_id: string; name: string }[], inRun: Set<string>, repeat: Record<string, string>,
  repeatRows: Pick<RepeatRow, "company_id" | "run_id" | "date">[],
): { name: string; earlier: { run_id: string; date: string } | null }[] {
  return companies.filter((c) => !inRun.has(c.company_id)).map((c) => {
    const kept = repeat[c.company_id] === "skip" ? repeatRows.find((r) => r.company_id === c.company_id) : undefined;
    return { name: c.name, earlier: kept ? { run_id: kept.run_id, date: kept.date } : null };
  });
}

/** Step 1's line about the flow's identity run; null when none was started. `status` is null while the run's
 * record cannot be read. `again` says whether "Resolve identities" is offered again (the run ended, companies remain). */
export function identityStatus(runId: string | null | undefined, status: string | null, unmatched: number): { text: string; again: boolean } | null {
  if (!runId) return null;
  if (status === null || !SEARCH_ENDED.includes(status)) return { text: "Identity run started.", again: false };
  if (unmatched === 0) return { text: "Identities resolved.", again: false };
  const one = unmatched === 1;
  return {
    text: `The identity run ended (${status.replace("_", " ")}): ${unmatched} ${one ? "company still has" : "companies still have"} no identifier. Add an ISIN, LEI or CIK for ${one ? "it" : "them"}, or try again.`,
    again: true,
  };
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
  /** A conflict: the accepted value the new one (`value`) would replace. */
  accepted?: string;
}

/** Step 5: one row per extracted value, the ones with an open review item first (in their order), then the rest.
 * An open item that is no value's (a company a pre-step stopped for review) gets a row of its own. */
export function resultRows(results: ExtractionRecord[], items: ReviewItem[]): ResultRow[] {
  const open = new Map(items.map((i) => [i.item_key, i]));
  const rows = results.flatMap((r) =>
    r.fields.map((f): ResultRow => {
      const key = fieldItemKey(r, f);
      const item = open.get(key) ?? null;
      const accepted = item?.kind === "conflict" ? (item.payload as { accepted?: { value?: unknown } }).accepted : undefined;
      return {
        key, companyId: r.company_id, company: r.name, field: r.field_names?.[f.field_id] ?? f.field_name, value: valueLabel(f),
        citation: f.citations.find((c) => c.grounded) ?? f.citations[0] ?? null, notFound: f.value_state === "not_found",
        item, ...(accepted ? { accepted: acceptedLabel(accepted.value, f.unit) } : {}),
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

const LIFECYCLE = new Set(["status", "version", "effective_from"]);
const content = (f: object) =>
  JSON.stringify(Object.keys(f).filter((k) => !LIFECYCLE.has(k)).sort().map((k) => [k, (f as Record<string, unknown>)[k]]));

/** A released field version never changes (the registry refuses it), so an edited released field
 * becomes its next version, a draft. Unchanged and never-released fields keep theirs. */
export function bumpChangedFields<S extends { fields: FieldDefinition[] }>(original: S | null, edited: S): S {
  if (!original) return edited;
  const before = new Map(original.fields.map((f) => [f.field_id, f]));
  return {
    ...edited,
    fields: edited.fields.map((f) => {
      const was = before.get(f.field_id);
      if (!was || was.status !== "released" || content(was) === content(f)) return f;
      return { ...f, version: (was.version ?? 1) + 1, status: "draft" as const };
    }),
  };
}

/** Calls `fn` unless a previous call is still running (then resolves at once): a double click sends once. */
export function singleFlight<A extends unknown[]>(fn: (...args: A) => Promise<void>): (...args: A) => Promise<void> {
  let running = false;
  return async (...args: A) => {
    if (running) return;
    running = true;
    try {
      await fn(...args);
    } finally {
      running = false;
    }
  };
}

type RunTimes = Pick<RunManifest, "status" | "created_at" | "updated_at" | "company_count"> & { estimated_cost_usd: number | null };

/** Step 3, next to the start button: time and cost of the latest finished run of this template, as it was. */
export function lastRunText(runs: RunTimes[]): string {
  const last = runs
    .filter((r) => r.status === "completed" || r.status === "partially_completed")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  if (!last) return "No earlier run of this template yet, so time and cost are not known. Try it on 1 company first: the run shows both.";
  const min = Math.max(1, Math.round((Date.parse(last.updated_at) - Date.parse(last.created_at)) / 60000));
  const companies = `${last.company_count} ${last.company_count === 1 ? "company" : "companies"}`;
  return last.estimated_cost_usd == null
    ? `The last run of this template took ${min} min for ${companies}; its cost was not recorded.`
    : `The last run of this template took ${min} min and $${last.estimated_cost_usd.toFixed(2)} for ${companies}.`;
}

export const TRANSITION_PLAN_TEMPLATE = "transition_plan_indicators";

/** Step 3's template line: the transition-plan template counts its indicators apart from its supporting figures. */
export function presetCountText(p: { preset_id: string; field_count: number }, indicators: number | null): string | null {
  if (p.preset_id !== TRANSITION_PLAN_TEMPLATE) return `${p.field_count} fields`;
  return indicators == null ? null : `${indicators} indicators + ${p.field_count - indicators} supporting figures`;
}

const isYes = (f: Pick<ExtractedField, "value" | "value_state">) =>
  f.value_state !== "not_found" && (f.value === true || (typeof f.value === "string" && ["yes", "true"].includes(f.value.toLowerCase())));

/** Step 5, per company of a transition-plan run: indicators answered Yes, in all and by walk and talk. No model call. */
export function walkTalkLine(
  record: Pick<ExtractionRecord, "fields" | "field_names">,
  indicators: { identifier: string; walk_or_talk: string }[],
): string {
  const yes = new Set(record.fields.filter(isYes).map((f) => record.field_names?.[f.field_id] ?? f.field_name));
  const count = (kind?: string) => {
    const of = indicators.filter((i) => !kind || i.walk_or_talk === kind);
    return `${of.filter((i) => yes.has(i.identifier)).length} of ${of.length}`;
  };
  return `Disclosed ${count()} · Walk ${count("walk")} · Talk ${count("talk")}`;
}
