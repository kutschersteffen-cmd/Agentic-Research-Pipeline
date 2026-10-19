import { useState } from "react";
import { api } from "../api/client";
import { BARRIER_KIND_LABEL, RATING_CLASS, cellHash, errorDetail } from "../lib/barrier";
import type { BarrierRating } from "../types";

export type BulkResult = { runId: string; accepted: number; second_review: string[]; refused: { item_key: string; reason: string }[] };

const rating = (r: unknown) => (r === "H" || r === "M" || r === "L" ? <span className={RATING_CLASS[r as BarrierRating]}>{r}</span> : <span className="muted">{String(r ?? "—")}</span>);

/** A barrier item's payload: what it is, current → proposed, the conflicting values, and the way to the figures. */
export function BarrierItemFields({ item }: { item: Record<string, unknown> }) {
  const kind = String(item.kind ?? "");
  const values = Array.isArray(item.values) ? (item.values as string[]) : [];
  return (
    <>
      <p>
        {BARRIER_KIND_LABEL[kind] ?? kind}
        {item.proposed != null && (
          <>
            {" "}
            · current {rating(item.current)} → proposed {rating(item.proposed)}
          </>
        )}
      </p>
      {values.length > 0 && (
        <ul>
          {values.map((v) => (
            <li key={v}>{v}</li>
          ))}
        </ul>
      )}
      <p>
        <a href={cellHash(String(item.code), String(item.region))}>Open the cell with its figures</a>
      </p>
    </>
  );
}

/** Accepts every open item of one barrier run in one call; the server lists what it refuses and why. */
export function BarrierBulkAccept({ runId, itemKeys, onResult }: { runId: string; itemKeys: string[]; onResult: (r: BulkResult) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const items = await Promise.all(itemKeys.map(async (item_key) => ({ item_key, context_etag: (await api.getItemContext(runId, item_key)).etag })));
      const res = await api.bulkAcceptItems(runId, items);
      onResult({ runId, accepted: res.accepted, second_review: res.second_review, refused: res.refused ?? [] });
    } catch (err) {
      setError(errorDetail(err as Error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="toolbar">
      <span className="muted">
        Transition barrier ratings · <span className="mono">{runId}</span>
      </span>
      <button type="button" className="secondary" onClick={() => void run()} disabled={busy || itemKeys.length === 0}>
        {busy ? "Accepting…" : `Bulk accept (${itemKeys.length})`}
      </button>
      {error && <span className="error-text" role="alert">{error}</span>}
    </div>
  );
}

export function BulkAcceptResult({ result }: { result: BulkResult }) {
  return (
    <div role="status">
      <p>
        Accepted {result.accepted}
        {result.second_review.length > 0 && `, ${result.second_review.length} sent to a second review`}
        {result.refused.length > 0 ? `, refused ${result.refused.length}:` : "."}
      </p>
      {result.refused.length > 0 && (
        <ul>
          {result.refused.map((r) => (
            <li key={r.item_key}>
              <span className="mono">{r.item_key}</span> {r.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
