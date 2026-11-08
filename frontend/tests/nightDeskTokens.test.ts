import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";

// Night Desk release 1 (docs/superpowers/specs/2026-11-08-night-desk-colours-design.md).
// DOM-less: the three theme blocks are parsed straight from index.css.
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");

function blockAfter(src: string, from: number): string {
  const open = src.indexOf("{", from);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(open + 1, i);
  }
  throw new Error("unclosed block");
}
function vars(body: string): Map<string, string> {
  const m = new Map<string, string>();
  for (const [, k, v] of body.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    assert.ok(!m.has(k), `${k} is declared twice in one block`);
    m.set(k, v.trim().toLowerCase());
  }
  return m;
}
function themes(src: string) {
  const light = vars(blockAfter(src, src.indexOf(":root")));
  const media = blockAfter(src, src.indexOf("@media (prefers-color-scheme: dark)"));
  const darkMedia = vars(blockAfter(media, media.indexOf(':root:not([data-theme="light"])')));
  const darkSwitch = vars(blockAfter(src, src.indexOf(':root[data-theme="dark"]')));
  return { light, darkMedia, darkSwitch };
}
const { light, darkMedia, darkSwitch } = themes(css);

const LIGHT: Record<string, string> = {
  "--bg": "#f4f6f9", "--panel": "#ffffff", "--panel-border": "#d8dee7", "--field-border": "#7b8696",
  "--well": "#eaeef3", "--text": "#121722", "--muted": "#4f5a6b", "--accent": "#121722",
  "--sidebar-bg": "#eaeef3", "--on-accent": "#ffffff", "--await": "#f6ecd6", "--await-edge": "#85601a",
  "--hi": "#85601a", "--hi-ink": "#85601a", "--on-hi": "#ffffff", "--high": "#13804f", "--low": "#c8323f",
};
const DARK: Record<string, string> = {
  "--bg": "#0d1015", "--panel": "#141921", "--panel-border": "#2c3644", "--field-border": "#6d7889",
  "--well": "#1b222d", "--text": "#e8ebf0", "--muted": "#a3acbb", "--accent": "#e8ebf0",
  "--sidebar-bg": "#10141a", "--on-accent": "#0d1015", "--await": "rgb(212 166 80 / 0.14)",
  "--await-edge": "#d4a650", "--hi": "#d4a650", "--hi-ink": "#d4a650", "--on-hi": "#0d1015",
  "--high": "#4fd69c", "--low": "#ff6b7a",
};
const eqAll = (got: Map<string, string>, want: Record<string, string>) =>
  assert.deepEqual(Object.fromEntries(Object.keys(want).map((k) => [k, got.get(k)])), want);

test("ac1_light_tokens", () => eqAll(light, LIGHT));
test("ac2_dark_switch_tokens", () => eqAll(darkSwitch, DARK));
test("ac3_dark_media_tokens", () => eqAll(darkMedia, DARK));
for (const [name, block] of [["ac4a_dark_switch_fonts", darkSwitch], ["ac4b_dark_media_fonts", darkMedia]] as const) {
  test(name, () => {
    assert.ok(block.get("--font-display")!.startsWith('"geist"'));
    assert.ok(block.get("--font-mono")!.startsWith('"geist mono"'));
  });
}
test("ac5_no_old_signal_colours", () => assert.doesNotMatch(css, /c6ff3d|ea4c14/i));

type RGB = [number, number, number];
const hex = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
const rgb = (v: string, under: RGB): RGB => {
  if (v.startsWith("#")) return hex(v);
  const [r, g, b, a] = v.match(/[\d.]+/g)!.map(Number);
  return [r, g, b].map((c, i) => c * a + under[i] * (1 - a)) as RGB;
};
const lum = (c: RGB) => {
  const [r, g, b] = c.map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: RGB, b: RGB) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const pairs = (t: Map<string, string>, list: [string, string][], min: number) => {
  const panel = hex(t.get("--panel")!);
  for (const [f, g] of list) {
    const c = contrast(rgb(t.get(f)!, panel), rgb(t.get(g)!, panel));
    assert.ok(c >= min, `${f} on ${g} = ${c.toFixed(2)} < ${min}`);
  }
};
const both = [light, darkSwitch, darkMedia];
test("ac6_text_contrast", () => both.forEach((t) =>
  pairs(t, ["--text", "--muted", "--hi-ink"].flatMap((f) => ["--bg", "--panel", "--well"].map((g) => [f, g] as [string, string])), 4.5)));
