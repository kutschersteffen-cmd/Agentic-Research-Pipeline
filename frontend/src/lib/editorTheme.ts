import { useState } from "react";

/** The rule editor's theme: always its dark setting, since ARP has one theme (black). Accent and font are
 * read from the CSS tokens so the editor never drifts from the palette. */
export function useEditorTheme() {
  const [theme] = useState(() => {
    const css = getComputedStyle(document.documentElement);
    return {
      mode: "dark" as const,
      token: { colorPrimary: css.getPropertyValue("--accent").trim(), fontFamily: css.getPropertyValue("--font-display").trim(), borderRadius: 0 },
    };
  });
  return theme;
}
