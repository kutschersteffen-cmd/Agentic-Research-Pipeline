import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Start page simplified (docs/superpowers/specs/2026-11-15-start-page-simplified-design.md).
const read = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");
const bar = () => read("../src/components/AppTopbar.tsx");
test("sp_ac3b_ask_only_when_available", () => assert.match(bar(), /\{canAsk && \(\s*<button[^>]*className="start-topbar-ask"/));
test("sp_ac5_same_badge_source", () => {
  assert.ok(bar().includes("reviewBadge("), "StartTopbar");
  assert.ok(read("../src/App.tsx").includes("reviewBadge("), "App");
});
test("sp_kbd_hints_hidden_from_names", () => {
  const kbds = bar().match(/<kbd[^>]*>/g) ?? [];
  assert.equal(kbds.length, 2);
  for (const k of kbds) assert.ok(k.includes('aria-hidden="true"'), k);
});
test("sp_ac1_home_has_no_sidebar", () => assert.match(read("../src/App.tsx"), /active === "home" \?\s*\(?\s*<AppTopbar/));

// App-wide top bar, PR 1.
test("pr1_workspaces_button_named", () => assert.match(bar(), /<button(?:(?!<\/button>)[\s\S])*aria-expanded(?:(?!<\/button>)[\s\S])*\)\}\s*>\s*Workspaces/));
test("pr1_menu_closes_on_hashchange", () => assert.ok(read("../src/lib/useDisclosure.ts").includes('addEventListener("hashchange"')));
