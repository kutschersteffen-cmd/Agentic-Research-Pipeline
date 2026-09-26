import "@gorules/jdm-editor/dist/style.css";
import { DecisionGraph, JdmConfigProvider, type DecisionGraphType, type Simulation } from "@gorules/jdm-editor";
import { useEffect, useMemo, useState } from "react";
import { activatable } from "../lib/activatable";
import { evaluateGraph, loadZen, zenErrorText, type ZenResponse } from "../lib/zenEngine";
import type { ColumnRole, DatasetSummary, RuleGraph } from "../types";

// Mirrors RULE_NODE_TYPES in backend/arp/schemas/decision.py.
const ALLOWED_NODES = new Set(["inputNode", "outputNode", "expressionNode", "decisionTableNode", "switchNode"]);

const node = (id: string, type: string, name: string, x: number, content?: object) => ({
  id,
  type,
  name,
  position: { x, y: 120 },
  ...(content ? { content } : {}),
});

const STARTER: RuleGraph = {
  nodes: [
    node("input", "inputNode", "Row", 0),
    node("formulas", "expressionNode", "Formulas", 280, {
      expressions: [],
      passThrough: false,
      inputField: null,
      outputPath: null,
      executionMode: "single",
    }),
    node("output", "outputNode", "Calculated columns", 620),
  ],
  edges: [
    { id: "input-formulas", sourceId: "input", targetId: "formulas", type: "edge" },
    { id: "formulas-output", sourceId: "formulas", targetId: "output", type: "edge" },
  ],
};

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

export default function RuleGraphEditor({
  graph,
  dataset,
  calculated,
  labelColumn,
  roles,
  onChange,
  onSetRole,
}: {
  graph: RuleGraph | null | undefined;
  dataset: DatasetSummary;
  /** The server's evaluation over every row; null while it is pending. */
  calculated: DatasetSummary | null;
  labelColumn: string | null | undefined;
  roles: Record<string, ColumnRole | undefined>;
  onChange: (next: RuleGraph | null) => void;
  onSetRole: (column: string, role: ColumnRole) => void;
}) {
  const current = graph ?? STARTER;
  const [outcomes, setOutcomes] = useState<RowOutcome[]>([]);
  const [trace, setTrace] = useState<Simulation | undefined>();
  const [traceRow, setTraceRow] = useState(0);
  const [engine, setEngine] = useState<"loading" | "ready" | string>("loading");
  const [elapsed, setElapsed] = useState<number | null>(null);

  const inputs = dataset.rule_inputs;
  const labels = dataset.preview.map((row, i) => (labelColumn && row[labelColumn]) || `Row ${i + 1}`);
  const blocked = current.nodes.filter((n) => !ALLOWED_NODES.has(n.type)).map((n) => n.name || n.type);
  const inputKeys = useMemo(() => new Set(inputs[0] ? Object.keys(inputs[0]) : []), [inputs]);
  // Show each column once, by the name an expression most easily uses.
  const variables = dataset.columns.map((column) => {
    const alias = column.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    return alias && alias !== column && inputKeys.has(alias) ? alias : column;
  });

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
  const columns = live ? browserColumns : (calculated?.calculated_columns ?? []);
  const failures = calculated?.rule_audit.filter((a) => a.needs_check && a.stage === "Rules") ?? [];

  return (
    <>
      <div className="card">
        <h3>Rules: calculated columns before anything is scored</h3>
        <p className="help-text">
          Drag an <strong>Expression</strong> box for formulas (<code>capex / revenue * 100</code>) or conditions
          (<code>coal_expansion_flag and not sbti_validated_target</code>), a <strong>Decision table</strong> where every
          column of a row must match (AND) and the first matching row wins (OR), or a <strong>Switch</strong> to branch.
          Each output becomes a column: make it a criterion to score it, or a gate to act on a yes/no. Refer to an
          earlier output in the same box as <code>$.name</code>.
        </p>
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
              Remove all rules
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
        {columns.length === 0 ? (
          <p className="muted">No calculated columns yet. Add an expression with a key and a value.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>{labelColumn ?? "Row"}</th>
                {columns.map((c) => (
                  <th key={c}>
                    {c}
                    <span className="rule-roles">
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
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((label, i) => {
                const outcome = outcomes[i];
                const serverRow = calculated?.preview[i];
                return (
                  <tr key={i} className={i === traceRow ? "clickable-row selected-row" : "clickable-row"} {...activatable(() => setTraceRow(i))}>
                    <td>{label}</td>
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
