import { test } from "node:test";
import assert from "node:assert/strict";
import { passageLabel, passageSummary } from "../src/lib/passages.ts";

// passage-view spec, AC-20 to AC-22 and AC-30
const p = (o: object) => ({ index: 3, char_start: 0, char_end: 3412, chars: 3412, page_start: null, page_end: null, section: null, speaker: null, ...o });

test("summary drops zero parts", () => {
  assert.equal(passageSummary({ passages: 48, short: 0, no_section: 5, empty_pages: [7, 8] }), "48 passages · 5 without a section · pages 7, 8 have no text");
  assert.equal(passageSummary({ passages: 12, short: 0, no_section: 0, empty_pages: [] }), "12 passages");
  assert.equal(passageSummary({ passages: 1, short: 1, no_section: 0, empty_pages: [2] }), "1 passage · 1 under 200 characters · page 2 has no text");
});

test("row label pages", () => {
  assert.equal(passageLabel(p({ page_start: 3, page_end: 3, section: "Item 7" })), "#3 · p. 3 · Item 7 · 3,412 chars");
  assert.equal(passageLabel(p({ page_start: 3, page_end: 4 })), "#3 · p. 3–4 · no section · 3,412 chars");
  assert.equal(passageLabel(p({})), "#3 · no section · 3,412 chars");
});

test("transcript rows name the speaker", () => {
  const label = passageLabel(p({ speaker: "Jane Doe" }));
  assert.ok(label.includes("Jane Doe") && !label.includes("no section"));
});
