import test from "node:test";
import assert from "node:assert/strict";
import { entryTab } from "../src/lib/nav.ts";

// Night Desk release 5 (docs/superpowers/specs/2026-11-09-night-desk-landing-design.md).
test("r5_ac1", () => { for (const h of ["", "#", "#/", "#/welcome"]) assert.equal(entryTab(h), "welcome", h); });
test("r5_ac2", () => { for (const h of ["#/home", "#/review/extraction/r1", "#/argus", "#/nonsense"]) assert.equal(entryTab(h), null, h); });
// Final-review fixes.
const read = async (p: string) => (await import("node:fs")).readFileSync(new URL(p, import.meta.url), "utf8");
test("phones_can_scroll_the_landing_page", async () => {
  const css = await read("../src/index.css");
  const m = css.slice(css.lastIndexOf("@media (max-width: 700px)"));
  assert.match(m, /\.landing \{[^}]*overflow-y: auto/);
});
// Landing brand refresh (docs/superpowers/specs/2026-11-14-landing-brand-refresh-design.md).
// Its see-through intro, serif headline and canvas tests went with the dot animation (expressive-ui-orb, Supersedes).
const css = async () => read("../src/index.css");
const rule = (src: string, sel: string) => {
  const i = src.indexOf(sel + " {");
  assert.ok(i >= 0, sel);
  return src.slice(i, src.indexOf("}", i));
};
const rootBlock = (src: string) => src.slice(src.indexOf(":root {"), src.indexOf("}", src.indexOf(":root {")));
const landingRules = (src: string) => src.match(/\.landing[^{]*\{[^}]*\}/g) ?? [];
// expressive-ui-orb: one token block, brand orange #ff6a2b.
test("ac4_brand_apex", async () => assert.match(rootBlock(await css()), /--brand-apex: #ff6a2b;/));
test("ac5_orb_token", async () => assert.match(rootBlock(await css()), /--orb: #ff6a2b;/));
test("ac6_no_signal_on_landing", async () => {
  for (const r of landingRules(await css())) assert.doesNotMatch(r, /--hi|--await-edge/, r);
});
test("ac7_no_colour_literals_in_landing_css", async () => {
  for (const r of landingRules(await css())) assert.doesNotMatch(r, /#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(/, r);
});
test("ac16_promise_squares", async () => {
  const b = rule(await css(), ".landing-promises b::before");
  for (const d of ["width: 6px", "height: 6px", "border-radius: 0", "background: var(--text)"]) assert.ok(b.includes(d), d);
});
const landingTsx = async () => read("../src/pages/Landing.tsx");
test("ac3_lockup_svg", async () => {
  const src = await landingTsx();
  assert.ok(src.includes('role="img"') && src.includes('aria-label="ARP"') && src.includes("var(--brand-apex)"));
  assert.doesNotMatch(src, /<\/svg>\s*ARP\b/);
});
test("ac14_copy", async () => {
  const src = await landingTsx();
  assert.ok(src.includes("Company research and stewardship at scale."));
  assert.ok(src.includes("Leveraging expert judgement through Agents."));
  assert.ok(!src.includes("Agents propose."));
});
test("ac7_no_colour_literals_in_landing_tsx", async () => assert.doesNotMatch(await landingTsx(), /#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(/));
test("ac6_no_signal_in_landing_tsx", async () => assert.doesNotMatch(await landingTsx(), /--hi\b|--hi-ink|--await-edge/));
