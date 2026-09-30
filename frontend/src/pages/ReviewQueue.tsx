import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfidenceBadge, VerdictBadge } from "../components/ConfidenceBadge";
import { CitationList } from "../components/CitationList";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { Citation, ReviewDecision, ReviewableRunKind, RunManifest } from "../types";
import { useReviewer } from "../lib/reviewer";
import { ReviewerField } from "../components/ReviewerField";
import { ReviewControls, decisionBadgeClass, decisionLabel } from "../components/ReviewControls";
import { useCardKeys } from "../lib/cardKeys";

const REVIEW_KIND_LABEL: Record<ReviewableRunKind, string> = {
  theme: "Thematic universe",
  extraction: "Data-point extraction",
  financials: "Company financials",
  identity: "Identity resolution",
  transition_plan: "Transition plan",
  tnfd: "TNFD",
};

const QUEUE_FNS: Record<ReviewableRunKind, (runId: string) => Promise<unknown>> = {
  theme: api.getThemeReviewQueue,
  extraction: api.getExtractionReviewQueue,
  financials: api.getFinancialsReviewQueue,
  identity: api.getIdentityReviewQueue,
  transition_plan: api.getTransitionPlanReviewQueue,
  tnfd: api.getTnfdReviewQueue,
};

const SUBMIT_FNS: Record<ReviewableRunKind, (runId: string, body: unknown) => Promise<unknown>> = {
  theme: api.submitThemeReview,
  extraction: api.submitExtractionReview,
  financials: api.submitFinancialsReview,
  identity: api.submitIdentityReview,
  transition_plan: api.submitTransitionPlanReview,
  tnfd: api.submitTnfdReview,
};

// Kinds without a per-item history endpoint get no History button.
const HISTORY_FNS: Partial<Record<ReviewableRunKind, (runId: string, itemKey: string) => Promise<unknown>>> = {
  extraction: api.getExtractionReviewHistory,
  financials: api.getFinancialsReviewHistory,
  transition_plan: api.getTransitionPlanReviewHistory,
  tnfd: api.getTnfdReviewHistory,
};

/** "C1:net_zero_target" reads as "C1 · net zero target" when an item carries no name. */
const readableKey = (key: string) => key.split(":").map((p) => p.replace(/_/g, " ")).join(" · ");

interface Props {
  pendingReview?: { kind: ReviewableRunKind; runId: string } | null;
}

function isCitationArray(v: unknown): v is Citation[] {
  return Array.isArray(v) && v.every((c) => c && typeof c === "object" && "quote" in c && "doc_type" in c);
}

/** Renders whatever a pending review item happens to carry: the fields
 * every run kind's flagged payload tends to share (item identity, a
 * confidence/verdict, citations) get the same badges/CitationList used
 * everywhere else in the app; anything kind-specific that doesn't map to a
 * known field stays available, just tucked behind "Full record" instead of
 * dominating the card the way a top-level JSON.stringify dump used to. */
function ReviewItemFields({ item, onOpenSource }: { item: Record<string, unknown>; onOpenSource: (s: ActiveSource) => void }) {
  const known = new Set(["item_key", "queued_at", "company_id", "name", "ticker", "confidence", "verdict", "citations", "adjudicator_rationale", "rationale", "failed_step_label", "error"]);
  const rest = Object.fromEntries(Object.entries(item).filter(([k]) => !known.has(k)));
  const hasRest = Object.keys(rest).length > 0;

  return (
    <div>
      <div className="run-progress-header">
        <strong>
          {(item.name as string | undefined) ?? readableKey(item.item_key as string)}
          {item.ticker ? <span className="muted"> ({item.ticker as string})</span> : null}
        </strong>
        <span>
          {typeof item.verdict === "string" && <VerdictBadge verdict={item.verdict} />}{" "}
          {typeof item.confidence === "number" && <ConfidenceBadge value={item.confidence} />}
        </span>
      </div>
      {typeof item.failed_step_label === "string" && (
        <p className="error-text" role="alert">
          Stopped at {item.failed_step_label}: {String(item.error ?? "")}
        </p>
      )}
      {Boolean(item.adjudicator_rationale || item.rationale) && <p>{(item.adjudicator_rationale ?? item.rationale) as string}</p>}
      {isCitationArray(item.citations) && (
        <>
          <p className="muted">Citations:</p>
          <CitationList citations={item.citations} onOpenSource={onOpenSource} />
        </>
      )}
      {hasRest && (
        <details className="inline-block">
          <summary className="muted" style={{ cursor: "pointer" }}>
            Full record
          </summary>
          <pre className="review-json">{JSON.stringify(rest, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

interface QueueItem {
  kind: ReviewableRunKind;
  runId: string;
  item: Record<string, unknown>;
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
  const [reopened, setReopened] = useState<string | null>(null);
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

  const keyOf = (q: QueueItem) => `${q.runId}/${q.item.item_key as string}`;

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
              {shown.map((q) => {
                const k = keyOf(q);
                const d = decided[k];
                if (d && reopened !== k) {
                  return (
                    <div className="review-item review-item-decided" key={k} tabIndex={-1}>
                      <strong>{(q.item.name as string | undefined) ?? readableKey(q.item.item_key as string)}</strong>
                      <span className={decisionBadgeClass(d.decision)}>
                        {decisionLabel(d)} by {d.reviewer}
                      </span>
                      <button className="link-button" onClick={() => setReopened(k)}>
                        Change
                      </button>
                    </div>
                  );
                }
                return (
                  <div className="review-item proposed" key={k} tabIndex={-1}>
                    <p className="muted review-item-source">
                      {REVIEW_KIND_LABEL[q.kind]} · {q.runId}
                    </p>
                    <ReviewItemFields item={q.item} onOpenSource={setActiveSource} />
                    <ReviewControls
                      runId={q.runId}
                      itemKey={q.item.item_key as string}
                      current={d}
                      reviewer={reviewer}
                      submitFn={SUBMIT_FNS[q.kind]}
                      historyFn={HISTORY_FNS[q.kind] ?? null}
                      onDone={(recorded) => {
                        setDecided((prev) => ({ ...prev, [k]: recorded }));
                        setReopened(null);
                      }}
                    />
                  </div>
                );
              })}
            </section>
          </div>
          <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
        </div>
      )}
      {items !== null && shown.length === 0 && !error && (
        <p className="muted">Nothing is waiting for review{filter ? " in this run" : ""}.</p>
      )}
    </div>
  );
}
