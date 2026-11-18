import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = (p: string) => readFileSync(new URL(`../src/${p}`, import.meta.url), "utf8");

test("step 1 and XBRL Facts mount the same company picker (AC-67)", () => {
  for (const page of ["pages/ArgusFlow.tsx", "components/XbrlFetchArea.tsx"]) {
    assert.match(src(page), /<CompanyPicker\b/, page);
    assert.doesNotMatch(src(page), /<UniversePicker\b/, page);
  }
});

test("the company picker has step 1's controls and labels", () => {
  const picker = src("components/CompanyPicker.tsx");
  for (const label of ["Upload a list", "Or pick a saved universe", "Add one company", "Name", "Ticker", ">Add<"]) assert.ok(picker.includes(label), label);
});
