const ROUTE_REASON: Record<string, string> = {
  unreleased_version: "the template is not released yet",
  not_applicable_by_rule: "a rule marks this field as not applicable",
  not_grounded: "the quote was not found in the source",
  boolean_not_applicable: "a yes/no field was answered not applicable",
  first_audit_pending: "the first audit of this field is not done yet",
  below_auto_accept_min: "confidence is below the auto-accept level",
  high_risk_not_found: "a high-risk field was not found",
  check_failed: "a check failed",
  low_confidence: "low confidence",
  verifier_disagrees: "the verifier disagrees",
  conflict: "sources conflict",
};

/** The review detail's "Routed for review" line in words; `check:` entries are left out (the failed checks are listed above it). */
export function routedLine(reasons: string[]): string | null {
  const words = reasons.filter((r) => !r.startsWith("check:")).map((r) => ROUTE_REASON[r] ?? r.replaceAll("_", " "));
  return words.length ? `Routed for review: ${words.join(", ")}` : null;
}