test("ac6b_fill_contrast", () => both.forEach((t) =>
  pairs(t, [["--on-accent", "--accent"], ["--on-hi", "--hi"], ["--hi-ink", "--await"]], 4.5)));
test("ac6c_status_contrast", () => both.forEach((t) => pairs(t, [["--high", "--panel"], ["--low", "--panel"]], 3)));

test("ac7_radii", () =>
  assert.deepEqual(["--r-sm", "--r-md", "--r-lg", "--r-pill"].map((k) => light.get(k)), ["6px", "8px", "12px", "999px"]));

test("ac8_nav_count_uses_signal_token", () => {
  const rule = blockAfter(css, css.indexOf("\n.nav-count {"));
  assert.match(rule, /background:\s*var\(--hi\)/);
});

test("ac9_mid_vs_hi_delta", () => {
  const lab = (c: RGB) => {
    const [r, g, b] = c.map((x) => { x /= 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
    const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    const X = f((r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047), Y = f(r * 0.2126 + g * 0.7152 + b * 0.0722),
      Z = f((r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883);
    return [116 * Y - 16, 500 * (X - Y), 200 * (Y - Z)];
  };
  const [a, b] = [lab(hex(darkSwitch.get("--mid")!)), lab(hex(darkSwitch.get("--hi")!))];
  assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) >= 10);
});

test("ac12a_chart_slots", () => {
  const cats = (t: Map<string, string>) => [1, 2, 3, 4].map((i) => t.get(`--cat-${i}`));
  assert.deepEqual(cats(light), ["#2a78d6", "#c2407f", "#a87400", "#6250d6"]);
  assert.deepEqual(cats(darkSwitch), ["#3987e5", "#d55181", "#c98500", "#9085e9"]);
  assert.deepEqual(cats(darkMedia), ["#3987e5", "#d55181", "#c98500", "#9085e9"]);
});

test("ac14_untouched_tokens", (t) => {
  let main: string;
  try { main = execSync("git show origin/main:frontend/src/index.css", { encoding: "utf8" }); }
  catch { t.skip("origin/main not fetched"); return; }
  const before = themes(main);
  const keep = (m: Map<string, string>) => [...m].filter(([k]) =>
    /^--(mid|neutral|accent-ink|accent-tint|text-(xs|sm|base|md|lg|xl)|s-[\w]+|shadow-(md|lg)|ease|dur)$/.test(k));
  assert.deepEqual(keep(light), keep(before.light));
  assert.deepEqual(keep(darkSwitch), keep(before.darkSwitch));
  assert.deepEqual(keep(darkMedia), keep(before.darkMedia));
});

// Amber is the "waiting on a person" colour only: its literals live in the token blocks, nowhere else.
test("amber_literals_only_in_token_blocks", () => {
  const outside = css.replace(/:root\s*\{[\s\S]*?\n\}/, "").replace(/@media \(prefers-color-scheme: dark\)\s*\{[\s\S]*?\n\}/, "")
    .replace(/:root\[data-theme="dark"\]\s*\{[\s\S]*?\n\}/, "");
  assert.doesNotMatch(outside, /#d4a650|#85601a|212 166 80/i);
});

function onMain(t: { skip: (m: string) => void }, cmd: string): string | null {
  try { return execSync(cmd, { encoding: "utf8", cwd: new URL("..", import.meta.url).pathname }); }
  catch { t.skip("origin/main not fetched"); return null; }
}
test("ac12b_palette_untouched", (t) => {
  const out = onMain(t, "git diff origin/main -- src/lib/palette.ts");
  if (out !== null) assert.equal(out, "");
});
test("ac13_amber_usage_unchanged", (t) => {
  // Amber may only be added by the rules that release 2 and 3 approved; everything else must match main.
  const allowed = /\.nav-dot-wait|\.source-excerpt-page mark/;
  const cmd = (ref: string) => `git grep -h -E "var\\(--(hi|hi-ink|await|await-edge)\\)" ${ref} -- src`;
  const main = onMain(t, cmd("origin/main"));
  const head = onMain(t, cmd("HEAD"));
  if (main === null || head === null) return;
  const others = (out: string) => out.split("\n").filter((l) => l && !allowed.test(l)).sort().join("\n");
  assert.equal(others(head), others(main));
});

// Night Desk release 2 (docs/superpowers/specs/2026-11-08-night-desk-status-design.md).
// All top-level rules for a selector, joined (a selector may be split over several rules).
const rule = (sel: string) => {
  const bodies: string[] = [];
  for (let i = css.indexOf(`\n${sel} {`); i >= 0; i = css.indexOf(`\n${sel} {`, i + 1)) bodies.push(blockAfter(css, i));
  assert.ok(bodies.length, `${sel} rule missing`);
  return bodies.join("\n");
};
test("r2_ac1_run_token", () => {
  assert.equal(light.get("--run"), "#2563c9");
  assert.equal(darkSwitch.get("--run"), "#6cb4ff");
  assert.equal(darkMedia.get("--run"), "#6cb4ff");
});
test("r2_ac2_run_contrast", () => both.forEach((t) => pairs(t, [["--run", "--panel"]], 4.5)));
test("r2_ac14_hub_card_radius", () => assert.match(rule(".hub-card"), /border-radius:\s*var\(--r-lg\)/));
test("r2_ac15_tiles_rounded", () => {
  for (const sel of [".dashboard-grid .stat-tile", ".pipeline-pill"]) {
    const r = rule(sel);
    assert.match(r, /border-radius:\s*var\(--r-md\)/, sel);
    assert.doesNotMatch(r, /border-radius:\s*0\b/, sel);
  }
});
test("r2_ac15b_square_controls_unchanged", (t) => {
  const main = onMain(t, "git show origin/main:frontend/src/index.css");
  if (main === null) return;
  for (const sel of [".touchpad button", ".grl-dn", ".view-toggle button:last-child"]) {
    const line = (src: string) => src.split("\n").find((l) => l.startsWith(`${sel} {`));
    assert.equal(line(css), line(main), sel);
  }
});
test("r2_ac16b_status_colours", () => {
  const want: [string, string][] = [
    [".hub-step-status-now", "--run"], [".hub-step-status-failed", "--low"], [".hub-step-status-done", "--muted"],
    [".hub-step-status-idle", "--muted"], [".nav-dot-now", "--run"], [".nav-dot-failed", "--low"], [".nav-dot-done", "--muted"],
  ];
  for (const [sel, tok] of want) {
    const r = rule(sel);
    assert.ok(r.includes(`var(${tok})`), `${sel} uses ${tok}`);
    assert.doesNotMatch(r, /var\(--(hi|hi-ink|await|await-edge)\)/, sel);
  }
});

// Night Desk release 3 (docs/superpowers/specs/2026-11-08-night-desk-excerpt-design.md).
test("r3_ac10_mark_uses_await", () => {
  const r = rule(".source-excerpt-page mark");
  assert.ok(r.includes("var(--await)") && r.includes("var(--await-edge)"));
});
test("r3_ac11_serif", () => assert.match(rule(".source-excerpt-page"), /font-family:\s*"Source Serif 4"/));
test("r3_ac11b_paper_tokens", () => {
  assert.equal(light.get("--paper"), "#ffffff");
  assert.equal(light.get("--ink"), "var(--text)");
  for (const d of [darkSwitch, darkMedia]) { assert.equal(d.get("--paper"), "#f5f2ea"); assert.equal(d.get("--ink"), "#1b1a17"); }
  const r = rule(".source-excerpt-page");
  assert.ok(r.includes("var(--paper)") && r.includes("var(--ink)"));
});
test("r3_ac12_font_loaded", () =>
  assert.match(readFileSync(new URL("../index.html", import.meta.url), "utf8"), /Source\+Serif\+4/));
