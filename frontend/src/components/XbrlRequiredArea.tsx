import { useEffect, useState } from "react";
import { api } from "../api/client";
import { when } from "../lib/runs";
import { formatFactValue, metricText, periodLabel } from "../lib/xbrlTags";
import type { RunManifest, XbrlRequiredRow } from "../types";
import { Pager, TagId } from "./XbrlFactsTable";

const PAGE = 50;
const msg = (err: unknown) => (err as Error).message;

/** XBRL Facts, Required area: revenue and capex per company and year for one fetch run. */
export function XbrlRequiredArea({ fetchRunId, refreshKey }: { fetchRunId: string | null; refreshKey: number }) {
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [picked, setPicked] = useState("");
  const [rows, setRows] = useState<XbrlRequiredRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [seenRun, setSeenRun] = useState(fetchRunId);
  const runId = picked || fetchRunId || runs?.[0]?.run_id || "";
  if (seenRun !== fetchRunId) {
    // A fetch was just started in the Fetch area: follow it.
    setSeenRun(fetchRunId);
    setPicked("");
  }

  useEffect(() => {
    let live = true;
    (api.listRuns("xbrl_fetch") as Promise<{ runs: RunManifest[] }>)
      .then((res) => live && (setRuns(res.runs), setRunsError(null)))
      .catch((err) => live && setRunsError(msg(err)));
    return () => {
      live = false;
    };
  }, [fetchRunId, refreshKey]);

  useEffect(() => {
    if (!runId) return;
    let live = true; // only the newest request may write results
    setRows(null);
    setError(null);
    setOffset(0);
    api
      .getXbrlRequired(runId)
      .then((res) => live && setRows(res))
      .catch((err) => live && setError(msg(err)));
    return () => {
      live = false;
    };
  }, [runId, refreshKey]);

  const shown = rows?.slice(offset, offset + PAGE) ?? [];
  const known = runs?.some((r) => r.run_id === runId);
  return (
    <section className="card" aria-labelledby="xbrl-required-title">
      <h2 id="xbrl-required-title">Required</h2>
      <p className="help-text" id="xbrl-required-hint">
        Revenue and capex for every company of one fetch run, one row per fiscal year. The fiscal year is the calendar year
        in which the period ends. Each value comes from the first concept of a fixed list that the company reported.
      </p>
      <label className="field-label">
        Fetch run
        <select value={runId} onChange={(e) => setPicked(e.target.value)} disabled={!runs && !runsError}>
          {!runs && !runsError && <option value="">Loading…</option>}
          {runs?.length === 0 && !runId && <option value="">No fetch run yet</option>}
          {runId && !known && <option value={runId}>{runId}</option>}
          {runs?.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id} · {when(r.created_at)} · {r.company_count.toLocaleString()} {r.company_count === 1 ? "company" : "companies"}
            </option>
          ))}
        </select>
      </label>
      {runsError && <p className="error-text">Fetch runs could not be loaded ({runsError}).</p>}
      {!runId && runs && <p className="muted">Start a fetch above to see its revenue and capex.</p>}
      {runId && !rows && !error && <p className="muted xbrl-status">Loading revenue and capex…</p>}
      {error && (
        <p className="error-text" role="alert">
          {/Run not found/i.test(error)
            ? `Run ${runId} was not found. Choose another fetch run.`
            : `Revenue and capex could not be loaded (${error}).`}
        </p>
      )}
      {rows && rows.length === 0 && (
        <p className="muted">No revenue or capex is stored for the companies of this run. Fetch them first.</p>
      )}
      {rows && rows.length > 0 && (
        <>
          <div className="table-wrap xbrl-table-wrap" tabIndex={0} role="region" aria-label="Revenue and capex, scrolls sideways">
            <table className="data-table xbrl-table xbrl-required" aria-describedby="xbrl-required-hint">
              <caption className="visually-hidden">Revenue and capex per company and fiscal year</caption>
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Metric</th>
                  <th scope="col">Fiscal year</th>
                  <th scope="col">Concept</th>
                  <th scope="col" className="num">Value</th>
                  <th scope="col">Unit</th>
                  <th scope="col">Period</th>
                  <th scope="col">Form</th>
                  <th scope="col">Filed</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={`${r.company_id}|${r.metric}|${r.fiscal_year}|${i}`}>
                    <th scope="row" className="xbrl-tag-cell">
                      <span className="xbrl-name">{r.company_id}</span>
                      <span className="xbrl-sub mono">CIK {r.cik}</span>
                      {r.status !== "found" && (
                        <span className="xbrl-sub" aria-hidden="true">
                          Not found
                        </span>
                      )}
                    </th>
                    <td>{metricText(r.metric)}</td>
                    <td className="mono">{r.fiscal_year ?? "–"}</td>
                    {r.status === "found" && r.value != null ? (
                      <>
                        <td className="mono xbrl-concept">{r.concept ? <TagId id={r.concept} /> : "–"}</td>
                        <td className="num mono">{formatFactValue(r.value, r.unit ?? "")}</td>
                        <td className="mono xbrl-unit-col">{r.unit}</td>
                        <td className="mono">{r.period_end ? periodLabel(r.period_start, r.period_end) : "–"}</td>
                        <td className="mono">{r.form ?? "–"}</td>
                        <td className="mono">{r.filed ?? "–"}</td>
                      </>
                    ) : (
                      <td colSpan={6} className="xbrl-not-found">
                        <strong>Not found.</strong> Nothing is guessed.
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.some((r) => r.status === "not_found") && (
            <p className="help-text xbrl-note">
              Not found means no concept of the fixed list has an annual value for that company, metric and year. A foreign
              filer using IFRS concepts, or a filer using a concept outside the list, ends up here. Nothing is guessed, so
              the value is left empty.
            </p>
          )}
          <Pager offset={offset} count={shown.length} total={rows.length} limit={PAGE} noun="rows" onPage={setOffset} />
        </>
      )}
    </section>
  );
}
