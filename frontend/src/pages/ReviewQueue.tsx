import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfidenceBadge, VerdictBadge } from "../components/ConfidenceBadge";
import { CitationList } from "../components/CitationList";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { Citation, ReviewableRunKind, RunManifest } from "../types";
import { REVIEWER_REQUIRED, useReviewer } from "../lib/reviewer";
import { ReviewerField } from "../components/ReviewerField";
import { DecisionBar } from "../components/DecisionBar";
import { ProposedTag } from "../components/ProposedTag";

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
          {(item.name as string | undefined) ?? (item.company_id as string | undefined) ?? (item.item_key as string)}
          {item.ticker ? <span className="muted"> ({item.ticker as string})</span> : null}
        </strong>
        <span>
          {typeof item.verdict === "string" && <VerdictBadge verdict={item.verdict} />}{" "}
          {typeof item.confidence === "number" && <ConfidenceBadge value={item.confidence} />}
        </span>
      </div>
      {Boolean(item.company_id && item.name) && <p className="muted">{item.item_key as string}</p>}
      {typeof item.failed_step_label === "string" && (
        <p className="error-text">
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
  const [deciding, setDeciding] = useState<string | null>(null);
  const [lastDecided, setLastDecided] = useState<string | null>(null);

  async function load() {
    setError(null);
    setItems(null);
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

  async function decide(q: QueueItem, decision: "approve" | "reject") {
    const itemKey = q.item.item_key as string;
    if (!reviewer.trim()) {
      setError(REVIEWER_REQUIRED);
      return;
    }
    setDeciding(itemKey);
    setError(null);
    try {
      await SUBMIT_FNS[q.kind](q.runId, { item_key: itemKey, decision, reviewer: reviewer.trim() });
      setItems((prev) => prev?.filter((p) => p !== q) ?? null);
      setLastDecided(`${decision === "approve" ? "Approved" : "Rejected"} ${itemKey} as ${reviewer.trim()}.`);
    } catch (err) {
      setError(`Could not record the decision on ${itemKey}: ${(err as Error).message}. It is still pending.`);
    } finally {
      setDeciding(null);
    }
  }

  const shown = (items ?? []).filter((q) => !filter || `${q.kind}/${q.runId}` === filter);
  const countFor = (r: RunManifest) => (items ?? []).filter((q) => q.runId === r.run_id).length;

  return (
    <div className="page">
      <h2>Review Queue</h2>
      <p className="help-text">Low-confidence verdicts, ungrounded citations and uncertain calls wait here, lowest confidence first. Nothing flagged reaches an export until a named person approves it.</p>

      <div className="toolbar">
        <label className="field-label inline-label">
          Show
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All runs ({items?.length ?? "…"} items)</option>
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
        <ReviewerField compact />
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <p className="status-text" aria-live="polite">
        {items === null ? "Loading flagged items…" : lastDecided}
      </p>

      {shown.length > 0 && (
        <div className="split-review">
          <div className="split-review-main">
            <section className="card">
              <h3>
                {shown.length} awaiting a decision
              </h3>
              {shown.map((q) => (
                <div className="review-item proposed" key={`${q.runId}/${q.item.item_key as string}`}>
                  <ProposedTag />
                  <p className="muted review-item-source">
                    {REVIEW_KIND_LABEL[q.kind]} · {q.runId}
                  </p>
                  <ReviewItemFields item={q.item} onOpenSource={setActiveSource} />
                  <DecisionBar
                    onApprove={() => decide(q, "approve")}
                    onReject={() => decide(q, "reject")}
                    disabled={deciding !== null}
                  />
                </div>
              ))}
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
