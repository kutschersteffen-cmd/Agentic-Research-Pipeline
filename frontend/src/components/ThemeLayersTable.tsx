import { useEffect, useState } from "react";
import { api } from "../api/client";
import { errorDetail, layersSummary, todayUtc, viaLabel } from "../lib/themeLayers";
import type { ThemeLayers } from "../types";

const num = (x: number | null) => (x === null ? "" : x.toFixed(4));

/** Exposure layers of one theme run: direct (L1), value chain (L2), macro (L3, no data yet) and score S. */
export function ThemeLayersTable({ runId }: { runId: string }) {
  const [asOf, setAsOf] = useState(todayUtc);
  const [layers, setLayers] = useState<ThemeLayers | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!asOf) return;
    let current = true;
    api
      .getThemeLayers(runId, asOf)
      .then((r) => current && (setLayers(r), setError(null)))
      .catch((e) => current && (setLayers(null), setError(errorDetail(e))));
    return () => {
      current = false;
    };
  }, [runId, asOf]);

  return (
    <section className="card">
      <h2>Layers</h2>
      <label className="field-label">
        As of
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      </label>
      {error && <p className="error-text" role="alert">{error}</p>}
      {layers && !error && (
        <>
          <p className="muted">{layersSummary(layers)}</p>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Company</th>
                  <th>Layer 1</th>
                  <th>Layer 2</th>
                  <th>Layer 3</th>
                  <th>Score</th>
                  <th>Via</th>
                </tr>
              </thead>
              <tbody>
                {layers.rows.map((r) => (
                  <tr key={r.issuer_key}>
                    <td>{r.rank ?? ""}</td>
                    <td>{r.name}</td>
                    <td>{num(r.l1)}</td>
                    <td>{num(r.l2)}</td>
                    <td className="muted">not available</td>
                    <td>{r.status === "insufficient data" ? <span className="muted">insufficient data</span> : num(r.score)}</td>
                    <td>{viaLabel(r, layers.rows)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
