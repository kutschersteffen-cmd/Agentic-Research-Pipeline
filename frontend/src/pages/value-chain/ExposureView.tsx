import { useEffect } from "react";
import { api } from "../../api/client";
import { exposureHash, meur, pct1, routeText } from "../../lib/valueChain";
import type { VcExposure } from "../../types";
import { useVcQuery } from "./useVcQuery";

/** One seller's route list. Route nodes outside the top sellers are named with a node lookup each. */
function RouteList({ target, from, exposure }: { target: string; from: string; exposure: VcExposure }) {
  const q = useVcQuery(async () => {
    const routes = await api.valueChainRoutes(target, from);
    const labels: Record<string, string> = { [target]: exposure.target_label };
    for (const i of exposure.items) labels[i.node_id] = `${i.sector} · ${i.region_label}`;
    const missing = [...new Set(routes.routes.flatMap((r) => r.nodes))].filter((id) => !(id in labels));
    const nodes = await Promise.all(missing.map((id) => api.valueChainNode(id, { order: "total", excludeOwn: false })));
    for (const n of nodes) labels[n.node_id] = `${n.sector} · ${n.region_label}`;
    return { routes, labels };
  }, [target, from]);

  return (
    <section className="card" aria-label="Routes">
      <h2>Routes from {q.data?.labels[from] ?? from}</h2>
      <p className="help-text">The largest chains of buyers through which this seller's revenue reaches the target, as shares of its sales.</p>
      {q.error && (
        <p className="error-text" role="alert">
          {q.error}
        </p>
      )}
      {q.loading && !q.data && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {q.data && (
        <ol className="vc-routes">
          {q.data.routes.routes.map((r) => (
            <li key={r.nodes.join(">")}>
              {routeText(r.nodes, q.data!.labels)} <span className="mono">{pct1(r.share)}</span>
            </li>
          ))}
          <li className="muted">
            Other routes <span className="mono">{pct1(q.data.routes.rest_share)}</span>
          </li>
        </ol>
      )}
    </section>
  );
}

/** `…/exposure[/<from id>]`: every seller's revenue share to the target, and one seller's routes. */
export function ExposureView({ target, from, onTitle }: { target: string; from?: string; onTitle: (title: string) => void }) {
  const q = useVcQuery(() => api.valueChainExposure(target), [target]);
  const body = q.data;
  useEffect(() => {
    if (body) onTitle(body.target_label);
  }, [body, onTitle]);

  return (
    <>
      {q.error && (
        <p className="error-text" role="alert">
          {q.error}
        </p>
      )}
      {q.loading && !body && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {body && (
        <>
          <section className="card" aria-label="Sellers">
            <h2>Revenue exposure · {body.target_label}</h2>
            <p className="help-text">Share of each seller's sales that ends up as purchases of the target, directly or through other buyers. Pick a seller to see its routes.</p>
            {body.items.length === 0 ? (
              <p className="muted">No seller.</p>
            ) : (
              <table className="data-table stack-on-phone">
                <thead>
                  <tr>
                    <th>Seller</th>
                    <th className="num">Share of sales</th>
                    <th className="num">Revenue</th>
                  </tr>
                </thead>
                <tbody>
                  {body.items.map((i) => (
                    <tr
                      key={i.node_id}
                      className={i.node_id === from ? "selected-row" : undefined}
                      onClick={() => (window.location.hash = exposureHash(target, i.node_id))}
                      style={{ cursor: "pointer" }}
                    >
                      <td>
                        <a href={exposureHash(target, i.node_id)} aria-current={i.node_id === from ? "true" : undefined}>
                          {i.sector} <span className="muted">· {i.region_label}</span>
                        </a>
                      </td>
                      <td className="num mono">{pct1(i.share)}</td>
                      <td className="num mono">{meur(i.revenue_meur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {body.basis === "recipe" && (
              <>
                <p className="help-text">Source: {body.recipe_source}</p>
                <p className="help-text">Unlisted share {pct1(body.unlisted_share ?? 0)}</p>
              </>
            )}
          </section>
          {from && <RouteList key={from} target={target} from={from} exposure={body} />}
          <p className="help-text vc-note">{body.caveat}</p>
          <p className="help-text vc-note">{body.model_caveat}</p>
        </>
      )}
    </>
  );
}
