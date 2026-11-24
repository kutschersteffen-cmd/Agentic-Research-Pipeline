/** The first fault in an Index Builder spec that the backend would refuse, as a message naming the card; else null. */
export function specProblem(spec: {
  base_weighting?: { scheme?: string; field?: string | null } | null;
  tilts?: { type?: string; normalisation?: string; group_by?: string | null }[] | null;
  constraints?: { solver?: { method?: string; score_field?: string | null } | null } | null;
}): string | null {
  const bw = spec.base_weighting;
  if ((bw?.scheme === "metric" || bw?.scheme === "inverse_metric") && !bw.field) {
    return "Choose the field to weight by under 3 · Base weighting.";
  }
  const tilts = spec.tilts ?? [];
  for (let i = 0; i < tilts.length; i++) {
    const t = tilts[i];
    if (t.type === "metric_tilt" && t.normalisation === "group_max" && (!t.group_by || t.group_by === "none")) {
      return `Choose the group of tilt ${i + 1} under 4 · Tilts.`;
    }
  }
  const solver = spec.constraints?.solver;
  if (solver?.method === "max_score" && !solver.score_field) {
    return "Choose the field to maximise under 5 · Constraints before running a max_score methodology.";
  }
  return null;
}
