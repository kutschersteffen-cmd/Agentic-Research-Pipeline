import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { BarrierFactForm } from "../components/BarrierFactForm";
import { FileLink } from "../components/FileLink";
import { RATING_CLASS, RATING_LABEL, errorDetail, historyLine, outcomeClass, ratifiedLine } from "../lib/barrier";
import type { BarrierCell, BarrierCriterion, BarrierRating, BarrierValue } from "../types";

const when = (iso: string) => iso.slice(0, 16).replace("T", " ");

function Figure({ v, label }: { v: BarrierValue; label: string }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="mono">{v.shown ?? "—"}</td>
      <td>
        {v.document_id != null ? (
          <FileLink url={api.barrierDocumentUrl(v.document_id, v.page)} name={`document-${v.document_id}.pdf`} open>
            {v.document}
          </FileLink>
        ) : (
          v.document ?? <span className="muted">computed</span>
        )}
        {v.page != null && <span className="mono"> p. {v.page}</span>}
        {v.page == null && v.locator && <span className="mono"> {v.locator}</span>}
      </td>
      <td>{v.quote ? `“${v.quote}”` : <span className="muted">—</span>}</td>
      <td className="mono">{v.confidence}</td>
      <td>{v.counted ? (v.machine_checked ? "checked in the document" : `entered by ${v.entered_by ?? "an analyst"}`) : <span className="error-text">not counted: {v.reason}</span>}</td>
    </tr>
  );
}

