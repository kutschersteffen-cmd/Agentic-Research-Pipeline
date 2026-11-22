import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Start page simplified (docs/superpowers/specs/2026-11-15-start-page-simplified-design.md).
const read = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");
const bar = () => read("../src/components/AppTopbar.tsx");
// ui-trim-workspaces: one box; it offers asking only when asking is available.
test("sp_ac3b_ask_only_when_available", () => {
  assert.ok(!bar().includes("start-topbar-ask"));
  assert.ok(bar().includes('canAsk ? "Search or ask…" : "Search…"'));
});
test("sp_ac5_same_badge_source", () => {
  // One badge: the top bar's, fed by /api/waiting.
  assert.ok(bar().includes("waitingBadge("), "AppTopbar");
  assert.ok(read("../src/App.tsx").includes("getWaiting("), "App");
});
test("wc_badge_not_from_review_count", () => {
  assert.ok(!read("../src/App.tsx").includes("review_count"));
});
test("sp_kbd_hints_hidden_from_names", () => {
  const kbds = bar().match(/<kbd[^>]*>/g) ?? [];
  assert.equal(kbds.length, 1); // ui-trim-workspaces: the ⌘J hint left with the Ask ARP button
  for (const k of kbds) assert.ok(k.includes('aria-hidden="true"'), k);
});
test("pr1_no_sidebar_anywhere", () => {
  const app = read("../src/App.tsx");
  for (const gone of ["app-sidebar", "app-topbar", "Open navigation", "nav-scrim"]) assert.ok(!app.includes(gone), gone);
  assert.doesNotMatch(app, /active === "home" \?\s*\(?\s*<AppTopbar/);
  assert.match(app, /<AppTopbar\b/);
  assert.match(app, /<WorkspaceRow\b/);
});

// App-wide top bar, PR 1.
test("pr1_workspaces_button_named", () => assert.match(bar(), /<button(?:(?!<\/button>)[\s\S])*aria-expanded(?:(?!<\/button>)[\s\S])*\)\}\s*>\s*Workspaces/));
test("pr1_menu_closes_on_hashchange", () => assert.ok(read("../src/lib/useDisclosure.ts").includes('addEventListener("hashchange"')));

// Review fix: sticky page parts sit below the sticky top bar instead of sliding under it.
test("pr1_sticky_parts_clear_the_top_bar", () => {
  const css = read("../src/index.css");
  assert.match(css, /--topbar-h: 76px;/);
  assert.match(css, /\.ballot-bar \{ position: sticky; top: var\(--topbar-h\);/);
  assert.match(css, /\.source-panel \{[^}]*top: calc\(var\(--topbar-h\) \+ 12px\);/);
  assert.match(css, /\.ix-rail \{ position: sticky; top: calc\(var\(--topbar-h\) \+ var\(--s-6\)\); \}/);
  // On a phone the two-row bar scrolls away, so nothing needs to clear it.
  assert.match(css, /@media \(max-width: 760px\) \{ :root \{ --topbar-h: 0px; \} \.start-topbar \{ position: static; \} \}/);
});

// Review fix: no message sends people to the sidebar, which is gone.
test("pr1_no_message_points_at_the_sidebar", () => {
  for (const f of ["../src/lib/reviewer.ts", "../src/pages/StewardWorkflow.tsx"]) assert.ok(!/in the sidebar/.test(read(f)), f);
  assert.match(read("../src/lib/reviewer.ts"), /SIGN_IN_REQUIRED = "[^"]*user menu/);
});
