import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { SimulatedObservation } from "../../types";
import { simulatedEsgView } from "./simulatedEsg";

const Simulated = () => <span className="badge badge-neutral">Simulated</span>;

/** The SIMULATED ESG values of one company (`arp showcase load`): its A-F transition grade against its peer group,
 * climate values and controversial revenue shares, each marked `Simulated` so none reads as real data.
 * `showEmpty` says so when the company has none; otherwise the card is left out. */
export function SimulatedEsg({ companyRef, showEmpty = false }: { companyRef: string; showEmpty?: boolean }) {
  const [obs, setObs] = useState<SimulatedObservation[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setObs(null);
    setError("");
    api.getSimulatedEsg(companyRef).then(
      (o) => live && setObs(o),
      // a portfolio company the registry does not know has no simulated values either
      (e: Error) => live && (e.message.startsWith("404") ? setObs([]) : setError(e.message)),
    );
    return () => {
      live = false;
    };
  }, [companyRef]);

  const view = obs && simulatedEsgView(obs);
  if (!error && !view && !(showEmpty && obs)) return null;
  return (
    <section className="card simulated-esg" aria-labelledby="simulated-esg-heading">
      <h2 id="simulated-esg-heading">Simulated ESG</h2>
      {error ? (
        <p className="error-text" role="alert">Simulated ESG could not be loaded: {error}</p>
      ) : !view ? (
        <p className="muted">No simulated ESG data for this issuer.</p>
      ) : (
        <>
          <p className="muted">Sector-based estimates, not real ESG data.</p>
          <dl className="company-ids">
            <div>
              <dt>Transition grade</dt>
              <dd>{view.grade ?? "—"} <Simulated /></dd>
            </div>
            <div>
              <dt>Peer group</dt>
              <dd>{view.peerGroup ?? "—"} <Simulated /></dd>
            </div>
          </dl>
          <div className="table-wrap">
            <table className="data-table stack-on-phone">
              <thead>
                <tr><th>Measure</th><th>Value</th></tr>
              </thead>
              <tbody>
                {view.rows.map((r) => (
                  <tr key={r.fieldId}>
                    <td data-label="Measure">{r.label}</td>
                    <td data-label="Value" className="mono"><span>{r.value} <Simulated /></span></td>
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
