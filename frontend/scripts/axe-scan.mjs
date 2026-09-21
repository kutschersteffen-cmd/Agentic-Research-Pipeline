#!/usr/bin/env node
/**
 * Accessibility scan of the busiest pages, in both themes.
 *
 * Not wired into CI and not a dependency of `npm install`: it needs a
 * browser, which would treble the install for everyone. Run it when the
 * shell, a primitive or a page template changes:
 *
 *   npm run build && npx vite preview --port 4173 &
 *   npm i --no-save playwright axe-core
 *   node scripts/axe-scan.mjs http://localhost:4173/
 *
 * Exits non-zero on any serious or critical violation. As of phase 5 the
 * scan is clean at every impact level, including best-practice rules, so
 * anything it prints is something this change introduced.
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
let chromium, axeSource;
try {
  ({ chromium } = await import("playwright"));
  axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
} catch {
  console.error("Needs playwright and axe-core:  npm i --no-save playwright axe-core");
  process.exit(2);
}

const base = process.argv[2] ?? "http://localhost:4173/";
const ROUTES = ["#/dashboard", "#/extraction", "#/history", "#/search", "#/index", "#/review", "#/library"];
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

const browser = await chromium.launch();
let serious = 0;

for (const colorScheme of ["light", "dark"]) {
  const context = await browser.newContext({ colorScheme, viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  for (const route of ROUTES) {
    await page.goto(base + route, { waitUntil: "networkidle" });
    await page.waitForTimeout(700);
    await page.addScriptTag({ content: axeSource });
    const { violations } = await page.evaluate(
      async (tags) => await window.axe.run(document, { resultTypes: ["violations"], runOnly: { type: "tag", values: tags } }),
      TAGS
    );
    const bad = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    serious += bad.length;
    console.log(`${colorScheme} ${route.padEnd(14)} serious/critical: ${bad.length}  other: ${violations.length - bad.length}`);
    for (const v of violations) {
      console.log(`    [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node${v.nodes.length === 1 ? "" : "s"})`);
      console.log(`        ${v.nodes[0].target.join(" ")}`);
    }
  }
  await context.close();
}

await browser.close();
console.log(`\nserious/critical total: ${serious}`);
process.exit(serious ? 1 : 0);
