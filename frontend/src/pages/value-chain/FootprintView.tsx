import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { footprintTotal, homeShare } from "../../lib/valueChain";
import type { VcFootprint, VcNode } from "../../types";
import { Bars } from "./NodeView";

type Indicator = "ghg" | "energy" | "jobs";
const INDICATORS: [Indicator, string][] = [
  ["ghg", "CO₂e"],
  ["energy", "Energy"],
  ["jobs", "Jobs"],
];

/** Footprint of final demand for one node: the total, the home-region share, and where it arises. */
export function FootprintView({ id }: { id: string }) {
  const [indicator, setIndicator] = useState<Indicator>("ghg");
  const [amountText, setAmountText] = useState("1");
  const [node, setNode] = useState<VcNode | null>(null);
  const [fp, setFp] = useState<VcFootprint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const amount = Number(amountText);
  const valid = amountText.trim() !== "" && Number.isFinite(amount) && amount > 0;

  // The footprint answer has no home region; the node gives it and the heading.
  useEffect(() => {
    let live = true;
    api
      .valueChainNode(id, { order: "total", excludeOwn: false })
      .then((n) => live && setNode(n))
      .catch((err) => live && setError(apiMessage(err)));
    return () => {
      live = false;
    };
  }, [id]);

  useEffect(() => {
    if (!valid) return;
    let live = true;
    api
      .valueChainFootprint(id, { indicator, amount })
      .then((f) => live && setFp(f))
      .catch((err) => live && setError(apiMessage(err)));
    return () => {
      live = false;
    };
  }, [id, indicator, amount, valid]);

  if (error)
    return (
      <p className="error-text" role="alert">
        {error}
      </p>
    );
  if (!node || !fp) return <p className="muted">Loading…</p>;
  const share = homeShare(fp.in_home_region, node.region_label);
  // The generated type widens the API's [name, value] pairs to (string | number)[].
  const bars = (pairs: VcFootprint["by_region"]) =>
    pairs.map(([name, v]) => ({ key: String(name), label: <span>{name}</span>, value: footprintTotal(Number(v), fp.unit), size: Number(v) }));
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
      <section className="card vc-total" aria-labelledby="vc-fp">
        <h2 id="vc-fp">
          Footprint · {node.sector} · {node.region_label}
        </h2>
        <p>
          <span className="vc-total-value">{footprintTotal(fp.total, fp.unit)}</span>{" "}
          <span className="muted">whole supply chain{share && ` · ${share}`}</span>
        </p>
      </section>
      <div className="vc-columns">
        <section className="card" aria-label="By region">
          <h2>By region</h2>
          {fp.by_region.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(fp.by_region)} />}
        </section>
        <section className="card" aria-label="By sector">
          <h2>By sector (all regions)</h2>
          {fp.by_sector.length === 0 ? <p className="muted">None.</p> : <Bars rows={bars(fp.by_sector)} />}
        </section>
      </div>
      <p className="help-text vc-note">{fp.caveat}</p>
    </>
  );
}
