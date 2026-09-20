import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  ConstraintSolver,
  ConstructionSpec,
  IndexCalibration,
  IndexCatalogue,
  IndexReviewResult,
  ScreenRule,
  SelectionRule,
  TiltRule,
} from "../types";

/**
 * Compose an index methodology out of named rules, save it as a versioned
 * calibration, and run a review from it.
 *
 * The rule pickers are driven by `GET /api/index/catalogue`, so a rule type
 * added on the backend shows up here without a frontend change. See
 * `docs/INDEX_METHODOLOGY_LANDSCAPE.md` for where each rule type comes from
 * and `docs/EQUITY_INDEX_CONSTRUCTION_PLAN.md` for the wider design.
 */

const SUB_TABS = [
  { id: "compose", label: "Compose" },
  { id: "calibrations", label: "Calibrations" },
  { id: "result", label: "Result" },
] as const;

const EMPTY_SPEC: ConstructionSpec = {
  index_currency: "EUR",
  screens: [],
  selection: { type: "select_all" },
  base_weighting: { scheme: "free_float_mcap" },
  tilts: [],
  constraints: {
    group_caps: [],
    ucits_5_10_40: false,
    single_name_cap: null,
    min_weight: null,
    solver: {
      method: "waterfall",
      solver: "CLARABEL",
      verify_tolerance: 1e-7,
      fallback_to_waterfall: true,
      tracking_error_budget: null,
      score_field: null,
      min_risk_coverage: 0.98,
      risk_model: { source: "ledoit_wolf", lookback_periods: 260, min_observations: 60, periods_per_year: 252, factor_fields: [] },
      enforce_semicontinuous: false,
      mip_solver: "SCIP",
      mip_gap: 0,
      mip_time_limit_seconds: 120,
      tie_break_epsilon: 1e-8,
    },
    max_constituents: null,
    min_constituents: null,
  },
  trajectory: {
    enabled: false,
    metric_field: "ghg_intensity",
    annual_reduction_rate: 0.07,
    universe_reduction_pct: null,
    base_date: null,
    compensate_missed_targets: true,
  },
  calendar: { review_frequency: "quarterly", selection_lag_days: 5, base_level: 100 },
  rounding: { weight_decimals: 10, shares_decimals: 6, level_decimals: 6 },
};

