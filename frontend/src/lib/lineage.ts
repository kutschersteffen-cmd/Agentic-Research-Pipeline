// Score lineage as plain lines: score → criterion → authoritative value → inputs → citations (spec §5).

export type Citation = { doc_id: string; page: number | null; quote: string | null; grounded: boolean };
export type LineageInput = {
  name: string;
  value: unknown;
  status: string | null;
  source: string | null;
  provider: string | null;
  period_end: string | null;
  unit?: string | null;
  observation_id: number | null;
  published_fact_id: string | null;
  link: "observation" | "no_observation";
  citations: Citation[];
};
export type LineageValue = {
  value: unknown;
  unit: string | null;
  status: string;
  reason: string | null;
  period_end: string | null;
  framework_id: string;
  framework_version: number;
  superseded: boolean;
  current_valid_to: string | null;
};
export type LineageCriterion = {
  column?: string;
  contribution?: number;
  imputed?: boolean;
  missing_reason?: string | null;
  link: "authoritative" | "dataset_cell" | "missing" | "not_recorded";
  value_id?: number | null;
  value?: LineageValue | null;
  inputs?: LineageInput[] | null;
};
export type RowLineage = {
  entity_id: string;
  name: string;
  status: string;
  reasons: string[];
  score: number | null;
  rank: number | null;
  tier: number | null;
  tier_name: string | null;
  framework_id?: string;
  snapshot_id?: string;
  published_at?: string;
  criteria: LineageCriterion[];
};

const show = (x: unknown) => (x !== null && typeof x === "object" ? JSON.stringify(x) : String(x));

function valueLine(c: LineageCriterion): string {
  if (c.link === "not_recorded") return "Lineage not recorded (published before lineage)";
  if (c.link === "dataset_cell") return `${c.column}: from the table (no authoritative value)`;
  if (c.link === "missing") return `${c.column}: authoritative value ${c.value_id ?? "?"} not found`;
  const v = c.value!;
  if (v.status !== "value") return `${c.column}: no value (${v.reason ?? "unknown"})`;
  return `${c.column} = ${[show(v.value), v.unit].filter(Boolean).join(" ")}${v.superseded ? " (since replaced)" : ""}`;
}

export function lineageLines(l: RowLineage): {
  header: string;
  reasons: string[];
  criteria: { title: string; value: string; inputs: string[]; citations: string[] }[];
} {
  const header = `${l.name} · ${l.status === "no_score" ? "no score" : `${l.score?.toFixed(1) ?? "—"}${l.tier_name ? ` · ${l.tier_name}` : ""}`}`;
  const criteria = l.criteria.map((c) => {
    const inputs = (c.inputs ?? []).map((i) =>
      i.value == null ? `${i.name} = —` : [`${i.name} = ${show(i.value)}`, i.status, [i.source, i.provider].filter(Boolean).join(" "), i.period_end].filter(Boolean).join(" · "),
    );
    const citations = (c.inputs ?? []).flatMap((i) =>
      i.link === "no_observation" ? [`${i.name}: no source observation`] : i.citations.map((t) => `${t.doc_id}${t.page != null ? ` p.${t.page}` : ""} · "${t.quote ?? ""}"`),
    );
    const title = c.column ? `${c.column}${c.missing_reason ? ` · missing (${c.missing_reason})` : ""}${c.imputed ? " · imputed" : ""}` : "";
    return { title, value: valueLine(c), inputs, citations };
  });
  return { header, reasons: l.reasons, criteria };
}

type LiveContribution = { column: string; contribution: number; imputed: boolean; value_id?: number | null; missing_reason?: string | null };
type LiveEntity = {
  entity_key: string;
  name: string;
  status: string;
  reasons?: string[];
  score: number | null;
  rank?: number | null;
  tier?: number | null;
  tier_name?: string | null;
  contributions: LiveContribution[];
};
type FetchedValue = {
  value: unknown;
  unit: string | null;
  status: string;
  reason: string | null;
  period_end: string | null;
  framework_id: string;
  framework_version: number;
  valid_to: string | null;
  derivation?: { inputs?: Record<string, Omit<LineageInput, "name" | "link" | "citations">> } | null;
};

/** Before publishing: the live result's contributions, with the authoritative values fetched by id. Citations are only
 *  resolved for published decisions (the server reads them). */
export function lineageFromEntity(e: LiveEntity, values: Record<number, FetchedValue>): RowLineage {
  return {
    entity_id: e.entity_key,
    name: e.name,
    status: e.status,
    reasons: e.reasons ?? [],
    score: e.score,
    rank: e.rank ?? null,
    tier: e.tier ?? null,
    tier_name: e.tier_name ?? null,
    criteria: e.contributions.map((c) => {
      const base = { column: c.column, contribution: c.contribution, imputed: c.imputed, missing_reason: c.missing_reason ?? null, value_id: c.value_id ?? null };
      if (c.value_id == null) return { ...base, link: "dataset_cell" as const, value: null, inputs: null };
      const v = values[c.value_id];
      if (!v) return { ...base, link: "missing" as const, value: null, inputs: null };
      return {
        ...base,
        link: "authoritative" as const,
        value: { value: v.value, unit: v.unit, status: v.status, reason: v.reason, period_end: v.period_end, framework_id: v.framework_id, framework_version: v.framework_version, superseded: v.valid_to != null, current_valid_to: v.valid_to },
        inputs: Object.entries(v.derivation?.inputs ?? {}).map(([name, i]) => ({
          name,
          ...i,
          link: i.observation_id ? ("observation" as const) : ("no_observation" as const),
          citations: [],
        })),
      };
    }),
  };
}
