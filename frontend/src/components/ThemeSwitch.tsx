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

// Skin: Default keeps Graphite/Night; the rest are palettes from awesome-design-md.
const SKIN_KEY = "arp.skin";
const SKINS = { default: "Default", linear: "Linear", notion: "Notion", stripe: "Stripe" } as const;
type Skin = keyof typeof SKINS;

function readSkin(): Skin {
  try {
    const k = localStorage.getItem(SKIN_KEY);
    return k === "linear" || k === "notion" || k === "stripe" ? k : "default";
  } catch {
    return "default";
  }
}

export function SkinSwitch() {
  const [skin, setSkin] = useState<Skin>(readSkin);

  useEffect(() => {
    const root = document.documentElement;
    if (skin === "default") delete root.dataset.skin;
    else root.dataset.skin = skin;
    try {
      if (skin === "default") localStorage.removeItem(SKIN_KEY);
      else localStorage.setItem(SKIN_KEY, skin);
    } catch {
      // Storage blocked: the choice holds for this page only.
    }
  }, [skin]);

  return (
    <label className="skin-switch">
      <span>Skin</span>
      <select value={skin} onChange={(e) => setSkin(e.target.value as Skin)}>
        {(Object.keys(SKINS) as Skin[]).map((k) => (
          <option key={k} value={k}>{SKINS[k]}</option>
        ))}
      </select>
    </label>
  );
}
