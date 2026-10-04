import type { ItemDecisionBody, ReviewDecision, ReviewItem, ReviewItemKind } from "../types";

export interface Me {
  user_id: string;
  name: string;
  role: "viewer" | "analyst" | "approver";
}

/** The key a decision is stored under: whatever the queue row carries, so old
 * company-level rows and new per-field rows both work. */
export const itemKeyOf = (row: { item_key: string }): string => row.item_key;

/** Key of one extracted field's decision: per-field and per-period for new runs, `company:field` for old ones. */
export const fieldItemKey = (
  r: { company_id: string; issuer_key?: string | null },
  f: { field_id: string; period_end?: string | null },
): string => (r.issuer_key ? `${r.issuer_key}:${f.field_id}:${f.period_end ?? "unspecified"}` : `${r.company_id}:${f.field_id}`);

/** A queued item's flag reasons: its review reasons, then its route reasons, each once. */
export const flaggedReasons = (item: { reason_codes?: unknown; route_reasons?: unknown }): string[] => [
  ...new Set([item.reason_codes, item.route_reasons].flatMap((v) => (Array.isArray(v) ? (v as string[]) : []))),
];

export const ITEM_KIND_LABEL: Record<ReviewItemKind, string> = {
  value: "Value",
  sector_code: "Sector code",
  identity: "Identity",
  quarantined_document: "Held document",
  restatement_candidate: "Restatement",
  other: "Other",
};

export const DECISION_REASONS = [
  "confirmed", "wrong_value", "wrong_unit_or_scale", "wrong_period", "wrong_entity", "not_disclosed", "bad_source", "needs_expert", "other",
] as const;

/** `other`: only an extraction failure report decides here; the legacy kinds keep their own endpoints. */
export const decisionChoices = (kind: ReviewItemKind, runType?: string): ItemDecisionBody["decision"][] =>
  kind === "quarantined_document" || (kind === "other" && runType === "extraction") ? ["approve", "reject", "escalate"]
  : kind === "other" ? []
  : ["approve", "correct", "reject", "escalate"];

export const needsCitation = (kind: ReviewItemKind): boolean => kind === "value" || kind === "restatement_candidate";

/** Why the signed-in person cannot decide this item, or null. */
export function decideBlock(item: Pick<ReviewItem, "state" | "escalated"> & { decision: Pick<ReviewDecision, "mine"> | null }, me: Me | null): string | null {
  if (!me || me.role === "viewer") return "Sign in as an analyst or approver to decide.";
  if (item.state === "first_done" && item.decision?.mine) return "Waiting for a second reviewer.";
  if (item.state === "disagreed" && me.role !== "approver") return "Reviewers disagree; an approver decides.";
  if (item.escalated && me.role !== "approver") return "Escalated; an approver decides.";
  return null;
}

/** A second reviewer agreeing with a first correction: that correction's value and quote, resubmitted for
 * the server to re-ground. Null unless the item awaits a second review of a visible, someone else's correction
 * (blind items hide it; legacy `edit` rows are resolved by an approver). */
export function agreeBody(
  kind: ReviewItemKind,
  state: ReviewItem["state"],
  ctx: { blind: boolean; decisions: ReviewDecision[] },
): Pick<ItemDecisionBody, "decision" | "reason_code" | "corrected_value" | "correction_citation" | "comment"> | null {
  const first = ctx.decisions[ctx.decisions.length - 1]; // in first_done the round's first row is the last one
  if (state !== "first_done" || ctx.blind || !first || first.decision !== "correct" || first.mine) return null;
  const c = first.correction_citation;
  if (needsCitation(kind) && !c) return null;
  return {
    decision: "correct",
    reason_code: first.reason_code ?? "other",
    corrected_value: (first.corrected_value as Record<string, unknown> | null | undefined) ?? null,
    correction_citation: needsCitation(kind) && c ? { doc_id: c.doc_id, doc_type: c.doc_type, quote: c.span_text ?? c.quote } : null,
    comment: first.comment ?? null,
  };
}
