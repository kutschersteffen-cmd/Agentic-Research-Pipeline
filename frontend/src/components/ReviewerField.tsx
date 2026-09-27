import { useReviewer } from "../lib/reviewer";

/** Edits the shared identity; any instance updates all the others. */
export function ReviewerField({ compact = false }: { compact?: boolean }) {
  const [reviewer, setReviewer] = useReviewer();
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
      />
    </label>
  );
}
