import { useEffect, useId, useState } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import { when } from "../lib/runs";
import {
  formatFactValue,
  metricText,
  outcomeText,
  sortVerifyRows,
  toleranceFraction,
  verifyDetailText,
  verifyMapping,
  verifySummary,
} from "../lib/xbrlTags";
import type { RunManifest, XbrlVerifyRow } from "../types";
import { Pager } from "./XbrlFactsTable";

const PAGE = 50;
const COUNTS = ["match", "mismatch", "missing_in_run", "missing_in_xbrl"];
const msg = (err: unknown) => (err as Error).message;
const GUARD =
  "This run used XBRL values, so comparing it would prove nothing. Re-run the extraction with ‘SEC XBRL facts first’ switched off.";

/** XBRL Facts, Verify area: compare an extraction run's revenue and capex with the XBRL values. */
export function XbrlVerifyArea() {
  const id = useId();
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runId, setRunId] = useState("");
  const [revenue, setRevenue] = useState("");
  const [capex, setCapex] = useState("");
  const [tolerance, setTolerance] = useState("0.5");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ circular: boolean; text: string } | null>(null);
  const [result, setResult] = useState<{ runId: string; rows: XbrlVerifyRow[] } | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    let live = true;
    (api.listRuns("extraction") as Promise<{ runs: RunManifest[] }>)
      .then((res) => live && setRuns(res.runs))
      .catch((err) => live && setRunsError(msg(err)));
    return () => {
      live = false;
    };
  }, []);

  const mapping = verifyMapping(revenue, capex);
  const fraction = toleranceFraction(tolerance);
  const problem = !runId
    ? "Choose an extraction run."
    : !mapping
      ? "Enter the field id that holds revenue, capex, or both."
      : fraction === null
        ? "Enter a tolerance between 0 and 100 percent."
        : null;
  const [tried, setTried] = useState(false);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setTried(true);
    setError(null); // a new attempt never leaves the last answer on screen
    if (problem || !mapping || fraction === null) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const rows = await api.verifyXbrl({ run_id: runId, mapping, tolerance: fraction });
      setResult({ runId, rows });
      setOffset(0);
      announce(`Verification finished: ${rows.length} compared values`);
    } catch (err) {
      const text = msg(err);
      setError({ circular: /409|xbrl_facts_enabled|cannot prove XBRL was off/i.test(text), text });
    } finally {
      setBusy(false);
    }
  }

  const sorted = result ? sortVerifyRows(result.rows).filter((r) => r.outcome !== "match") : [];
  const counts = result ? verifySummary(result.rows) : null;
  const shown = sorted.slice(offset, offset + PAGE);
  return (
    <section className="card" aria-labelledby="xbrl-verify-title">
      <h2 id="xbrl-verify-title">Verify</h2>
      <p className="help-text">
        Compare an extraction run’s revenue and capex with the XBRL values above. Only a run that did not use XBRL
        can be checked. Say which field of the run holds each figure.
      </p>
      <form onSubmit={verify} noValidate>
        <label className="field-label">
          Extraction run
          <select value={runId} onChange={(e) => setRunId(e.target.value)} disabled={!runs && !runsError}>
            <option value="">{!runs && !runsError ? "Loading…" : runs?.length === 0 ? "No extraction run yet" : "Select…"}</option>
            {runs?.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} · {when(r.created_at)} · {r.company_count.toLocaleString()} {r.company_count === 1 ? "company" : "companies"}
              </option>
            ))}
          </select>
        </label>
        {runsError && <p className="error-text">Extraction runs could not be loaded ({runsError}).</p>}
        <div className="xbrl-filters">
          <label className="field-label xbrl-filter-wide">
            Revenue field id
            <input type="text" value={revenue} onChange={(e) => setRevenue(e.target.value)} placeholder="e.g. revenue" autoComplete="off" />
          </label>
          <label className="field-label xbrl-filter-wide">
            Capex field id
            <input type="text" value={capex} onChange={(e) => setCapex(e.target.value)} placeholder="e.g. capex" autoComplete="off" />
          </label>
          <label className="field-label">
            Tolerance (%)
            <input
              type="text"
              inputMode="decimal"
              value={tolerance}
              onChange={(e) => setTolerance(e.target.value)}
              aria-invalid={fraction === null || undefined}
              aria-describedby={`${id}-tol`}
            />
          </label>
        </div>
        <p className={fraction === null ? "error-text xbrl-field-error" : "help-text xbrl-field-error"} id={`${id}-tol`}>
          {fraction === null
            ? "Enter a tolerance between 0 and 100 percent."
            : "A value matches when it is within this share of the XBRL value."}
        </p>
        {tried && problem && fraction !== null && (
          <p className="error-text" role="alert">
            {problem}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Verifying…" : "Verify"}
        </button>
      </form>

      {error?.circular && (
        <div className="error-text" role="alert">
          <p>
            <strong>This run cannot be verified.</strong> {GUARD}
          </p>
          <p className="xbrl-sub">Reason given: {error.text}</p>
        </div>
      )}
      {error && !error.circular && (
        <p className="error-text" role="alert">
          {/Run not found/i.test(error.text) ? "That run was not found. Choose another extraction run." : `Verification failed (${error.text}).`}
        </p>
      )}

      {result && counts && (
        <div className="xbrl-run">
          <h3>Result for <span className="mono">{result.runId}</span></h3>
          <dl className="xbrl-counts" aria-label="Outcome counts">
            {COUNTS.map((c) => (
              <div key={c}>
                <dt>{outcomeText(c)}</dt>
                <dd className="mono">{counts[c].toLocaleString()}</dd>
              </div>
            ))}
          </dl>
          <p className="help-text">
            Written to <span className="mono">runs/{result.runId}/xbrl_verify.jsonl</span>.
          </p>
          {result.rows.length === 0 && (
            <p className="muted">Nothing could be compared: the run has no revenue or capex value for a year, and XBRL has none either.</p>
          )}
          {result.rows.length > 0 && sorted.length === 0 && <p className="muted">Every compared value matches. Nothing to review.</p>}
          {sorted.length > 0 && (
            <>
              <div className="table-wrap xbrl-table-wrap" tabIndex={0} role="region" aria-label="Values to review, scrolls sideways">
                <table className="data-table xbrl-table">
                  <caption className="visually-hidden">Values that do not match, mismatches first, then missing values</caption>
                  <thead>
                    <tr>
                      <th scope="col">Company</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">Metric</th>
                      <th scope="col">Fiscal year</th>
                      <th scope="col" className="num">Run value</th>
                      <th scope="col" className="num">XBRL value</th>
                      <th scope="col">Unit</th>
                      <th scope="col">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r, i) => (
                      <tr key={`${r.company_id}|${r.metric}|${r.fiscal_year}|${i}`}>
                        <th scope="row" className="xbrl-tag-cell">{r.company_id}</th>
                        <td><strong>{outcomeText(r.outcome)}</strong></td>
                        <td>{metricText(r.metric)}</td>
                        <td className="mono">{r.fiscal_year}</td>
                        <td className="num mono">{r.run_value == null ? <span className="xbrl-gap">None</span> : formatFactValue(r.run_value, r.unit ?? "")}</td>
                        <td className="num mono">{r.xbrl_value == null ? <span className="xbrl-gap">None</span> : formatFactValue(r.xbrl_value, r.unit ?? "")}</td>
                        <td className="mono xbrl-unit-col">{r.unit ?? "–"}</td>
                        <td>{verifyDetailText(r.detail)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager offset={offset} count={shown.length} total={sorted.length} limit={PAGE} noun="rows to review" onPage={setOffset} />
            </>
          )}
        </div>
      )}
    </section>
  );
}
