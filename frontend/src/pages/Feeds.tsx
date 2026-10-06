import { useEffect, useState } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import type { FeedRow } from "../types";

const LABEL: Record<FeedRow["feed"], string> = {
  security_master: "Security master",
  holdings: "Portfolio holdings",
  index: "Index constituents",
  esg: "ESG data",
  news: "News",
};
// Where each feed is loaded by hand. Feeds only reads; loading stays on those screens.
const LOAD_HREF: Partial<Record<FeedRow["feed"], string>> = {
  security_master: "#/securityMaster",
  holdings: "#/portfolio-monitoring/holdings",
  index: "#/portfolio-monitoring/holdings",
  esg: "#/portfolio-monitoring/holdings",
};

/** Data Hub · Feeds: every input feed, its last load and whether it is behind, in one table. */
export function Feeds() {
  const [rows, setRows] = useState<FeedRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pulling, setPulling] = useState<string | null>(null);

  const load = () => api.listFeeds().then((r) => setRows(r.feeds), (e: Error) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);

  const key = (r: FeedRow) => `${r.feed}/${r.source_id}`;

  async function pull(r: FeedRow) {
    setPulling(key(r));
    setError(null);
    try {
      if (r.feed === "news") {
        const res = await api.pullNews();
        announce(`News: ${res.added} new stories${res.unmatched ? `, ${res.unmatched} not matched to an issuer` : ""}`);
      } else if (r.feed === "esg") {
        const res = await api.pullEsg(r.source_id);
        announce(`ESG ${r.source_id}: ${res.status === "unchanged" ? "no change" : `${res.rows} rows written`}`);
      } else {
        const res = await api.pullHolder(r.feed === "index" ? "index" : "portfolio", r.source_id);
        announce(`${r.source_id}: ${res.status === "unchanged" ? "no change" : `revision ${res.revision} written`}`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPulling(null);
      void load();
    }
  }

  const behind = rows?.filter((r) => r.stale).length ?? 0;

  return (
    <div className="page">
      <h1>Feeds</h1>
      <p className="help-text">
        Every input the tool runs on: the security master, holdings and index constituents, ESG data and news. A feed is
        behind when its latest good load is older than last month end (or, for the master and news, when nothing is loaded).
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {rows && <p role="status">{behind === 0 ? "All feeds are current." : `${behind} of ${rows.length} feeds are behind.`}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Feed</th><th>Source</th><th>Via</th><th>Data as of</th><th>Last load</th><th>Status</th><th /></tr>
          </thead>
          <tbody>
            {!rows && !error && <tr><td colSpan={7} className="muted">Loading…</td></tr>}
            {rows?.map((r) => (
              <tr key={`${r.feed}/${r.source_id}`}>
                <td>{LABEL[r.feed]}</td>
                <td>{r.source_id}</td>
                <td>{r.channel === "api" ? "API" : r.channel === "file" ? "File" : "—"}</td>
                <td>{r.as_of ?? "—"}</td>
                <td>
                  {r.last_load ? (
                    <>
                      {new Date(r.last_load.at).toLocaleDateString()} · {r.last_load.status === "ok" ? "ok" : <strong>failed</strong>}
                      {r.last_load.detail && <span className="muted"> · {r.last_load.detail}</span>}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <span className={r.stale ? "badge badge-low" : "badge badge-neutral"}>{r.stale ? "Behind" : "Current"}</span>
                  {r.detail && <span className="muted"> {r.detail}</span>}
                </td>
                <td>
                  {(r.feed === "news" || r.feed === "esg" || ((r.feed === "holdings" || r.feed === "index") && r.channel === "api")) && (
                    <button className="secondary" onClick={() => void pull(r)} disabled={pulling !== null}>
                      {pulling === key(r) ? "Pulling…" : "Pull now"}
                    </button>
                  )}{" "}
                  {LOAD_HREF[r.feed] && <a href={LOAD_HREF[r.feed]}>Load →</a>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
