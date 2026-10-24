import type { DataIssue, FeedRow, OutputItem, SmartSearchAnswer } from "../types";
import { fixHref } from "../pages/Issues";

/** The rows a Smart Search filter matched, as issues, outputs or feeds (Smart Search page and the Ask ARP panel). */
export function SmartSearchRows({ answer: a }: { answer: SmartSearchAnswer }) {
  if (!a.filter) return null;
  return (
    <div className="table-wrap">
      <table className="data-table">
        {a.filter.target === "issues" && (
          <>
            <thead><tr><th>Issue</th><th>Severity</th><th>Detail</th><th /></tr></thead>
            <tbody>
              {(a.rows as unknown as DataIssue[]).map((i) => (
                <tr key={i.ref}>
                  <td>{i.title}</td><td>{i.severity === "block" ? "Blocking" : "Warning"}</td><td>{i.detail}</td>
                  <td><a href={fixHref(i)}>{i.source === "check" ? "Review →" : "Fix →"}</a></td>
                </tr>
              ))}
            </tbody>
          </>
        )}
        {a.filter.target === "outputs" && (
          <>
            <thead><tr><th>Output</th><th>Kind</th><th>Status</th><th>Used by</th></tr></thead>
            <tbody>
              {(a.rows as unknown as OutputItem[]).map((o) => (
                <tr key={`${o.kind}/${o.id}`}>
                  <td>{o.name}</td><td>{o.kind}</td><td>{o.status}</td>
                  <td>{o.used_by.length ? o.used_by.map((u) => u.label).join(", ") : <span className="muted">nothing yet</span>}</td>
                </tr>
              ))}
            </tbody>
          </>
        )}
        {a.filter.target === "feeds" && (
          <>
            <thead><tr><th>Feed</th><th>Source</th><th>Last load</th><th>Status</th><th /></tr></thead>
            <tbody>
              {(a.rows as unknown as FeedRow[]).map((f) => (
                <tr key={`${f.feed}/${f.source_id}`}>
                  <td>{f.feed}</td><td>{f.source_id}</td><td>{f.last_load ? f.last_load.status : "—"}</td>
                  <td>{f.stale ? "Behind" : "Current"}</td><td><a href="#/feeds">Feeds →</a></td>
                </tr>
              ))}
            </tbody>
          </>
        )}
      </table>
    </div>
  );
}
