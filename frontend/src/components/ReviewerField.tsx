import { useId, useState } from "react";
import { useReviewer } from "../lib/reviewer";

/** Edits the shared identity; any instance updates all the others. The name
 * is typed, not authenticated, and the full field says so: an auditor reading
 * "approved by X" should know it rests on trust.
 *
 * The sidebar carries the full field. Page toolbars use `compact`: once a name
 * is set it reads "Deciding as <name>" with a Change link, so the same person
 * is never shown as three different inputs; with no name it is the input. */
export function ReviewerField({ compact = false }: { compact?: boolean }) {
  const [reviewer, setReviewer] = useReviewer();
  const [editing, setEditing] = useState(false);
  const hintId = useId();
  const name = reviewer.trim();

  if (compact && name && !editing) {
    return (
      <span className="reviewer-field reviewer-field-compact reviewer-readonly">
        Deciding as <b>{name}</b>
        <button className="link-button" onClick={() => setEditing(true)}>
          Change
        </button>
      </span>
    );
  }

  return (
    <label className={compact ? "reviewer-field reviewer-field-compact" : "reviewer-field"}>
      <span>Deciding as</span>
      <input
        value={reviewer}
        onChange={(e) => setReviewer(e.target.value)}
        placeholder="Your name"
        autoComplete="name"
        autoFocus={editing}
        aria-invalid={!name || undefined}
        onBlur={(e) => {
          setReviewer(e.target.value.trim());
          setEditing(false);
        }}
        aria-describedby={hintId}
      />
      <small id={hintId} className={compact ? "visually-hidden" : "reviewer-hint"}>
        Typed on this device, not verified by a login.
      </small>
    </label>
  );
}
