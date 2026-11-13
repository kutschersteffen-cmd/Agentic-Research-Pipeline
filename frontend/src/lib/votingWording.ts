import type { JobStatus, VoteRecord } from "../types";

/** The page cannot read `confidence_review_threshold`; this is its default (spec showcase-stewardship-fixes B4). */
const ROUTINE_MIN_CONFIDENCE = 0.6;
const REDOMICILE = /redomicil|re-domicil|reincorporat|re-incorporat|(jurisdiction|state|place|country) of incorporation/i;

/** Routine: a rule (not the model) recommends the vote at confidence 0.6 or more, nothing flags it for a
 * second person, and it is not say-on-pay or a redomiciliation. Routine proposals read as one row and can be
 * approved as a batch; the rest always get the full card and a decision of their own. */
export function isRoutine(v: VoteRecord): boolean {
  const rec = v.policy_recommendation;
  return Boolean(
    rec &&
      !rec.engagement_alignment_flag &&
      rec.policy_rule_id &&
      rec.confidence >= ROUTINE_MIN_CONFIDENCE &&
      v.proposal.type !== "say_on_pay" &&
      !REDOMICILE.test(v.proposal.resolution_text),
  );
}

// Nothing is sent anywhere: the only platform writes one instruction file per vote (B5).
export function castDialogText(n: number): string {
  const what = n === 1 ? "1 vote as a voting instruction, in its own file," : `${n} votes as voting instructions, one file per vote,`;
  return `This records ${what} to be entered on the ballot platform by hand. Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.`;
}

export function castBannerText(n: number, by: string, at: string): string {
  const what = n === 1 ? "1 vote recorded as a voting instruction" : `${n} votes recorded as voting instructions`;
  return `${what} by ${by} at ${at}. The instruction reference is shown on each proposal below.`;
}

export function missingCoSignText(n: number): string {
  return `${n} flagged vote${n === 1 ? " has" : "s have"} no co-sign and will be refused when the votes are recorded.`;
}

export function castFailedText(message: string): string {
  return `Recording the votes failed: ${message.replace(/^\d{3}: /, "")}. Nothing was recorded; try again.`;
}

export function recordedText(ref: string): string {
  return `Recorded · instruction ref ${ref}`;
}

/** What an empty ballot list means, by the run's status. */
export function emptyBallotsText(run: { status: JobStatus; company_count: number; completed_count: number; failed_count: number } | null): string {
  if (run && (run.status === "pending" || run.status === "running")) {
    const done = run.completed_count + run.failed_count;
    return `This voting run is still in progress (${done} of ${run.company_count} companies done). Ballots appear here as they are ready.`;
  }
  if (run && (run.status === "failed" || run.status === "cancelled")) {
    return `This voting run stopped before any ballot was ready (status: ${run.status}). Run History shows why.`;
  }
  return "No ballots in this run yet: none of its companies has a proxy statement for an upcoming meeting. Start a new voting run once one is filed.";
}
