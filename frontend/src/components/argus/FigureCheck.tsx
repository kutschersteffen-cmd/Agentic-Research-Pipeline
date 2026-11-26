import type { DeskAnswer } from "../../types";

/** How many sentences were found in a source, calculated or still to check. */
export function FigureCheck({ check }: { check: DeskAnswer["check"] }) {
  return (
    <div className="desk-figurecheck">
      <strong>{check.to_check === 0 ? "Every figure checked." : `${check.to_check} to check.`}</strong>
      <span className="desk-pill" data-kind="found">{check.found} in source</span>
      <span className="desk-pill" data-kind="calculated">{check.calculated} calculated</span>
      <span className="desk-pill" data-kind="to_check">{check.to_check} to check</span>
    </div>
  );
}
