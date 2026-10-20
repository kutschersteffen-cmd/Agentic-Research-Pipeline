import type { ReactNode } from "react";
import { api } from "../../api/client";
import { FileLink } from "../../components/FileLink";
import { RATING_CLASS, sourceHref } from "../../lib/barrier";
import type { BarrierRating, BarrierValue, CompanyTransition, TransitionAction, TransitionShare } from "../../types";
import { barrierFigure, fmtNumber as num } from "./companyQuery";

type OpenFact = (factId: number, el: HTMLElement) => void;


function FactButton({ factId, onOpenFact, mono = true, children }: { factId: number; onOpenFact: OpenFact; mono?: boolean; children: ReactNode }) {
  return (
    <button type="button" className={mono ? "link-button mono" : "link-button"} onClick={(e) => onOpenFact(factId, e.currentTarget)}>
      {children}
    </button>
  );
}

function Share({ label, share, onOpenFact }: { label: string; share: TransitionShare | null; onOpenFact: OpenFact }) {
  const text = share && `${num(share.value)}%`;
  return (
    <tr>
      <td data-label="Capex">{label}</td>
      <td data-label="Share" className="mono">
        {!share ? "—" : share.fact_ids.length ? <FactButton factId={share.fact_ids[0]} onOpenFact={onOpenFact}>{text}</FactButton> : text}
      </td>
      <td data-label="Basis">{share?.source ?? "not known"}</td>
    </tr>
  );
}

/** A barrier figure opening its barrier citation, as the barrier cell's Figures table does. */
function BarrierFigure({ v }: { v: BarrierValue }) {
  const text = barrierFigure(v);
  if (v.document_id != null) return <FileLink url={api.barrierDocumentUrl(v.document_id, v.page)} name={`document-${v.document_id}.pdf`} open>{text}</FileLink>;
  const href = sourceHref(v);
  return href ? <a href={href} target="_blank" rel="noopener noreferrer">{text}</a> : <>{text}</>;
}

