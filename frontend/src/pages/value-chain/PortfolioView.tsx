import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { activityLine, cents, pct1, pickerHits, portfolioHash, searchable, unresolvedText } from "../../lib/valueChain";
import type { PortfolioSummary, Taxonomy, VcIcioCode, VcLinkRuleIn, VcLinks, VcNodeRef, VcPortfolio } from "../../types";
import { Bars } from "./NodeView";
import { useVcQuery } from "./useVcQuery";

type Indicator = "ghg" | "energy" | "jobs";
const INDICATORS: [Indicator, string][] = [
  ["ghg", "CO₂e"],
  ["energy", "Energy"],
  ["jobs", "Jobs"],
];
type Mode = "default" | "split" | "nodes";
type Row = { key: number; code: string; region: string; sector: string; pct: string };
type Part = { icio_code?: string; region?: string; sector?: string; share: number };

let nextKey = 0;
const blankRow = (): Row => ({ key: nextKey++, code: "", region: "", sector: "", pct: "100" });

// The generated type widens the API's [name, value] pairs to (string | number)[].
const bars = (pairs: VcPortfolio["direct_by_region"], format: (v: number) => string) =>
  pairs.map(([name, v]) => ({ key: String(name), label: <span>{name}</span>, value: format(Number(v)), size: Number(v) }));

