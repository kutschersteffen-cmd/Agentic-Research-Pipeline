import type { Walkthrough } from "../types";

// The Argus walkthrough screen (#/argusWalkthrough/<run>/<company>/<item>[/<period_end>][?basis=]): its route and
// the steps one stored row went through, built from GET /api/walkthrough (argus-walkthrough spec, "The screen").

export interface Step {
  n: number;
  name: string;
  kind: "llm" | "code";
  model: string | null;
  label: string;
  /** false: the run kept no trace for this step, shown as `not recorded`. */
  recorded: boolean;
  answer: unknown;
}

export interface WalkthroughParams { runId?: string; companyId?: string; item?: string; periodEnd?: string; basis?: string }

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {});
const list = (v: unknown): Obj[] => (Array.isArray(v) ? v.map(obj) : []);

/** `periodEnd` undefined adds no period segment (Financials/TNFD); null is a row without one. */
export function walkthroughHref(runId: string, companyId: string, item: string, periodEnd?: string | null, basis?: string | null): string {
  const parts = [runId, companyId, item, ...(periodEnd === undefined ? [] : [periodEnd ?? "unspecified"])];
  // ':' is legal in a fragment; left as is so a plan row's route reads `?basis=action:3`.
  const query = basis ? `?basis=${encodeURIComponent(basis).replaceAll("%3A", ":")}` : "";
  return `#/argusWalkthrough/${parts.map(encodeURIComponent).join("/")}${query}`;
}

// The plan actions schema's list fields carry a basis; its "operates in" fields are plain data points (backend preset).
const PLAN_SCHEMA = "sch_transition_plan_actions";
// A review item knows no schema; these basis prefixes mark a list row there (the backend's review `period_key`).
const LIST_BASIS = /^(action|region|target|phaseout):/;

/** The basis that puts a plan list row on its own route, else null. `schemaId` undefined: a review item. */
export function planBasis(schemaId: string | undefined, field: { field_id: string; basis?: string | null }): string | null {
  const basis = field.basis ?? null;
  if (schemaId === undefined) return basis && LIST_BASIS.test(basis) ? basis : null;
  return schemaId === PLAN_SCHEMA && !field.field_id.startsWith("ta_operates_") ? basis : null;
}

/** A result row (or review item's value): its field, period and, for a plan list row, basis. */
export function rowWalkthroughHref(
  runId: string,
  record: { company_id: string; schema_id?: string },
  field: { field_id: string; period_end?: string | null; basis?: string | null },
): string {
  return walkthroughHref(runId, record.company_id, field.field_id, field.period_end ?? null, planBasis(record.schema_id, field));
}

/** A Financials or TNFD section: no period. */
export const recordWalkthroughHref = (runId: string, companyId: string, section: string) => walkthroughHref(runId, companyId, section);

/** App's parseHash splits on "/" and decodes, so a plan row's `?basis=` is still on the last part. */
export function parseWalkthroughParams(params: string[]): WalkthroughParams {
  const parts = [...params];
  let basis: string | undefined;
  const last = parts.length - 1;
  const q = last >= 0 ? parts[last].indexOf("?") : -1;
  if (q >= 0) {
    const query = parts[last].slice(q + 1);
    basis = query.startsWith("basis=") ? query.slice("basis=".length) : undefined;
    parts[last] = parts[last].slice(0, q);
  }
  const [runId, companyId, item, periodEnd] = parts;
  return { runId, companyId, item, periodEnd, basis };
}

const NOTES: Record<string, (days: number) => string> = {
  before_traces: () =>
    "This run is from before walkthroughs were recorded. Passages and model answers were not saved; the steps below show what the stored row holds.",
  expired: (days) =>
    `This run's walkthrough has expired: runs older than ${days} days keep only their results. The steps below show what the stored row holds.`,
  write_failed: () =>
    "The walkthrough for this company could not be saved during the run. The steps below show what the stored row holds.",
};

export function notRecordedNote(reason: string, retentionDays: number): string | null {
  return NOTES[reason]?.(retentionDays) ?? null;
}

/** A number as printed in a label: grouped thousands, its decimals kept. */
export function fmt(v: unknown): string {
  if (typeof v === "number") return v.toLocaleString("en-US", { maximumFractionDigits: 6 });
  return v == null ? "—" : String(v);
}
const conf = (v: unknown) => (typeof v === "number" ? v.toFixed(2) : "—");
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The data-point or plan row the route picks (its period), else the first. */
export function pickRow(w: Walkthrough, periodEnd?: string): Obj {
  return w.rows.find((r) => (r.period_end ?? "unspecified") === periodEnd) ?? w.rows[0] ?? {};
}

/** Every citation in a row or section, at any depth (`citations`, `description_citations`, ...). */
export function allCitations(v: unknown): Obj[] {
  if (Array.isArray(v)) return v.flatMap(allCitations);
  if (!v || typeof v !== "object") return [];
  return Object.entries(v as Obj).flatMap(([k, x]) => (k.endsWith("citations") ? list(x) : allCitations(x)));
}

/** True when a value's raw text or a citation quote names SEC XBRL (the Financials overlay). */
function xbrlUsed(v: unknown): boolean {
  if (Array.isArray(v)) return v.some(xbrlUsed);
  if (!v || typeof v !== "object") return false;
  return Object.entries(v as Obj).some(([k, x]) =>
    (k === "raw_value_text" || k === "quote") && typeof x === "string" ? /sec xbrl/i.test(x) : xbrlUsed(x),
  );
}

const grounded = (cites: Obj[]) => (cites.length ? `${cites.filter((c) => c.grounded).length} of ${cites.length} grounded` : "no quotes");

