import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";

// Night Desk release 1 (docs/superpowers/specs/2026-11-08-night-desk-colours-design.md).
// DOM-less: the token block is parsed straight from index.css. Since expressive-ui-orb
// (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md, Supersedes) there is one block: black.
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
const root = vars(blockAfter(css, css.indexOf(":root {")));

// expressive-ui-orb, The black look: the token table (all other tokens keep the old dark value).
const BLACK: Record<string, string> = {
  "--bg": "#000000", "--panel": "#0b0c0f", "--panel-2": "#101217", "--panel-border": "rgb(255 255 255 / 0.10)",
  "--panel-border-strong": "rgb(255 255 255 / 0.18)", "--field-border": "#6d7889", "--well": "#101217",
  "--text": "#eceef2", "--muted": "#9aa3b2", "--accent": "#eceef2", "--accent-tint": "rgb(236 238 242 / 0.08)",
  "--sidebar-bg": "#050506", "--on-accent": "#000000", "--await": "rgb(224 178 90 / 0.14)",
  "--await-edge": "#e0b25a", "--hi": "#e0b25a", "--hi-ink": "#e0b25a", "--on-hi": "#000000",
  "--high": "#4fd69c", "--low": "#ff6b7a", "--brand-apex": "#ff6a2b", "--orb": "#ff6a2b",
  "--font-pixel": '"geist pixel square", "geist mono", ui-monospace, monospace',
};
const eqAll = (got: Map<string, string>, want: Record<string, string>) =>
  assert.deepEqual(Object.fromEntries(Object.keys(want).map((k) => [k, got.get(k)])), want);

test("orb_ac5_black_tokens", () => eqAll(root, BLACK));
test("orb_one_theme_block", () => {
  assert.equal(css.match(/(^|\n):root\s*\{/g)?.length, 1, "one :root block");
  assert.doesNotMatch(css, /prefers-color-scheme|data-theme/);
  assert.match(blockAfter(css, css.indexOf(":root {")), /color-scheme: dark;/);
});
test("ac4_fonts", () => {
  assert.ok(root.get("--font-display")!.startsWith('"geist"'));
  assert.ok(root.get("--font-mono")!.startsWith('"geist mono"'));
});
// The old light brand orange #ea4c14 is gone with the light theme; #ff6a2b is the brand orange and is never the signal. Lime stays banned.
test("ac5_no_old_signal_colours", () => {
  assert.doesNotMatch(css, /c6ff3d/i);
  assert.doesNotMatch(css, /ea4c14/i);
});
test("ac5_brand_orange_is_not_the_signal", () => {
  for (const k of ["--hi", "--hi-ink", "--await-edge", "--on-hi"]) assert.doesNotMatch(root.get(k) ?? "", /ea4c14|ff6a2b/i, k);
});

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
const both = [root];
test("ac6_text_contrast", () => both.forEach((t) =>
  pairs(t, ["--text", "--muted", "--hi-ink"].flatMap((f) => ["--bg", "--panel", "--well"].map((g) => [f, g] as [string, string])), 4.5)));
test("ac6b_fill_contrast", () => both.forEach((t) =>
  pairs(t, [["--on-accent", "--accent"], ["--on-hi", "--hi"], ["--hi-ink", "--await"]], 4.5)));
test("ac6c_status_contrast", () => both.forEach((t) => pairs(t, [["--high", "--panel"], ["--low", "--panel"]], 3)));

test("ac7_radii", () =>
  assert.deepEqual(["--r-sm", "--r-md", "--r-lg", "--r-pill"].map((k) => root.get(k)), ["6px", "8px", "12px", "999px"]));

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
  const [a, b] = [lab(hex(root.get("--mid")!)), lab(hex(root.get("--hi")!))];
  assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) >= 10);
});

test("ac12a_chart_slots", () => {
  const cats = (t: Map<string, string>) => [1, 2, 3, 4].map((i) => t.get(`--cat-${i}`));
  assert.deepEqual(cats(root), ["#3987e5", "#d55181", "#c98500", "#9085e9"]);
});

