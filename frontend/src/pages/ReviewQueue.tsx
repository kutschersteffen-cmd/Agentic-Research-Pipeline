import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ReviewableRunKind } from "../types";

const QUEUE_FNS: Record<ReviewableRunKind, (runId: string) => Promise<unknown>> = {
  theme: api.getThemeReviewQueue,
  extraction: api.getExtractionReviewQueue,
  financials: api.getFinancialsReviewQueue,
  identity: api.getIdentityReviewQueue,
};

const SUBMIT_FNS: Record<ReviewableRunKind, (runId: string, body: unknown) => Promise<unknown>> = {
  theme: api.submitThemeReview,
  extraction: api.submitExtractionReview,
  financials: api.submitFinancialsReview,
  identity: api.submitIdentityReview,
};

interface Props {
  pendingReview?: { kind: ReviewableRunKind; runId: string } | null;
}

export function ReviewQueue({ pendingReview }: Props = {}) {
  const [kind, setKind] = useState<ReviewableRunKind>(pendingReview?.kind ?? "theme");
  const [runId, setRunId] = useState(pendingReview?.runId ?? "");
  const [pending, setPending] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(loadKind: ReviewableRunKind = kind, loadRunId: string = runId) {
    if (!loadRunId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await QUEUE_FNS[loadKind](loadRunId);
      setPending((res as { pending: Record<string, unknown>[] }).pending);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // A run clicked from Run History's "Review" link arrives here -- load its
  // queue immediately instead of making the user re-pick the type and
  // re-type/paste the run ID they just came from.
  useEffect(() => {
    if (!pendingReview) return;
    setKind(pendingReview.kind);
    setRunId(pendingReview.runId);
    load(pendingReview.kind, pendingReview.runId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingReview]);

  async function decide(itemKey: string, decision: "approve" | "reject") {
    await SUBMIT_FNS[kind](runId, { item_key: itemKey, decision, reviewer: "ui-user" });
    setPending((prev) => prev.filter((p) => p.item_key !== itemKey));
  }

  return (
    <div className="page">
      <h2>Review Queue</h2>
      <p className="help-text">
        Every low-confidence verdict, ungrounded citation, or "uncertain" call lands here instead of the trusted
        output. Nothing flagged is included in exports until a human approves it.
      </p>

      <section className="card">
        <label className="field-label">Run type</label>
        <select value={kind} onChange={(e) => setKind(e.target.value as ReviewableRunKind)}>
          <option value="theme">Thematic universe</option>
          <option value="extraction">Data-point extraction</option>
          <option value="financials">Company financials</option>
          <option value="identity">Identity resolution</option>
        </select>
        <label className="field-label">Run ID</label>
        <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="theme_xxxxxxxxxxxx" />
        <button onClick={() => load()} disabled={busy || !runId}>
          Load pending items
        </button>
        {error && <p className="error-text">{error}</p>}
      </section>

      {pending.length > 0 && (
        <section className="card">
          <h3>{pending.length} pending</h3>
          {pending.map((item) => (
            <div className="review-item" key={item.item_key as string}>
              <pre className="review-json">{JSON.stringify(item, null, 2)}</pre>
              <div className="toolbar">
                <button onClick={() => decide(item.item_key as string, "approve")}>Approve</button>
                <button onClick={() => decide(item.item_key as string, "reject")} className="danger">
                  Reject
                </button>
              </div>
            </div>
          ))}
        </section>
      )}
      {pending.length === 0 && runId && !busy && <p className="muted">Nothing pending for this run.</p>}
    </div>
  );
}