/** The explorer's search over sectors and regions, picking one node for a link editor row. */
export function NodeSearch({ row, onPick }: { row: Pick<Row, "region" | "sector">; onPick: (n: VcNodeRef) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<VcNodeRef[]>([]);
  useEffect(() => {
    if (!searchable(q)) {
      setHits([]);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      // A region after a comma filters a wider sector search: one sector spans every region.
      pickerHits(q, (text, limit) => api.valueChainSearch(text, limit).then((r) => r.items)).then(
        (items) => live && setHits(items),
        () => live && setHits([]),
      );
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q]);
  return (
    <div className="vc-node-search">
      <label className="field-label">
        Node
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={row.sector ? `${row.region} · ${row.sector}` : "e.g. copper, CN"} />
      </label>
      {row.sector && (
        <span className="muted">
          {row.region} · {row.sector}
        </span>
      )}
      {hits.length > 0 && (
        <ul className="vc-hits">
          {hits.map((h) => (
            <li key={h.node_id}>
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  onPick(h);
                  setQ("");
                }}
              >
                {h.sector} <span className="muted">· {h.region}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The panel behind `Edit link`: the current source, any parts the build lacks, and a split or node rule to save. */
function LinkEditor({ subject, title, isCompany, codes, onChanged, onClose }: {
  subject: string; title: string; isCompany: boolean; codes: VcIcioCode[]; onChanged: () => void; onClose: () => void;
}) {
  const [version, setVersion] = useState(0);
  const current = useVcQuery<VcLinks>(() => api.valueChainLinks(subject), [subject, version]);
  const [mode, setMode] = useState<Mode | null>(null);
  const [rows, setRows] = useState<Row[]>([blankRow()]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => panel.current?.scrollIntoView?.({ block: "nearest" }), []);

  // The first load sets the mode and rows from the stored rule.
  const links = current.data;
  useEffect(() => {
    if (!links || mode !== null) return;
    const rule = links.rule;
    const kind: Mode = rule?.kind === "split" || rule?.kind === "nodes" ? rule.kind : "default";
    setMode(kind);
    if (kind !== "default" && rule) {
      setRows((rule.parts as Part[]).map((p) => ({ ...blankRow(), code: p.icio_code ?? "", region: p.region ?? "", sector: p.sector ?? "", pct: String(Number((p.share * 100).toFixed(6))) })));
    }
  }, [links, mode]);

  const modes: [Mode, string][] = [["default", "Default"], ...(isCompany ? [["split", "Revenue split"] as [Mode, string]] : []), ["nodes", "Nodes"]];
  const setRow = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setVersion((v) => v + 1);
      onChanged();
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const save = () => {
    const kind = mode === "split" ? "split" : "nodes";
    const parts = rows.map((r) =>
      kind === "split" ? { icio_code: r.code, share: Number(r.pct) / 100 } : { region: r.region, sector: r.sector, share: Number(r.pct) / 100 },
    );
    return run(() => api.saveValueChainLinks(subject, { kind, parts } as VcLinkRuleIn));
  };
  const reset = () =>
    run(async () => {
      await api.resetValueChainLinks(subject);
      setMode("default");
      setRows([blankRow()]);
    });

  return (
    <section ref={panel} className="card vc-editor" aria-label="Link editor">
      <div className="vc-editor-head">
        <h2>Link: {title}</h2>
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>
      {current.error && (
        <p className="error-text" role="alert">
          {current.error}
        </p>
      )}
      {links && (
        <>
          <p>
            Current source: <strong>{links.source}</strong>
          </p>
          {(links.unresolved as Part[]).map((p) => (
            <p key={JSON.stringify(p)} className="warning-banner">
              {unresolvedText(p)}
            </p>
          ))}
        </>
      )}
      <div className="view-toggle" role="group" aria-label="Link mode">
        {modes.map(([m, label]) => (
          <button key={m} type="button" className={m === mode ? "active" : ""} aria-pressed={m === mode} onClick={() => {
              // the other mode's rows (codes vs. nodes) would be sent as empty fields
              if (m !== mode) setRows([blankRow()]);
              setMode(m);
            }}>
            {label}
          </button>
        ))}
      </div>
      {mode === "default" ? (
        <p className="help-text">{isCompany ? "Uses the company's own industry code and country." : "Uses the activity's core industry codes, in every region."}</p>
      ) : (
        mode && (
          <>
            <ul className="vc-editor-rows">
              {rows.map((r) => (
                <li key={r.key}>
                  {mode === "split" ? (
                    <label className="field-label">
                      ICIO code
                      <select value={r.code} onChange={(e) => setRow(r.key, { code: e.target.value })}>
                        <option value="">Pick a code</option>
                        {codes.map((c) => (
                          <option key={c.code} value={c.code}>
                            {c.code} · {c.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <NodeSearch row={r} onPick={(n) => setRow(r.key, { region: n.region, sector: n.sector })} />
                  )}
                  <label className="field-label vc-share">
                    Share %
                    <input type="number" min={0} max={100} step="any" value={r.pct} onChange={(e) => setRow(r.key, { pct: e.target.value })} />
                  </label>
                  {rows.length > 1 && (
                    <button type="button" className="secondary" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} aria-label="Remove row">
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {rows.length < 20 && (
              <button type="button" className="secondary" onClick={() => setRows((rs) => [...rs, { ...blankRow(), pct: "" }])}>
                Add row
              </button>
            )}
          </>
        )
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="toolbar">
        {mode !== "default" && (
          <button type="button" onClick={save} disabled={busy || mode === null}>
            Save
          </button>
        )}
        <button type="button" className="secondary" onClick={reset} disabled={busy}>
          Reset to default
        </button>
      </div>
    </section>
  );
}

/** `#/valueChain/portfolio[/<portfolio id>]`: a portfolio's holdings on value-chain nodes, its upstream and its footprint. */
export function PortfolioView({ id }: { id?: string }) {
  const [asOf, setAsOf] = useState("");
  const [indicator, setIndicator] = useState<Indicator>("ghg");
  const [taxonomyId, setTaxonomyId] = useState("");
  const [activityId, setActivityId] = useState("");
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState<{ subject: string; title: string; isCompany: boolean } | null>(null);
  const portfolios = useVcQuery<PortfolioSummary[]>(() => api.listPortfolios(), []);
  const taxonomies = useVcQuery(() => api.listTaxonomies().then((r) => r.taxonomies as Taxonomy[]), []);
  const codes = useVcQuery<VcIcioCode[]>(() => api.valueChainCodes(), []);
  const lens = taxonomyId && activityId ? { taxonomy: taxonomyId, activity: activityId } : {};
  const overlay = useVcQuery<VcPortfolio>(
    () => (id ? api.valueChainPortfolio(id, { asOf, indicator, ...lens }) : null),
    [id, asOf, indicator, taxonomyId, activityId, reload],
  );
  const o = overlay.data;
  const activities = taxonomies.data?.find((t) => t.taxonomy_id === taxonomyId)?.theme.activities ?? [];
  const error = portfolios.error ?? overlay.error;

  return (
    <>
      <div className="toolbar vc-portfolio-controls">
        <label className="field-label">
          Portfolio
          <select value={id ?? ""} onChange={(e) => (window.location.hash = portfolioHash(e.target.value || undefined))}>
            <option value="">Pick a portfolio</option>
            {(portfolios.data ?? []).map((p) => (
              <option key={p.portfolio_id} value={p.portfolio_id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Snapshot on or before
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </label>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!id && <p className="muted">Pick a portfolio.</p>}
      {id && !o && !error && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {o && (
        <div aria-busy={overlay.loading}>
          <p className="vc-coverage">
            Linked {pct1(o.linked_weight)} of NAV · footprint covers {pct1(o.attributed_weight)}
          </p>
          <p className="muted">Snapshot {o.as_of}</p>
          <section className="card vc-total" aria-labelledby="vc-pf-fp">
            <div className="vc-editor-head">
              <h2 id="vc-pf-fp">Footprint</h2>
              <div className="view-toggle" role="group" aria-label="Indicator">
                {INDICATORS.map(([key, label]) => (
                  <button key={key} type="button" className={key === indicator ? "active" : ""} aria-pressed={key === indicator} onClick={() => setIndicator(key)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <p className="vc-total-value">
              {o.footprint.per_meur_invested === null ? "—" : `${o.footprint.per_meur_invested.toFixed(1)} ${o.footprint.unit} per M EUR invested`}
            </p>
            <p className="help-text vc-note">Whole supply chain of the attributed holdings' share of company output (EVIC-attributed).</p>
          </section>
          <div className="vc-columns">
            <section className="card" aria-label="Direct region mix">
              <h2>Direct region mix</h2>
              {o.direct_by_region.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(o.direct_by_region, pct1)} />}
            </section>
            <section className="card" aria-label="Upstream by region">
              <h2>Upstream by region</h2>
              <p className="help-text">Cents from each region per € of the linked holdings' output.</p>
              {o.upstream_by_region.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(o.upstream_by_region, (v) => cents(v))} />}
            </section>
            <section className="card" aria-label="Upstream by sector">
              <h2>Upstream by sector</h2>
              <p className="help-text">Cents from each sector, all regions.</p>
              {o.upstream_by_sector.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(o.upstream_by_sector, (v) => cents(v))} />}
            </section>
          </div>
          <section className="card" aria-label="Holdings">
            <h2>Holdings</h2>
            <table className="data-table stack-on-phone">
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="num">Weight</th>
                  <th>Link source</th>
                  <th>Top node</th>
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {o.holdings.map((h) => (
                  <tr key={h.security_id}>
                    <td data-label="Name">{h.name}</td>
                    <td data-label="Weight" className="num">
                      {pct1(h.weight)}
                    </td>
                    <td data-label="Link source">{h.link_source}</td>
                    <td data-label="Top node">{h.top_node ? `${h.top_node.region_label} · ${h.top_node.sector} ${pct1(h.top_node.weight)}` : "—"}</td>
                    <td>
                      {h.company_id && (
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => setEditing({ subject: `company/${encodeURIComponent(h.company_id!)}`, title: h.name, isCompany: true })}
                        >
                          Edit link
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
      {id && (
        <section className="card" aria-label="Activity">
          <h2>Activity</h2>
          <div className="toolbar">
            <label className="field-label">
              Taxonomy
              <select
                value={taxonomyId}
                onChange={(e) => {
                  setTaxonomyId(e.target.value);
                  setActivityId("");
                }}
              >
                <option value="">Pick a taxonomy</option>
                {(taxonomies.data ?? []).map((t) => (
                  <option key={t.taxonomy_id} value={t.taxonomy_id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              Activity
              <select value={activityId} onChange={(e) => setActivityId(e.target.value)} disabled={!taxonomyId}>
                <option value="">Pick an activity</option>
                {activities.map((a) => (
                  <option key={a.activity_id} value={a.activity_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {o?.activity && (
            <p className="vc-activity">
              {activityLine(o.activity)}{" "}
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setEditing({
                    subject: `activity/${encodeURIComponent(o.activity!.taxonomy_id)}/${encodeURIComponent(o.activity!.activity_id)}`,
                    title: o.activity!.name,
                    isCompany: false,
                  })
                }
              >
                Edit link
              </button>
            </p>
          )}
        </section>
      )}
      {editing && (
        <LinkEditor
          key={editing.subject}
          {...editing}
          codes={codes.data ?? []}
          onChanged={() => setReload((r) => r + 1)}
          onClose={() => setEditing(null)}
        />
      )}
      {o && <p className="help-text vc-note">{o.caveat}</p>}
    </>
  );
}
