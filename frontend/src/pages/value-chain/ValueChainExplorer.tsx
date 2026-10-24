import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { nodeHash, searchable } from "../../lib/valueChain";
import type { VcNodeRef } from "../../types";
import { FootprintView } from "./FootprintView";
import { NodeView } from "./NodeView";
import { TreeView } from "./TreeView";

const VIEWS = [
  [undefined, "Node page"],
  ["tree", "Upstream tree"],
  ["footprint", "Footprint"],
] as const;

/** Search box over sectors and regions; each hit links to its node page. */
function Picker({ onError }: { onError: (message: string) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<VcNodeRef[] | null>(null);

  useEffect(() => {
    if (!searchable(q)) {
      setHits(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      api
        .valueChainSearch(q)
        .then((r) => live && setHits(r.items))
        .catch((err) => live && onError(apiMessage(err)));
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q, onError]);

  return (
    <section className="card" aria-label="Pick a node">
      <label className="field-label">
        Sector or region
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. copper, DE, RoW Asia-Pacific" />
      </label>
      {hits !== null &&
        (hits.length === 0 ? (
          <p className="muted">No sector or region matches.</p>
        ) : (
          <ul className="vc-hits">
            {hits.map((h) => (
              <li key={h.node_id}>
                <a href={nodeHash(h.node_id)}>
                  {h.sector} <span className="muted">· {h.region_label}</span>
                </a>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}

/** `#/valueChain[/<node id>[/tree|/footprint]]`: picker on top, then the chosen view. */
export function ValueChainExplorer({ params }: { params: string[] }) {
  const [id, sub] = params;
  const view = sub === "tree" || sub === "footprint" ? sub : undefined;
  const [message, setMessage] = useState<string | null>(null);
  const [caveat, setCaveat] = useState<string | null>(null);

  // Before a node is picked, the status call says whether the data is built and gives the caveat.
  useEffect(() => {
    if (id) return;
    api
      .valueChainStatus()
      .then((s) => setCaveat(s.caveat))
      .catch((err) => setMessage(apiMessage(err)));
  }, [id]);

  return (
    <div className="page">
      <h1>Value Chain Explorer</h1>
      <p className="help-text">Pick a sector in a region to see who it buys from, who it sells to, and what it takes to make one euro of its&nbsp;output.</p>
      {message && (
        <p className="error-text" role="alert">
          {message}
        </p>
      )}
      <Picker onError={setMessage} />
      {!id ? (
        <>
          <p className="muted">Pick a sector and region.</p>
          {caveat && <p className="help-text vc-note">{caveat}</p>}
        </>
      ) : (
        <>
          <nav className="sub-nav" aria-label="Views">
            {VIEWS.map(([v, label]) => (
              <a key={label} href={nodeHash(id, v)} className={v === view ? "nav-tab active" : "nav-tab"} aria-current={v === view ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
          {view === "tree" ? <TreeView id={id} /> : view === "footprint" ? <FootprintView id={id} /> : <NodeView id={id} />}
        </>
      )}
    </div>
  );
}
