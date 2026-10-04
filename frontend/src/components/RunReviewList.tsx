import { valueLabel } from "../lib/fieldValue";
import type { ExtractedField } from "../types";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { ConfidenceBadge, VerdictBadge } from "./ConfidenceBadge";
import { CitationList } from "./CitationList";
import type { ActiveSource } from "./SourcePanel";
import { ReviewControls, decisionBadgeClass, decisionLabel } from "./ReviewControls";
import { api } from "../api/client";
import { focusNextCard, useCardKeys } from "../lib/cardKeys";
import { ITEM_KIND_LABEL, flaggedReasons } from "../lib/reviewKeys";
import { matchesTile, type ReviewTileCounts } from "../lib/stagedFlow";
import type { Citation, ReviewDecision, ReviewItem, ReviewableRunKind } from "../types";

// eslint-disable-next-line react-refresh/only-export-components
export const REVIEW_KIND_LABEL: Record<ReviewableRunKind, string> = {
  theme: "Thematic universe",
  extraction: "Data-point extraction",
  financials: "Company financials",
  identity: "Identity resolution",
  transition_plan: "Transition plan",
  tnfd: "TNFD",
};

// eslint-disable-next-line react-refresh/only-export-components
export const SUBMIT_FNS: Partial<Record<ReviewableRunKind, (runId: string, body: unknown) => Promise<unknown>>> = {
  theme: api.submitThemeReview,
  financials: api.submitFinancialsReview,
  transition_plan: api.submitTransitionPlanReview,
  tnfd: api.submitTnfdReview,
};

// Kinds without a per-item history endpoint get no History button.
// eslint-disable-next-line react-refresh/only-export-components
export const HISTORY_FNS: Partial<Record<ReviewableRunKind, (runId: string, itemKey: string) => Promise<unknown>>> = {
  financials: api.getFinancialsReviewHistory,
  transition_plan: api.getTransitionPlanReviewHistory,
  tnfd: api.getTnfdReviewHistory,
};

/** "C1:net_zero_target" reads as "C1 · net zero target" when an item carries no name. */
const readableKey = (key: string) => key.split(":").map((p) => p.replace(/_/g, " ")).join(" · ");


function isCitationArray(v: unknown): v is Citation[] {
  return Array.isArray(v) && v.every((c) => c && typeof c === "object" && "quote" in c && "doc_type" in c);
}

/** Renders whatever a pending review item happens to carry: the fields
 * every run kind's flagged payload tends to share (item identity, a
 * confidence/verdict, citations) get the same badges/CitationList used
 * everywhere else in the app; anything kind-specific that doesn't map to a
 * known field stays available, just tucked behind "Full record" instead of
 * dominating the card the way a top-level JSON.stringify dump used to. */
