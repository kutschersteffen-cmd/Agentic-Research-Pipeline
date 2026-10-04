import { useEffect, useState } from "react";
import { api } from "../api/client";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { ReviewDecision, ReviewableRunKind } from "../types";
import { useMe } from "../lib/reviewer";
import { SignedInAs } from "../components/SignedInAs";
import { useCardKeys, type CardHandlers } from "../lib/cardKeys";
import { REVIEW_KIND_LABEL, ReviewItems, applyDecision, fromReviewItem, keyOf, type QueueItem } from "../components/RunReviewList";

/** A / C / R open the focused item's approve / correct / reject form and focus it.
 * They only press the choice button; submitting stays a click or Enter. */
const openDecision = (decision: string) => (card: HTMLElement) => {
  const button = card.querySelector<HTMLButtonElement>(`button[data-decision="${decision}"]:not(:disabled)`);
  if (!button) return;
  button.click();
  requestAnimationFrame(() =>
    card.querySelector<HTMLElement>(".inline-fields :is(input, select, button):not(:disabled)")?.focus(),
  );
};
const DECISION_KEYS: CardHandlers = { a: openDecision("approve"), c: openDecision("correct"), r: openDecision("reject") };

interface Props {
  pendingReview?: { kind: ReviewableRunKind; runId: string } | null;
}

/** One inbox across every run with flagged items, lowest confidence first,
 * so the reviewer starts deciding instead of picking a type and a run.
 * A run opened from elsewhere (`#/review/<kind>/<run id>`) starts filtered
 * to that run. */
export function ReviewQueue({ pendingReview }: Props = {}) {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [filter, setFilter] = useState(pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "");
  const [error, setError] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const reviewer = useMe()?.name ?? "";
  // Decided items stay in place, collapsed: decisions are append-only and the
  // latest wins, so "Change" records a new one and the history keeps both.
  const [decided, setDecided] = useState<Record<string, ReviewDecision>>({});
  useCardKeys(".review-item", DECISION_KEYS);

  async function load() {
    setError(null);
    setItems(null);
    setDecided({});
    try {
      const loaded = (await api.listReviewItems()).items.map(fromReviewItem);
      const conf = (q: QueueItem) => {
        const c = q.item.confidence ?? (q.item.field as { confidence?: unknown } | undefined)?.confidence;
        return typeof c === "number" ? c : 1;
      };
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
  // The run filter: each run with open items, plus a run opened from elsewhere.
  const runs = [...new Set([...(items ?? []).map((q) => `${q.kind}/${q.runId}`), ...(pendingReview ? [`${pendingReview.kind}/${pendingReview.runId}`] : [])])];
  const countFor = (run: string) => (items ?? []).filter((q) => `${q.kind}/${q.runId}` === run && !decided[keyOf(q)]).length;
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
              <option key={r} value={r}>
                {REVIEW_KIND_LABEL[r.slice(0, r.indexOf("/")) as ReviewableRunKind]}: {r.slice(r.indexOf("/") + 1)} ({countFor(r)})
              </option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={load} disabled={items === null}>
          Refresh
        </button>
        {!reviewer.trim() && <SignedInAs compact />}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {items === null && <p className="status-text">Loading flagged items…</p>}

      {shown.length > 0 && (
        <div className="split-review">
          <div className="split-review-main">
            <section className="card">
              <h2>{open > 0 ? `${open} awaiting a decision` : "All decided"}</h2>
              <p className="help-text"><span className="kbd-hint">Press <kbd>J</kbd> / <kbd>K</kbd> to move between items, <kbd>A</kbd> / <kbd>C</kbd> / <kbd>R</kbd> to open approve, correct or reject. </span>A decision can be changed; every one is kept.</p>
              <ReviewItems
                items={shown}
                decided={decided}
                reviewer={reviewer}
                onOpenSource={setActiveSource}
                onDecided={(q, recorded) => void applyDecision(q, recorded, setItems, setDecided)}
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
