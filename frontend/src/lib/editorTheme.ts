import { useEffect, useState } from "react";

/** The rule editor's theme, following the app's live colour theme: a pinned
 * data-theme on <html> wins, otherwise the OS setting. Accent and font are
 * read from the CSS tokens so the editor never drifts from the palette. */
export function useEditorTheme() {
  const read = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const css = getComputedStyle(root);
    return {
      mode: dark ? ("dark" as const) : ("light" as const),
      token: { colorPrimary: css.getPropertyValue("--accent").trim(), fontFamily: css.getPropertyValue("--font-display").trim(), borderRadius: 0 },
    };
  };
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const update = () => setTheme(read());
    const media = matchMedia("(prefers-color-scheme: dark)");
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    media.addEventListener("change", update);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, []);
  return theme;
}
