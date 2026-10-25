import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { footprintTotal, homeShare } from "../../lib/valueChain";
import type { VcFootprint } from "../../types";
import { Bars } from "./NodeView";
import { useVcQuery } from "./useVcQuery";

type Indicator = "ghg" | "energy" | "jobs";
const INDICATORS: [Indicator, string][] = [
  ["ghg", "CO₂e"],
  ["energy", "Energy"],
  ["jobs", "Jobs"],
];

// The generated type widens the API's [name, value] pairs to (string | number)[].
const bars = (pairs: VcFootprint["by_region"], unit: string) =>
  pairs.map(([name, v]) => ({ key: String(name), label: <span>{name}</span>, value: footprintTotal(Number(v), unit), size: Number(v) }));

/** Footprint of final demand for one node: the total, the home-region share, and where it arises. */
export function FootprintView({ id, onTitle }: { id: string; onTitle: (title: string) => void }) {
  const [indicator, setIndicator] = useState<Indicator>("ghg");
  const [amountText, setAmountText] = useState("1");
  const amount = Number(amountText);
  const valid = amountText.trim() !== "" && Number.isFinite(amount) && amount > 0;
  // The footprint answer has no home region; the node gives it and the heading.
  const nodeQ = useVcQuery(() => api.valueChainNode(id, { order: "total", excludeOwn: false }), [id]);
  const fpQ = useVcQuery(() => (valid ? api.valueChainFootprint(id, { indicator, amount }) : null), [id, indicator, amount, valid]);
  const node = nodeQ.data;
  const fp = valid ? fpQ.data : null;
  const error = nodeQ.error ?? fpQ.error;
  useEffect(() => {
    if (node) onTitle(`${node.sector} · ${node.region_label}`);
  }, [node, onTitle]);

  const share = node && fp ? homeShare(fp.in_home_region, node.region_label) : "";
  return (
    <>
      <div className="toolbar">
        <label className="field-label vc-amount">
          Amount (€ million)
          <input type="number" min={0} step="any" value={amountText} onChange={(e) => setAmountText(e.target.value)} aria-invalid={!valid || undefined} />
          {!valid && <span className="error-text">Enter an amount above 0.</span>}
        </label>
        <div>
          <span className="field-label" id="vc-indicator">
            Indicator
          </span>
          <div className="view-toggle" role="group" aria-labelledby="vc-indicator">
            {INDICATORS.map(([key, label]) => (
              <button key={key} type="button" className={key === indicator ? "active" : ""} aria-pressed={key === indicator} onClick={() => setIndicator(key)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {valid && !error && !(node && fp) && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {node && fp && (
        <>
          <section className="card vc-total" aria-labelledby="vc-fp" aria-busy={fpQ.loading}>
            <h2 id="vc-fp">Footprint</h2>
            <p>
              <span className="vc-total-value">{footprintTotal(fp.total, fp.unit)}</span>{" "}
              <span className="muted">whole supply chain{share && ` · ${share}`}</span>
            </p>
          </section>
          <div className="vc-columns" aria-busy={fpQ.loading}>
            <section className="card" aria-label="By region">
              <h2>By region</h2>
              {fp.by_region.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(fp.by_region, fp.unit)} />}
            </section>
            <section className="card" aria-label="By sector">
              <h2>By sector (all regions)</h2>
              {fp.by_sector.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(fp.by_sector, fp.unit)} />}
            </section>
          </div>
          <p className="help-text vc-note">{fp.caveat}</p>
        </>
      )}
    </>
  );
}
