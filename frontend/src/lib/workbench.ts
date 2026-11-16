// The Workbench table (spec stewardship-priority-worklist, "Screen"): its columns, how each one sorts and reads, and
// the sort-key rules. Pure, so the node tests can time a sort of 2,500 rows (AC-27).
import type { ProgrammeDetail, SelectionList, WorklistRow } from "../types";

export type SortKey = { id: string; desc: boolean };
type Sortable = number | string | number[] | null;

export type Column = {
  id: string;
  label: string;
  /** Always shown, at the left, in this order (spec "Always-shown columns"). */
  pinned?: boolean;
  /** Hidden until switched on in Columns ▾. */
  hidden?: boolean;
  /** Numbers (and dates) sort descending on the first click, text and ordered categories ascending. */
  numeric?: boolean;
  title?: string;
  value: (r: WorklistRow) => Sortable;
  /** Which observation of the row carries the `Simulated` flag for this column, if any. */
  simulated?: (r: WorklistRow) => boolean;
};

export const TIER_LABEL: Record<string, string> = { bilateral: "Bilateral", letter: "Letter", monitor: "Monitor" };
const TIER_RANK: Record<string, number> = { bilateral: 0, letter: 1, monitor: 2 };
const SELECTED_RANK = { confirmed: 0, proposed: 1 } as const;
const lower = (s: string) => s.toLocaleLowerCase();
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

/** "Climate engagement programme" → "Climate" (any case). */
export const programmeShort = (name: string) => name.replace(/ engagement programme$/i, "");
export const programmeChip = (p: { name: string; status: string }) => `${programmeShort(p.name)} ${p.status === "confirmed" ? "✓" : "?"}`;
export const tierText = (r: Pick<WorklistRow, "coverage_tier" | "coverage_tier_confirmed">) =>
  `${TIER_LABEL[r.coverage_tier] ?? r.coverage_tier}${r.coverage_tier_confirmed ? "" : " (proposed)"}`;

