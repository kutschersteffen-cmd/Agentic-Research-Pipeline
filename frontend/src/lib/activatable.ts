import type { KeyboardEvent } from "react";

/** Props that make a non-button element -- a clickable table row -- work from
 * the keyboard: it takes focus, and Enter or Space activates it like a click.
 * Pass `expanded` for rows that toggle a detail row open. */
export function activatable(onActivate: () => void, expanded?: boolean) {
  return {
    tabIndex: 0,
    onClick: onActivate,
    onKeyDown: (e: KeyboardEvent) => {
      // Keys typed into a control nested in the row are not row activations.
      if (e.target !== e.currentTarget) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate();
      }
    },
    "aria-expanded": expanded,
  };
}
