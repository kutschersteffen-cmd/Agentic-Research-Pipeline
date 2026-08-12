import { useState } from "react";
import { api } from "../api/client";

type RunKind = "theme" | "extraction";

export function ReviewQueue() {
  const [kind, setKind] = useState<RunKind>("theme");
  const [runId, setRunId] = useState("");
  const [pending, setPending] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      const res =
        kind === "theme" ? await api.getThemeReviewQueue(runId) : await api.getExtractionReviewQueue(runId);
      setPending((res as { pending: Record<string, unknown>[] }).pending);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(itemKey: string, decision: "approve" | "reject") {
    const submit = kind === "theme" ? api.submitThemeReview : api.submitExtractionReview;
    await submit(runId, { item_key: itemKey, decision, reviewer: "ui-user" });
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
        <select value={kind} onChange={(e) => setKind(e.target.value as RunKind)}>
          <option value="theme">Thematic universe</option>
          <option value="extraction">Data-point extraction</option>
        </select>
        <label className="field-label">Run ID</label>
        <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="theme_xxxxxxxxxxxx" />
        <button onClick={load} disabled={busy || !runId}>
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