function pct(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "--" : `${(value * 100).toFixed(digits)}%`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "--";
  // A small-but-nonzero metric (a residual coal revenue share, say) must not
  // render as a flat "0" next to a relative change of -100%: that reads as a
  // bug in the engine when it is only a formatting choice.
  if (value !== 0 && Math.abs(value) < 10 ** -digits) return value.toPrecision(3);
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** A number input that keeps an empty box empty instead of coercing to 0. */
function NumberField({
  label,
  value,
  onChange,
  step = "any",
  placeholder,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (next: number | null) => void;
  step?: string;
  placeholder?: string;
}) {
  return (
    <label className="field-label" style={{ flex: 1 }}>
      {label}
      <input
        type="number"
        step={step}
        placeholder={placeholder}
        value={value === null || value === undefined ? "" : value}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
  allowEmpty,
}: {
  label: string;
  value: string | undefined;
  options: string[];
  onChange: (next: string) => void;
  allowEmpty?: boolean;
}) {
  return (
    <label className="field-label" style={{ flex: 1 }}>
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {allowEmpty && <option value="">--</option>}
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function RuleShell({
  title,
  enabled,
  onToggle,
  onRemove,
  onMoveUp,
  onMoveDown,
  label,
  onLabel,
  children,
}: {
  title: string;
  enabled: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  label: string;
  onLabel: (next: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="activity-editor" style={enabled ? undefined : { opacity: 0.55 }}>
      <div className="toolbar" style={{ marginTop: 0 }}>
        <strong style={{ flex: 1 }}>{title}</strong>
        <label className="checkbox-label" style={{ margin: 0 }}>
          <input type="checkbox" checked={enabled} onChange={onToggle} /> on
        </label>
        <button className="link-button" onClick={onMoveUp} disabled={!onMoveUp} title="Move earlier">
          ↑
        </button>
        <button className="link-button" onClick={onMoveDown} disabled={!onMoveDown} title="Move later">
          ↓
        </button>
        <button className="link-button" onClick={onRemove} title="Remove rule">
          remove
        </button>
      </div>
      <label className="field-label">
        Label (shown on the committee pack)
        <input type="text" value={label} onChange={(e) => onLabel(e.target.value)} placeholder="optional" />
      </label>
      {children}
    </div>
  );
}

export function IndexBuilder() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("compose");
  const [catalogue, setCatalogue] = useState<IndexCatalogue | null>(null);
  const [spec, setSpec] = useState<ConstructionSpec>(EMPTY_SPEC);
  const [calibrations, setCalibrations] = useState<IndexCalibration[]>([]);
  const [loaded, setLoaded] = useState<IndexCalibration | null>(null);
  const [result, setResult] = useState<IndexReviewResult | null>(null);
  const [indexId, setIndexId] = useState("demo_index");
  const [reviewDate, setReviewDate] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const fields = catalogue?.fields ?? { metrics: [], flags: [], categories: [] };

  useEffect(() => {
    api.getIndexCatalogue().then(setCatalogue).catch((e) => setError(String(e)));
    refreshCalibrations();
  }, []);

  async function refreshCalibrations() {
    try {
      setCalibrations(await api.listIndexCalibrations());
    } catch {
      setCalibrations([]);
    }
  }

  async function loadPreset(name: string) {
    setError(null);
    try {
      const preset = await api.getIndexPreset(name);
      setSpec(preset);
      setLoaded(null);
      setStatus(`Loaded the "${name}" preset -- every rule below is editable.`);
    } catch (e) {
      setError(String(e));
    }
  }

  async function addBundle(name: string) {
    setError(null);
    try {
      const bundle = await api.getIndexScreenBundle(name);
      setSpec({ ...spec, screens: [...spec.screens, ...bundle.screens] });
      setStatus(`Added ${bundle.screens.length} screens from "${name}". They are ordinary rules -- edit or delete any of them.`);
    } catch (e) {
      setError(String(e));
    }
  }

  async function runReview(persist: boolean) {
    if (spec.constraints.solver?.method === "max_score" && !spec.constraints.solver.score_field) {
      setError("Choose the field to maximise under 5 · Constraints before running a max_score methodology.");
      setSub("compose");
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const review = await api.runIndexReview({
        index_id: indexId,
        review_date: reviewDate,
        spec,
        persist,
        use_prior_state: true,
      });
      setResult(review);
      setSub("result");
      setStatus(persist ? `Review saved for ${indexId} @ ${reviewDate}.` : "Preview only -- nothing was written.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>Index Construction</h2>
      <p className="help-text">
        Compose screens, a selection rule, weighting, tilts, constraints and the path-dependent decarbonisation layer into
        one methodology, save it as a versioned calibration, and run a review. Everything here is deterministic and
        zero-LLM. See <code>docs/INDEX_METHODOLOGY_LANDSCAPE.md</code> for where each rule type comes from.
      </p>

      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {error && <p className="error-text">{error}</p>}
      {status && <p className="status-text">{status}</p>}

      {sub === "compose" && (
        <>
          <div className="card">
            <h3>Start from a preset</h3>
            <p className="help-text">
              A preset expands into the ordinary rules below -- nothing is hidden, and every rule stays editable.
            </p>
            <div className="toolbar" style={{ flexWrap: "wrap" }}>
              {(catalogue?.presets ?? []).map((p) => (
                <button key={p.name} className="nav-tab" title={p.description} onClick={() => loadPreset(p.name)}>
                  {p.label}
                </button>
              ))}
              <button className="nav-tab" onClick={() => { setSpec(EMPTY_SPEC); setLoaded(null); setStatus("Started from an empty methodology."); }}>
                Empty
              </button>
            </div>
          </div>

          <ScreensCard spec={spec} setSpec={setSpec} catalogue={catalogue} fields={fields} onAddBundle={addBundle} />
          <SelectionCard spec={spec} setSpec={setSpec} fields={fields} />
          <WeightingCard spec={spec} setSpec={setSpec} fields={fields} />
          <TiltsCard spec={spec} setSpec={setSpec} fields={fields} />
          <ConstraintsCard spec={spec} setSpec={setSpec} fields={fields} optimizerAvailable={catalogue?.constraint_solver?.available ?? null} integerAvailable={catalogue?.constraint_solver?.integer_available ?? null} />
          <TrajectoryCard spec={spec} setSpec={setSpec} fields={fields} />

          <div className="card">
            <h3>Run a review</h3>
            <div className="inline-fields">
              <label className="field-label" style={{ flex: 1 }}>
                Index id
                <input type="text" value={indexId} onChange={(e) => setIndexId(e.target.value)} />
              </label>
              <label className="field-label" style={{ flex: 1 }}>
                Review date
                <input type="date" value={reviewDate} onChange={(e) => setReviewDate(e.target.value)} />
              </label>
            </div>
            <p className="help-text">
              A saved review chains state into the next one: the decarbonisation base, the shortfall carried forward, and
              the incumbents a selection buffer needs. A preview writes nothing.
            </p>
            <div className="toolbar">
              <button onClick={() => runReview(false)} disabled={busy}>
                {busy ? "Running..." : "Preview"}
              </button>
              <button onClick={() => runReview(true)} disabled={busy} className="nav-tab">
                Run &amp; save
              </button>
            </div>
          </div>
        </>
      )}

      {sub === "calibrations" && (
        <CalibrationsTab
          spec={spec}
          setSpec={setSpec}
          calibrations={calibrations}
          loaded={loaded}
          setLoaded={setLoaded}
          refresh={refreshCalibrations}
          setError={setError}
          setStatus={setStatus}
        />
      )}

      {sub === "result" && <ResultTab result={result} indexId={indexId} />}
    </div>
  );
}

// ------------------------------------------------------------- screens

function ScreensCard({
  spec,
  setSpec,
  catalogue,
  fields,
  onAddBundle,
}: {
  spec: ConstructionSpec;
  setSpec: (s: ConstructionSpec) => void;
  catalogue: IndexCatalogue | null;
  fields: IndexCatalogue["fields"];
  onAddBundle: (name: string) => void;
}) {
  function update(i: number, patch: Partial<ScreenRule>) {
    const screens = spec.screens.map((s, idx) => (idx === i ? ({ ...s, ...patch } as ScreenRule) : s));
    setSpec({ ...spec, screens });
  }
  function move(i: number, delta: number) {
    const screens = [...spec.screens];
    const [item] = screens.splice(i, 1);
    screens.splice(i + delta, 0, item);
    setSpec({ ...spec, screens });
  }
  function add(type: ScreenRule["type"]) {
    const base = { enabled: true, label: "" };
    const rule: ScreenRule =
      type === "metric_threshold"
        ? { ...base, type, field: fields.metrics[0] ?? "float_mcap", min_value: null, max_value: null, missing: "block" }
        : type === "flag_exclusion"
          ? { ...base, type, field: fields.flags[0] ?? "norms_violation", exclude_when: true, missing: "block" }
          : { ...base, type, field: fields.categories[0] ?? "sector", allow: [], deny: [], missing: "block" };
    setSpec({ ...spec, screens: [...spec.screens, rule] });
  }

  return (
    <div className="card">
      <h3>1 · Screens</h3>
      <p className="help-text">
        Applied in order. Order is part of the methodology: screens do not commute once a later one is rank-based, and the
        funnel a committee reviews depends on the order they ran in.
      </p>
      <div className="toolbar" style={{ flexWrap: "wrap" }}>
        {(catalogue?.screens ?? []).map((s) => (
          <button key={s.type} className="nav-tab" title={s.help} onClick={() => add(s.type as ScreenRule["type"])}>
            + {s.label}
          </button>
        ))}
        {(catalogue?.screen_bundles ?? []).map((b) => (
          <button key={b.name} className="nav-tab" title={b.description} onClick={() => onAddBundle(b.name)}>
            + {b.label}
          </button>
        ))}
      </div>

      {spec.screens.length === 0 && <p className="muted">No screens. Every company in the parent universe is eligible.</p>}

      {spec.screens.map((screen, i) => (
        <RuleShell
          key={screen.rule_id ?? i}
          title={screen.type}
          enabled={screen.enabled !== false}
          onToggle={() => update(i, { enabled: screen.enabled === false } as Partial<ScreenRule>)}
          onRemove={() => setSpec({ ...spec, screens: spec.screens.filter((_, idx) => idx !== i) })}
          onMoveUp={i > 0 ? () => move(i, -1) : undefined}
          onMoveDown={i < spec.screens.length - 1 ? () => move(i, 1) : undefined}
          label={screen.label ?? ""}
          onLabel={(label) => update(i, { label } as Partial<ScreenRule>)}
        >
          <div className="inline-fields">
            <SelectField
              label="Field"
              value={screen.field}
              options={
                screen.type === "metric_threshold" ? fields.metrics : screen.type === "flag_exclusion" ? fields.flags : fields.categories
              }
              onChange={(field) => update(i, { field } as Partial<ScreenRule>)}
            />
            <SelectField
              label="If the value is missing"
              value={screen.missing ?? "block"}
              options={["block", "fail", "pass"]}
              onChange={(missing) => update(i, { missing } as Partial<ScreenRule>)}
            />
          </div>
          {screen.type === "metric_threshold" && (
            <div className="inline-fields">
              <NumberField label="Minimum" value={screen.min_value} onChange={(min_value) => update(i, { min_value } as Partial<ScreenRule>)} />
              <NumberField label="Maximum" value={screen.max_value} onChange={(max_value) => update(i, { max_value } as Partial<ScreenRule>)} />
            </div>
          )}
          {screen.type === "flag_exclusion" && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={screen.exclude_when !== false}
                onChange={(e) => update(i, { exclude_when: e.target.checked } as Partial<ScreenRule>)}
              />
              Exclude when the flag is true
            </label>
          )}
          {screen.type === "category_screen" && (
            <div className="inline-fields">
              <label className="field-label" style={{ flex: 1 }}>
                Allow only (comma separated)
                <input
                  type="text"
                  value={(screen.allow ?? []).join(", ")}
                  onChange={(e) => update(i, { allow: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) } as Partial<ScreenRule>)}
                />
              </label>
              <label className="field-label" style={{ flex: 1 }}>
                Deny (comma separated)
                <input
                  type="text"
                  value={(screen.deny ?? []).join(", ")}
                  onChange={(e) => update(i, { deny: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) } as Partial<ScreenRule>)}
                />
              </label>
            </div>
          )}
          <p className="muted">
            {screen.missing === "block"
              ? "A missing value stops the run rather than defaulting silently."
              : `A missing value is treated as "${screen.missing}" -- a deliberate override that appears in the calibration diff.`}
          </p>
        </RuleShell>
      ))}
    </div>
  );
}

// ----------------------------------------------------------- selection

function SelectionCard({
  spec,
  setSpec,
  fields,
}: {
  spec: ConstructionSpec;
  setSpec: (s: ConstructionSpec) => void;
  fields: IndexCatalogue["fields"];
}) {
  const selection = spec.selection;
  function update(patch: Record<string, unknown>) {
    setSpec({ ...spec, selection: { ...selection, ...patch } as SelectionRule });
  }
  function setType(type: SelectionRule["type"]) {
    const scoreField = fields.metrics[0] ?? "esg_score";
    const next: SelectionRule =
      type === "select_all"
        ? { type }
        : type === "best_in_class_coverage"
          ? { type, score_field: scoreField, group_by: "sector", target_pct: 0.5, basis: "float_mcap", buffer_pct: 0, higher_is_better: true }
          : type === "absolute_threshold"
            ? { type, score_field: scoreField, threshold: 5, group_by: "sector", on_empty_group: "leave_empty", fallback_target_pct: 0.25 }
            : { type, score_field: scoreField, n: 50, group_by: "none" };
    setSpec({ ...spec, selection: next });
  }

  return (
    <div className="card">
      <h3>2 · Selection</h3>
      <p className="help-text">
        Who is in the index. One rule covers the published variants: a coverage target by market cap or by count, an
        absolute bar, or a fixed-size list.
      </p>
      <SelectField
        label="Rule"
        value={selection.type}
        options={["select_all", "best_in_class_coverage", "absolute_threshold", "top_n"]}
        onChange={(t) => setType(t as SelectionRule["type"])}
      />

      {selection.type !== "select_all" && (
        <>
          <div className="inline-fields">
            <SelectField label="Score field" value={selection.score_field} options={fields.metrics} onChange={(v) => update({ score_field: v })} />
            <SelectField
              label="Group by"
              value={selection.group_by ?? "sector"}
              options={["none", ...fields.categories]}
              onChange={(v) => update({ group_by: v })}
            />
          </div>
          <label className="checkbox-label">
            <input type="checkbox" checked={selection.higher_is_better !== false} onChange={(e) => update({ higher_is_better: e.target.checked })} />
            A higher score is better
          </label>
        </>
      )}

      {selection.type === "best_in_class_coverage" && (
        <>
          <div className="inline-fields">
            <NumberField label="Coverage target (0-1)" value={selection.target_pct} onChange={(v) => update({ target_pct: v })} step="0.01" />
            <SelectField label="Measured by" value={selection.basis ?? "float_mcap"} options={["float_mcap", "count"]} onChange={(v) => update({ basis: v })} />
            <NumberField label="Buffer (0-1)" value={selection.buffer_pct} onChange={(v) => update({ buffer_pct: v })} step="0.01" />
          </div>
          <p className="muted">
            The buffer is one-sided hysteresis: an incumbent just past the target stays in, a newcomer does not get in on
            it. This is what stops the index churning when a name drifts a rank or two.
          </p>
        </>
      )}

      {selection.type === "absolute_threshold" && (
        <>
          <div className="inline-fields">
            <NumberField label="Threshold" value={selection.threshold} onChange={(v) => update({ threshold: v ?? 0 })} />
            <SelectField
              label="If a group is empty"
              value={selection.on_empty_group ?? "leave_empty"}
              options={["leave_empty", "fallback_relative", "block"]}
              onChange={(v) => update({ on_empty_group: v })}
            />
            <NumberField label="Fallback coverage" value={selection.fallback_target_pct} onChange={(v) => update({ fallback_target_pct: v })} step="0.01" />
          </div>
          <p className="muted">
            An absolute bar can leave a whole sector empty where a relative rank never can, so the fallback is declared up
            front rather than discovered in production.
          </p>
        </>
      )}

      {selection.type === "top_n" && <NumberField label="N per group" value={selection.n} onChange={(v) => update({ n: v ?? 1 })} step="1" />}
    </div>
  );
}

// ----------------------------------------------------------- weighting

function WeightingCard({ spec, setSpec, fields }: { spec: ConstructionSpec; setSpec: (s: ConstructionSpec) => void; fields: IndexCatalogue["fields"] }) {
  const needsField = spec.base_weighting.scheme === "metric" || spec.base_weighting.scheme === "inverse_metric";
  return (
    <div className="card">
      <h3>3 · Base weighting</h3>
      <div className="inline-fields">
        <SelectField
          label="Scheme"
          value={spec.base_weighting.scheme}
          options={["free_float_mcap", "equal", "metric", "inverse_metric"]}
          onChange={(scheme) => setSpec({ ...spec, base_weighting: { ...spec.base_weighting, scheme: scheme as never } })}
        />
        {needsField && (
          <SelectField
            label="Field"
            value={spec.base_weighting.field ?? fields.metrics[0]}
            options={fields.metrics}
            onChange={(field) => setSpec({ ...spec, base_weighting: { ...spec.base_weighting, field } })}
          />
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------- tilts

function TiltsCard({ spec, setSpec, fields }: { spec: ConstructionSpec; setSpec: (s: ConstructionSpec) => void; fields: IndexCatalogue["fields"] }) {
  function update(i: number, patch: Record<string, unknown>) {
    setSpec({ ...spec, tilts: spec.tilts.map((t, idx) => (idx === i ? ({ ...t, ...patch } as TiltRule) : t)) });
  }
  function move(i: number, delta: number) {
    const tilts = [...spec.tilts];
    const [item] = tilts.splice(i, 1);
    tilts.splice(i + delta, 0, item);
    setSpec({ ...spec, tilts });
  }
  function add(type: TiltRule["type"]) {
    const rule: TiltRule =
      type === "metric_tilt"
        ? { type, enabled: true, label: "", field: fields.metrics[0] ?? "esg_score", normalisation: "max", group_by: "none", floor: 0.5, ceiling: 1.5, higher_is_better: true }
        : { type, enabled: true, label: "", field: fields.categories[0] ?? "sector", multipliers: {}, default_multiplier: 1 };
    setSpec({ ...spec, tilts: [...spec.tilts, rule] });
  }

  return (
    <div className="card">
      <h3>4 · Tilts</h3>
      <p className="help-text">
        Applied in order, multiplicatively, onto the base weight. Floor and ceiling are mandatory: an unbounded tilt
        silently becomes an exclusion, which is a methodology change nobody approved.
      </p>
      <div className="toolbar">
        <button className="nav-tab" onClick={() => add("metric_tilt")}>
          + Metric tilt
        </button>
        <button className="nav-tab" onClick={() => add("bucket_tilt")}>
          + Category multiplier table
        </button>
      </div>

      {spec.tilts.length === 0 && <p className="muted">No tilts. Constituents keep their base weight.</p>}

      {spec.tilts.map((tilt, i) => (
        <RuleShell
          key={tilt.rule_id ?? i}
          title={tilt.type}
          enabled={tilt.enabled !== false}
          onToggle={() => update(i, { enabled: tilt.enabled === false })}
          onRemove={() => setSpec({ ...spec, tilts: spec.tilts.filter((_, idx) => idx !== i) })}
          onMoveUp={i > 0 ? () => move(i, -1) : undefined}
          onMoveDown={i < spec.tilts.length - 1 ? () => move(i, 1) : undefined}
          label={tilt.label ?? ""}
          onLabel={(label) => update(i, { label })}
        >
          {tilt.type === "metric_tilt" ? (
            <>
              <div className="inline-fields">
                <SelectField label="Field" value={tilt.field} options={fields.metrics} onChange={(field) => update(i, { field })} />
                <SelectField
                  label="Normalisation"
                  value={tilt.normalisation ?? "max"}
                  options={["none", "max", "group_max", "rank_percentile", "zscore"]}
                  onChange={(normalisation) => update(i, { normalisation })}
                />
                {tilt.normalisation === "group_max" && (
                  <SelectField label="Within" value={tilt.group_by ?? "sector"} options={fields.categories} onChange={(group_by) => update(i, { group_by })} />
                )}
              </div>
              <div className="inline-fields">
                <NumberField label="Floor multiplier" value={tilt.floor} onChange={(floor) => update(i, { floor })} step="0.05" />
                <NumberField label="Ceiling multiplier" value={tilt.ceiling} onChange={(ceiling) => update(i, { ceiling })} step="0.05" />
              </div>
              <label className="checkbox-label">
                <input type="checkbox" checked={tilt.higher_is_better !== false} onChange={(e) => update(i, { higher_is_better: e.target.checked })} />
                A higher value earns a higher weight
              </label>
            </>
          ) : (
            <>
              <SelectField label="Category field" value={tilt.field} options={fields.categories} onChange={(field) => update(i, { field })} />
              <label className="field-label">
                Multipliers, one &quot;value = factor&quot; per line
                <textarea
                  rows={4}
                  value={Object.entries(tilt.multipliers ?? {}).map(([k, v]) => `${k} = ${v}`).join("\n")}
                  onChange={(e) => {
                    const multipliers: Record<string, number> = {};
                    for (const line of e.target.value.split("\n")) {
                      const [key, value] = line.split("=");
                      const factor = Number((value ?? "").trim());
                      if (key?.trim() && Number.isFinite(factor) && factor > 0) multipliers[key.trim()] = factor;
                    }
                    update(i, { multipliers });
                  }}
                />
              </label>
              <NumberField label="Default multiplier" value={tilt.default_multiplier} onChange={(v) => update(i, { default_multiplier: v ?? 1 })} step="0.05" />
            </>
          )}
        </RuleShell>
      ))}
    </div>
  );
}

// --------------------------------------------------------- constraints

function ConstraintsCard({
  spec,
  setSpec,
  fields,
  optimizerAvailable,
  integerAvailable,
}: {
  spec: ConstructionSpec;
  setSpec: (s: ConstructionSpec) => void;
  fields: IndexCatalogue["fields"];
  optimizerAvailable: boolean | null;
  integerAvailable: boolean | null;
}) {
  const c = spec.constraints;
  const solver = c.solver ?? EMPTY_SPEC.constraints.solver;
  const needsRiskModel = solver.method === "min_tracking_error" || solver.method === "max_score" || solver.tracking_error_budget != null;
  const usesIntegers = Boolean(c.max_constituents || c.min_constituents || (solver.enforce_semicontinuous && c.min_weight));
  function update(patch: Partial<ConstructionSpec["constraints"]>) {
    setSpec({ ...spec, constraints: { ...c, ...patch } });
  }
  function setSolver(patch: Partial<ConstraintSolver>) {
    setSpec({ ...spec, constraints: { ...c, solver: { ...solver, ...patch } } });
  }
  return (
    <div className="card">
      <h3>5 · Constraints</h3>
      <p className="help-text">
        Applied by a deterministic waterfall, not a solver: pin every breach at its cap, redistribute pro-rata, repeat
        until no name breaches and the weights sum to one.
      </p>
      <div className="inline-fields">
        <NumberField label="Single-name cap (0-1)" value={c.single_name_cap} onChange={(single_name_cap) => update({ single_name_cap })} step="0.01" placeholder="none" />
        <NumberField label="Minimum weight (0-1)" value={c.min_weight} onChange={(min_weight) => update({ min_weight })} step="0.001" placeholder="none" />
      </div>
      {c.min_weight ? (
        <>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={solver.enforce_semicontinuous}
              onChange={(e) => setSolver({ enforce_semicontinuous: e.target.checked })}
            />
            Enforce the floor properly — hold at or above it, or not at all
          </label>
          <p className="muted">
            {solver.enforce_semicontinuous
              ? "The real constraint. Small names are lifted to the floor rather than dropped, which needs integer variables and gives a materially different index."
              : "Currently a prune-and-redistribute heuristic: names below the floor are dropped. That answers a different question from the one the floor asks."}
          </p>
        </>
      ) : null}
      <div className="inline-fields">
        <NumberField label="Max constituents" value={c.max_constituents} onChange={(max_constituents) => update({ max_constituents })} step="1" placeholder="none" />
        <NumberField label="Min constituents" value={c.min_constituents} onChange={(min_constituents) => update({ min_constituents })} step="1" placeholder="none" />
      </div>
      {(c.max_constituents || c.min_constituents) && (
        <p className="muted">
          A ceiling is not a target: a linear objective concentrates into the fewest names the caps allow. Pin both
          bounds to the same number for a fixed-size index.
        </p>
      )}
      <label className="checkbox-label">
        <input type="checkbox" checked={c.ucits_5_10_40} onChange={(e) => update({ ucits_5_10_40: e.target.checked })} />
        UCITS 5/10/40 — no issuer above 10%, and issuers above 5% summing to at most 40%
      </label>

      <label className="field-label">Group caps</label>
      {c.group_caps.map((cap, i) => (
        <div className="inline-fields" key={i}>
          <SelectField
            label="Dimension"
            value={cap.dimension}
            options={fields.categories}
            onChange={(dimension) => update({ group_caps: c.group_caps.map((g, idx) => (idx === i ? { ...g, dimension } : g)) })}
          />
          <NumberField
            label="Max weight"
            value={cap.max_weight}
            step="0.01"
            onChange={(max_weight) => update({ group_caps: c.group_caps.map((g, idx) => (idx === i ? { ...g, max_weight: max_weight ?? 0.4 } : g)) })}
          />
          <button className="link-button" onClick={() => update({ group_caps: c.group_caps.filter((_, idx) => idx !== i) })}>
            remove
          </button>
        </div>
      ))}
      <button className="nav-tab" onClick={() => update({ group_caps: [...c.group_caps, { dimension: fields.categories[0] ?? "sector", max_weight: 0.4 }] })}>
        + Group cap
      </button>

      {usesIntegers && solver.method === "waterfall" && (
        <p className="error-text">
          Cardinality limits and an enforced floor need integer variables, which the waterfall cannot express. Pick a
          solver-backed objective below, or drop the constraint.
        </p>
      )}
      <h4>How the constraints are satisfied</h4>
      <p className="help-text">
        The <strong>waterfall</strong> needs nothing installed and is byte-identical everywhere, but applies the
        constraints in sequence. The <strong>least-squares projection</strong> solves them simultaneously and returns the
        closest feasible portfolio to what the rules asked for — and takes the decarbonisation target in the same solve,
        so no tilt search is needed. Whichever is chosen, every constraint is re-checked here afterwards; a solver&apos;s
        own &quot;optimal&quot; status is never taken as proof.
      </p>
      <div className="inline-fields">
        <SelectField
          label="Objective"
          value={solver.method}
          options={["waterfall", "least_squares", "min_tracking_error", "max_score"]}
          onChange={(value) => {
            // Fill the fields the chosen objective requires. A picker that
            // shows a default it never writes into the spec produces a
            // request the server rejects, with nothing on screen explaining
            // why -- so the defaults are committed here, not just displayed.
            const method = value as ConstraintSolver["method"];
            const patch: Partial<ConstraintSolver> = { method };
            if (method === "max_score" && solver.tracking_error_budget == null) {
              // A budget is required and 2% is a visible, editable starting
              // point. The score field is deliberately *not* defaulted:
              // whichever metric happens to sort first is not a methodology,
              // and silently maximising it would be obeyed exactly.
              patch.tracking_error_budget = 0.02;
            }
            setSolver(patch);
          }}
        />
        {solver.method !== "waterfall" && (
          <SelectField
            label="Solver (pinned)"
            value={solver.solver}
            options={["CLARABEL", "OSQP", "SCS"]}
            onChange={(name) => setSolver({ solver: name as ConstraintSolver["solver"] })}
          />
        )}
      </div>
      {solver.method !== "waterfall" && (
        <>
          {optimizerAvailable === false && (
            <p className="error-text">
              cvxpy is not installed on the server, so this calibration will fall back to the waterfall and record why.
              Install it with <code>pip install -e &quot;.[optimize]&quot;</code>.
            </p>
          )}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={solver.fallback_to_waterfall}
              onChange={(e) => setSolver({ fallback_to_waterfall: e.target.checked })}
            />
            Fall back to the waterfall if the solve fails or fails verification
          </label>
          <p className="muted">
            A solver swap can move the last digits, so it is stored with the calibration and changes its config hash —
            the same treatment any other methodology parameter gets.
          </p>

          {usesIntegers && (
            <>
              <h4>
                Mixed-integer solve <span className="badge badge-neutral">cardinality / floor</span>
              </h4>
              <p className="help-text">
                Cardinality limits and an enforced minimum weight are disjunctions, not bounds, so they need a binary per
                name. Reproducibility is weaker here than anywhere else in the engine: branch-and-bound has no
                unique-optimum guarantee, so the result is pinned by requiring a proven optimum, a zero gap, and a
                tie-break on a fixed name ordering. A solve that hits the time limit is recorded as a failure rather than
                published — otherwise a slower machine would produce a different index.
              </p>
              {integerAvailable === false && (
                <p className="error-text">
                  No mixed-integer backend is installed on the server, so this calibration will fall back to the
                  deterministic waterfall. Install one with <code>pip install pyscipopt</code>.
                </p>
              )}
              <div className="inline-fields">
                <SelectField
                  label="MIP solver (pinned)"
                  value={solver.mip_solver}
                  options={["SCIP", "HIGHS", "GUROBI", "MOSEK", "CPLEX"]}
                  onChange={(name) => setSolver({ mip_solver: name as ConstraintSolver["mip_solver"] })}
                />
                <NumberField label="Optimality gap" value={solver.mip_gap} step="0.0001" onChange={(v) => setSolver({ mip_gap: v ?? 0 })} />
                <NumberField
                  label="Time limit (s)"
                  value={solver.mip_time_limit_seconds}
                  step="10"
                  onChange={(v) => setSolver({ mip_time_limit_seconds: v })}
                />
              </div>
              <p className="muted">
                Leave the gap at 0. Any positive value lets the solver return whichever incumbent it found inside it, and
                which one that is varies by solver version and machine.
              </p>
            </>
          )}

          <h4>Tracking error</h4>
          <p className="help-text">
            An ex-ante budget turns tracking error from something you measure afterwards into something you constrain.
            It needs a risk model. Note that the least-squares projection minimises distance in <em>weight</em> space,
            which is not the same as distance in <em>risk</em> space — only <code>min_tracking_error</code> minimises the
            latter. Where a budget and a decarbonisation target cannot both hold, the budget binds and the shortfall is
            carried forward.
          </p>
          <div className="inline-fields">
            <NumberField
              label="Annualised TE budget (0-1)"
              value={solver.tracking_error_budget}
              step="0.0025"
              placeholder="none"
              onChange={(tracking_error_budget) => setSolver({ tracking_error_budget })}
            />
            {solver.method === "max_score" && (
              <SelectField
                label="Score to maximise"
                value={solver.score_field ?? ""}
                options={fields.metrics}
                allowEmpty
                onChange={(score_field) => setSolver({ score_field: score_field || null })}
              />
            )}
          </div>
          {needsRiskModel && (
            <>
              <div className="inline-fields">
                <SelectField
                  label="Risk model"
                  value={solver.risk_model.source}
                  options={["ledoit_wolf", "sample", "factor", "supplied"]}
                  onChange={(source) =>
                    setSolver({ risk_model: { ...solver.risk_model, source: source as ConstraintSolver["risk_model"]["source"] } })
                  }
                />
                <NumberField
                  label="Lookback periods"
                  value={solver.risk_model.lookback_periods}
                  step="10"
                  onChange={(v) => setSolver({ risk_model: { ...solver.risk_model, lookback_periods: v ?? 260 } })}
                />
                <NumberField
                  label="Periods per year"
                  value={solver.risk_model.periods_per_year}
                  step="1"
                  onChange={(v) => setSolver({ risk_model: { ...solver.risk_model, periods_per_year: v ?? 252 } })}
                />
              </div>
              {solver.risk_model.source === "factor" && (
                <label className="field-label">
                  Factor fields (comma separated) — numeric fields are standardised, categorical ones become dummies
                  <input
                    type="text"
                    value={solver.risk_model.factor_fields.join(", ")}
                    onChange={(e) =>
                      setSolver({
                        risk_model: {
                          ...solver.risk_model,
                          factor_fields: e.target.value.split(",").map((v) => v.trim()).filter(Boolean),
                        },
                      })
                    }
                  />
                </label>
              )}
              <p className="muted">
                {solver.risk_model.source === "supplied"
                  ? "The licensed path: a vendor factor model is handed to the engine directly. Estimated models need only a returns panel."
                  : "Estimated from a returns panel. Without one supplied, the server falls back to its synthetic demo panel — illustrative only, it describes nothing real."}
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------- trajectory

function TrajectoryCard({ spec, setSpec, fields }: { spec: ConstructionSpec; setSpec: (s: ConstructionSpec) => void; fields: IndexCatalogue["fields"] }) {
  const t = spec.trajectory;
  function update(patch: Partial<ConstructionSpec["trajectory"]>) {
    setSpec({ ...spec, trajectory: { ...t, ...patch } });
  }
  return (
    <div className="card">
      <h3>6 · Decarbonisation trajectory <span className="badge badge-neutral">path dependent</span></h3>
      <p className="help-text">
        The only layer whose result depends on prior reviews. Two reductions bind at once: the trajectory decays
        geometrically from a fixed base, while the universe-relative floor moves with the investable universe. The engine
        takes whichever is tighter and records which one bound.
      </p>
      <label className="checkbox-label">
        <input type="checkbox" checked={t.enabled} onChange={(e) => update({ enabled: e.target.checked })} />
        Enabled
      </label>
      {t.enabled && (
        <>
          <div className="inline-fields">
            <SelectField label="Metric" value={t.metric_field} options={fields.metrics} onChange={(metric_field) => update({ metric_field })} />
            <NumberField label="Annual reduction (0-1)" value={t.annual_reduction_rate} onChange={(v) => update({ annual_reduction_rate: v ?? 0.07 })} step="0.005" />
            <NumberField
              label="Reduction vs. universe (0-1)"
              value={t.universe_reduction_pct}
              onChange={(universe_reduction_pct) => update({ universe_reduction_pct })}
              step="0.05"
              placeholder="none"
            />
          </div>
          <div className="inline-fields">
            <label className="field-label" style={{ flex: 1 }}>
              Base date
              <input type="date" value={t.base_date ?? ""} onChange={(e) => update({ base_date: e.target.value || null })} />
            </label>
          </div>
          <label className="checkbox-label">
            <input type="checkbox" checked={t.compensate_missed_targets} onChange={(e) => update({ compensate_missed_targets: e.target.checked })} />
            Compensate missed targets — a year that misses is owed and tightens the next target
          </label>
          <p className="muted">0.30 versus the universe is an EU CTB, 0.50 an EU PAB. An empty base date makes the first review the base.</p>
        </>
      )}
    </div>
  );
}

// -------------------------------------------------------- calibrations

function CalibrationsTab({
  spec,
  setSpec,
  calibrations,
  loaded,
  setLoaded,
  refresh,
  setError,
  setStatus,
}: {
  spec: ConstructionSpec;
  setSpec: (s: ConstructionSpec) => void;
  calibrations: IndexCalibration[];
  loaded: IndexCalibration | null;
  setLoaded: (c: IndexCalibration | null) => void;
  refresh: () => void;
  setError: (e: string | null) => void;
  setStatus: (s: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const [versions, setVersions] = useState<IndexCalibration[]>([]);

  useEffect(() => {
    if (!loaded) {
      setVersions([]);
      return;
    }
    api.listIndexCalibrationVersions(loaded.calibration_id).then(setVersions).catch(() => setVersions([]));
  }, [loaded]);

  async function save(asNewVersion: boolean) {
    setError(null);
    const body = {
      name: asNewVersion ? (loaded?.name ?? name) : name,
      effective_from: effectiveFrom,
      spec,
      notes,
      approved_by: approvedBy.split(",").map((a) => a.trim()).filter(Boolean),
    };
    try {
      const saved =
        asNewVersion && loaded
          ? await api.createIndexCalibrationVersion(loaded.calibration_id, body)
          : await api.createIndexCalibration(body);
      setLoaded(saved);
      setStatus(`Saved ${saved.name} v${saved.version}, effective ${saved.effective_from}.`);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function load(calibrationId: string, version?: number) {
    setError(null);
    try {
      const calibration = await api.getIndexCalibration(calibrationId, version);
      setLoaded(calibration);
      setSpec(calibration.spec);
      setName(calibration.name);
      setNotes(calibration.notes);
      setStatus(`Loaded ${calibration.name} v${calibration.version}. Edits become a new version -- history is never overwritten.`);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <>
      <div className="card">
        <h3>Save the current methodology</h3>
        <p className="help-text">
          A calibration is the whole composition above, versioned and effective-dated. Versions are append-only and
          forward-only, and a review resolves the version <em>in force on its review date</em> rather than the latest one —
          otherwise today&apos;s parameters would silently rewrite past reviews.
        </p>
        <div className="inline-fields">
          <label className="field-label" style={{ flex: 2 }}>
            Name
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="DWS Electrification PAB" />
          </label>
          <label className="field-label" style={{ flex: 1 }}>
            Effective from
            <input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
          </label>
        </div>
        <div className="inline-fields">
          <label className="field-label" style={{ flex: 2 }}>
            Notes
            <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="what changed and why" />
          </label>
          <label className="field-label" style={{ flex: 1 }}>
            Approved by
            <input type="text" value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} placeholder="IC-2026-06-11" />
          </label>
        </div>
        <div className="toolbar">
          <button onClick={() => save(false)} disabled={!name.trim()}>
            Save as new calibration
          </button>
          <button className="nav-tab" onClick={() => save(true)} disabled={!loaded}>
            {loaded ? `Save as v${loaded.version + 1} of ${loaded.name}` : "Save as new version"}
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Saved calibrations</h3>
        {calibrations.length === 0 && <p className="muted">Nothing saved yet.</p>}
        {calibrations.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Version</th>
                <th>Effective from</th>
                <th>Config hash</th>
                <th>Notes</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {calibrations.map((c) => (
                <tr key={c.calibration_id}>
                  <td>{c.name}</td>
                  <td>v{c.version}</td>
                  <td>{c.effective_from}</td>
                  <td>
                    <code>{c.calibration_id}</code>
                  </td>
                  <td>{c.notes}</td>
                  <td>
                    <button className="link-button" onClick={() => load(c.calibration_id)}>
                      load
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {loaded && versions.length > 0 && (
        <div className="card">
          <h3>Version history — {loaded.name}</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Version</th>
                <th>Governs</th>
                <th>Approved by</th>
                <th>Notes</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.version}>
                  <td>v{v.version}</td>
                  <td>
                    {v.effective_from} → {v.effective_to ?? "open"}
                  </td>
                  <td>{v.approved_by.join(", ") || "--"}</td>
                  <td>{v.notes}</td>
                  <td>
                    <button className="link-button" onClick={() => load(v.calibration_id, v.version)}>
                      load
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// -------------------------------------------------------------- result

function ResultTab({ result, indexId }: { result: IndexReviewResult | null; indexId: string }) {
  const [showAll, setShowAll] = useState(false);
  const sorted = useMemo(() => (result ? [...result.constituents].sort((a, b) => b.weight - a.weight) : []), [result]);

  if (!result) return <p className="muted">Run a preview from the Compose tab to see a result.</p>;
  const d = result.diagnostics;
  const shown = showAll ? sorted : sorted.slice(0, 25);

  return (
    <>
      <div className="card">
        <h3>
          {indexId} @ {result.review_date}
        </h3>
        <p className="muted">
          config <code>{result.config_hash.slice(0, 12)}</code>
          {result.calibration_id ? ` · calibration ${result.calibration_id} v${result.calibration_version}` : " · ad-hoc spec"}
        </p>
        <div className="stat-tile-grid">
          <div className="stat-tile">
            <span className="stat-value">{d.final_size}</span>
            <span className="stat-label">constituents</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{pct(d.max_weight)}</span>
            <span className="stat-label">largest weight</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{num(d.effective_n, 1)}</span>
            <span className="stat-label">effective N</span>
          </div>
          <div className="stat-tile">
            <span className="stat-value">{d.one_way_turnover === null || d.one_way_turnover === undefined ? "--" : pct(d.one_way_turnover)}</span>
            <span className="stat-label">one-way turnover</span>
          </div>
          {d.tracking_error !== null && d.tracking_error !== undefined && (
            <div className="stat-tile">
              <span className="stat-value">{pct(d.tracking_error)}</span>
              <span className="stat-label">ex-ante tracking error</span>
            </div>
          )}
        </div>

        {result.exceptions.length > 0 && (
          <>
            <h4>Exceptions</h4>
            <p className="help-text">Every relaxation and data-quality override applied, in order. These belong on the committee pack.</p>
            <ul>
              {result.exceptions.map((e, i) => (
                <li key={i} className="error-text">
                  {e}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="card">
        <h3>Construction funnel</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Stage</th>
              <th>Rule</th>
              <th>In</th>
              <th>Out</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {result.trace.map((t, i) => (
              <tr key={i}>
                <td>{t.stage}</td>
                <td>{t.label || t.rule_type}</td>
                <td>{t.candidates_in}</td>
                <td>{t.candidates_out}</td>
                <td className="muted">
                  {Object.entries(t.detail)
                    .map(([k, v]) => `${k}=${v}`)
                    .join("  ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Index vs. universe</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Index</th>
              <th>Eligible universe</th>
              <th>Relative</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(d.weighted_metrics).map(([field, value]) => {
              const universe = d.universe_weighted_metrics[field];
              return (
                <tr key={field}>
                  <td>{field}</td>
                  <td>{num(value, 4)}</td>
                  <td>{num(universe, 4)}</td>
                  <td>{universe && Math.abs(universe) > 1e-9 ? `${((value / universe - 1) * 100).toFixed(2)}%` : "--"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {result.state.required_metric_value !== null && result.state.required_metric_value !== undefined && (
          <p className="help-text">
            Trajectory: target {num(result.state.required_metric_value, 4)}, achieved {num(result.state.achieved_metric_value, 4)}, binding{" "}
            <strong>{result.state.binding_constraint}</strong>, carried forward {pct(result.state.shortfall_carry)}. Base{" "}
            {num(result.state.base_metric_value, 4)} set on {result.state.base_date}.
          </p>
        )}
      </div>

      <div className="card">
        <h3>Constituents</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Sector</th>
              <th>Weight</th>
              <th>Base weight</th>
              <th>Tilt</th>
              <th>Index shares</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.company_id}>
                <td>{c.name}</td>
                <td>{c.sector ?? "--"}</td>
                <td>{pct(c.weight, 3)}</td>
                <td>{pct(c.base_weight, 3)}</td>
                <td>{num(c.tilt_multiplier, 3)}×</td>
                <td>{num(c.index_shares, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length > 25 && (
          <button className="link-button" onClick={() => setShowAll(!showAll)}>
            {showAll ? "show top 25" : `show all ${sorted.length}`}
          </button>
        )}
      </div>
    </>
  );
}
