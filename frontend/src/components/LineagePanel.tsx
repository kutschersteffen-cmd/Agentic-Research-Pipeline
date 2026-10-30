import { useEffect, useState } from "react";
import { api } from "../api/client";
import { lineageFromEntity, lineageLines, type RowLineage } from "../lib/lineage";
import type { EntityDecision } from "../types";

/** Score → criterion → authoritative value → inputs → citations, for one company. */
export function LineagePanel({ lineage, onClose }: { lineage: RowLineage; onClose?: () => void }) {
  const l = lineageLines(lineage);
  return (
    <section aria-label="Score lineage" className="detail-cell derivation-panel">
      <div className="toolbar">
        <h3>{l.header}</h3>
        {onClose && <button className="link-button" onClick={onClose}>Close</button>}
      </div>
      {l.reasons.length > 0 && (
        <ul>{l.reasons.map((r) => <li key={r}><strong>{r}</strong></li>)}</ul>
      )}
      {l.criteria.map((c, i) => (
        <div key={`${c.title}-${i}`}>
          {c.title && <h4>{c.title}</h4>}
          <p>{c.value}</p>
          {c.inputs.length > 0 && <ul>{c.inputs.map((x) => <li key={x}>{x}</li>)}</ul>}
          {c.citations.length > 0 && <ul className="muted">{c.citations.map((x) => <li key={x}>{x}</li>)}</ul>}
        </div>
      ))}
    </section>
  );
}

/** Published: the server's lineage (with citations). Not yet published: built from the live result. */
export function EntityLineage({ entity, snapshotId, entityId }: { entity: EntityDecision; snapshotId?: string; entityId?: string }) {
  const [lineage, setLineage] = useState<RowLineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setError(null);
    if (snapshotId && entityId) {
      api.getRowLineage(snapshotId, entityId).then(setLineage, (e: Error) => setError(e.message));
      return;
    }
    const ids = entity.contributions.map((c) => c.value_id).filter((x): x is number => x != null);
    Promise.all(ids.map((id) => api.getAuthoritativeValue(id).then((v) => [id, v] as const, () => null)))
      .then((pairs) => setLineage(lineageFromEntity(entity, Object.fromEntries(pairs.filter((p) => p !== null)))), (e: Error) => setError(e.message));
  }, [entity, snapshotId, entityId]);
  if (error) return <p className="decision-check-banner" role="alert">{error}</p>;
  if (!lineage) return <p className="status-text">Loading lineage…</p>;
  return <LineagePanel lineage={lineage} />;
}
