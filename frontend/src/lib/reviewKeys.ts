export interface Me {
  user_id: string;
  name: string;
  role: "viewer" | "analyst" | "approver";
}

/** The key a decision is stored under: whatever the queue row carries, so old
 * company-level rows and new per-field rows both work. */
export const itemKeyOf = (row: { item_key: string }): string => row.item_key;

/** Key of one extracted field's decision: per-field for new runs, `company:field` for old ones. */
export const fieldItemKey = (r: { company_id: string; issuer_key?: string | null }, fieldId: string): string =>
  r.issuer_key ? `${r.issuer_key}:${fieldId}:unspecified` : `${r.company_id}:${fieldId}`;

/** An override counts once a different approver co-signs it. */
export function canCosign(
  decision: { decision: string; user_id?: string | null; cosigned?: boolean },
  me: Me | null,
): boolean {
  return !!me && me.role === "approver" && decision.decision === "edit" && !decision.cosigned && decision.user_id !== me.user_id;
}
