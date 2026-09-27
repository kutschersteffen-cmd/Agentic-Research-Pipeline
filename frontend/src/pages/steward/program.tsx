import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ProgramParams, ProgramSimulation } from "../../types";
import { ActorField, DataTable, Section, useActor, words } from "./common";

// Traffic lights reuse the score badges: green = good, amber = mid, red = low.
const LIGHT: Record<string, string> = { green: "badge-high", amber: "badge-mid", red: "badge-low" };

type NumberKey = { [K in keyof ProgramParams]: ProgramParams[K] extends number ? K : never }[keyof ProgramParams];

const FIELDS: { key: NumberKey; label: string; step: number; hint: string }[] = [
  { key: "tilt_floor", label: "Tilt floor", step: 0.05, hint: "Weight multiplier for the worst CLTI score" },
  { key: "tilt_ceiling", label: "Tilt ceiling", step: 0.05, hint: "Weight multiplier for the best CLTI score" },
  { key: "leader_clti", label: "Leader CLTI from", step: 1, hint: "Labels leaders in the tilt table" },
  { key: "laggard_clti", label: "Engage on climate below CLTI", step: 1, hint: "CLTI laggards become climate targets" },
  { key: "max_targets", label: "Max targets", step: 1, hint: "Top of the ranking by leverage" },
  { key: "min_weight_ratio", label: "Coherence: min weight kept", step: 0.05, hint: "Share of benchmark weight a target should keep" },
  { key: "effort_days", label: "Days per new engagement", step: 1, hint: "Analyst days per year" },
  { key: "free_capacity_days", label: "Free house capacity (days)", step: 5, hint: "Analyst days per year" },
];

/** Client program (operating model Part 5): calibrate tilt -> selection -> sanction ->
 * escalation against the house program, save the calibration, download the proposal. */
