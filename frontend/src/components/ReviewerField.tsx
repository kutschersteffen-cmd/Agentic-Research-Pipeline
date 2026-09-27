import { useId } from "react";
import { useReviewer } from "../lib/reviewer";

/** Edits the shared identity; any instance updates all the others. The name
 * is typed, not authenticated, and the full field says so: an auditor reading
 * "approved by X" should know it rests on trust. */
export function ReviewerField({ compact = false }: { compact?: boolean }) {
  const [reviewer, setReviewer] = useReviewer();
  const hintId = useId();
  return (
    <label className={compact ? "reviewer-field reviewer-field-compact" : "reviewer-field"}>
      <span>Reviewing as</span>
      <input
        value={reviewer}
        onChange={(e) => setReviewer(e.target.value)}
        placeholder="Your name"
        autoComplete="name"
        aria-invalid={!reviewer.trim() || undefined}
        onBlur={(e) => setReviewer(e.target.value.trim())}
        aria-describedby={hintId}
      />
      <small id={hintId} className={compact ? "visually-hidden" : "reviewer-hint"}>
        Typed on this device, not verified by a login.
      </small>
    </label>
  );
}
