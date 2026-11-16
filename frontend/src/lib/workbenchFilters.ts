// The Workbench filter builder (spec stewardship-priority-worklist, "Filter builder (step 2)"): which indicators can
// be filtered, the control each type gets, and how a set of filters narrows the rows. Pure, so the node tests can time
// a filter over 2,500 rows (AC-139). Filtering runs on the rows the screen already has: no request per change.
import type { WorklistRow } from "../types";
import { TIER_LABEL, programmeShort, type Column } from "./workbench.ts";

export type FilterKind = "range" | "count" | "days" | "yesno" | "category" | "text";
type Value = number | string | string[] | boolean | null;

export type Indicator = {
  id: string;
  label: string;
  kind: FilterKind;
  /** A `simulated_esg` field with no column of its own: labelled `Simulated` in the menu. */
  simulated?: boolean;
  /** Range: the column's decimals and unit, for the chip text and the number boxes. */
  decimals?: number;
  unit?: string;
  /** Category: values offered even when no row in the scope has them, in this order. */
  options?: string[];
  value: (r: WorklistRow) => Value;
};

/** One chip. `lo`/`hi` null = at the scope's bound, so the full range follows a new scope. */
export type Filter = {
  ind: Indicator;
  includeEmpty: boolean;
  lo: number | null;
  hi: number | null;
  n: number;
  yes: boolean;
  no: boolean;
  values: string[];
  text: string;
};

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const lower = (s: string) => s.toLocaleLowerCase();
const range = (id: string, label: string, decimals: number, value: Indicator["value"], unit?: string): Indicator => ({ id, label, kind: "range", decimals, unit, value });
const count = (id: string, label: string, value: Indicator["value"]): Indicator => ({ id, label, kind: "count", value });

type Control = Pick<Indicator, "label" | "kind" | "decimals" | "unit">;
/** Numeric columns: the filter reads the column's own value (lib/workbench.ts COLUMNS); only its control is set here. */
const NUMERIC: Record<string, Control> = {
  funds: { label: "Funds", kind: "count" },
  holdings_weight: { label: "Holdings weight", kind: "range", decimals: 3, unit: "%" },
  aum_held: { label: "AUM held", kind: "range", decimals: 1, unit: "EUR m" },
  open_engagements: { label: "Open engagements", kind: "count" },
  escalated: { label: "Escalated", kind: "count" },
  overdue_commitments: { label: "Overdue commitments", kind: "count" },
  next_meeting: { label: "Next meeting", kind: "days" },
  esg_score: { label: "ESG score", kind: "range", decimals: 1 },
  controversy: { label: "Controversy", kind: "range", decimals: 0 },
  carbon_intensity: { label: "Carbon intensity", kind: "range", decimals: 0, unit: "tCO2e / EUR m" },
  equity_held: { label: "Equity held", kind: "range", decimals: 1, unit: "EUR m" },
  ownership: { label: "Ownership share", kind: "range", decimals: 4, unit: "%" },
  selected_elsewhere: { label: "Also selected in", kind: "count" },
  notes: { label: "Notes", kind: "count" },
  score: { label: "Priority score", kind: "range", decimals: 1 },
};

/** The other filters a table column offers, by column id (the spec's type table). */
const BY_COLUMN: Record<string, Indicator[]> = {
  company: [{ id: "company", label: "Name", kind: "text", value: (r) => r.company }],
  sector: [{ id: "sector", label: "Sector", kind: "category", value: (r) => (r.sector === "unknown" ? "Unknown" : r.sector) }],
  identifier: [{ id: "identifier", label: "ISIN / identifier", kind: "text", value: (r) => r.identifier }],
  engaged: [{ id: "engaged", label: "Engaged", kind: "yesno", value: (r) => r.engaged.yes }],
  last_topics: [{ id: "last_topics", label: "Last engagement topics", kind: "text", value: (r) => (r.last_topics.length ? r.last_topics.join("; ") : null) }],
  programmes: [
    {
      id: "programmes", label: "Programmes", kind: "category",
      value: (r) => (r.programmes.length ? r.programmes.map((p) => `${programmeShort(p.name)} (${p.status})`) : null),
    },
  ],
  norms_violation: [{ id: "norms_violation", label: "Norm violation", kind: "yesno", value: (r) => r.norms_violation?.value ?? null }],
  coverage_tier: [
    { id: "coverage_tier", label: "Coverage tier", kind: "category", options: Object.values(TIER_LABEL), value: (r) => TIER_LABEL[r.coverage_tier] ?? r.coverage_tier },
  ],
  triggers: [
    count("triggers_any", "Open triggers – any", (r) => r.triggers.high + r.triggers.medium + r.triggers.low),
    count("triggers_high", "Open triggers – high", (r) => r.triggers.high),
  ],
  transition_grade: [
    {
      id: "transition_grade", label: "Transition grade", kind: "category", options: ["A", "B", "C", "D", "E", "F"],
      value: (r) => (r.transition_grade ? String(r.transition_grade.value) : null),
    },
  ],
  notes: [{ id: "has_notes", label: "Has notes", kind: "yesno", value: (r) => r.notes.count > 0 }],
  selection: [
    {
      id: "selection", label: "Selected", kind: "category", options: ["Confirmed", "Proposed"],
      value: (r) => (r.selection ? (r.selection.status === "confirmed" ? "Confirmed" : "Proposed") : null),
    },
  ],
};

