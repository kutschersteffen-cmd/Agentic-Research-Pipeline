import { valueLabel } from "../../lib/fieldValue.ts";
import { DECISION_REASONS, agreeBody, decideBlock, decisionChoices, flaggedReasons, needsCitation, type Me } from "../../lib/reviewKeys.ts";
import type { ExtractedField, ItemContext, ItemDecisionBody, ItemState, ReviewDecision } from "../../types";
import type { QueueItem } from "../../components/RunReviewList";

/** The decisions the tape offers. Correct needs a citation picker the tape does not have. */
export type TapeAction = "approve" | "reject" | "escalate";

/** Reasons for reject and escalate: "confirmed" belongs to approve only. */
export const REASON_OPTIONS: readonly string[] = DECISION_REASONS.filter((r) => r !== "confirmed");

export const READ_ONLY_REASON = "This kind is decided in the Review Queue.";
const FINISHED: ReadonlySet<ItemState> = new Set<ItemState>(["second_done", "final"]);

/** Same key as RunReviewList's keyOf. */
export const rowKey = (q: QueueItem): string => `${q.runId}/${q.review.item_key}`;

const readableKey = (key: string): string => key.split(":").map((p) => p.replace(/_/g, " ")).join(" · ");

/** Confidence as ReviewQueue reads it: the item's own, else its field's; null when absent. */
export function confidenceOf(q: QueueItem): number | null {
  const c = q.item.confidence ?? (q.item.field as { confidence?: unknown } | undefined)?.confidence;
  return typeof c === "number" ? c : null;
}

/** Lowest confidence first, items without one last; stable, input untouched. */
export const sortQueue = (items: QueueItem[]): QueueItem[] =>
  [...items].sort((a, b) => (confidenceOf(a) ?? 1) - (confidenceOf(b) ?? 1));

type Access = { ok: true; actions: TapeAction[] } | { ok: false; reason: string };

/** Whether this person may decide the item here, by the same rules as ReviewControls. */
export function accessFor(q: QueueItem, me: Me | null, done = false): Access {
  const choices = decisionChoices(q.review.kind, q.review.run_type);
  if (choices.length === 0) return { ok: false, reason: READ_ONLY_REASON };
  if (done || FINISHED.has(q.review.state)) return { ok: false, reason: "Already decided." };
  const block = decideBlock(q.review, me);
  if (block) return { ok: false, reason: block };
  const actions = (["approve", "reject", "escalate"] as const).filter(
    (a) => choices.includes(a) && !(a === "escalate" && q.review.state === "disagreed"),
  );
  return { ok: true, actions };
}

const LABEL: Record<ReviewDecision["decision"], string> = { approve: "approved", reject: "rejected", escalate: "escalated", correct: "corrected", edit: "overridden" };

/** "approved by approver (you)". */
export function decisionText(d: Pick<ReviewDecision, "decision" | "role" | "mine">): string {
  return `${LABEL[d.decision]}${d.role ? ` by ${d.role}` : ""}${d.mine ? " (you)" : ""}`;
}

export interface TapeRow {
  key: string;
  q: QueueItem;
  queued: string | null;
  entity: string | null;
  field: string | null;
  proposed: string | null;
  confidence: number | null;
  reasons: string[];
  state: ItemState;
  escalated: boolean;
  highRisk: boolean;
  decision: string | null;
  /** A person must act: the signed-in user can decide this and has not yet. */
  awaiting: boolean;
  readOnly: boolean;
  /** Correcting needs a citation, which only the Review Queue takes. */
  citation: boolean;
  href: string;
}

function queuedLabel(v: unknown): string | null {
  if (typeof v !== "string" || !v.trim()) return null;
  const t = new Date(v);
  return Number.isNaN(t.getTime()) ? v : `${t.toISOString().slice(5, 10)} ${t.toISOString().slice(11, 16)}`;
}

/** `decided`: the decision recorded this session for an item the server no longer lists. */
export function toRow(q: QueueItem, me: Me | null, decided?: ReviewDecision): TapeRow {
  const f = q.item.field as Partial<ExtractedField> | null | undefined;
  const name = q.item.name;
  const company = q.item.company_id;
  const fieldName = f?.field_name ?? q.item.field_id;
  const acc = accessFor(q, me, !!decided);
  const d = decided ?? q.review.decision;
  return {
    key: rowKey(q),
    q,
    queued: queuedLabel(q.item.queued_at),
    entity: typeof name === "string" && name ? name : typeof company === "string" && company ? company : readableKey(q.review.item_key),
    field: typeof fieldName === "string" && fieldName ? fieldName : null,
    proposed: f && typeof f === "object" ? valueLabel(f as ExtractedField) : null,
    confidence: confidenceOf(q),
    reasons: flaggedReasons(q.item),
    state: decided ? "final" : q.review.state,
    escalated: q.review.escalated,
    highRisk: q.review.high_risk,
    decision: d ? decisionText(d) : null,
    awaiting: acc.ok,
    readOnly: decisionChoices(q.review.kind, q.review.run_type).length === 0,
    citation: needsCitation(q.review.kind),
    href: `#/review/${q.review.run_type}/${q.review.run_id}`,
  };
}

/** The request body, built as ReviewControls builds it; null when a reject or escalate has no reason. */
export function decisionBody(
  action: TapeAction,
  q: QueueItem,
  ctx: Pick<ItemContext, "etag" | "blind" | "decisions">,
  pick: { reason: string; comment: string } = { reason: "", comment: "" },
): ItemDecisionBody | null {
  if (action === "approve") {
    // A second reviewer agreeing with a first correction resubmits it.
    const agree = agreeBody(q.review.kind, q.review.state, ctx);
    if (agree) return { ...agree, context_etag: ctx.etag };
    return { decision: "approve", reason_code: "confirmed", corrected_value: null, correction_citation: null, comment: null, context_etag: ctx.etag };
  }
  if (!pick.reason || !REASON_OPTIONS.includes(pick.reason)) return null;
  return { decision: action, reason_code: pick.reason, corrected_value: null, correction_citation: null, comment: pick.comment.trim() || null, context_etag: ctx.etag };
}

/** The decision as the server now holds it, for a row it no longer lists. */
export const recordedFrom = (body: ItemDecisionBody, me: Me, itemKey: string, state: ItemState, now: Date): ReviewDecision => ({
  item_key: itemKey,
  decision: body.decision,
  reason_code: body.reason_code,
  corrected_value: body.corrected_value,
  edited_value: body.corrected_value,
  role: me.role,
  mine: true,
  decided_at: now.toISOString(),
  step: state === "first_done" ? "second" : state === "disagreed" ? "resolution" : "first",
});

/** After the server confirms: swap in the run's fresh items; the row is decided at once for the
 * `other` kind or when the run no longer lists it. Mirrors applyDecision. */
export function mergeDecided(
  items: QueueItem[],
  q: QueueItem,
  recorded: ReviewDecision,
  fresh: QueueItem[] | null,
): { items: QueueItem[]; decided: ReviewDecision | null } {
  if (q.review.kind === "other" || !fresh) return { items, decided: recorded };
  const byKey = new Map(fresh.map((x) => [rowKey(x), x]));
  return { items: items.map((x) => byKey.get(rowKey(x)) ?? x), decided: byKey.has(rowKey(q)) ? null : recorded };
}

/** The next row after `from` still awaiting this person, else `from`. */
export function nextAwaiting(rows: readonly Pick<TapeRow, "awaiting">[], from: number): number {
  const i = rows.findIndex((r, n) => n > from && r.awaiting);
  return i < 0 ? from : i;
}
