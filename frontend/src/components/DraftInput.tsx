import { useState, type InputHTMLAttributes } from "react";

/** A text field for a parsed value (a comma list, tier boundaries, multiplier lines). While it has focus it
 * shows exactly what was typed and hands the owner each parsed change; without focus it shows the owner's
 * value, so a loaded preset shows at once and a half-typed tail disappears on blur. */
export function DraftInput({
  value,
  onText,
  multiline = false,
  rows,
  ...rest
}: { value: string; onText: (text: string) => void; multiline?: boolean; rows?: number } & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "rows">) {
  const [draft, setDraft] = useState<string | null>(null);
  const shared = {
    value: draft ?? value,
    onFocus: () => setDraft(value),
    onBlur: () => setDraft(null),
    onChange: (e: { target: { value: string } }) => {
      setDraft(e.target.value);
      onText(e.target.value);
    },
  };
  return multiline ? (
    <textarea rows={rows} aria-label={rest["aria-label"]} {...shared} />
  ) : (
    <input type="text" {...rest} {...shared} />
  );
}
