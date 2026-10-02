import { useEffect, useState } from "react";
import { api } from "../api/client";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { ReviewDecision, ReviewableRunKind, RunManifest } from "../types";
import { useReviewer } from "../lib/reviewer";
import { ReviewerField } from "../components/ReviewerField";
import { useCardKeys } from "../lib/cardKeys";
import { QUEUE_FNS, REVIEW_KIND_LABEL, ReviewItems, keyOf, type QueueItem } from "../components/RunReviewList";

interface Props {
  pendingReview?: { kind: ReviewableRunKind; runId: string } | null;
}

/** One inbox across every run with flagged items, lowest confidence first,
 * so the reviewer starts deciding instead of picking a type and a run.
 * A run opened from elsewhere (`#/review/<kind>/<run id>`) starts filtered
 * to that run. */
export function ReviewQueue({ pendingReview }: Props = {}) {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [filter, setFilter] = useState(pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "");
  const [error, setError] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const [reviewer] = useReviewer();
  // Decided items stay in place, collapsed: decisions are append-only and the
  // latest wins, so "Change" records a new one and the history keeps both.
  const [decided, setDecided] = useState<Record<string, ReviewDecision>>({});
  useCardKeys(".review-item");

  async function load() {
    setError(null);
    setItems(null);
    setDecided({});
    try {
      const all = ((await api.listRuns()) as { runs: RunManifest[] }).runs;
      const flagged = all.filter(
        (r) =>
          r.run_type in QUEUE_FNS &&
          (r.review_count > 0 || (pendingReview?.runId === r.run_id && pendingReview.kind === r.run_type)),
      );
      setRuns(flagged);
      const results = await Promise.allSettled(
        flagged.map(async (r) => {
          const kind = r.run_type as ReviewableRunKind;
          const res = (await QUEUE_FNS[kind](r.run_id)) as { pending: Record<string, unknown>[] };
          return res.pending.map((item) => ({ kind, runId: r.run_id, item }));
        }),
      );
      const failed = results.filter((x) => x.status === "rejected").length;
      if (failed) setError(`${failed} run${failed === 1 ? "" : "s"} could not be loaded; their items are missing below.`);
      const loaded = results.flatMap((x) => (x.status === "fulfilled" ? x.value : []));
      const conf = (q: QueueItem) => (typeof q.item.confidence === "number" ? q.item.confidence : 1);
      setItems(loaded.sort((a, b) => conf(a) - conf(b)));
    } catch (err) {
      setError(`Flagged items could not be loaded: ${(err as Error).message}.`);
      setItems([]);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const shown = (items ?? []).filter((q) => !filter || `${q.kind}/${q.runId}` === filter);
  const countFor = (r: RunManifest) => (items ?? []).filter((q) => q.runId === r.run_id && !decided[keyOf(q)]).length;
  const open = shown.filter((q) => !decided[keyOf(q)]).length;

  return (
    <div className="page">
      <h1>Review Queue</h1>
      <p className="help-text">Low-confidence verdicts, ungrounded citations and uncertain calls wait here, lowest confidence first. Nothing flagged reaches an export until a named person approves it.</p>

      <div className="toolbar">
        <label className="field-label inline-label">
          Show
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All runs ({items ? items.length - Object.keys(decided).length : "…"} items)</option>
            {runs.map((r) => (
              <option key={r.run_id} value={`${r.run_type}/${r.run_id}`}>
                {REVIEW_KIND_LABEL[r.run_type as ReviewableRunKind]}: {r.run_id} ({countFor(r)})
              </option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={load} disabled={items === null}>
          Refresh
        </button>
        {!reviewer.trim() && <ReviewerField compact />}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {items === null && <p className="status-text">Loading flagged items…</p>}

      {shown.length > 0 && (
        <div className="split-review">
          <div className="split-review-main">
            <section className="card">
              <h2>{open > 0 ? `${open} awaiting a decision` : "All decided"}</h2>
              <p className="help-text"><span className="kbd-hint">Press <kbd>J</kbd> / <kbd>K</kbd> to move between items. </span>A decision can be changed; every one is kept.</p>
              <ReviewItems
                items={shown}
                decided={decided}
                reviewer={reviewer}
                onOpenSource={setActiveSource}
                onDecided={(k, recorded) => setDecided((prev) => ({ ...prev, [k]: recorded }))}
              />
            </section>
          </div>
          {activeSource && <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />}
        </div>
      )}
      {items !== null && shown.length === 0 && !error && (
        <p className="muted">Nothing is waiting for review{filter ? " in this run" : ""}.</p>
      )}
    </div>
  );
}
