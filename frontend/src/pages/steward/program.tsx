import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { BenchmarkInfo, ProgramMonitor, ProgramParams, ProgramRun, ProgramSimulation, ProgramVersion } from "../../types";
import { ActorField, DataTable, Section, useActor, words } from "./common";

// Traffic lights reuse the score badges: green = good, amber = mid, red = low.
const LIGHT: Record<string, string> = { green: "badge-high", amber: "badge-mid", red: "badge-low", not_built: "badge-neutral" };

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
  const [actor] = useActor();
  const [params, setParams] = useState<ProgramParams | null>(null);
  const [saved, setSaved] = useState<ProgramParams | null>(null);
  const [savedBy, setSavedBy] = useState<string | null>(null);
  const [savedAuthor, setSavedAuthor] = useState<string | null>(null);
  const [versions, setVersions] = useState<ProgramVersion[]>([]);
  const [runs, setRuns] = useState<ProgramRun[]>([]);
  const [watch, setWatch] = useState<ProgramMonitor | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sim, setSim] = useState<ProgramSimulation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [benchmarks, setBenchmarks] = useState<BenchmarkInfo[]>([]);
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const run = useRef(0);

  useEffect(() => {
    api.getProgram(streamId).then(
      (r) => {
        setParams(r.simulation.params);
        setSaved(r.simulation.params);
        setSavedBy(r.saved ? `${r.saved.updated_by}, ${new Date(r.saved.updated_at).toLocaleDateString()}` : null);
        setSavedAuthor(r.saved?.updated_by ?? null);
        setVersions(r.versions);
        setRuns(r.runs);
        setSim(r.simulation);
      },
      (e) => setError((e as Error).message),
    );
    api.monitorProgram(streamId).then(setWatch, (e) => setError((e as Error).message));
    api.listBenchmarks().then((r) => setBenchmarks(r.benchmarks), () => undefined);
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
      setSavedAuthor(actor);
      setMessage("Calibration saved. The proposal now uses it.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function act(kind: "approve" | "run") {
    setBusy(kind);
    setError(null);
    setMessage(null);
    try {
      if (kind === "approve") {
        const v = await api.approveProgram(streamId, actor);
        setVersions([...versions, v]);
        setMessage(`Program version ${v.version} approved: its ${v.targets.length} targets are now monitored.`);
      } else {
        const run = await api.recordProgramRun(streamId, actor);
        setRuns([...runs, run]);
      }
      setWatch(await api.monitorProgram(streamId));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function upload(file: File | undefined) {
    if (!file || !params) return;
    setUploading(true);
    setError(null);
    try {
      const b = await api.uploadBenchmark(await file.text(), actor);
      setBenchmarks([...benchmarks.filter((x) => x.benchmark_id !== b.benchmark_id), b]);
      setParams({ ...params, benchmark: b.benchmark_id });
      setMessage(`${b.name}, holdings as of ${b.as_of}: ${b.constituents} equities loaded (${b.dropped} cash, futures and unlisted lines dropped).`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  }
  const selfApproval = !!savedAuthor && savedAuthor.trim().toLowerCase() === actor.trim().toLowerCase();

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
        {sim.score_note && <p className="warning-banner">{sim.score_note}</p>}
        <p className="muted">
          {sim.constituents} companies. {sim.data_note}
        </p>
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
      <ActorField />
      <Section step="Calibrate" title="Settings">
        <label className="field-label">
          Client objective
          <textarea rows={2} value={params.objective} onChange={(e) => set("objective", e.target.value)} />
        </label>
        <div className="inline-fields">
          <label className="field-label">
            Benchmark
            <select value={params.benchmark} onChange={(e) => set("benchmark", e.target.value)}>
              <option value="sample">House companies (synthetic sample or portfolio holdings, per the house setting)</option>
              {benchmarks.map((b) => (
                <option key={b.benchmark_id} value={b.benchmark_id}>
                  {b.name}, {b.as_of} ({b.constituents} companies)
                </option>
              ))}
            </select>
          </label>
          <label className="field-label" title={actor ? undefined : "Enter your name above first"}>
            Upload iShares holdings (CSV)
            <input type="file" accept=".csv,text/csv" disabled={!actor || uploading} onChange={(e) => upload(e.target.files?.[0])} />
          </label>
        </div>
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
      <Section step="Approve" title="Program versions">
        <p className="help-text">
          Approving freezes the saved calibration as a new, unchangeable version with its target list. Monitoring always runs against
          the latest approved version; recalibrating means approving a new one. A second person (not the one who saved the
          calibration) approves.
        </p>
        <div className="toolbar">
          <button
            onClick={() => act("approve")}
            disabled={!actor || !savedAuthor || dirty || selfApproval || busy !== null}
            title={
              !actor
                ? "Enter your name above first"
                : !savedAuthor
                  ? "Save a calibration first"
                  : dirty
                    ? "Save or discard the changes first"
                    : selfApproval
                      ? "Four-eyes: someone other than the person who saved the calibration approves"
                      : undefined
            }
          >
            {busy === "approve" ? "Approving…" : "Approve the saved calibration"}
          </button>
        </div>
        <DataTable
          rows={[...versions].reverse().map((v) => ({
            version: `v${v.version}`,
            targets: v.targets.length,
            "CLTI uplift": v.kpis.clti_uplift,
            "proposed by": v.proposed_by,
            "approved by": `${v.approved_by} · ${new Date(v.approved_at).toLocaleDateString()}`,
          }))}
          empty="Not approved yet."
        />
      </Section>
      <Section step="Monitor" title="The approved program against today's data">
        {!watch?.approved ? (
          <p className="muted">Monitoring starts once a version is approved.</p>
        ) : (
          <>
            <p className="muted">
              Version {watch.approved.version}, approved by {watch.approved.approved_by}.
              {watch.calibration_changed ? " The saved calibration has changed since: approve it to monitor the new one." : ""}
            </p>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>KPI</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {watch.alerts?.map((a) => (
                    <tr key={a.kpi}>
                      <td>{a.kpi}</td>
                      <td>
                        <span className={`badge ${LIGHT[a.status]}`}>{a.status === "not_built" ? "not built" : a.status}</span>
                      </td>
                      <td>{a.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h4>Approved targets</h4>
            <DataTable rows={watch.targets ?? []} />
            <div className="toolbar">
              <button onClick={() => act("run")} disabled={!actor || busy !== null} title={actor ? undefined : "Enter your name above first"}>
                {busy === "run" ? "Recording…" : "Record this monitoring run"}
              </button>
            </div>
            <DataTable
              rows={[...runs].reverse().map((r) => ({
                date: new Date(r.as_of).toLocaleString(),
                version: `v${r.version}`,
                "CLTI uplift": r.kpis.clti_uplift,
                targets: r.kpis.targets,
                alerts: r.alerts,
                "recorded by": r.recorded_by,
              }))}
              empty="No run recorded yet."
            />
          </>
        )}
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
        <p className="muted">
          The {sim.holdings.length} largest active weights of {sim.constituents} companies.
        </p>
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