export function ReviewItemFields({ item, onOpenSource }: { item: Record<string, unknown>; onOpenSource: (s: ActiveSource) => void }) {
  const known = new Set(["item_key", "queued_at", "company_id", "name", "ticker", "confidence", "verdict", "citations", "field", "field_id", "issuer_key", "issuer_scheme", "schema_id", "run_id", "reason_codes", "route_reasons", "adjudicator_rationale", "rationale", "failed_step_label", "error"]);
  // Per-field extraction rows carry the field itself; old rows keep these at top level.
  const field = (item.field ?? null) as { field_name?: string; value?: unknown; value_state?: ExtractedField["value_state"]; unit?: string | null; period_end?: string | null; citations?: unknown; confidence?: number } | null;
  const citations = item.citations ?? field?.citations;
  const confidence = typeof item.confidence === "number" ? item.confidence : field?.confidence;
  const reasons = flaggedReasons(item);
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
          {typeof confidence === "number" && <ConfidenceBadge value={confidence} />}
        </span>
      </div>
      {field?.field_name && (
        <p>
          {field.field_name}: <strong>{valueLabel(field as ExtractedField)}</strong>
          {"period_end" in field && <span className="muted"> · {field.period_end ?? "period unspecified"}</span>}
        </p>
      )}
      {reasons.length > 0 && <p className="muted">Flagged: {reasons.map((c) => c.replaceAll("_", " ")).join(", ")}</p>}
      {typeof item.failed_step_label === "string" && (
        <p className="error-text" role="alert">
          Stopped at {item.failed_step_label}: {String(item.error ?? "")}
        </p>
      )}
      {Boolean(item.adjudicator_rationale || item.rationale) && <p>{(item.adjudicator_rationale ?? item.rationale) as string}</p>}
      {isCitationArray(citations) && (
        <>
          <p className="muted">Citations:</p>
          <CitationList citations={citations} onOpenSource={onOpenSource} />
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

export interface QueueItem {
  kind: ReviewableRunKind;
  runId: string;
  item: Record<string, unknown>;
  review: ReviewItem;
}

// eslint-disable-next-line react-refresh/only-export-components
export const fromReviewItem = (r: ReviewItem): QueueItem => ({ kind: r.run_type, runId: r.run_id, item: { ...r.payload, item_key: r.item_key }, review: r });

// eslint-disable-next-line react-refresh/only-export-components
export const keyOf = (q: QueueItem) => `${q.runId}/${q.review.item_key}`;

/** After a decision: legacy kinds are final at once. A workbench item reloads its run's open
 * items so its status line updates (first done, disagreed); gone from the list means final. */
// eslint-disable-next-line react-refresh/only-export-components
export async function applyDecision(
  q: QueueItem,
  recorded: ReviewDecision,
  setItems: Dispatch<SetStateAction<QueueItem[] | null>>,
  setDecided: Dispatch<SetStateAction<Record<string, ReviewDecision>>>,
) {
  const k = keyOf(q);
  const decide = () => setDecided((prev) => ({ ...prev, [k]: recorded }));
  if (q.review.kind === "other") return decide();
  try {
    const fresh = new Map((await api.listReviewItems(q.runId)).items.map((r) => [`${r.run_id}/${r.item_key}`, fromReviewItem(r)]));
    setItems((prev) => prev && prev.map((x) => fresh.get(keyOf(x)) ?? x));
    if (!fresh.has(k)) decide();
  } catch {
    decide();
  }
}

/** The review cards themselves: decided items stay in place, collapsed, and
 * "Change" reopens one. Decision state is owned by the caller. */
export function ReviewItems({
  items,
  decided,
  reviewer,
  onOpenSource,
  onDecided,
}: {
  items: QueueItem[];
  decided: Record<string, ReviewDecision>;
  reviewer: string;
  onOpenSource: (s: ActiveSource) => void;
  onDecided: (q: QueueItem, recorded: ReviewDecision) => void;
}) {
  const [reopened, setReopened] = useState<string | null>(null);
  return (
    <>
      {items.map((q) => {
        const k = keyOf(q);
        const d = decided[k];
        if (d && reopened !== k) {
          return (
            <div className="review-item review-item-decided" key={k} tabIndex={-1}>
              <strong>{(q.item.name as string | undefined) ?? readableKey(q.item.item_key as string)}</strong>
              <span className="muted">
                {REVIEW_KIND_LABEL[q.kind]} · {ITEM_KIND_LABEL[q.review.kind]} · <span className="mono">{q.runId}</span>
              </span>
              <span className={decisionBadgeClass(d.decision)}>
                {decisionLabel(d)}
                {d.role ? ` by ${d.role}` : ""}
                {d.mine ? " (you)" : ""}
              </span>
              <button className="link-button" onClick={() => setReopened(k)}>
                Change
              </button>
            </div>
          );
        }
        return (
          <div className="review-item proposed" key={k} tabIndex={-1} data-review-key={k}>
            <p className="muted review-item-source">
              {REVIEW_KIND_LABEL[q.kind]} · {ITEM_KIND_LABEL[q.review.kind]} · {q.runId}
            </p>
            <ReviewItemFields item={q.item} onOpenSource={onOpenSource} />
            {d && (
              <button className="link-button" onClick={() => setReopened(null)}>
                Keep the current decision
              </button>
            )}
            {q.review.kind !== "other" || SUBMIT_FNS[q.kind] || q.kind === "extraction" ? (
              <ReviewControls
                runId={q.runId}
                itemKey={q.review.item_key}
                current={d}
                reviewer={reviewer}
                submitFn={SUBMIT_FNS[q.kind]}
                historyFn={HISTORY_FNS[q.kind] ?? null}
                item={q.review.kind === "other" && q.kind !== "extraction" ? undefined : q.review}
                onOpenSource={onOpenSource}
                onDone={(recorded) => {
                  focusNextCard(document.querySelector<HTMLElement>(`[data-review-key="${CSS.escape(k)}"]`), ".review-item");
                  onDecided(q, recorded);
                  setReopened(null);
                }}
              />
            ) : (
              <p className="muted">Nothing to decide here.</p>
            )}
          </div>
        );
      })}
    </>
  );
}

/** One run's flagged items with their review controls. `filter` narrows the
 * list to a status tile; `onCounts` reports the pending count and the
 * decisions made so a parent can render tiles. */
export function RunReviewList({
  runId,
  reviewer,
  onOpenSource,
  filter = null,
  onCounts,
}: {
  runId: string;
  reviewer: string;
  onOpenSource: (s: ActiveSource) => void;
  filter?: keyof ReviewTileCounts | null;
  onCounts?: (pending: number, decisions: ReviewDecision[]) => void;
}) {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [decided, setDecided] = useState<Record<string, ReviewDecision>>({});
  const [error, setError] = useState<string | null>(null);
  useCardKeys(".review-item");

  useEffect(() => {
    let live = true;
    setItems(null);
    setDecided({});
    setError(null);
    api
      .listReviewItems(runId)
      .then((res) => live && setItems(res.items.map(fromReviewItem)))
      .catch((err: Error) => {
        if (!live) return;
        setError(`Flagged items could not be loaded: ${err.message}.`);
        setItems([]);
      });
    return () => {
      live = false;
    };
  }, [runId]);

  useEffect(() => {
    if (items === null) return;
    onCounts?.(items.filter((q) => !decided[keyOf(q)]).length, Object.values(decided));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, decided]);

  const shown = (items ?? []).filter((q) => matchesTile(filter, true, decided[keyOf(q)]));

  return (
    <div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {items === null && <p className="status-text">Loading flagged items…</p>}
      {items !== null && shown.length === 0 && !error && <p className="muted">Nothing to show here.</p>}
      <ReviewItems
        items={shown}
        decided={decided}
        reviewer={reviewer}
        onOpenSource={onOpenSource}
        onDecided={(q, recorded) => void applyDecision(q, recorded, setItems, setDecided)}
      />
    </div>
  );
}
