import { evenCuts } from "../lib/levels";
import type { LevelCriterion, LevelRule, MechanismConfig } from "../types";

/** A column as an expression can name it: its slug, as the rule engine exposes it. */
function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function nextId(prefix: string, taken: string[]): string {
  let n = taken.length + 1;
  while (taken.includes(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

interface Props {
  config: MechanismConfig;
  /** The table's columns, including calculated ones, so conditions can be written against them. */
  columns: string[];
  onChange: (next: MechanismConfig) => void;
}

/** The level grid: clusters, then criteria, each with ordered rules — the first that holds sets the level. */
export function LevelGridEditor({ config, columns, onChange }: Props) {
  const set = (patch: Partial<MechanismConfig>) => onChange({ ...config, ...patch });
  const criteria = config.level_criteria ?? [];
  const levelMin = config.level_min ?? 1;
  const levelMax = config.level_max ?? 7;
  const levels = Array.from({ length: levelMax - levelMin + 1 }, (_, i) => levelMax - i);

  const setCriterion = (id: string, patch: Partial<LevelCriterion>) =>
    set({ level_criteria: criteria.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
  const setRule = (criterion: LevelCriterion, index: number, patch: Partial<LevelRule>) =>
    setCriterion(criterion.id, { rules: criterion.rules.map((r, i) => (i === index ? { ...r, ...patch } : r)) });

  function addCriterion() {
    const id = nextId("crit", criteria.map((c) => c.id));
    set({
      level_criteria: [
        ...criteria,
        { id, name: `Criterion ${criteria.length + 1}`, dimension_id: config.dimensions[0]?.id ?? "", weight: 1, enabled: true, rules: [], otherwise: levelMin, otherwise_on_blank: false },
      ],
    });
  }

  function addCluster() {
    const id = nextId("c", config.dimensions.map((d) => d.id));
    set({ dimensions: [...config.dimensions, { id, name: `Cluster ${config.dimensions.length + 1}`, weight: 1, derived_from: [] }] });
  }

  function removeCluster(id: string) {
    const fallback = config.dimensions.find((d) => d.id !== id)?.id ?? "";
    set({
      dimensions: config.dimensions.filter((d) => d.id !== id),
      level_criteria: criteria.map((c) => (c.dimension_id === id ? { ...c, dimension_id: fallback } : c)),
    });
  }

  function setScale(min: number, max: number) {
    if (!(min < max)) return;
    set({ level_min: min, level_max: max, pinned_cuts: evenCuts(min, max, config.tiers.length) });
  }

  return (
    <div className="card">
      <h2>Level grid</h2>
      <p className="help-text">
        Each criterion gets a level on a fixed scale from the company&apos;s own data: its rules are tried top to bottom and the
        first that holds sets the level. A blank value never matches, so a company that does not disclose falls to the default.
        Cluster scores average their criteria&apos;s levels, and the total averages the clusters, both on the same scale — a
        company&apos;s score does not move when the other companies change.
      </p>

      <div className="inline-fields">
        <label className="field-label">
          Lowest level
          <input type="number" value={levelMin} onChange={(e) => setScale(Number(e.target.value), levelMax)} />
        </label>
        <label className="field-label">
          Highest level
          <input type="number" value={levelMax} onChange={(e) => setScale(levelMin, Number(e.target.value))} />
        </label>
        <label className="field-label">
          Tier boundaries (best first)
          <input
            value={(config.pinned_cuts ?? []).join(", ")}
            onChange={(e) =>
              set({
                cut_mode: "absolute",
                pinned_cuts: e.target.value
                  .split(",")
                  .map((v) => Number(v.trim()))
                  .filter((v) => !Number.isNaN(v)),
              })
            }
          />
        </label>
      </div>
      <p className="help-text">
        {config.tiers.length} tiers need {Math.max(0, config.tiers.length - 1)} boundaries. A total at or above the first
        boundary is {config.tiers[0]?.name ?? "Tier 1"}. Tier rules in the Decision tree tab can also read each criterion&apos;s
        level as <code>lvl_&lt;criterion&gt;</code>.
      </p>

      <h3>Clusters</h3>
      <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Cluster</th>
            <th>Weight</th>
            <th>Criteria</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {config.dimensions.map((d) => (
            <tr key={d.id}>
              <td>
                <input aria-label="Cluster name" value={d.name} onChange={(e) => set({ dimensions: config.dimensions.map((x) => (x.id === d.id ? { ...x, name: e.target.value } : x)) })} />
              </td>
              <td>
                <input
                  aria-label={`${d.name} weight`}
                  type="number"
                  min={0}
                  step={0.5}
                  value={d.weight}
                  onChange={(e) => set({ dimensions: config.dimensions.map((x) => (x.id === d.id ? { ...x, weight: Number(e.target.value) } : x)) })}
                />
              </td>
              <td className="muted">{criteria.filter((c) => c.dimension_id === d.id).length}</td>
              <td>
                {config.dimensions.length > 1 && (
                  <button className="link-button" onClick={() => removeCluster(d.id)}>
                    Remove
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <button className="link-button" onClick={addCluster}>
        Add cluster
      </button>

      <h3>Criteria</h3>
      <p className="help-text">
        Conditions are expressions over the table&apos;s columns, e.g. <code>target_coverage_pct &gt;= 65 and net_zero_target</code>.
        Columns: {columns.map((c) => slug(c)).filter(Boolean).join(", ")}
      </p>
      {criteria.map((criterion) => (
        <div key={criterion.id} className="activity-editor">
          <div className="inline-fields">
            <input aria-label="Criterion name" value={criterion.name} onChange={(e) => setCriterion(criterion.id, { name: e.target.value })} />
            <select aria-label={`${criterion.name} cluster`} value={criterion.dimension_id} onChange={(e) => setCriterion(criterion.id, { dimension_id: e.target.value })}>
              {config.dimensions.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <label>
              Weight{" "}
              <input
                aria-label={`${criterion.name} weight`}
                type="number"
                min={0}
                step={0.5}
                value={criterion.weight}
                onChange={(e) => setCriterion(criterion.id, { weight: Number(e.target.value) })}
              />
            </label>
            <label>
              <input type="checkbox" checked={criterion.enabled} onChange={(e) => setCriterion(criterion.id, { enabled: e.target.checked })} /> on
            </label>
            <button className="link-button" onClick={() => set({ level_criteria: criteria.filter((c) => c.id !== criterion.id) })}>
              Remove criterion
            </button>
          </div>
          <input
            aria-label={`${criterion.name} hint`}
            placeholder="What this criterion asks (shown to reviewers)"
            value={criterion.hint ?? ""}
            onChange={(e) => setCriterion(criterion.id, { hint: e.target.value })}
          />
          <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Level</th>
                <th>When</th>
                <th>Note</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {criterion.rules.map((rule, i) => (
                <tr key={i}>
                  <td>
                    <select aria-label="Level" value={rule.level} onChange={(e) => setRule(criterion, i, { level: Number(e.target.value) })}>
                      {levels.map((lv) => (
                        <option key={lv} value={lv}>
                          {lv}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input aria-label="Condition" className="level-condition" value={rule.when} onChange={(e) => setRule(criterion, i, { when: e.target.value })} />
                  </td>
                  <td>
                    <input aria-label="Note" value={rule.note ?? ""} onChange={(e) => setRule(criterion, i, { note: e.target.value })} />
                  </td>
                  <td>
                    <button className="link-button" onClick={() => setCriterion(criterion.id, { rules: criterion.rules.filter((_, j) => j !== i) })}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              <tr>
                <td>
                  <select
                    aria-label="Default level"
                    value={criterion.otherwise ?? ""}
                    onChange={(e) => setCriterion(criterion.id, { otherwise: e.target.value === "" ? null : Number(e.target.value) })}
                  >
                    <option value="">none</option>
                    {levels.map((lv) => (
                      <option key={lv} value={lv}>
                        {lv}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="muted" colSpan={3}>
                  Otherwise — when no rule holds. &ldquo;none&rdquo; leaves the criterion without a level, which counts against
                  coverage.{" "}
                  <label>
                    <input
                      type="checkbox"
                      checked={criterion.otherwise_on_blank ?? true}
                      disabled={criterion.otherwise == null}
                      onChange={(e) => setCriterion(criterion.id, { otherwise_on_blank: e.target.checked })}
                    />{" "}
                    Also when a value is blank
                  </label>
                </td>
              </tr>
            </tbody>
          </table>
          </div>
          <button
            className="link-button"
            onClick={() => setCriterion(criterion.id, { rules: [...criterion.rules, { level: criterion.rules.at(-1)?.level ? Math.max(levelMin, criterion.rules.at(-1)!.level - 1) : levelMax, when: "", note: "" }] })}
          >
            Add rule
          </button>
        </div>
      ))}
      <button onClick={addCriterion}>Add criterion</button>
    </div>
  );
}
