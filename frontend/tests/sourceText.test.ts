import test from "node:test";
import assert from "node:assert/strict";
import { highlightParts } from "../src/lib/sourceText.ts";

const text = "Emissions (in thousands)\nScope 1  1,234  1,100\nScope 2  500  400\n";
const s = text.indexOf("1,234");

test("highlightParts splits around the span and its line", () => {
  assert.deepEqual(highlightParts(text, s, s + 5), {
    before: "Emissions (in thousands)\n",
    lineBefore: "Scope 1  ",
    mark: "1,234",
    lineAfter: "  1,100",
    after: "\nScope 2  500  400\n",
  });
});

test("highlightParts on the first line has empty before", () => {
  assert.equal(highlightParts(text, 0, 9)?.before, "");
});

test("highlightParts rejects bad offsets", () => {
  assert.equal(highlightParts(text, 5, 5), null);
  assert.equal(highlightParts(text, 0, 999), null);
});
