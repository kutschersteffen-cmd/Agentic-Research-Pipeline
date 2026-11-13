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

// One sentence per reason code (schemas/review.py ReasonCode and the literals in extraction/routing.py).
const REASON_SENTENCE: Record<string, string> = {
  unreleased_version: "The schema is a draft, so every value is reviewed.",
  check_failed: "A check on this value failed.",
  first_audit_pending: "The first values of a new schema version are always reviewed.",
  below_auto_accept_min: "Confidence is below the level for automatic acceptance.",
  not_applicable_by_rule: "A rule marks this field as not applicable.",
  not_grounded: "The quote was not found in the source.",
  boolean_not_applicable: "A yes/no field was answered not applicable.",
  high_risk_not_found: "A high-risk field was not found.",
  high_risk_not_found_unranked: "A high-risk field was not found, and the search read only the first pages.",
  verifier_disagrees: "The verifier disagrees with the extracted value.",
  conflict: "Sources give different values.",
  low_confidence: "Confidence is low.",
  match_ambiguous: "More than one company or document could match.",
  number_locale_ambiguous: "The number could be read with a comma or a point as the decimal sign.",
  verifier_correction_uncited: "The verifier corrected the value without citing a source.",
  adjudicator_unresolved: "The extractor and the verifier disagree, and the tie-break did not settle it.",
  unverified_list_item: "List rows are not verified, so they are always reviewed.",
  auto_corrected: "The value was corrected automatically.",
  period_missing: "The value has no reporting period.",
  extraction_failed: "The model's answer did not fit the field type.",
  no_documents: "No document was found for the company.",
};

/** A route reason as a sentence; a code with no sentence reads `Reason: <code with spaces>.` */
export const reasonSentence = (code: string): string => REASON_SENTENCE[code] ?? `Reason: ${code.replaceAll("_", " ")}.`;

/** The review detail's "Routed for review:" line, one sentence per reason; `check:` entries are left out
 * (the failed checks are listed above it). Supersedes `routedLine` on screen (owner, PR #446). */
export function routedSentences(reasons: string[]): string | null {
  const sentences = reasonSentences(reasons);
  return sentences ? `Routed for review: ${sentences}` : null;
}

/** Route reasons as sentences, the failed checks left out (they are listed on their own). */
export const reasonSentences = (reasons: string[]): string =>
  reasons.filter((r) => !r.startsWith("check:")).map(reasonSentence).join(" ");

/** A run's verifier notes (several notes joined by spaces) with each unit converter note in words. */
export const notesInWords = (notes: string): string =>
  notes.replace(/cannot convert '(.+?)' to '(.+?)' \([a-z_]+\)/g, (_, unit: string, target: string) => `The unit "${unit}" could not be converted to ${target}.`);

/** A check's stored note in words: the unit converter's `cannot convert 'x' to 'y' (reason)` becomes a sentence; other notes stay. */
export function noteSentence(note: string): string {
  const m = /^cannot convert '(.+)' to '(.+)' \([a-z_]+\)$/.exec(note);
  return m ? `The unit "${m[1]}" could not be converted to ${m[2]}.` : note;
}