/** A conflict: the facts with several counted values, and the choice of which counts. */
function ConflictChoice({ code, region, cell, labels, onChosen }: {
  code: string; region: string; cell: BarrierCell; labels: Record<string, string>; onChosen: (runId: string) => void;
}) {
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const counted = (cell.latest_result?.values ?? []).filter((v) => v.counted && v.document);
  const facts = [...new Set(counted.map((v) => v.fact))].filter((f) => counted.filter((v) => v.fact === f).length > 1);

  async function choose(fact: string) {
    setError(null);
    try {
      onChosen((await api.chooseBarrierValue(code, region, { fact, value_id: picked[fact], reason: reasons[fact] ?? "" })).run_id);
    } catch (err) {
      setError(errorDetail(err as Error));
    }
  }

  return (
    <div className="card">
      <h2>Choose the value that counts</h2>
      <p className="help-text">Sources disagree. Pick one value for each fact and say why; the cell is derived again with it.</p>
      {facts.map((fact) => (
        <fieldset key={fact}>
          <legend>{labels[fact] ?? fact}</legend>
          {counted.filter((v) => v.fact === fact).map((v) => (
            <label key={v.id} className="field-label checkbox-label">
              <input type="radio" name={`choice-${fact}`} checked={picked[fact] === v.id} onChange={() => setPicked((p) => ({ ...p, [fact]: v.id }))} />
              <span><span className="mono">{v.shown}</span>, {v.document}{v.page != null ? `, p. ${v.page}` : ""}</span>
            </label>
          ))}
          <div className="inline-fields">
            <label className="field-label">
              Reason
              <input value={reasons[fact] ?? ""} onChange={(e) => setReasons((r) => ({ ...r, [fact]: e.target.value }))} />
            </label>
            <button type="button" className="secondary" disabled={!picked[fact]} onClick={() => void choose(fact)}>Use this value</button>
          </div>
        </fieldset>
      ))}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}

export function BarrierCellDetail({ code, region }: { code: string; region: string }) {
  const [cell, setCell] = useState<BarrierCell | null>(null);
  const [criterion, setCriterion] = useState<BarrierCriterion | null>(null);
  const [criterionError, setCriterionError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [derived, setDerived] = useState<string | null>(null);
  const [deriveError, setDeriveError] = useState<string | null>(null);

  const load = useCallback(() => api.getBarrierCell(code, region).then(setCell).catch((e: Error) => setError(errorDetail(e))), [code, region]);
  useEffect(() => {
    void load();
    api.getBarrierCriterionDetail(code).then((d) => setCriterion(d.criterion), (e: Error) => setCriterionError(errorDetail(e)));
  }, [code, load]);

  async function derive() {
    setDeriveError(null);
    setDerived(null);
    try {
      setDerived((await api.deriveBarrierCells([{ code, region }])).run_id);
      void load();
    } catch (err) {
      setDeriveError(errorDetail(err as Error));
    }
  }

  if (error) return <p className="error-text" role="alert">{error}</p>;
  if (!cell) return <p className="muted">Loading the cell…</p>;

  const labels = Object.fromEntries((criterion?.facts ?? []).map((f) => [f.id, f.label]));
  const result = cell.latest_result;

  return (
    <div className="page">
      <p><a href="#/transitionBarrier">Transition Barriers</a></p>
      <h1>{cell.code} — {cell.region}</h1>
      <p className="muted">{cell.sector} / {cell.category} · {cell.criterion}</p>

      <div className="card">
        <h2>Current rating</h2>
        <p>
          <span className={RATING_CLASS[cell.rating]} title={RATING_LABEL[cell.rating]}>{cell.rating}</span>{" "}
          confidence <span className="mono">{cell.confidence}</span> · {ratifiedLine(cell)}
        </p>
        <p>{cell.evidence}</p>
        <p className="muted">Source: {cell.source}</p>
        {cell.flags.length > 0 && (
          <>
            <h3>Flags</h3>
            <ul>{cell.flags.map((f) => <li key={f}>{f}</li>)}</ul>
          </>
        )}
      </div>

      <div className="card">
        <div className="section-heading">
          <h2>Latest derivation</h2>
          <button type="button" className="secondary" onClick={() => void derive()}>Derive this cell</button>
        </div>
        {derived && (
          <p role="status">
            Derivation <span className="mono tb-wrap">{derived}</span> finished. <a href={`#/review/transition_barrier_derivation/${encodeURIComponent(derived)}`}>Review the result</a>
          </p>
        )}
        {deriveError && <p className="error-text" role="alert">{deriveError}</p>}
        {!result && <p className="muted">This cell has not been derived. Enter its facts below, then derive it.</p>}
        {result && (
          <>
            <p>
              Result{" "}
              {result.rating === "H" || result.rating === "M" || result.rating === "L" ? <span className={RATING_CLASS[result.rating as BarrierRating]}>{result.rating}</span> : <span className="mono">{result.rating}</span>}
              {" "}· confidence <span className="mono">{result.confidence}</span> · rule book v{result.rule_book_version} · run <span className="mono tb-wrap">{result.run_id}</span>
            </p>
            {result.missing_facts.length > 0 && <p>Missing facts: {result.missing_facts.join(", ")}</p>}
            {result.open_params.length > 0 && <p>Open thresholds: {result.open_params.join(", ")}</p>}
            {result.notes.map((n) => <p key={n} className="muted">{n}</p>)}
            {(["H", "M"] as const).map((level) => {
              const l = result.levels[level];
              return l && (
                <div key={level}>
                  <h3>
                    <span className={RATING_CLASS[level]}>{level}</span> <span className={outcomeClass(l.outcome)}>{l.outcome}</span>
                  </h3>
                  {l.detail && <p className="muted">{l.detail}</p>}
                  <ul>
                    {l.conditions.map((c) => (
                      <li key={c.text}>
                        <span className={outcomeClass(c.outcome)}>{c.outcome}</span> {c.text}
                        {c.clause && <div className="muted">{c.clause}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
            <h3>Figures</h3>
            {result.values.length === 0 ? <p className="muted">No figures yet.</p> : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>Fact</th><th>Value</th><th>Source</th><th>Quote</th><th>Confidence</th><th>Status</th></tr>
                  </thead>
                  <tbody>{result.values.map((v, i) => <Figure key={`${i}:${v.id}`} v={v} label={labels[v.fact] ?? v.fact} />)}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {result?.rating === "conflict" && <ConflictChoice code={code} region={region} cell={cell} labels={labels} onChosen={(runId) => { setDerived(runId); void load(); }} />}

      <div className="card">
        <h2>Enter a fact</h2>
        <p className="help-text">For a source the system cannot read. The quote must be word for word, and a number must appear in it.</p>
        {criterion ? (
          <BarrierFactForm code={code} region={region} facts={criterion.facts} sources={criterion.primary_sources} onAdded={() => void load()} />
        ) : criterionError ? (
          <p className="error-text" role="alert">The criterion could not be loaded: {criterionError}</p>
        ) : (
          <p className="muted">Loading the criterion…</p>
        )}
      </div>

      <div className="card">
        <h2>History</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>When</th><th>By</th><th>What</th></tr></thead>
            <tbody>
              {cell.history.map((h, i) => (
                <tr key={i}>
                  <td className="mono">{when(h.at)}</td>
                  <td>{h.by ?? <span className="muted">—</span>}</td>
                  <td>{historyLine(h)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
