import { useState } from "react";

/** An optional comment on a decision: folded until wanted, then a labelled
 * field (a placeholder is not a label once someone starts typing). */
export function CommentField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(value !== "");
  if (!open) {
    return (
      <button className="link-button comment-toggle" onClick={() => setOpen(true)}>
        Add a comment
      </button>
    );
  }
  return (
    <label className="field-label">
      Comment (optional)
      <textarea rows={2} value={value} onChange={(e) => onChange(e.target.value)} autoFocus />
    </label>
  );
}
