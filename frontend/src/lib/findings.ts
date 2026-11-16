// A deck finding as the report page shows it: what was checked and what to do, without stage/rule ids or slot names.

const STAGE_LABELS: Record<string, string> = { lint: "Wording", fit: "Layout", data: "Data", qa: "Visual check" };

/** The line for one finding, or null for one that is not listed (an edit the visual check proposed and dropped). */
export function findingText(finding: { stage: string; rule: string; message: string }): string | null {
  if (finding.rule === "invalid_edit") return null;
  if (finding.rule === "applied") return `Visual check: adjusted. ${finding.message}`;
  if (finding.rule === "slot_dropped") return "Layout: some content did not fit this slide and was left out.";
  return `${STAGE_LABELS[finding.stage] ?? "Check"}: ${finding.message}`;
}

/** The slide number in the download gate's refusal ("409: Slide 2 needs review"), or null for any other error. */
export function reviewSlide(error: string): number | null {
  const m = /^409: Slide (\d+) needs review$/.exec(error);
  return m ? Number(m[1]) : null;
}
