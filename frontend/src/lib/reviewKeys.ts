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

/** An override counts once a different approver co-signs it. */
export function canCosign(
  decision: { decision: string; user_id?: string | null; cosigned?: boolean },
  me: Me | null,
): boolean {
  return !!me && me.role === "approver" && decision.decision === "edit" && !decision.cosigned && decision.user_id !== me.user_id;
}

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

export const decisionChoices = (kind: ReviewItemKind): ItemDecisionBody["decision"][] =>
  kind === "quarantined_document" ? ["approve", "reject", "escalate"]
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