function Action({ a, onOpenFact }: { a: TransitionAction; onOpenFact: OpenFact }) {
  const b02 = (k: string) => {
    const r = a.b02[k];
    return r?.fact_ids.length ? <FactButton factId={r.fact_ids[0]} onOpenFact={onOpenFact} mono={false}>{r.text}</FactButton> : r?.text;
  };
  const items: [string, ReactNode][] = [
    ["Action id", a.action_id ?? "—"],
    ["ACT lever", a.act_lever ? `${a.act_lever.wording} (${a.act_lever.citation})` : "No ACT Core lever wording"],
    ["Status", a.status ?? "—"],
    ["Timeframe", a.timeframe ?? "—"],
    ["Region", a.region ?? "—"],
    ["B02.b", b02("b")],
    ["B02.c", b02("c")],
    ["B02.d", b02("d")],
  ];
  return (
    <article aria-label={a.text}>
      <h4>
        {a.fact_ids.length ? (
          <button type="button" className="link-button" style={{ textAlign: "left" }} onClick={(e) => onOpenFact(a.fact_ids[0], e.currentTarget)}>{a.text}</button>
        ) : a.text}
      </h4>
      {a.citation && <p className="muted">{a.citation}</p>}
      <dl className="company-ids">
        {items.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className={k === "Action id" ? "mono" : undefined}>{v}</dd></div>)}
      </dl>
      {a.note && <p>{a.note}</p>}
      {a.barriers.length > 0 && (
        <div className="table-wrap">
          <table className="data-table stack-on-phone">
            <caption className="visually-hidden">Barrier criteria matched to this action; choose a figure to open its source</caption>
            <thead>
              <tr><th scope="col">Region</th><th scope="col">Criterion</th><th scope="col">Rating</th><th scope="col">Basis</th><th scope="col">Evidence</th><th scope="col">Figures</th></tr>
            </thead>
            <tbody>
              {a.barriers.map((b) => (
                <tr key={`${b.region}:${b.code}`}>
                  <td data-label="Region">{b.region}</td>
                  <td data-label="Criterion" className="mono">{b.code}</td>
                  <td data-label="Rating">{b.rating ? <span className={RATING_CLASS[b.rating as BarrierRating] ?? "badge badge-neutral"}>{b.rating}</span> : "not rated"}</td>
                  <td data-label="Basis">{b.basis ?? "—"}</td>
                  <td data-label="Evidence">{b.evidence || "—"}</td>
                  <td data-label="Figures">
                    {b.values.length ? <span>{b.values.map((v, i) => <span key={v.id}>{i > 0 && ", "}<BarrierFigure v={v} /></span>)}</span> : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

/** The company's transition check against its sector benchmarks (spec section 6); each company figure opens its fact. */
export function TransitionSection({ data, error, onOpenFact }: { data: CompanyTransition | null; error: string; onOpenFact: OpenFact }) {
  const c = data?.capex;
  const ry = c?.reporting_year;
  return (
    <section className="page-body" aria-labelledby="transition-heading">
      <h2 id="transition-heading">Transition</h2>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!data && !error && <p className="muted" role="status">Loading…</p>}
      {data && !data.in_scope && <p>Not in scope: {data.reason}</p>}
      {data && c && (
        <>
          <p className="muted company-meta">
            {[data.sector, ry != null && `reporting year ${ry}`, `benchmarks v${data.benchmarks_version}`].filter(Boolean).join(" · ")}
          </p>
          <p><strong>{c.headline}</strong></p>
          <div className="table-wrap">
            <table className="data-table stack-on-phone">
              <caption className="visually-hidden">Low-carbon capex share; choose a share to open its source</caption>
              <thead>
                <tr><th scope="col">Capex</th><th scope="col">Share</th><th scope="col">Basis</th></tr>
              </thead>
              <tbody>
                <Share label={`RY${ry != null ? ` ${ry}` : ""}`} share={c.share_ry} onOpenFact={onOpenFact} />
                <Share label={`RY+1${ry != null ? ` ${ry + 1}` : ""}`} share={c.share_ry1} onOpenFact={onOpenFact} />
                <tr>
                  <td data-label="Capex">Share used</td>
                  <td data-label="Share" className="mono">{c.share_used_shown != null ? `${c.share_used_shown}%` : "—"}</td>
                  <td data-label="Basis">{c.rule ?? c.not_scored}</td>
                </tr>
                <tr>
                  <td data-label="Capex">Benchmark</td>
                  <td data-label="Share" className="mono">{num(c.benchmark.value)}{c.benchmark.unit === "%" ? "%" : ` ${c.benchmark.unit}`}</td>
                  <td data-label="Basis">
                    {c.benchmark.method} ·{" "}
                    {c.benchmark.url ? <a href={c.benchmark.url} target="_blank" rel="noopener noreferrer">{c.benchmark.citation}</a> : c.benchmark.citation}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {c.amounts.length > 0 && (
            <div className="table-wrap">
              <table className="data-table stack-on-phone">
                <caption className="visually-hidden">Amounts; choose one to open its source</caption>
                <thead>
                  <tr><th scope="col">Figure</th><th scope="col">Year</th><th scope="col">Amount</th><th scope="col">Source</th></tr>
                </thead>
                <tbody>
                  {c.amounts.map((a) => (
                    <tr key={`${a.field_id}:${a.year}`}>
                      <td data-label="Figure" className="mono">{a.field_id}</td>
                      <td data-label="Year" className="mono">{a.year}</td>
                      <td data-label="Amount"><FactButton factId={a.fact_id} onOpenFact={onOpenFact}>{a.shown}</FactButton></td>
                      <td data-label="Source">{a.citation ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {c.rnd_tests.length > 0 && (
            <div className="table-wrap">
              <table className="data-table stack-on-phone">
                <caption className="visually-hidden">R&amp;D tests</caption>
                <thead>
                  <tr><th scope="col">R&amp;D test</th><th scope="col">Used</th><th scope="col">Rule</th><th scope="col">Benchmark</th><th scope="col">Ratio</th></tr>
                </thead>
                <tbody>
                  {c.rnd_tests.map((t) => (
                    <tr key={t.id}>
                      <td data-label="R&D test">{t.label}</td>
                      <td data-label="Used" className="mono">{t.used != null ? `${num(t.used)}%` : "—"}</td>
                      <td data-label="Rule">{t.rule ?? t.not_scored}</td>
                      <td data-label="Benchmark" className="mono">{num(t.benchmark)}%</td>
                      <td data-label="Ratio" className="mono">{t.ratio_shown ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {c.redlines.length > 0 && (
            <div className="table-wrap">
              <table className="data-table stack-on-phone">
                <caption className="visually-hidden">Redlines</caption>
                <thead>
                  <tr><th scope="col">Redline</th><th scope="col">Status</th><th scope="col">Source</th></tr>
                </thead>
                <tbody>
                  {c.redlines.map((r) => (
                    <tr key={r.id}>
                      <td data-label="Redline">{r.text}</td>
                      <td data-label="Status" className="mono">{r.status}</td>
                      <td data-label="Source">
                        {r.fact_id != null ? <FactButton factId={r.fact_id} onOpenFact={onOpenFact} mono={false}>{r.citation ?? "open fact"}</FactButton> : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="muted">{c.licence_note}</p>
        </>
      )}
      {data?.in_scope && (
        <>
          <h3>Plan actions</h3>
          {data.actions.length === 0 && <p className="muted">No plan actions disclosed</p>}
          {data.actions.map((a) => <Action key={a.key} a={a} onOpenFact={onOpenFact} />)}
          {data.b02a && <p><strong>B02.a: {data.b02a.text}</strong></p>}

          <h3>Assumptions vs evidence</h3>
          {data.assumptions.every((x) => x.comparisons.length === 0) ? (
            <p className="muted">No assumptions compared</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table stack-on-phone">
                <caption className="visually-hidden">Plan assumptions against barrier evidence; choose an assumption to open its source</caption>
                <thead>
                  <tr><th scope="col">Criterion</th><th scope="col">Region</th><th scope="col">Assumption</th><th scope="col">Evidence</th><th scope="col">Gap</th></tr>
                </thead>
                <tbody>
                  {data.assumptions.flatMap((x) => x.comparisons.map((cmp) => (
                    <tr key={`${x.fact_id}:${cmp.region}:${cmp.code}`}>
                      <td data-label="Criterion" className="mono">{cmp.code}</td>
                      <td data-label="Region">{cmp.region}</td>
                      <td data-label="Assumption">
                        <FactButton factId={x.fact_id} onOpenFact={onOpenFact}>{cmp.assumption ?? cmp.reason ?? "—"}</FactButton>
                        {x.citation && <span className="muted"> {x.citation}</span>}
                      </td>
                      <td data-label="Evidence">{cmp.evidence}</td>
                      <td data-label="Gap" className="mono">{cmp.gap ?? cmp.reason ?? "—"}</td>
                    </tr>
                  )))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
