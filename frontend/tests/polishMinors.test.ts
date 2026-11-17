import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Deferred minors from UI polish 2 (#573, #574) and the app-wide top bar PR 2 (#577).
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
const rule = (sel: string) => {
  const i = css.indexOf(`${sel} {`);
  assert.ok(i >= 0, `${sel} rule missing`);
  return css.slice(i, css.indexOf("}", i));
};

test("minor_dashboard_grid_frame_not_doubled", () => {
  // The translucent dark border must not sit over the grid's own translucent background.
  assert.match(rule(".dashboard-grid"), /background-clip: padding-box/);
});

test("minor_company_facts_frame_steps_back_on_phone", () => {
  assert.match(css, /@media \(max-width: 560px\) \{ \.company-page \.split-review-main > \.table-wrap:has\(> \.data-table\.stack-on-phone\) \{ padding: 0; border: 0; \} \}/);
});

test("minor_selected_and_await_rows_tint_the_card", () => {
  assert.match(rule(".data-table.stack-on-phone tr:is([aria-current], .selected-row)"), /background: var\(--accent-tint\)/);
  assert.match(rule(".data-table.stack-on-phone tr.argus-row-await"), /background: color-mix\(in srgb, var\(--await\) 60%, transparent\)/);
  assert.match(rule(".data-table.stack-on-phone tr:is([aria-current], .selected-row, .argus-row-await) > :is(td, th)"), /background: transparent/);
});

test("minor_argus_cards_no_double_inset", () => {
  assert.doesNotMatch(css, /\.argus-results \.data-table\.stack-on-phone td, \.argus-progress \.data-table\.stack-on-phone td \{ padding-inline/);
});

test("minor_tablet_header_skips_argus_start", () => {
  assert.ok(css.includes(".page.hub:not(.hub-start, .argus-start) { position: relative; }"));
  assert.ok(!css.includes(".page.hub:not(.hub-start) { position: relative; }"));
});
