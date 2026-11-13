import { useEffect, useRef, useState } from "react";

/** Keyboard focus after a row action took the focused button away (Save, Cancel, Remove, Delete): `focusRow(id)`
 * moves it to the first link or button of the row marked `data-row={id}`, or to the table when that row is gone
 * or `id` is undefined. Give the table the returned ref and `tabIndex={-1}`. */
export function useRowFocus() {
  const table = useRef<HTMLTableElement>(null);
  const [target, setTarget] = useState<{ id?: string } | null>(null);
  useEffect(() => {
    if (!target) return; // runs after the render that removed or restored the row
    const row = target.id === undefined ? null : table.current?.querySelector<HTMLElement>(`[data-row="${CSS.escape(target.id)}"] :is(a, button)`);
    (row ?? table.current)?.focus();
  }, [target]);
  return [table, (id?: string) => setTarget({ id })] as const;
}

/** The row to move to when row `i` goes away: the next one, else the one before. */
export const neighbour = <T>(rows: T[], i: number): T | undefined => rows[i + 1] ?? rows[i - 1];