export function ProgramStudio({ streamId }: { streamId: string }) {
  const [actor, setActor] = useActor();
  const [params, setParams] = useState<ProgramParams | null>(null);
  const [saved, setSaved] = useState<ProgramParams | null>(null);
  const [savedBy, setSavedBy] = useState<string | null>(null);
  const [sim, setSim] = useState<ProgramSimulation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const run = useRef(0);

  useEffect(() => {
    api.getProgram(streamId).then(
      (r) => {
        setParams(r.simulation.params);
        setSaved(r.simulation.params);
        setSavedBy(r.saved ? `${r.saved.updated_by}, ${new Date(r.saved.updated_at).toLocaleDateString()}` : null);
        setSim(r.simulation);
      },
      (e) => setError((e as Error).message),
    );
  }, [streamId]);

  // One page, rerun on every change (debounced); only the latest run is shown.
  useEffect(() => {
    if (!params || params === saved) return;
    const id = ++run.current;
    const timer = setTimeout(async () => {
      setRunning(true);
      try {
        const next = await api.simulateProgram(streamId, params);
        if (id === run.current) {
          setSim(next);
          setError(null);
        }
      } catch (err) {
        if (id === run.current) setError((err as Error).message);
      } finally {
        if (id === run.current) setRunning(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [params, saved, streamId]);

  const dirty = !!params && !!saved && JSON.stringify(params) !== JSON.stringify(saved);
  const set = <K extends keyof ProgramParams>(key: K, value: ProgramParams[K]) => params && setParams({ ...params, [key]: value });

  async function save() {
    if (!params) return;
    setMessage(null);
    try {
      await api.saveProgram(streamId, params, actor);
      setSaved(params);
      setSavedBy(`${actor}, ${new Date().toLocaleDateString()}`);
      setMessage("Calibration saved. The proposal now uses it.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!params || !sim) return <p className="status-text">{error ?? "Loading…"}</p>;
  const k = sim.kpis;
  const tiles: [string, string | number, string?][] = [
    ["Weighted CLTI", `${k.weighted_clti_portfolio} vs ${k.weighted_clti_benchmark}`, `${k.clti_uplift >= 0 ? "+" : ""}${k.clti_uplift} uplift`],
    ["Active share", `${k.active_share_pct}%`],
    ["Targets", k.targets, `${k.client_only_targets} not yet engaged by the house`],
    ["Expected sanctions", k.sanctions, `${k.vote_conflicts} votes differ from the house`],
  ];

  return (
    <>
      <section className="card">
        <div className="section-heading">
          <h3>Client program: {sim.client}</h3>
          <span className="chip">
            {sim.benchmark} · {sim.vehicle}
          </span>
        </div>
        <p className="help-text">
          Calibrate the four steps (tilt, engagement selection, vote sanction, escalation) against the house program. Every change
          reruns the whole pipeline. Voting policy: {sim.voting_policy}. Escalation rules: {sim.escalation_rules} (stage 7).
        </p>
        <p className="muted">{sim.data_note}</p>
        <div className="metric-grid">
          {tiles.map(([label, value, hint]) => (
            <div key={label} className="metric-tile">
              <span className="metric-tile-label">{label}</span>
              <strong className="metric-tile-value">{value}</strong>
              {hint && <span className="muted">{hint}</span>}
            </div>
          ))}
        </div>
      </section>
      <ActorField actor={actor} onChange={setActor} />
      <Section step="Calibrate" title="Settings">
        <label className="field-label">
          Client objective
          <textarea rows={2} value={params.objective} onChange={(e) => set("objective", e.target.value)} />
        </label>
        <div className="program-fields">
          <label className="field-label">
            Tilt normalisation
            <select value={params.normalisation} onChange={(e) => set("normalisation", e.target.value as ProgramParams["normalisation"])}>
              <option value="rank_percentile">rank percentile</option>
              <option value="zscore">z-score</option>
              <option value="max">share of the best score</option>
            </select>
          </label>
          {FIELDS.map((f) => (
            <label key={f.key} className="field-label" title={f.hint}>
              {f.label}
              <input
                type="number"
                step={f.step}
                value={params[f.key]}
                onChange={(e) => e.target.value !== "" && set(f.key, Number(e.target.value))}
              />
            </label>
          ))}
          <label className="field-label checkbox-label">
            <input type="checkbox" checked={params.include_triggers} onChange={(e) => set("include_triggers", e.target.checked)} />
            Also select on medium and high monitoring triggers
          </label>
        </div>
        <div className="toolbar">
          <button onClick={save} disabled={!actor || !dirty} title={!actor ? "Enter your name above first" : !dirty ? "No changes to save" : undefined}>
            Save calibration
          </button>
          <a className="button-link" href={api.programProposalUrl(streamId)} download>
            Download proposal (PowerPoint)
          </a>
          <span className="muted">
            {running ? "Running…" : dirty ? "Unsaved changes: the proposal uses the saved calibration." : savedBy ? `Saved by ${savedBy}` : "Defaults, not saved yet"}
          </span>
        </div>
        {message && <p className="status-text">{message}</p>}
        {error && <p className="error-text">{error}</p>}
      </Section>
      <Section step="House comparison" title="Feasibility against the house program">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Check</th>
                <th>Status</th>
                <th>Result</th>
                <th>Why it matters</th>
              </tr>
            </thead>
            <tbody>
              {sim.checks.map((c) => (
                <tr key={c.check}>
                  <td>{c.check}</td>
                  <td>
                    <span className={`badge ${LIGHT[c.status]}`}>{c.status}</span>
                  </td>
                  <td>{c.value}</td>
                  <td className="muted">{c.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section step="2 · 3 · 4" title="Engagement targets, escalation and sanction">
        <p className="help-text">
          {sim.targets.length} of {sim.candidates} candidates, ranked by leverage (portfolio weight × gap). A target whose client step
          reaches vote against management is at the vote step: its next meeting carries an expected sanction.
        </p>
        <DataTable
          rows={sim.targets.map((t) => ({
            company: t.company,
            theme: t.theme,
            why: t.reason,
            "weight %": t.portfolio_pct,
            leverage: t.leverage,
            origin: t.origin === "house" ? "house engagement" : "client only",
            "step now": t.step_now,
            house: t.house_step,
            client: t.client_step + (t.above_house ? " (above house)" : ""),
            sanction: t.at_vote_step ? "yes" : "",
          }))}
          empty="No company qualifies with these settings."
        />
        <h4>Expected votes that matter: sanctions and differences from the house</h4>
        <DataTable rows={sim.votes.filter((v) => v.sanction || v.house !== v.client)} empty="The client's expected votes match the house." />
      </Section>
      <Section step="1" title="Tilt">
        <DataTable
          rows={sim.holdings.map((h) => ({
            company: h.company,
            sector: h.sector,
            CLTI: h.clti,
            "benchmark %": h.benchmark_pct,
            "portfolio %": h.portfolio_pct,
            "active %": h.active_pct,
            role: h.role ? words(h.role) : "",
          }))}
        />
      </Section>
    </>
  );
}