export type SchemaField = { field_id: string; name: string; data_type: string; allowed_values?: string[] | null };

/** A `simulated_esg` field read from the row's `esg_extra`, its control from the schema's type (or the values). */
function esgIndicator(field: string, label: string, type: string | undefined, rows: WorklistRow[], allowed?: string[] | null): Indicator {
  const sample = type ?? typeof rows.find((r) => r.esg_extra[field])?.esg_extra[field].value;
  const kind: FilterKind = sample === "number" || sample === "currency_amount" || sample === "percentage" ? "range" : sample === "boolean" ? "yesno" : "category";
  const value = (r: WorklistRow): Value => {
    const v = r.esg_extra[field]?.value;
    if (v === undefined || v === null) return null;
    return kind === "range" ? num(v) : kind === "yesno" ? (typeof v === "boolean" ? v : null) : String(v);
  };
  return { id: `esg:${field}`, label, kind, simulated: true, decimals: kind === "range" ? 2 : undefined, options: allowed ?? undefined, value };
}

/** Every indicator of the Add filter menu: each table column, in table order, then each `simulated_esg` field that
 * is not already a column. A column this list does not know yet filters by its own sort value. */
export function indicators(columns: Column[], schema: SchemaField[], rows: WorklistRow[]): Indicator[] {
  const fields = new Map(schema.map((f) => [f.field_id, f]));
  const out: Indicator[] = [];
  for (const c of columns) {
    if (c.id.startsWith("esg:")) {
      const f = fields.get(c.id.slice(4));
      out.push(esgIndicator(c.id.slice(4), f?.name ?? c.label, f?.data_type, rows, f?.allowed_values));
    } else if (NUMERIC[c.id] || BY_COLUMN[c.id]) {
      if (NUMERIC[c.id]) out.push({ id: c.id, ...NUMERIC[c.id], value: (r) => num(c.value(r)) });
      out.push(...(BY_COLUMN[c.id] ?? []));
    } else
      out.push(
        c.numeric
          ? range(c.id, c.label, 2, (r) => num(c.value(r)))
          : { id: c.id, label: c.label, kind: "text", value: (r) => { const v = c.value(r); return v === null ? null : String(v); } },
      );
  }
  const have = new Set(out.map((i) => i.id));
  // The fields shown in their own columns (worklist.py OBSERVED and NORMS).
  const asColumn = new Set(["transition_grade", "esg_score", "controversy_level", "ghg_intensity", "norms_violation"]);
  const extra = schema
    .filter((f) => !asColumn.has(f.field_id) && !have.has(`esg:${f.field_id}`))
    .map((f) => esgIndicator(f.field_id, f.name, f.data_type, rows, f.allowed_values));
  return [...out, ...extra.sort((a, b) => a.label.localeCompare(b.label))];
}

/** Where the two range handles overlap, the one on top takes the pointer: Lowest once it is in the upper half, so a
 * handle pushed to the top end can still be dragged back. */
export const lowOnTop = (lo: number, b: Bounds) => lo > (b.min + b.max) / 2;

/** A new chip with the spec's default: full range, at least 1, at most 90 days, `Yes`, nothing ticked, empty. */
export const newFilter = (ind: Indicator): Filter => ({ ind, includeEmpty: false, lo: null, hi: null, n: ind.kind === "days" ? 90 : 1, yes: true, no: false, values: [], text: "" });

const isEmpty = (v: Value) => v === null || v === "" || (Array.isArray(v) && v.length === 0);

export type Bounds = { min: number; max: number };

/** The slider's ends in this scope: range = the lowest and highest value (to the column's decimals, outward);
 * count = 0 to the highest count (at least 1); days = 0 to the furthest meeting (at least 90). Null without values. */
