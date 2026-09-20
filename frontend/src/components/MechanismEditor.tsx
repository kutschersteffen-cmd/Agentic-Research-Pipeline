import type { ColumnProfile, MechanismConfig, MissingPolicy, NormMethod, WeightPreset } from "../types";

const NORMS: { value: NormMethod; label: string; note: string }[] = [
  { value: "percentile", label: "Percentile rank", note: "Unaffected by outliers and by the units each indicator is reported in. Measures position in the field, so it cannot show absolute improvement between two snapshots." },
  { value: "minmax", label: "Min–max", note: "Keeps the distance between values, so absolute improvement shows. Sensitive to the extremes, which winsorising trims." },
  { value: "zscore", label: "Z-score", note: "Scores by distance from the mean in standard deviations. Assumes a roughly symmetric spread." },
];

const MISSING: { value: MissingPolicy; label: string; note: string }[] = [
  { value: "renormalise", label: "Re-weight", note: "Nothing is invented: the criterion leaves this entity's weight base, and coverage records how much was left." },
  { value: "neutral", label: "Neutral 50", note: "Treats a gap as an average answer. Flatters a company that discloses nothing." },
  { value: "mean", label: "Peer mean", note: "Imputes the field's mean. Hides the gap rather than reporting it." },
  { value: "penalise", label: "Penalise", note: "Scores a gap at 25. Treats non-disclosure as a finding, which is a policy choice worth stating." },
];

const WEIGHTS: { value: WeightPreset; label: string; note: string }[] = [
  { value: "balanced", label: "Breadth-adjusted", note: "A dimension weighs the square root of how many criteria it holds — measured seven ways counts for more than once, but not seven times more." },
  { value: "equal", label: "Equal criteria", note: "Every criterion counts the same, so a theme measured seven ways counts seven times." },
  { value: "entropy", label: "Discriminating power", note: "Weights by how much a criterion separates the field. Data-driven, and it changes when the universe changes." },
  { value: "manual", label: "Manual", note: "Your weights, exactly as set below." },
];

export function MechanismEditor({
  config,
  profiles,
  weights,
  onChange,
}: {
  config: MechanismConfig;
  profiles: ColumnProfile[];
  weights: Record<string, number>;
  onChange: (next: MechanismConfig) => void;
}) {
  const set = (patch: Partial<MechanismConfig>) => onChange({ ...config, ...patch });
  const categorical = profiles.filter((p) => p.type === "categorical" || p.type === "text");

  const setCriterion = (column: string, patch: Partial<MechanismConfig["criteria"][number]>) =>
    set({ criteria: config.criteria.map((c) => (c.column === column ? { ...c, ...patch } : c)) });
  const setDimension = (id: string, patch: Partial<MechanismConfig["dimensions"][number]>) =>
    set({ dimensions: config.dimensions.map((d) => (d.id === id ? { ...d, ...patch } : d)) });

  const note = (options: { value: string; note: string }[], value: string) => options.find((o) => o.value === value)?.note;

  return (
    <div>
      <div className="decision-grid">
        <div className="card">
          <h3>Normalisation</h3>
          <select value={config.norm} onChange={(e) => set({ norm: e.target.value as NormMethod })}>
            {NORMS.map((n) => (
              <option key={n.value} value={n.value}>
                {n.label}
              </option>
            ))}
          </select>
          <p className="help-text">{note(NORMS, config.norm)}</p>
          <label className="field-label">
            Winsorise tails (%)
            <input type="number" min={0} max={20} value={config.winsor_pct} onChange={(e) => set({ winsor_pct: Number(e.target.value) })} />
          </label>
          <label className="field-label">
            Peer cohort — normalise within
            <select value={config.normalise_within ?? ""} onChange={(e) => set({ normalise_within: e.target.value || null })}>
              <option value="">(whole table)</option>
              {categorical.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <p className="help-text">
            An intensity percentile computed across utilities and software companies together is close to meaningless.
            Cohorts with fewer than {config.min_cohort_size} rows fall back to the whole table, because a rank over three
            peers is noise dressed as a score.
          </p>
        </div>

        <div className="card">
          <h3>Missing values</h3>
          <select value={config.missing} onChange={(e) => set({ missing: e.target.value as MissingPolicy })}>
            {MISSING.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          <p className="help-text">{note(MISSING, config.missing)}</p>
          <label className="field-label">
            Minimum weight covered (%)
            <input type="number" min={0} max={100} step={5} value={config.min_coverage_pct} onChange={(e) => set({ min_coverage_pct: Number(e.target.value) })} />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={config.require_grounded_coverage}
              onChange={(e) => set({ require_grounded_coverage: e.target.checked })}
            />
            Require grounded coverage
          </label>
          <p className="help-text">
            Keys the sufficiency gate off the share of weight backed by an independently verified value rather than
            merely a present one. Only has an effect where the table carries per-cell confidence — any table built from
            an extraction run does.
          </p>
        </div>

        <div className="card">
          <h3>Weighting</h3>
          <select value={config.weighting} onChange={(e) => set({ weighting: e.target.value as WeightPreset })}>
            {WEIGHTS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
          <p className="help-text">{note(WEIGHTS, config.weighting)}</p>
          <label className="field-label">
            Grouping threshold (rank correlation)
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={config.cluster_threshold}
              onChange={(e) => set({ cluster_threshold: Number(e.target.value) })}
            />
          </label>
          <p className="help-text">
            Re-derive to regroup. Two frameworks built at different thresholds are not directly comparable, and the audit
            log says so.
          </p>
        </div>
      </div>

      <div className="card">
        <h3>Dimensions &amp; criteria</h3>
        <p className="help-text">
          Weights are relative and normalised to 100% behind the scenes. Park a criterion at weight 0 to keep it visible
          without letting it count. The effective column is what each criterion actually contributes once its dimension's
          weight is shared out.
        </p>
        {config.dimensions.map((dimension) => {
          const members = config.criteria.filter((c) => c.dimension_id === dimension.id);
          return (
            <div key={dimension.id} className="decision-dimension">
              <div className="decision-dimension-head">
                <input value={dimension.name} onChange={(e) => setDimension(dimension.id, { name: e.target.value })} />
                <label className="field-label inline-block">
                  weight
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={dimension.weight}
                    onChange={(e) => setDimension(dimension.id, { weight: Number(e.target.value) })}
                  />
                </label>
                <span className="muted">
                  {members.length} {members.length === 1 ? "criterion" : "criteria"}
                </span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Criterion</th>
                    <th>On</th>
                    <th>Direction</th>
                    <th>Weight</th>
                    <th>Effective</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((criterion) => (
                    <tr key={criterion.column}>
                      <td>{criterion.column}</td>
                      <td>
                        <input
                          type="checkbox"
                          checked={criterion.enabled}
                          onChange={(e) => setCriterion(criterion.column, { enabled: e.target.checked })}
                          aria-label={`Include ${criterion.column}`}
                        />
                      </td>
                      <td>
                        <select
                          value={criterion.direction}
                          onChange={(e) => setCriterion(criterion.column, { direction: e.target.value as "higher" | "lower" })}
                        >
                          <option value="higher">higher is better</option>
                          <option value="lower">lower is better</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          min={0}
                          step={0.1}
                          value={criterion.weight}
                          onChange={(e) => setCriterion(criterion.column, { weight: Number(e.target.value) })}
                        />
                      </td>
                      <td>{weights[criterion.column] != null ? `${(weights[criterion.column] * 100).toFixed(1)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </div>
  );
}