/** A date as the screen shows it, `12 Sep 2026`, read in UTC so a date never shifts a day. */
export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? iso : `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
// Fixed, not toLocaleDateString: en-GB writes "Sept" in current ICU.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const COLUMNS: Column[] = [
  { id: "company", label: "Name", pinned: true, value: (r) => lower(r.company) },
  { id: "sector", label: "Sector", pinned: true, value: (r) => lower(r.sector === "unknown" ? "Unknown" : r.sector) },
  { id: "identifier", label: "ISIN / identifier", pinned: true, value: (r) => lower(r.identifier) },
  { id: "engaged", label: "Engaged", pinned: true, numeric: true, value: (r) => (r.engaged.yes ? Date.parse(r.engaged.last ?? "") || 0 : null) },
  { id: "last_topics", label: "Last engagement topics", pinned: true, value: (r) => (r.last_topics.length ? lower(r.last_topics.join("; ")) : null) },
  { id: "programmes", label: "Programmes", pinned: true, value: (r) => (r.programmes.length ? lower(r.programmes.map(programmeChip).join(" ")) : null) },
  {
    id: "norms_violation", label: "Norm violation", pinned: true, numeric: true,
    value: (r) => (r.norms_violation === null ? null : r.norms_violation.value ? 1 : 0), simulated: (r) => !!r.norms_violation?.simulated,
  },
  { id: "funds", label: "Funds", numeric: true, title: "How many house funds hold the company", value: (r) => r.held_in.length },
  {
    id: "holdings_weight", label: "Holdings weight %", numeric: true,
    title: "The company's share of the scope's holdings (not a benchmark weight)", value: (r) => r.holdings_weight_pct,
  },
  { id: "aum_held", label: "AUM held (EUR m)", numeric: true, value: (r) => r.aum_held_eur_m },
  { id: "coverage_tier", label: "Coverage tier", value: (r) => TIER_RANK[r.coverage_tier] ?? 9 },
  { id: "triggers", label: "Open triggers", numeric: true, value: (r) => [r.triggers.high, r.triggers.medium, r.triggers.low] },
  { id: "open_engagements", label: "Open engagements", numeric: true, value: (r) => r.open_engagements },
  { id: "escalated", label: "Escalated", numeric: true, value: (r) => r.escalated },
  { id: "overdue_commitments", label: "Overdue commitments", numeric: true, value: (r) => r.overdue_commitments },
  { id: "next_meeting", label: "Next meeting", numeric: true, value: (r) => r.next_meeting?.days ?? null },
  { id: "transition_grade", label: "Grade", value: (r) => (r.transition_grade ? String(r.transition_grade.value) : null), simulated: (r) => !!r.transition_grade?.simulated },
  { id: "esg_score", label: "ESG score", numeric: true, value: (r) => num(r.esg_score?.value), simulated: (r) => !!r.esg_score?.simulated },
  { id: "controversy", label: "Controversy", numeric: true, value: (r) => num(r.controversy?.value), simulated: (r) => !!r.controversy?.simulated },
  {
    id: "carbon_intensity", label: "Carbon intensity", numeric: true, title: "tCO2e per EUR m revenue",
    value: (r) => num(r.carbon_intensity?.value), simulated: (r) => !!r.carbon_intensity?.simulated,
  },
  { id: "equity_held", label: "Equity held (EUR m)", numeric: true, hidden: true, value: (r) => r.equity_held_eur_m },
  {
    id: "ownership", label: "Ownership share %", numeric: true, hidden: true,
    value: (r) => num(r.ownership_pct?.value), simulated: (r) => !!r.ownership_pct?.simulated,
  },
  { id: "selected_elsewhere", label: "Also selected in", numeric: true, value: (r) => r.selected_elsewhere.length },
  { id: "notes", label: "Notes", numeric: true, value: (r) => r.notes.count },
  { id: "score", label: "Score", numeric: true, title: "Priority score, 0 to 100: one indicator among the others", value: (r) => r.score },
  { id: "selection", label: "Selected", value: (r) => (r.selection ? SELECTED_RANK[r.selection.status] : null) },
];

/** Columns for the `simulated_esg` fields that have no column of their own (`esg_extra`), hidden by default. */
export function extraColumns(rows: WorklistRow[], labels: Record<string, string>): Column[] {
  const ids = [...new Set(rows.flatMap((r) => Object.keys(r.esg_extra)))].sort();
  return ids.map((id) => ({
    id: `esg:${id}`,
    label: labels[id] ?? id.replace(/_/g, " "),
    hidden: true,
    numeric: true,
    value: (r: WorklistRow) => {
      const v = r.esg_extra[id]?.value;
      return v === undefined ? null : typeof v === "number" ? v : typeof v === "boolean" ? (v ? 1 : 0) : lower(String(v));
    },
    simulated: (r: WorklistRow) => !!r.esg_extra[id]?.simulated,
  }));
}

export const DEFAULT_SORT: SortKey[] = [
  { id: "score", desc: true },
  { id: "company", desc: false },
];

/** A header click. Plain: sort by that column alone (numbers descending first), or flip it when it already is the
 * only key. Shift (or "Add as next sort"): add it as the next key, up to three; a fourth replaces the third; a key
 * already there flips. */
export function nextSort(keys: SortKey[], col: Column, add: boolean): SortKey[] {
  const at = keys.findIndex((k) => k.id === col.id);
  if (!add) return keys.length === 1 && at === 0 ? [{ id: col.id, desc: !keys[0].desc }] : [{ id: col.id, desc: !!col.numeric }];
  if (at >= 0) return keys.map((k, i) => (i === at ? { ...k, desc: !k.desc } : k));
  const key = { id: col.id, desc: !!col.numeric };
  return keys.length < 3 ? [...keys, key] : [...keys.slice(0, 2), key];
}

function compare(a: Exclude<Sortable, null>, b: Exclude<Sortable, null>): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
    return 0;
  }
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0;
}

/** Rows ordered by the keys; empty values last in both directions, then by name so the order is stable. */
export function sortRows(rows: WorklistRow[], keys: SortKey[], columns: Column[]): WorklistRow[] {
  const byId = new Map(columns.map((c) => [c.id, c]));
  const used = [...keys.filter((k) => byId.has(k.id)), ...(keys.some((k) => k.id === "company") ? [] : [{ id: "company", desc: false }])];
  const values = used.map((k) => rows.map((r) => byId.get(k.id)!.value(r)));
  const order = rows.map((_, i) => i);
  order.sort((i, j) => {
    for (let k = 0; k < used.length; k++) {
      const a = values[k][i], b = values[k][j];
      if (a === null || b === null) {
        if (a !== b) return a === null ? 1 : -1;
        continue;
      }
      const c = compare(a, b);
      if (c !== 0) return used[k].desc ? -c : c;
    }
    return 0;
  });
  return order.map((i) => rows[i]);
}

export const PAGE_SIZE = 100;

/** The scope's selection this cycle: how many rows are proposed, confirmed, and both. */
export function selectionCounts(rows: WorklistRow[]) {
  const proposed = rows.filter((r) => r.selection?.status === "proposed").length;
  const confirmed = rows.filter((r) => r.selection?.status === "confirmed").length;
  return { proposed, confirmed, selected: proposed + confirmed };
}

/** `≈ 42 d (est.)` and its tooltip: the last ledger meeting rolled forward by whole years (Q1). */
export function nextMeetingText(m: NonNullable<WorklistRow["next_meeting"]>, asOf: string) {
  const target = new Date(Date.parse(`${asOf}T00:00:00Z`) + m.days * 86_400_000);
  const years = target.getUTCFullYear() - Number(m.last_meeting.slice(0, 4));
  return {
    text: `≈ ${m.days} d${m.estimated ? " (est.)" : ""}`,
    title: `Estimated: last meeting ${day(m.last_meeting)} + ${years} year${years === 1 ? "" : "s"}. No meeting calendar is connected.`,
  };
}

/** Weights section: component id → the label of its column. */
export const COMPONENT_LABEL: Record<string, string> = {
  open_triggers: "Open triggers",
  holdings_weight: "Holdings weight",
  overdue_commitments: "Overdue commitments",
  escalated: "Escalated",
  transition_grade: "Transition grade",
  aum_held: "AUM held",
  next_meeting: "Next meeting",
  coverage_tier: "Coverage tier",
  open_engagements: "Open engagements",
  esg_score: "ESG score",
  controversy: "Controversy",
  carbon_intensity: "Carbon intensity",
  broken_commitments: "Broken commitments",
};

export const weightsTotal = (components: { weight: number }[]) => components.reduce((s, c) => s + (Number.isFinite(c.weight) ? c.weight : 0), 0);
export const totalText = (total: number) => (total === 100 ? "Total 100" : `Total ${total} — must be 100`);
/** Why a set of weights cannot be saved or previewed (the server's own checks), or undefined. */
export function weightsProblem(components: { weight: number }[]): string | undefined {
  if (components.some((c) => !Number.isInteger(c.weight) || c.weight < 0 || c.weight > 100)) return "Each weight is a whole number from 0 to 100";
  const total = weightsTotal(components);
  return total === 100 ? undefined : totalText(total);
}

/** The selection object of a worklist row, from a GET or POST /selection response. */
export function withSelection(rows: WorklistRow[], list: SelectionList): WorklistRow[] {
  const by = new Map(list.rows.map(({ issuer_id, company: _c, in_scope: _s, ...sel }) => [issuer_id, sel]));
  return rows.map((r) => ({ ...r, selection: by.get(r.issuer_id) ?? null }));
}

export function withProgramme(rows: WorklistRow[], p: ProgrammeDetail): WorklistRow[] {
  const by = new Map(p.members.filter((m) => m.status !== "ended").map((m) => [m.issuer_id, m.status as "proposed" | "confirmed"]));
  return rows.map((r) => {
    const others = r.programmes.filter((c) => c.programme_id !== p.programme_id);
    const status = by.get(r.issuer_id);
    return { ...r, programmes: status ? [...others, { programme_id: p.programme_id, name: p.name, status }] : others };
  });
}