export function bounds(ind: Indicator, rows: WorklistRow[]): Bounds | null {
  let min = Infinity, max = -Infinity;
  for (const r of rows) {
    const v = ind.value(r);
    if (typeof v !== "number") continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (ind.kind === "count") return { min: 0, max: Math.max(1, max === -Infinity ? 0 : max) };
  if (ind.kind === "days") return { min: 0, max: Math.max(90, max === -Infinity ? 0 : max) };
  if (min === Infinity) return null;
  const f = 10 ** (ind.decimals ?? 2);
  return { min: Math.floor(min * f + 1e-9) / f, max: Math.ceil(max * f - 1e-9) / f };
}

const clamp = (v: number, b: Bounds) => Math.min(b.max, Math.max(b.min, v));

/** A range chip's ends in this scope, clamped to its bounds (a value set in another scope reads as the nearest bound
 * here); null on a side the user left at its bound (filters nothing). */
export function effectiveRange(f: Filter, b: Bounds | null): { lo: number | null; hi: number | null } {
  return { lo: f.lo === null || !b ? f.lo : clamp(f.lo, b), hi: f.hi === null || !b ? f.hi : clamp(f.hi, b) };
}

/** The count or days slider's value in this scope, clamped to its bounds. */
export const effectiveN = (f: Filter, b: Bounds | null) => (b ? clamp(f.n, b) : f.n);

/** A test for one row, or null when the chip filters nothing yet (full range, nothing ticked, empty box). */
function predicate(f: Filter, rows: WorklistRow[]): ((v: Value) => boolean) | null {
  switch (f.ind.kind) {
    case "range": {
      const { lo, hi } = effectiveRange(f, bounds(f.ind, rows));
      if (lo === null && hi === null) return null;
      return (v) => typeof v === "number" && (lo === null || v >= lo) && (hi === null || v <= hi);
    }
    case "count": {
      const n = effectiveN(f, bounds(f.ind, rows));
      return n > 0 ? (v) => typeof v === "number" && v >= n : null;
    }
    case "days": {
      const n = effectiveN(f, bounds(f.ind, rows));
      return (v) => typeof v === "number" && v <= n;
    }
    case "yesno":
      if (!f.yes && !f.no) return null;
      return (v) => (v === true && f.yes) || (v === false && f.no);
    case "category": {
      if (!f.values.length) return null;
      const set = new Set(f.values);
      return (v) => (Array.isArray(v) ? v.some((x) => set.has(x)) : set.has(String(v)));
    }
    case "text": {
      const q = lower(f.text.trim());
      return q ? (v) => lower(String(v)).includes(q) : null;
    }
  }
}

/** The rows that pass every chip (AND). A row with no value for an active chip is left out unless Include empty. */
export function filterRows(rows: WorklistRow[], filters: Filter[]): WorklistRow[] {
  const tests = filters.flatMap((f) => {
    const p = predicate(f, rows);
    return p ? [{ f, p }] : [];
  });
  if (!tests.length) return rows;
  return rows.filter((r) =>
    tests.every(({ f, p }) => {
      const v = f.ind.value(r);
      return isEmpty(v) ? f.includeEmpty : p(v);
    }),
  );
}

/** The category checklist: the fixed values first, then every other value present in the scope. */
export function categoryOptions(ind: Indicator, rows: WorklistRow[]): string[] {
  const seen = new Set<string>();
  for (const r of rows) {
    const v = ind.value(r);
    for (const x of Array.isArray(v) ? v : v === null || v === "" ? [] : [String(v)]) seen.add(x);
  }
  const fixed = ind.options ?? [];
  return [...fixed, ...[...seen].filter((x) => !fixed.includes(x)).sort((a, b) => a.localeCompare(b))];
}

/** A number as the column shows it, with its unit: `0.0100 %`, `12.5 EUR m`. */
export const amount = (v: number, ind: Indicator) => `${v.toFixed(ind.decimals ?? 2)}${ind.unit ? ` ${ind.unit}` : ""}`;

/** The chip's condition in words, e.g. `Ownership share ≥ 0.0100 %`, `Norm violation: Yes`, `Sector: Energy, Utilities`. */
export function chipText(f: Filter, rows: WorklistRow[]): string {
  const { ind } = f;
  const b = ind.kind === "range" || ind.kind === "count" || ind.kind === "days" ? bounds(ind, rows) : null;
  let text: string;
  switch (ind.kind) {
    case "range": {
      const { lo, hi } = effectiveRange(f, b);
      text =
        lo !== null && hi !== null ? `${ind.label} ${amount(lo, { ...ind, unit: undefined })} – ${amount(hi, ind)}`
        : lo !== null ? `${ind.label} ≥ ${amount(lo, ind)}`
        : hi !== null ? `${ind.label} ≤ ${amount(hi, ind)}`
        : `${ind.label}: any`;
      break;
    }
    case "count":
      text = `${ind.label}: at least ${effectiveN(f, b)}`;
      break;
    case "days":
      text = `${ind.label}: within ${effectiveN(f, b)} days`;
      break;
    case "yesno":
      text = `${ind.label}: ${[f.yes && "Yes", f.no && "No"].filter(Boolean).join(", ") || "any"}`;
      break;
    case "category":
      text = `${ind.label}: ${f.values.length ? f.values.join(", ") : "any"}`;
      break;
    case "text":
      text = f.text.trim() ? `${ind.label} contains “${f.text.trim()}”` : `${ind.label}: any`;
      break;
  }
  return f.includeEmpty ? `${text} · or empty` : text;
}