test("ac14_untouched_tokens", (t) => {
  let main: string;
  try { main = execSync("git show origin/main:frontend/src/index.css", { encoding: "utf8" }); }
  catch { t.skip("origin/main not fetched"); return; }
  // Compared with origin/main's root block, or, while main still has the dark blocks, with its dark values over its root block.
  const mainRoot = vars(blockAfter(main, main.indexOf(":root {")));
  const darkAt = main.indexOf(':root[data-theme="dark"]');
  const before = new Map([...mainRoot, ...(darkAt >= 0 ? vars(blockAfter(main, darkAt)) : [])]);
  const keep = (m: Map<string, string>) => [...m].filter(([k]) =>
    /^--(mid|neutral|accent-ink|text-(xs|sm|base|md|lg|xl)|s-[\w]+|shadow-(md|lg)|ease|dur)$/.test(k)).sort();
  assert.deepEqual(keep(root), keep(before));
});

// Amber is the "waiting on a person" colour only: its literals live in the token blocks, nowhere else.
test("amber_literals_only_in_token_blocks", () => {
  const outside = css.replace(/:root\s*\{[\s\S]*?\n\}/, "");
  assert.doesNotMatch(outside, /#e0b25a|#d4a650|#85601a|224 178 90|212 166 80/i);
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
  // The ARP logo's highlight square (sidebar and landing page) is the brand mark, not a status.
  // UI polish 2 L9: the Argus phone card's "Needs you" status dot is a waiting state.
  // Deferred polish minors: a waiting Argus document row tints its whole phone card (the cells' amber, moved to the card).
  // Expressive UI Orb, slice 2: the rail's wait segment, the waiting glow of a start card and its figure area, the
  // drawing's status part, and the hero's "n items need you" link, which the spec sets in the signal colour.
  // Slice 3: the waiting glow of a workspace's figure area and of a process panel.
  const allowed = /\.hub-ws-fig\[data-tone="wait"\] \{|\.hub-process\[data-state="wait"\] \{|\.hub-rail \[data-seg="wait"\] \{|@keyframes rail-breathe \{|\.hub-card-await \.hub-card-fig \{|\.ws-drawing \.ws-lit-wait \{|\.hub-hero-lead a \{|\.source-excerpt-page mark|\.hub-status-wait|\.hub-mark-wait|\.ws-accent-wait|\.hub-card-await \{|td\[data-status="needs-you"\]::before|tr\.argus-row-await \{|<rect x="26" y="2" width="10" height="10" fill="var\(--hi\)" \/>/;
  const cmd = (ref: string) => `git grep -h -E "var\\(--(hi|hi-ink|await|await-edge)\\)" ${ref} -- src`;
  const main = onMain(t, cmd("origin/main"));
  const head = onMain(t, cmd("HEAD"));
  if (main === null || head === null) return;
  const others = (out: string) => out.split("\n").filter((l) => l && !allowed.test(l));
  // Removing amber (with the code that used it) is fine; adding a use main doesn't have is not.
  const mainLines = new Set(others(main));
  assert.deepEqual(others(head).filter((l) => !mainLines.has(l)), []);
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
  assert.equal(root.get("--run"), "#5fb0ff");
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
    // .nav-dot-* went with the sidebar (2026-11-15-app-wide-top-bar spec).
    [".hub-step-status-idle", "--muted"],
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
  assert.equal(root.get("--paper"), "#f5f2ea");
  assert.equal(root.get("--ink"), "#1b1a17");
  const r = rule(".source-excerpt-page");
  assert.ok(r.includes("var(--paper)") && r.includes("var(--ink)"));
});
test("r3_ac12_font_loaded", () =>
  assert.match(readFileSync(new URL("../index.html", import.meta.url), "utf8"), /Source\+Serif\+4/));
// The card is light paper on the black page, so its mark uses the paper's own amber.
test("r3_paper_mark_visible_in_dark", () => {
  const r = rule(".source-excerpt-page");
  assert.match(r, /--await:\s*var\(--paper-mark\)/);
  assert.match(r, /--await-edge:\s*var\(--paper-mark-edge\)/);
  assert.equal(root.get("--paper-mark"), "#f6ecd6");
  assert.equal(root.get("--paper-mark-edge"), "#85601a");
});

// Night Desk release 4 rows r4_ac10–r4_ac11c and r4_waiting_link_wraps (card icon box, footer, waiting
// link, stats) were retired by docs/superpowers/specs/2026-11-15-start-page-simplified-design.md (Supersedes).
