import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { linkText, nodeHash, percent, tile } from "../../lib/valueChain";
import type { VcLink, VcNode } from "../../types";

export type Bar = { key: string; label: ReactNode; value: string; size: number };

/** A ranked list where each row carries a bar scaled to the list's largest value. */
export function Bars({ rows }: { rows: Bar[] }) {
  const max = Math.max(...rows.map((r) => r.size));
  return (
    <ol className="vc-bars">
      {rows.map((r) => (
        <li key={r.key}>
          <div className="vc-bar-head">
            {r.label}
            <span className="mono">{r.value}</span>
          </div>
          <div className="vc-bar">
            <div style={{ width: `${(100 * r.size) / max}%` }} />
          </div>
        </li>
      ))}
    </ol>
  );
}

const HELP = {
  suppliers: {
    total: "Cents needed from each sector per € of output, counting suppliers of suppliers.",
    direct: "Cents bought directly from each supplier per € of output.",
  },
  customers: {
    total: "Cents of each sector's output that rest on €1 from this sector, counting intermediaries. Can add up to more than €1.",
    direct: "Cents of every € of output sold directly to each customer.",
  },
};

function Links({ title, links, mode, help }: { title: string; links: VcLink[]; mode: "total" | "direct"; help: string }) {
  return (
    <section className="card" aria-label={title}>
      <h2>{title}</h2>
      <p className="help-text">{help}</p>
      {links.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <Bars
          rows={links.map((l) => ({
            key: l.node_id,
            label: (
              <a href={nodeHash(l.node_id)}>
                {l.sector} <span className="muted">· {l.region_label}</span>
              </a>
            ),
            value: linkText(l, mode),
            size: l[mode],
          }))}
        />
      )}
    </section>
  );
}

/** Node page: intensity tiles, then top suppliers and customers by total or direct flow. */
export function NodeView({ id }: { id: string }) {
  const [mode, setMode] = useState<"total" | "direct">("total");
  const [excludeOwn, setExcludeOwn] = useState(false);
  const [node, setNode] = useState<VcNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .valueChainNode(id, { order: mode, excludeOwn })
      .then((n) => {
        if (!live) return;
        setNode(n);
        setError(null);
      })
      .catch((err) => live && setError(apiMessage(err)));
    return () => {
      live = false;
    };
  }, [id, mode, excludeOwn]);

  if (error)
    return (
      <p className="error-text" role="alert">
        {error}
      </p>
    );
  if (!node) return <p className="muted">Loading…</p>;
  const tiles = [
    ["CO₂e", tile(node.ghg_t_per_meur), "t per €1M output"],
    ["Energy", tile(node.energy_tj_per_meur), "TJ per €1M output"],
    ["Jobs", tile(node.jobs_per_meur), "people per €1M output"],
    ["Value added", percent(node.va_share), "of output"],
  ];
  return (
    <>
      <section className="card" aria-labelledby="vc-node">
        <h2 id="vc-node">
          {node.sector} · {node.region_label}
        </h2>
        <div className="stat-tile-grid">
          {tiles.map(([label, value, unit]) => (
            <div key={label} className="stat-tile">
              <span className="stat-value">{value}</span>
              <span className="stat-label">
                {label} · {unit}
              </span>
            </div>
          ))}
        </div>
        <p className="help-text">Direct, at the sector itself. The footprint view adds everything upstream.</p>
      </section>
      <div className="toolbar">
        <div className="view-toggle" role="group" aria-label="Measure">
          {(["total", "direct"] as const).map((m) => (
            <button key={m} type="button" className={m === mode ? "active" : ""} aria-pressed={m === mode} onClick={() => setMode(m)}>
              {m === "total" ? "Total" : "Direct"}
            </button>
          ))}
        </div>
        <label className="checkbox-label">
          <input type="checkbox" checked={excludeOwn} onChange={(e) => setExcludeOwn(e.target.checked)} /> Hide this node
        </label>
      </div>
      <div className="vc-columns">
        <Links title="Suppliers · upstream" links={node.suppliers} mode={mode} help={HELP.suppliers[mode]} />
        <Links title="Customers · downstream" links={node.customers} mode={mode} help={HELP.customers[mode]} />
      </div>
      <p className="help-text vc-note">{node.caveat}</p>
    </>
  );
}
