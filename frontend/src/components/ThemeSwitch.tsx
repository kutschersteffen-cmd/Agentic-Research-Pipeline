import { useEffect, useState } from "react";

// "System" follows the OS setting through the CSS media query; Light and Dark
// pin a mode with data-theme on <html>. index.html applies a pinned mode
// before first paint; this keeps it in step when someone changes it.
const KEY = "arp.theme";
type Mode = "system" | "light" | "dark";
const LABEL: Record<Mode, string> = { system: "System", light: "Light", dark: "Dark" };

function read(): Mode {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function ThemeSwitch() {
  const [mode, setMode] = useState<Mode>(read);

  useEffect(() => {
    const root = document.documentElement;
    if (mode === "system") delete root.dataset.theme;
    else root.dataset.theme = mode;
    try {
      if (mode === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch {
      // Storage blocked: the choice holds for this page only.
    }
  }, [mode]);

  return (
    <div className="theme-switch" role="group" aria-label="Colour theme">
      {(Object.keys(LABEL) as Mode[]).map((m) => (
        <button key={m} className={mode === m ? "on" : undefined} aria-pressed={mode === m} onClick={() => setMode(m)}>
          {LABEL[m]}
        </button>
      ))}
    </div>
  );
}
