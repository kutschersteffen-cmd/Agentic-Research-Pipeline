import type { AuditEntry } from "../types";

/** The audit log is the product of this layer as much as the ranking is.
 * Its one job is letting a reviewer tell apart what the data proposed from
 * what a person then changed, so origin is the column that leads. */
export function AuditLogView({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) return <p className="muted">Nothing derived yet.</p>;

  const flagged = entries.filter((e) => e.needs_check);
  const stages = Array.from(new Set(entries.map((e) => e.stage)));

  return (
    <div>
      {flagged.length > 0 && (
        <p className="decision-check-banner">
          {flagged.length} {flagged.length === 1 ? "choice needs" : "choices need"} checking — a guess this layer is not
          confident in is surfaced rather than quietly applied.
        </p>
      )}
      {stages.map((stage) => (
        <div key={stage} className="audit-stage">
          <h3>{stage}</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>From</th>
                <th>Item</th>
                <th>Decision</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {entries
                .filter((e) => e.stage === stage)
                .map((entry, index) => (
                  <tr key={`${entry.item}-${index}`} className={entry.needs_check ? "audit-needs-check" : undefined}>
                    <td>
                      <span className={entry.origin === "human" ? "badge badge-mid" : "badge badge-neutral"}>
                        {entry.origin === "human" ? entry.by || "you" : "data"}
                      </span>
                    </td>
                    <td>{entry.item}</td>
                    <td>{entry.decision}</td>
                    <td className="muted">{entry.why}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
