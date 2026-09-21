#!/usr/bin/env node
/**
 * Design-system guardrails, with no dependency to install.
 *
 * The rules below are the ones docs/UI_DESIGN_IMPROVEMENT_PLAN.md says the
 * system depends on. They are cheap to check and expensive to rediscover by
 * eye, which is exactly what drifted the first time:
 *
 *   1. Colour, type and radius values live in tokens.css and nowhere else.
 *   2. Spacing in the stylesheets comes off the --sp-* scale.
 *   3. An inline style in a component is a computed value, never a static one.
 *   4. Every class a component names exists in the stylesheets.
 *
 * Run: npm run check:design     (also runs in CI)
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;
const TOKENS = "styles/tokens.css";
const problems = [];

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const files = walk(SRC);
const cssFiles = files.filter((f) => f.endsWith(".css"));
const tsxFiles = files.filter((f) => f.endsWith(".tsx"));

const report = (file, line, rule, detail) =>
  problems.push(`${relative(SRC, file)}:${line}  [${rule}] ${detail}`);

/** Strip comment bodies (keeping line numbers) so a hex quoted in a comment
 *  is not a finding. A line carrying `ds-allow` opts out entirely -- used
 *  where a value genuinely is not on a scale, e.g. a clip-path offset. */
function lines(file) {
  const raw = readFileSync(file, "utf8").split("\n");
  const stripped = readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .split("\n");
  return stripped.map((text, i) => (raw[i].includes("ds-allow") ? "" : text));
}

// --- 1..2: stylesheet rules ---------------------------------------------------

const RADIUS_PART = /^(0|50%|var\(--r-[a-z]+\))$/;

/** Squashes whitespace inside parentheses so calc(a + b) is a single token. */
function collapseParens(value) {
  let depth = 0;
  let out = "";
  for (const ch of value) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    out += depth > 0 && /\s/.test(ch) ? "" : ch;
  }
  return out;
}
// Viewport- and percentage-relative values are positions, not spacing steps.
const SPACE_VALUE = /^(0|auto|inherit|revert|-?\d+(\.\d+)?(vh|vw|%)|var\(--sp-[0-9]+\)|calc\(.+\))$/;

for (const file of cssFiles) {
  const isTokens = relative(SRC, file) === TOKENS;
  lines(file).forEach((text, i) => {
    const n = i + 1;
    if (!isTokens) {
      const colour = text.match(/(#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\()/);
      if (colour) report(file, n, "raw-colour", `${colour[0]} — colours live in ${TOKENS}`);

      const fontSize = text.match(/font-size:\s*([^;]+)/);
      if (fontSize && !fontSize[1].includes("var(--fs-")) {
        report(file, n, "raw-type", `font-size: ${fontSize[1].trim()} — use a --fs-* step`);
      }

      const radius = text.match(/border-radius:\s*([^;]+)/);
      if (radius && !radius[1].split(/\s+/).every((part) => RADIUS_PART.test(part))) {
        report(file, n, "raw-radius", `border-radius: ${radius[1].trim()} — use a --r-* step`);
      }

      const space = text.match(/(?:^|[;{]|\s)(padding|margin|gap|row-gap|column-gap):\s*([^;}]+)/);
      // A function value is one token however many spaces are inside it.
      const spaceParts = space ? collapseParens(space[2]).trim().split(/\s+/) : [];
      if (space && !spaceParts.every((part) => SPACE_VALUE.test(part))) {
        report(file, n, "raw-space", `${space[1]}: ${space[2].trim()} — use --sp-* steps`);
      }
    }
  });
}

// --- 3: static inline styles --------------------------------------------------

const LITERAL_PAIR = /^[A-Za-z-]+\s*:\s*("[^"]*"|'[^']*'|-?\d+(\.\d+)?)$/;

for (const file of tsxFiles) {
  const text = readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    const m = line.match(/style=\{\{([^}]*)\}\}/);
    if (!m) return;
    const body = m[1].trim();
    if (!body) return;
    const parts = body.split(",").map((p) => p.trim()).filter(Boolean);
    if (parts.every((p) => LITERAL_PAIR.test(p))) {
      report(file, i + 1, "static-inline-style", `${body} — give it a class instead`);
    }
  });
}

// --- 4: class names that exist ------------------------------------------------

const defined = new Set();
for (const file of cssFiles) {
  for (const match of readFileSync(file, "utf8").matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) defined.add(match[1]);
}
// Classes the app never writes in CSS but the platform or a library owns.
const ALLOWED = new Set(["sr-only"]);

for (const file of tsxFiles) {
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((line, i) => {
      for (const match of line.matchAll(/className=(?:"([^"]*)"|\{([^}]*)\})/g)) {
        let value = match[1];
        if (value === undefined) {
          // An expression: only the branches of a conditional name classes --
          // the strings before the `?` are the test, not class names.
          const expr = match[2] ?? "";
          if (expr.includes("${")) continue; // interpolated at runtime
          const branches = expr.includes("?") ? expr.slice(expr.indexOf("?")) : expr;
          value = [...branches.matchAll(/["`]([^"`]*)["`]/g)].map((m) => m[1]).join(" ");
        }
        if (value.includes("${")) continue; // built at runtime
        for (const name of value.split(/\s+/).filter(Boolean)) {
          if (!defined.has(name) && !ALLOWED.has(name)) {
            report(file, i + 1, "unknown-class", `"${name}" is not defined in any stylesheet`);
          }
        }
      }
    });
}

// --- report -------------------------------------------------------------------

if (problems.length) {
  console.error(`Design-system check: ${problems.length} problem${problems.length === 1 ? "" : "s"}\n`);
  for (const p of problems) console.error("  " + p);
  console.error("\nSee docs/UI_DESIGN_IMPROVEMENT_PLAN.md for why each rule exists.");
  process.exit(1);
}
console.log("Design-system check: clean");
