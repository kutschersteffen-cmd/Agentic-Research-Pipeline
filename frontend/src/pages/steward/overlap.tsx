import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { day } from "../../lib/workbench";
import { count, pairOf, pairText, pairTitle, shortName, tintStep, weight } from "../../lib/overlap";
import type { FundOverlap, OverlapMatrix, WorklistScope } from "../../types";
import "./overlap.css";

const TOP = [25, 50, 100, 200];

/** Steward Workflow tab "Overlap" (spec stewardship-workbench-overlap): what the house funds hold in common.
 * It only reads; picking stays in the Workbench. */
export function OverlapStudio() {
  const [data, setData] = useState<FundOverlap | null>(null);
  const [sample, setSample] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getFundOverlap()
      .then((d) => {
        setData(d);
        // No funds: either the sample universe (say how to switch) or no holdings loaded. A failed lookup keeps the picks shown.
        if (d.funds.length === 0)
          api
            .getHouseUniverse()
            .then((u) => setSample(u.source === "sample"))
            .catch(() => setSample(false));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="ov">
      <section className="card">
        <div className="section-heading">
          <h2>Overlap</h2>
          {data && (
            <span className="ov-meta">
              {[data.as_of && `As of ${day(data.as_of)}`, `${count(data.funds.length)} funds`, `${count(data.companies)} companies`, `Cycle ${data.cycle}`]
                .filter(Boolean)
                .join(" · ")}
            </span>
          )}
        </div>
        <p className="help-text">
          How much the house funds hold the same companies. Shared weight adds up, for each company two funds both hold, the lower of its two
          weights.
        </p>
        {error && <p className="error-text" role="alert">{error}</p>}
        {!data && !error && <p className="status-text">Loading the fund holdings…</p>}
        {data && data.funds.length === 0 && sample !== null && (
          <p className="muted">
            {sample
              ? "Fund overlap needs the portfolio universe. Switch the house universe to portfolio holdings in Selection."
              : "No fund holds a company at the latest holdings snapshot."}
          </p>
        )}
      </section>
      {data && data.funds.length > 0 && <FundTable data={data} />}
      {data && data.funds.length > 0 && <CompanyGrid cycle={data.cycle} />}
      {data && <SharedPicks data={data} />}
    </div>
  );
}

function FundTable({ data }: { data: FundOverlap }) {
  const { funds, pairs } = data;
  return (
    <section className="card">
      <h2>Funds side by side</h2>
      <p className="muted">Each cell: shared companies · shared weight. The darker the cell, the larger the shared weight.</p>
      <div className="ov-frame">
        <table className="data-table ov-table ov-funds">
          <thead>
            <tr>
              <th className="ov-pin">
                <span className="visually-hidden">Fund</span>
              </th>
              {funds.map((f) => (
                <th key={f.portfolio_id} className="num" scope="col" title={f.name}>
                  {shortName(f.name)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {funds.map((a) => (
              <tr key={a.portfolio_id}>
                <th scope="row" className="ov-pin" title={a.name}>
                  {shortName(a.name)}
                </th>
                {funds.map((b) => {
                  if (a === b)
                    return (
                      <td key={b.portfolio_id} className="num muted">
                        {count(a.companies)} companies
                      </td>
                    );
                  const p = pairOf(pairs, a.portfolio_id, b.portfolio_id)!;
                  return (
                    <td key={b.portfolio_id} className={`num ov-tint-${tintStep(p.shared_weight_pct)}`} title={pairTitle(a, b, p)}>
                      {pairText(p)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CompanyGrid({ cycle }: { cycle: string }) {
  const [basis, setBasis] = useState<"top" | "selection">("top");
  const [n, setN] = useState(100);
  const [scopes, setScopes] = useState<WorklistScope[]>([]);
  const [scope, setScope] = useState("house");
  const [grid, setGrid] = useState<OverlapMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getWorklistScopes()
      .then((r) => setScopes(r.scopes))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    let live = true;
    setError(null);
    setGrid(null); // no old rows under a new choice
    api
      .getOverlapMatrix(basis, n, basis === "selection" ? scope : undefined)
      .then((g) => live && setGrid(g))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [basis, n, scope]);

  const label = scopes.find((s) => s.key === scope)?.label ?? scope;
  return (
    <section className="card">
      <div className="section-heading ov-grid-head">
        <h2>Companies across funds</h2>
        <fieldset className="ov-switch">
          <legend>Show</legend>
          <label className="checkbox-label">
            <input type="radio" name="ov-basis" checked={basis === "top"} onChange={() => setBasis("top")} />
            Top
          </label>
          <select aria-label="How many companies" value={n} onChange={(e) => setN(Number(e.target.value))} disabled={basis !== "top"}>
            {TOP.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <span className="muted">by house weight</span>
          <label className="checkbox-label">
            <input type="radio" name="ov-basis" checked={basis === "selection"} onChange={() => setBasis("selection")} />
            Picked in
          </label>
          <select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} disabled={basis !== "selection"}>
            {scopes.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <span className="muted">{cycle}</span>
        </fieldset>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!grid && !error && <p className="status-text">Loading…</p>}
      {grid && grid.companies.length === 0 && basis === "selection" && <p className="muted">{`No company is picked in ${label} in ${cycle}.`}</p>}
      {grid && grid.companies.length > 0 && (
        <div className="ov-frame ov-scroll">
          <table className="data-table ov-table">
            <thead>
              <tr>
                <th className="ov-pin" scope="col">
                  Company
                </th>
                <th className="num" scope="col">
                  House wt %
                </th>
                <th className="num" scope="col">
                  Funds
                </th>
                {grid.funds.map((f) => (
                  <th key={f.portfolio_id} className="num" scope="col" title={`${f.name}, weight %`}>
                    {shortName(f.name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.companies.map((c) => (
                <tr key={c.issuer_id}>
                  <th scope="row" className="ov-pin" title={c.company}>
                    {c.company}
                  </th>
                  <td className="num">{weight(c.house_weight_pct)}</td>
                  <td className="num">{c.funds}</td>
                  {grid.funds.map((f) => (
                    <td key={f.portfolio_id} className={c.weights[f.portfolio_id] == null ? "num muted" : "num"}>
                      {weight(c.weights[f.portfolio_id])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SharedPicks({ data }: { data: FundOverlap }) {
  const rows = data.shared_selections;
  return (
    <section className="card">
      <h2>Picked in more than one scope · {data.cycle}</h2>
      {rows.length === 0 ? (
        <p className="muted">{`No company is picked in more than one scope in ${data.cycle}.`}</p>
      ) : (
        <div className="ov-frame">
          <table className="data-table ov-table">
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Picked in</th>
                <th scope="col">Held by</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.issuer_id}>
                  <th scope="row">{r.company}</th>
                  <td>
                    <ul className="ov-scopes">
                      {r.scopes.map((s) => (
                        <li key={s.scope}>
                          {s.label} · {s.status === "confirmed" ? "Confirmed" : <span className="proposed-tag">✎ Proposed</span>}
                        </li>
                      ))}
                    </ul>
                  </td>
                  <td title={r.held_in.map((h) => `${h.name}: ${h.weight_pct.toFixed(2)} %`).join("\n")}>
                    {r.held_in.length ? r.held_in.map((h) => shortName(h.name)).join(", ") : <span className="muted">No fund</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
