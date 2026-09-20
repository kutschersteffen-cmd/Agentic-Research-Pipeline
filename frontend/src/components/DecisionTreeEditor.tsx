import type { ColumnProfile, CutMode, DecisionResult, GateOutcome, MechanismConfig } from "../types";

const OUTCOMES: { value: GateOutcome; label: string }[] = [
  { value: "exclude", label: "Exclude outright" },
  { value: "demote", label: "Demote one tier" },
  { value: "flag", label: "Flag only" },
];

/** The evaluation order is fixed, and that is what makes a result
 * reproducible: sufficiency, then hard gates, then the band, then
 * modifiers. Anything a gate settles never reaches the score. */
export function DecisionTreeEditor({
  config,
  profiles,
  result,
  onChange,
}: {
  config: MechanismConfig;
  profiles: ColumnProfile[];
  result: DecisionResult | null;
  onChange: (next: MechanismConfig) => void;
}) {
  const set = (patch: Partial<MechanismConfig>) => onChange({ ...config, ...patch });
  const cuts = result?.effective_cuts ?? config.pinned_cuts ?? [];

  const addGate = () => {
    const candidate = profiles.find((p) => !config.gates.some((g) => g.column === p.name));
    if (!candidate) return;
    set({
      gates: [
        ...config.gates,
        { id: `gate_${Date.now()}`, column: candidate.name, op: "is", value: "Yes", outcome: "demote" },
      ],
    });
  };

  return (
    <div>
      <div className="card">
        <h3>Order of decisions</h3>
        <ol className="decision-tree-steps">
          <li>
            <strong>Sufficiency</strong> — below {config.min_coverage_pct}% of{" "}
            {config.require_grounded_coverage ? "grounded " : ""}weight covered, an entity is routed to data collection
            rather than scored on a fraction of its criteria.
            {result ? <span className="muted"> {result.insufficient_count} routed here.</span> : null}
          </li>
          <li>
            <strong>Hard gates</strong> — a knockout is a decision, not a deduction, so it is settled before the average
            exists.
            {result ? <span className="muted"> {result.excluded_count} excluded.</span> : null}
          </li>
          <li>
            <strong>Score band</strong> — cut-points drawn over the entities still eligible, never over the whole table.
            {cuts.length > 0 ? <span className="muted"> Cutting at {cuts.map((c) => c.toFixed(1)).join(", ")}.</span> : null}
          </li>
          <li>
            <strong>Modifiers</strong> — demote-gates and the dimension floor, applied last so they adjust a decision
            rather than dilute into one.
          </li>
        </ol>
      </div>

      <div className="decision-grid">
        <div className="card">
          <div className="toolbar">
            <h3>Gates</h3>
            <button className="link-button" onClick={addGate}>
              Add gate
            </button>
          </div>
          {config.gates.length === 0 && <p className="muted">No gates. Every entity reaches the score.</p>}
          {config.gates.map((gate) => (
            <div key={gate.id} className="inline-fields decision-gate">
              <select
                value={gate.column}
                onChange={(e) => set({ gates: config.gates.map((g) => (g.id === gate.id ? { ...g, column: e.target.value } : g)) })}
              >
                {profiles.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
              <select
                value={gate.op}
                onChange={(e) => set({ gates: config.gates.map((g) => (g.id === gate.id ? { ...g, op: e.target.value as typeof g.op } : g)) })}
              >
                <option value="is">is</option>
                <option value="isnot">is not</option>
                <option value="lt">&lt;</option>
                <option value="gt">&gt;</option>
                <option value="eq">=</option>
              </select>
              <input
                value={gate.value}
                onChange={(e) => set({ gates: config.gates.map((g) => (g.id === gate.id ? { ...g, value: e.target.value } : g)) })}
              />
              <select
                value={gate.outcome}
                onChange={(e) =>
                  set({ gates: config.gates.map((g) => (g.id === gate.id ? { ...g, outcome: e.target.value as GateOutcome } : g)) })
                }
              >
                {OUTCOMES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <button className="link-button" onClick={() => set({ gates: config.gates.filter((g) => g.id !== gate.id) })}>
                Remove
              </button>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Tier cut-points</h3>
          <select value={config.cut_mode} onChange={(e) => set({ cut_mode: e.target.value as CutMode })}>
            <option value="quantile">Quantiles</option>
            <option value="breaks">Natural breaks</option>
            <option value="absolute">Fixed</option>
          </select>
          <p className="help-text">
            {config.cut_mode === "quantile"
              ? "Bands sized by share of the field. Re-derived against whatever data is loaded."
              : config.cut_mode === "breaks"
                ? "Cuts at the widest gaps, with a minimum band width so one outlier cannot claim a tier."
                : "Your cut-points, pinned. These survive a re-run against a different snapshot, which is what a period-on-period comparison needs."}
          </p>
          {config.cut_mode === "absolute" && (
            <div className="inline-fields">
              {(config.pinned_cuts ?? cuts).map((cut, index) => (
                <input
                  key={index}
                  type="number"
                  value={cut}
                  onChange={(e) => {
                    const next = [...(config.pinned_cuts ?? cuts)];
                    next[index] = Number(e.target.value);
                    set({ pinned_cuts: next });
                  }}
                />
              ))}
              {(config.pinned_cuts ?? []).length === 0 && cuts.length > 0 && (
                <button className="link-button" onClick={() => set({ pinned_cuts: cuts })}>
                  Pin the current cut-points
                </button>
              )}
            </div>
          )}

          <h3>Dimension floor</h3>
          <label className="checkbox-label">
            <input type="checkbox" checked={config.veto.enabled} onChange={(e) => set({ veto: { ...config.veto, enabled: e.target.checked } })} />
            Demote one tier when any dimension scores below
            <input
              type="number"
              min={0}
              max={100}
              value={config.veto.min_score}
              onChange={(e) => set({ veto: { ...config.veto, min_score: Number(e.target.value) } })}
            />
          </label>
          <p className="help-text">
            Stops one strong dimension carrying an entity that fails elsewhere. Applied only to dimensions measured by{" "}
            {config.veto.min_criteria} or more criteria, so a single yes/no answer cannot demote on its own.
          </p>
        </div>
      </div>
    </div>
  );
}
