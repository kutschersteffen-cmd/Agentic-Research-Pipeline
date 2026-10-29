import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { EU27, lensLine, nodeHash, pricePct, shockHash, signed } from "../../lib/valueChain";
import type { PortfolioSummary, VcNode, VcPriceShock, VcQuantityShock } from "../../types";
import { Bars } from "./NodeView";
import { useVcQuery } from "./useVcQuery";

type Model = "demand" | "supply" | "price";
type Target = "node" | "region" | "sector";
type Coverage = "all" | "eu27" | "home";

const MODELS: [Model, string][] = [
  ["demand", "Demand"],
  ["supply", "Supply dependency"],
  ["price", "Carbon price"],
];
const HEADINGS: Record<Model, string> = { demand: "Output change", supply: "Dependency indicator: output change", price: "Price change" };

function Toggle<T extends string>({ label, options, value, onChange }: { label: string; options: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div>
      <span className="field-label">{label}</span>
      <div className="view-toggle" role="group" aria-label={label}>
        {options.map(([key, text]) => (
          <button key={key} type="button" className={key === value ? "active" : ""} aria-pressed={key === value} onClick={() => onChange(key)}>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

// The generated type widens the API's [name, value] pairs to (string | number)[].
const bars = (pairs: VcQuantityShock["by_region"], fmt: (v: number) => string) =>
  pairs.map(([name, v]) => ({ key: String(name), label: <span>{name}</span>, value: fmt(Number(v)), size: Math.abs(Number(v)) }));

const meur = (v: number) => `${signed(v)} M EUR`;

function Results({ heading, total, tiles, byRegion, bySector, nodes, fmt }: {
  heading: string;
  total: string;
  tiles: [string, string][];
  byRegion: VcQuantityShock["by_region"];
  bySector: VcQuantityShock["by_sector"];
  nodes: { node_id: string; sector: string; region_label: string; value: number }[];
  fmt: (v: number) => string;
}) {
  return (
    <>
      <section className="card vc-total" aria-labelledby="vc-shock">
        <h2 id="vc-shock">{heading}</h2>
        <p className="vc-total-value">{total}</p>
        {tiles.length > 0 && (
          <div className="stat-tile-grid">
            {tiles.map(([label, value]) => (
              <div key={label} className="stat-tile">
                <span className="stat-value">{value}</span>
                <span className="stat-label">{label}</span>
              </div>
            ))}
          </div>
        )}
      </section>
      <div className="vc-columns">
        <section className="card" aria-label="By region">
          <h2>By region</h2>
          {byRegion.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(byRegion, fmt)} />}
        </section>
        <section className="card" aria-label="By sector">
          <h2>By sector (all regions)</h2>
          {bySector.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(bySector, fmt)} />}
        </section>
      </div>
      <section className="card" aria-label="Top nodes">
        <h2>Top nodes</h2>
        {nodes.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <Bars
            rows={nodes.map((n) => ({
              key: n.node_id,
              label: (
                <a href={nodeHash(n.node_id, "shock")}>
                  {n.sector} <span className="muted">· {n.region_label}</span>
                </a>
              ),
              value: fmt(n.value),
              size: Math.abs(n.value),
            }))}
          />
        )}
      </section>
    </>
  );
}

function quantityRequest(node: VcNode, model: "demand" | "supply", target: Target, change: number, portfolio: string) {
  const pick = target === "node" ? { node: [node.node_id] } : target === "region" ? { region: [node.region] } : { sector: [node.sector] };
  return api.valueChainShockQuantity({ model, change, focus: node.node_id, portfolio: portfolio || undefined, ...pick });
}

function priceRequest(node: VcNode, coverage: Coverage, carbon: number, portfolio: string) {
  const region = coverage === "eu27" ? EU27 : coverage === "home" ? [node.region] : [];
  return api.valueChainShockPrice({ carbon, region, focus: node.node_id, portfolio: portfolio || undefined });
}

/** "What happens if…?" for one node: a demand or supply shock on it, its region or its sector, or a carbon price. */
export function ShockView({ id, onTitle, initialPortfolio, onPortfolio }: {
  id: string;
  onTitle: (title: string) => void;
  initialPortfolio?: string;
  onPortfolio?: (portfolio: string) => void;
}) {
  const [model, setModel] = useState<Model>("demand");
  const [target, setTarget] = useState<Target>("node");
  const [coverage, setCoverage] = useState<Coverage>("all");
  const [changeText, setChangeText] = useState("-10");
  const [carbonText, setCarbonText] = useState("100");
  const [portfolio, setPortfolio] = useState(initialPortfolio ?? "");
  const portfolios = useVcQuery<PortfolioSummary[]>(() => api.listPortfolios(), []);
  const change = Number(changeText);
  const carbon = Number(carbonText);
  const quantity = model !== "price";
  const valid = quantity
    ? changeText.trim() !== "" && Number.isFinite(change) && change >= -100 && change <= 100
    : carbonText.trim() !== "" && Number.isFinite(carbon) && carbon >= 0 && carbon <= 10000;

  const nodeQ = useVcQuery(() => api.valueChainNode(id, { order: "total", excludeOwn: false }), [id]);
  const node = nodeQ.data;
  // Each result is kept with the request it answers, so a change never leaves the last scenario's numbers on screen.
  const requestKey = JSON.stringify([node?.node_id, model, target, coverage, change, carbon, portfolio]);
  const shockQ = useVcQuery<{ key: string; model: Model; q?: VcQuantityShock; p?: VcPriceShock } | null>(
    () =>
      !node || !valid
        ? null
        : model === "price"
          ? priceRequest(node, coverage, carbon, portfolio).then((p) => ({ key: requestKey, model, p }))
          : quantityRequest(node, model, target, change, portfolio).then((q) => ({ key: requestKey, model, q })),
    [requestKey, valid],
  );
  useEffect(() => {
    if (node) onTitle(`${node.sector} · ${node.region_label}`);
  }, [node, onTitle]);

  const r = valid && shockQ.data?.key === requestKey ? shockQ.data : null;
  const error = nodeQ.error ?? shockQ.error;
  const caveat = r?.q?.model_caveat ?? r?.p?.model_caveat;
  return (
    <>
      <div className="toolbar vc-tree-controls">
        <Toggle label="Model" options={MODELS} value={model} onChange={setModel} />
        {node && quantity && (
          <Toggle<Target>
            label="Target"
            options={[
              ["node", "This node"],
              ["region", `All of ${node.region_label}`],
              ["sector", `${node.sector} in all regions`],
            ]}
            value={target}
            onChange={setTarget}
          />
        )}
        {node && !quantity && (
          <Toggle<Coverage>
            label="Coverage"
            options={[
              ["all", "All regions"],
              ["eu27", "EU-27"],
              ["home", `${node.region_label} only`],
            ]}
            value={coverage}
            onChange={setCoverage}
          />
        )}
        {quantity ? (
          <label className="field-label vc-amount">
            Change (%)
            <input type="number" min={-100} max={100} step="any" value={changeText} onChange={(e) => setChangeText(e.target.value)} aria-invalid={!valid || undefined} />
            {!valid && <span className="error-text">Enter a change from −100 to 100.</span>}
          </label>
        ) : (
          <label className="field-label vc-amount">
            Price (EUR per t CO₂e)
            <input type="number" min={0} max={10000} step="any" value={carbonText} onChange={(e) => setCarbonText(e.target.value)} aria-invalid={!valid || undefined} />
            {!valid && <span className="error-text">Enter a price from 0 to 10,000.</span>}
          </label>
        )}
        <label className="field-label">
          Portfolio
          <select
            value={portfolio}
            onChange={(e) => {
              setPortfolio(e.target.value);
              onPortfolio?.(e.target.value);
              // replaceState: no hashchange, so the view keeps its model and inputs; a reload restores the lens
              history.replaceState(null, "", shockHash(id, e.target.value));
            }}
          >
            <option value="">None</option>
            {/* a portfolio from the URL that is not in the list (stale or mistyped link) stays selectable, so None can clear it */}
            {portfolio && portfolios.data && !portfolios.data.some((p) => p.portfolio_id === portfolio) && <option value={portfolio}>{portfolio}</option>}
            {(portfolios.data ?? []).map((p) => (
              <option key={p.portfolio_id} value={p.portfolio_id}>
                {p.name}
              </option>
            ))}
          </select>
          {portfolios.error && <span className="error-text">{portfolios.error}</span>}
        </label>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {valid && !error && !r && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {r && (
        <>
          <p className="help-text vc-note">{caveat}</p>
          {(r.q?.portfolio ?? r.p?.portfolio) && <p className="vc-coverage">{r.q ? lensLine("output", r.q.portfolio?.change_pct) : lensLine("price", r.p?.portfolio?.dp_pct)}</p>}
          {r.q && (
            <Results
              heading={HEADINGS[r.model]}
              total={`Δ output ${meur(r.q.total_meur)}`}
              tiles={[
                ["GHG", `${signed(r.q.indicators.ghg)} t CO₂e`],
                ["Energy", `${signed(r.q.indicators.energy)} TJ`],
                ["Jobs", `${signed(r.q.indicators.jobs)} people`],
              ]}
              byRegion={r.q.by_region}
              bySector={r.q.by_sector}
              nodes={r.q.nodes.map((n) => ({ ...n, value: n.delta_meur }))}
              fmt={meur}
            />
          )}
          {r.p && (
            <Results
              heading={HEADINGS.price}
              total={`this node ${pricePct(r.p.focus?.dp_pct ?? 0)}`}
              tiles={[]}
              byRegion={r.p.by_region}
              bySector={r.p.by_sector}
              nodes={r.p.nodes.map((n) => ({ ...n, value: n.dp_pct }))}
              fmt={pricePct}
            />
          )}
          {r.p && (
            <p className="help-text">
              {r.p.priced_t.toFixed(1)} t CO₂e priced · carbon cost {r.p.carbon_cost_meur.toFixed(1)} M EUR
            </p>
          )}
          <p className="help-text vc-note">{r.q?.caveat ?? r.p?.caveat}</p>
        </>
      )}
    </>
  );
}
