import "@gorules/jdm-editor/dist/style.css";
import { DecisionGraph, JdmConfigProvider, type DecisionGraphType, type Simulation } from "@gorules/jdm-editor";
import { useEffect, useMemo, useState } from "react";
import { activatable } from "../lib/activatable";
import { evaluateGraph, loadZen, zenErrorText, type ZenResponse } from "../lib/zenEngine";
import { STARTER, TIER_STARTER } from "../lib/ruleGraphs";
import type { ColumnRole, DatasetSummary, DecisionResult, RuleGraph } from "../types";

// Mirrors RULE_NODE_TYPES in backend/arp/schemas/decision.py.
const ALLOWED_NODES = new Set(["inputNode", "outputNode", "expressionNode", "decisionTableNode", "switchNode"]);

type RowOutcome = { result: Record<string, unknown> } | { error: string };

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, "");
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** Flattens nested outputs to dotted keys, as the backend names the columns. */
function flatten(value: Record<string, unknown>, prefix = ""): Record<string, unknown> {
  return Object.entries(value).reduce<Record<string, unknown>>((out, [key, v]) => {
    if (v && typeof v === "object" && !Array.isArray(v)) Object.assign(out, flatten(v as Record<string, unknown>, `${prefix}${key}.`));
    else out[`${prefix}${key}`] = v;
    return out;
  }, {});
}

/** Tiers mode without the browser engine: what the server decided. */
function serverTierRow(result: DecisionResult | null, i: number): Record<string, string> | undefined {
  const entity = result?.entities[i];
  if (!entity) return undefined;
  return { tier: entity.tier != null ? String(entity.tier) : "", exclude: entity.status === "excluded" ? "Yes" : "", note: entity.notes.join("; ") };
}