function extractLabel(answer: unknown): string {
  const a = obj(answer);
  const values = list(a.values);
  const read = !("values" in a) ? "" : values.length === 1 ? `${fmt(values[0].value)} · ` : values.length ? `${values.length} values · ` : "not disclosed · ";
  return `${read}confidence ${conf(a.confidence)}`;
}

const agreeLabel = (agrees: unknown) => (agrees === undefined ? "answered" : agrees ? "agrees" : "disagrees");

export function steps(w: Walkthrough, pick: { periodEnd?: string; basis?: string } = {}): Step[] {
  const call = (name: string, c: { model: string; answer: unknown } | null, label: string, recorded = true) =>
    ({ name, kind: "llm" as const, model: c?.model ?? null, label, recorded, answer: c?.answer ?? null });
  const code = (name: string, label: string, recorded = true) => ({ name, kind: "code" as const, model: null, label, recorded, answer: null });
  const NR = "not recorded";
  const evidence = w.recorded ? code("Find evidence", plural(w.passages.length, "passage")) : code("Find evidence", NR, false);
  const model = (name: string, c: Walkthrough["extractor"], label: (a: unknown) => string) =>
    !w.recorded ? call(name, null, NR, false) : c ? call(name, c, label(c.answer)) : call(name, null, "not reached");

  let out: Omit<Step, "n">[];
  if (w.run_type === "financials" || w.run_type === "tnfd") {
    const v = w.verifier;
    out = [
      evidence,
      model("Extract", w.extractor, extractLabel),
      w.recorded
        ? v ? call("Verify", v, agreeLabel(obj(v.answer)[`${w.item}_agree`])) : call("Verify", null, "not reached")
        : call("Verify", null, "notes from the stored row"),
      code("Ground every quote", grounded(allCitations(w.rows))),
      ...(w.run_type === "financials" ? [code("XBRL overlay", xbrlUsed(w.rows) ? "XBRL value used" : "not used")] : []),
      code("Combine", w.rows.length === 1 ? `confidence ${conf(w.rows[0].confidence)}` : `${w.rows.length} entries`),
    ];
  } else {
    const row = pickRow(w, pick.periodEnd);
    const checks = list(row.checks);
    const failed = checks.filter((c) => c.outcome === "fail").length;
    const fromRow = [
      code("Ground every quote", grounded(list(row.citations))),
      ...(pick.basis ? [] : [code("Combine into one record", combineLabel(row))]),
      code("Auto-corrections", list(row.corrections).length ? plural(list(row.corrections).length, "correction") : "none"),
      code("Checks", !checks.length ? "none" : failed ? `${failed} failed` : `${checks.filter((c) => c.outcome === "pass").length} passed`),
      code("Route", typeof row.route === "string" ? row.route : "none"),
    ];
    if (pick.basis) {
      out = [evidence, model("Extract plan", w.extractor, extractLabel), ...fromRow];
    } else {
      const s = w.skipped;
      const ruled = { tagged: "taken from XBRL tag", derived: "derived by rule", not_applicable: "not applicable by rule" }[s as string];
      const stopped = { no_evidence: "no passage matched", documents_held: "documents held" }[s as string];
      const reached = (st: Omit<Step, "n">) => (s ? { ...st, label: "not reached", recorded: true, model: null, answer: null } : st);
      const v = w.verifier;
      const verify = !w.recorded
        ? call("Verify", null, `confidence ${conf(row.verifier_confidence)}`)
        : v ? call(v.blind ? "Verify, blind" : "Verify", v, agreeLabel(v.blind ? obj(v.verdict).agrees : obj(v.answer).agrees))
        : call("Verify", null, "not reached");
      out = [
        code("Tagged data first", ruled ?? (row.method === "tagged" ? "taken from XBRL tag" : "skipped")),
        ruled ? reached(evidence) : stopped ? code("Find evidence", stopped) : evidence,
        reached(model("Extract", w.extractor, extractLabel)),
        reached(verify),
        reached(!w.recorded ? call("Adjudicate", null, NR, false) : w.adjudicator
          ? call("Adjudicate", w.adjudicator, obj(w.adjudicator.answer).settled ? "settled" : "unresolved")
          : call("Adjudicate", null, "not needed")),
        ...fromRow,
      ];
    }
  }
  return out.map((s, i) => ({ n: i + 1, ...s }));
}

function combineLabel(row: Obj): string {
  const alts = list(row.alternatives).length;
  const value = row.value == null ? String(row.value_state ?? "not found").replace("_", " ") : fmt(row.value);
  return alts ? `${value} + ${plural(alts, "alternative")}` : value;
}

/** The passage that holds a quote; an empty quote matches none. */
export function passageFor<P extends { text: string | null }>(passages: P[], quote: string): P | undefined {
  return quote ? passages.find((x) => x.text?.includes(quote)) : undefined;
}

/** Passage text split around the quoted words, each occurrence of each quote marked. */
export function markQuotes(text: string, quotes: string[]): { text: string; mark: boolean }[] {
  const hits: [number, number][] = [];
  for (const q of quotes.filter(Boolean)) {
    for (let i = text.indexOf(q); i >= 0; i = text.indexOf(q, i + q.length)) hits.push([i, i + q.length]);
  }
  hits.sort((a, b) => a[0] - b[0]);
  const out: { text: string; mark: boolean }[] = [];
  let at = 0;
  for (const [s, e] of hits) {
    if (s < at) continue; // overlapping quotes: the first wins
    if (s > at) out.push({ text: text.slice(at, s), mark: false });
    out.push({ text: text.slice(s, e), mark: true });
    at = e;
  }
  if (at < text.length || !out.length) out.push({ text: text.slice(at), mark: false });
  return out;
}
