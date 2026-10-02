import { when } from "../lib/runs";
import { valueOrigin, type ReviewTileCounts } from "../lib/stagedFlow";
import type { ReviewDecision } from "../types";

const TILES: [keyof ReviewTileCounts, string][] = [
  ["pending", "Pending"],
  ["approved", "Approved"],
  ["edited", "Edited"],
  ["rejected", "Rejected"],
  ["flagged", "Flagged"],
];

export function ReviewTiles({
  counts,
  active,
  onSelect,
}: {
  counts: ReviewTileCounts;
  active: keyof ReviewTileCounts | null;
  onSelect: (k: keyof ReviewTileCounts | null) => void;
}) {
  return (
    <div className="review-tiles">
      {TILES.map(([k, label]) => (
        <button key={k} type="button" className="secondary" aria-pressed={active === k} onClick={() => onSelect(active === k ? null : k)}>
          <span className="review-tile-count">{counts[k]}</span>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Where a value came from: the system, or a named reviewer's override. */
export function OriginTag({ decision, systemValue }: { decision?: ReviewDecision; systemValue?: string }) {
  if (valueOrigin(decision) === "system" || !decision) return <span className="origin-tag">System</span>;
  return (
    <span className="origin-tag origin-tag-edited">
      Edited by {decision.reviewer ?? "unknown"}, {when(decision.decided_at)}
      {systemValue !== undefined && (
        <details>
          <summary>was: {systemValue}</summary>
        </details>
      )}
    </span>
  );
}