export default function RuleGraphEditor({
  mode = "columns",
  graph,
  dataset,
  calculated = null,
  result = null,
  labelColumn,
  roles = {},
  onChange,
  onSetRole = () => {},
}: {
  /** "columns": calculated columns before scoring (Rules tab). "tiers": the
   * final tier after scoring (Decision tree tab). */
  mode?: "columns" | "tiers";
  graph: RuleGraph | null | undefined;
  dataset: DatasetSummary;
  /** Columns mode: the server's evaluation over every row; null while pending. */
  calculated?: DatasetSummary | null;
  /** Tiers mode: the latest scored result, which carries the tier inputs. */
  result?: DecisionResult | null;
  labelColumn: string | null | undefined;
  roles?: Record<string, ColumnRole | undefined>;
  onChange: (next: RuleGraph | null) => void;
  onSetRole?: (column: string, role: ColumnRole) => void;
}) {
  const tiers = mode === "tiers";
  const current = graph ?? (tiers ? TIER_STARTER : STARTER);
  const [outcomes, setOutcomes] = useState<RowOutcome[]>([]);
  const [trace, setTrace] = useState<Simulation | undefined>();
  const [traceRow, setTraceRow] = useState(0);
  const [engine, setEngine] = useState<"loading" | "ready" | string>("loading");
  const [elapsed, setElapsed] = useState<number | null>(null);

  const inputs = useMemo(() => (tiers ? (result?.tier_inputs ?? []) : dataset.rule_inputs), [tiers, result, dataset]);
  const labels = dataset.preview.map((row, i) => (labelColumn && row[labelColumn]) || `Row ${i + 1}`);
  const blocked = current.nodes.filter((n) => !ALLOWED_NODES.has(n.type)).map((n) => n.name || n.type);
  const inputKeys = useMemo(() => new Set(inputs[0] ? Object.keys(inputs[0]) : []), [inputs]);
  // Show each column once, by the name an expression most easily uses.
  const columnVariables = dataset.columns.map((column) => {
    const alias = column.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    return alias && alias !== column && inputKeys.has(alias) ? alias : column;
  });
  const engineVariables = [...inputKeys].filter((k) => !dataset.columns.some((c) => c === k || columnVariables.includes(k)));
  const variables = tiers ? [...engineVariables, ...columnVariables] : columnVariables;

  useEffect(() => {
    loadZen().then(
      () => setEngine("ready"),
      (error) => setEngine(zenErrorText(error)),
    );
  }, []);

  // Live preview: every preview row, in the browser, on every edit.
  useEffect(() => {
    if (engine !== "ready" || blocked.length) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const started = performance.now();
      const settled = await Promise.allSettled(inputs.map((context) => evaluateGraph(current, context)));
      if (cancelled) return;
      setElapsed(performance.now() - started);
      setOutcomes(
        settled.map((s) => (s.status === "fulfilled" ? { result: flatten(s.value.result ?? {}) } : { error: zenErrorText(s.reason) })),
      );
      const row = inputs[traceRow];
      if (!row) return setTrace(undefined);
      try {
        const traced: ZenResponse = await evaluateGraph(current, row, true);
        if (!cancelled)
          setTrace({
            result: {
              performance: traced.performance,
              result: traced.result,
              snapshot: current as unknown as DecisionGraphType,
              trace: (traced.trace ?? {}) as NonNullable<Simulation["result"]>["trace"],
            },
          });
      } catch (error) {
        if (!cancelled) setTrace({ error: { title: "Evaluation failed", message: zenErrorText(error), data: {} } });
      }
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [engine, current, inputs, traceRow, blocked.length]);

  // Output keys that are not source columns, in first-seen order -- the
  // same rule the backend applies when it adds the columns.
  const browserColumns = useMemo(() => {
    const keys: string[] = [];
    for (const outcome of outcomes) {
      if (!("result" in outcome)) continue;
      for (const key of Object.keys(outcome.result)) if (!inputKeys.has(key) && !keys.includes(key)) keys.push(key);
    }
    return keys;
  }, [outcomes, inputKeys]);

  const live = engine === "ready";
  const columns = tiers ? ["tier", "exclude", "note"] : live ? browserColumns : (calculated?.calculated_columns ?? []);
  // With no output columns there is no row to show an error in, so the
  // first one is shown on its own -- otherwise a broken graph looks empty.
  const browserError = live ? outcomes.map((o) => ("error" in o ? o.error : null)).find(Boolean) : null;
  const failures = tiers
    ? (result?.audit.filter((a) => a.needs_check && a.stage === "Tier rules") ?? [])
    : (calculated?.rule_audit.filter((a) => a.needs_check && a.stage === "Rules") ?? []);

  return (
    <>
      <div className="card">
        {tiers ? (
          <>
            <h3>Tier rules: the final tier, decided after scoring</h3>
            <p className="help-text">
              Each entity arrives with its <code>band</code> (the tier its score earns from the cut-points), its{" "}
              <code>score</code>, <code>rank</code>, <code>percentile</code> within its cohort, <code>coverage</code>,
              dimension scores (<code>dim_…</code>) and every column. Output <code>tier</code> (1–{result?.tier_summary.length ?? "N"}),
              and optionally <code>exclude</code> (true removes it from the tiers) and <code>note</code>. In a decision
              table the first matching row wins, so put knock-outs first and keep the catch-all{" "}
              <code>tier = band</code> last. These rules replace the gates and the dimension floor above.
            </p>
          </>
        ) : (
          <>
            <h3>Rules: calculated columns before anything is scored</h3>
            <p className="help-text">
              Drag an <strong>Expression</strong> box for formulas (<code>capex / revenue * 100</code>) or conditions
              (<code>coal_expansion_flag and not sbti_validated_target</code>), a <strong>Decision table</strong> where
              every column of a row must match (AND) and the first matching row wins (OR), or a <strong>Switch</strong> to
              branch. Each output becomes a column: make it a criterion to score it, or a gate to act on a yes/no. Refer
              to an earlier output in the same box as <code>$.name</code>.
            </p>
          </>
        )}
        <details>
          <summary>Variables you can use ({variables.length})</summary>
          <p className="rule-variables">
            {variables.map((v) => (
              <code key={v}>{v}</code>
            ))}
          </p>
        </details>
        {blocked.length > 0 && (
          <p className="error-text">
            Not allowed in a framework: {blocked.join(", ")}. Formulas and conditions only — function and sub-decision
            boxes are refused when the framework is scored or saved.
          </p>
        )}
      </div>

      <div className="card rule-canvas">
        <JdmConfigProvider theme={{ token: { colorPrimary: "#33507a", fontFamily: "IBM Plex Sans, sans-serif", borderRadius: 6 } }}>
          <DecisionGraph
            value={current as unknown as DecisionGraphType}
            simulate={trace}
            onChange={(next) => {
              if (JSON.stringify(next) !== JSON.stringify(current)) onChange(next as unknown as RuleGraph);
            }}
          />
        </JdmConfigProvider>
      </div>

      <div className="card">
        <div className="toolbar">
          <h3>Live preview</h3>
          {graph && (
            <button className="link-button" onClick={() => onChange(null)}>
              {tiers ? "Remove tier rules (back to gates)" : "Remove all rules"}
            </button>
          )}
        </div>
        <p className="help-text">
          {engine === "loading" && "Loading the rule engine (about 14 MB, once per visit)…"}
          {live &&
            `Evaluated in your browser on the first ${inputs.length} rows${elapsed != null ? ` in ${elapsed.toFixed(0)} ms` : ""}, with the same engine build the server scores with. Click a row to trace it through the boxes above.`}
          {!live && engine !== "loading" && `Browser evaluation unavailable (${engine}); showing the server's values instead.`}
        </p>
        {failures.map((f) => (
          <p key={f.item + f.decision} className="decision-check-banner">
            {f.item}: {f.decision} — {f.why}
          </p>
        ))}
        {tiers && inputs.length === 0 ? (
          <p className="muted">Score the table first — tier rules need its results.</p>
        ) : columns.length === 0 && browserError ? (
          <p className="error-text">Every preview row failed: {browserError}</p>
        ) : columns.length === 0 ? (
          <p className="muted">{tiers ? "Score the table first — tier rules need its results." : "No calculated columns yet. Add an expression with a key and a value."}</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>{labelColumn ?? "Row"}</th>
                {tiers && <th>band</th>}
                {columns.map((c) => (
                  <th key={c}>
                    {c}
                    {!tiers && <span className="rule-roles">
                      <button
                        className="link-button"
                        disabled={!calculated?.calculated_columns.includes(c) || roles[c] === "criterion"}
                        onClick={() => onSetRole(c, "criterion")}
                      >
                        {roles[c] === "criterion" ? "criterion ✓" : "score it"}
                      </button>
                      <button
                        className="link-button"
                        disabled={!calculated?.calculated_columns.includes(c) || roles[c] === "gate"}
                        onClick={() => onSetRole(c, "gate")}
                      >
                        {roles[c] === "gate" ? "gate ✓" : "gate on it"}
                      </button>
                    </span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(tiers ? labels.slice(0, inputs.length) : labels).map((label, i) => {
                const outcome = outcomes[i];
                const serverRow = tiers ? serverTierRow(result, i) : calculated?.preview[i];
                return (
                  <tr key={i} className={i === traceRow ? "clickable-row selected-row" : "clickable-row"} {...activatable(() => setTraceRow(i))}>
                    <td>{label}</td>
                    {tiers && <td>{cell(inputs[i]?.band)}</td>}
                    {live && outcome && "error" in outcome ? (
                      <td colSpan={columns.length} className="error-text">
                        {outcome.error}
                      </td>
                    ) : (
                      columns.map((c) => (
                        <td key={c}>{live ? cell(outcome && "result" in outcome ? outcome.result[c] : undefined) : serverRow?.[c] || "—"}</td>
                      ))
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
