import { useEffect, useState } from "react";
import { api } from "../api/client";
import { activatable } from "../lib/activatable";
import { apiMessage } from "../lib/projects";
import { useMe } from "../lib/reviewer";
import { compareMessage, cutoffNotice, decisionBlocks, methodNote, windowLabel } from "../lib/signals";
import type { SignalExperimentDetail, SignalExperimentSummary, SignalMethod } from "../types";

const num = (v: number | null) => (v == null ? "—" : v.toFixed(3));

function Evidence({ detail, onDecided }: { detail: SignalExperimentDetail; onDecided: (d: SignalExperimentDetail) => void }) {
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notice = cutoffNotice(detail.cutoff_status);
  const blocks = decisionBlocks(me?.role ?? null, detail.cutoff_status);

  async function decide(decision: "graduate" | "shelve") {
    setBusy(true);
    setError(null);
    try {
      await api.signalDecide(detail.experiment_id, decision);
      onDecided(await api.signalExperiment(detail.experiment_id));
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="signals-evidence">
      <h2 id="signals-evidence">Evidence</h2>
      <p className="help-text">
        {detail.recipe.method} <code>{detail.experiment_id}</code> · model {detail.model ?? "none"}
        {detail.cutoff && ` · cutoff ${detail.cutoff}`} · {detail.evidence.n_trials} trials
      </p>
      {notice && <p className="error-text">{notice}</p>}
      {detail.evidence.windows.length === 0 ? (
        <p className="muted">No evidence windows</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Window</th>
                <th>Periods</th>
                <th>IC mean</th>
                <th>IC t (NW)</th>
                <th>IC n</th>
              </tr>
            </thead>
            <tbody>
              {detail.evidence.windows.map((w, i) => {
                const label = windowLabel(w.window, detail.cutoff_status);
                return (
                  <tr key={i}>
                    <td>
                      {w.window} {label && <span className="badge badge-low">{label}</span>}
                    </td>
                    <td>{w.periods}</td>
                    <td>{num(w.ic.mean)}</td>
                    <td>{num(w.ic.t_nw)}</td>
                    <td>{w.ic.n}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p>
        Decision: <strong>{detail.decision}</strong>
        {detail.decided_by && ` by ${detail.decided_by}`}
      </p>
      <div className="toolbar">
        <button onClick={() => decide("graduate")} disabled={busy || !!blocks.graduate} aria-describedby={blocks.graduate ? "signals-graduate-block" : undefined}>
          Graduate
        </button>
        {blocks.graduate && <span id="signals-graduate-block" className="muted">{blocks.graduate}</span>}
        <button onClick={() => decide("shelve")} disabled={busy || !!blocks.shelve} aria-describedby={blocks.shelve ? "signals-shelve-block" : undefined}>
          Shelve
        </button>
        {blocks.shelve && <span id="signals-shelve-block" className="muted">{blocks.shelve}</span>}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  );
}

function Compare({ experiments }: { experiments: SignalExperimentSummary[] }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const methodOf = (id: string) => experiments.find((e) => e.experiment_id === id)?.method ?? id;

  async function compare() {
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      setResult(compareMessage(await api.signalCompare(a, b), methodOf));
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const picker = (label: string, value: string, set: (v: string) => void) => (
    <label className="field-label">
      {label}
      <select value={value} onChange={(e) => set(e.target.value)}>
        <option value="">Choose an experiment</option>
        {experiments.map((e) => (
          <option key={e.experiment_id} value={e.experiment_id}>
            {e.method} {e.experiment_id}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <section className="card" aria-labelledby="signals-compare">
      <h2 id="signals-compare">Compare</h2>
      {picker("Experiment A", a, setA)}
      {picker("Experiment B", b, setB)}
      <button onClick={compare} disabled={busy || !a || !b}>
        Compare
      </button>
      {result && <p role="status">{result}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  );
}

function Run({ methods, onRan }: { methods: SignalMethod[]; onRan: (d: SignalExperimentDetail) => void }) {
  const [recipe, setRecipe] = useState<File | null>(null);
  const [prices, setPrices] = useState<File | null>(null);
  const [panels, setPanels] = useState<{ name: string; file: File | null }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setPanel = (i: number, patch: Partial<{ name: string; file: File | null }>) =>
    setPanels((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  async function submit() {
    if (!recipe || !prices) return;
    setBusy(true);
    setError(null);
    try {
      const named = Object.fromEntries(panels.filter((p) => p.name.trim() && p.file).map((p) => [p.name.trim(), p.file as File]));
      onRan(await api.signalRun({ recipe, prices, panels: named }));
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="signals-run">
      <h2 id="signals-run">Run</h2>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s-4)", alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 18rem", minWidth: 0 }}>
          <label className="field-label">
            Recipe JSON
            <input type="file" accept=".json,application/json" onChange={(e) => setRecipe(e.target.files?.[0] ?? null)} />
          </label>
          <label className="field-label">
            Prices CSV (month-end dates, one column per issuer)
            <input type="file" accept=".csv" onChange={(e) => setPrices(e.target.files?.[0] ?? null)} />
          </label>
          {panels.map((p, i) => (
            <div className="toolbar" key={i}>
              <input aria-label={`Panel ${i + 1} name`} value={p.name} onChange={(e) => setPanel(i, { name: e.target.value })} placeholder="Panel name" />
              <input aria-label={`Panel ${i + 1} file`} type="file" accept=".csv" onChange={(e) => setPanel(i, { file: e.target.files?.[0] ?? null })} />
              <button className="secondary" onClick={() => setPanels((ps) => ps.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          <div className="toolbar">
            <button className="secondary" onClick={() => setPanels((ps) => [...ps, { name: "", file: null }])}>
              Add panel
            </button>
            <button onClick={submit} disabled={busy || !recipe || !prices}>
              Submit
            </button>
          </div>
          {error && <p className="error-text" role="alert">{error}</p>}
        </div>
        <div style={{ flex: "1 1 14rem", minWidth: 0 }}>
          <h3>Methods</h3>
          <ul>
            {methods.map((m) => {
              const note = methodNote(m);
              return (
                <li key={m.name}>
                  <code>{m.name}</code> {note && <span className="muted">{note}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </section>
  );
}

export function SignalsWorkbench() {
  const [experiments, setExperiments] = useState<SignalExperimentSummary[]>([]);
  const [methods, setMethods] = useState<SignalMethod[]>([]);
  const [detail, setDetail] = useState<SignalExperimentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () =>
    api
      .signalExperiments()
      .then(setExperiments)
      .catch((err) => setError(apiMessage(err)));

  useEffect(() => {
    reload();
    api
      .signalMethods()
      .then(setMethods)
      .catch((err) => setError(apiMessage(err)));
  }, []);

  async function open(id: string) {
    setError(null);
    try {
      setDetail(await api.signalExperiment(id));
    } catch (err) {
      setError(apiMessage(err));
    }
  }

  function changed(d: SignalExperimentDetail) {
    setDetail(d);
    reload();
  }

  return (
    <div className="page">
      <h1>Signals workbench</h1>
      <p className="help-text">
        Run a signal recipe, read its evidence by window, compare two signals, and graduate or shelve one. The list is newest first: only Compare orders
        one signal above another.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}

      <section className="card" aria-labelledby="signals-experiments">
        <h2 id="signals-experiments">Experiments</h2>
        {experiments.length === 0 ? (
          <p className="muted">No experiments registered yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Category</th>
                  <th>Universe</th>
                  <th>Window</th>
                  <th>Model</th>
                  <th>Decision</th>
                  <th>Trials</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((e) => (
                  <tr
                    key={e.experiment_id}
                    className="clickable-row"
                    {...activatable(() => open(e.experiment_id))}
                    aria-current={e.experiment_id === detail?.experiment_id || undefined}
                  >
                    <td>{e.method}</td>
                    <td>{e.category}</td>
                    <td>{e.universe}</td>
                    <td>
                      {e.window_start}..{e.window_end}
                    </td>
                    <td>{e.model ?? "—"}</td>
                    <td>{e.decision}</td>
                    <td>{e.n_trials}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detail && <Evidence key={detail.experiment_id} detail={detail} onDecided={changed} />}
      <Compare experiments={experiments} />
      <Run methods={methods} onRan={changed} />
    </div>
  );
}
