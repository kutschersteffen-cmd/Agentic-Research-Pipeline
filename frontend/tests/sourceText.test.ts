import test from "node:test";
import assert from "node:assert/strict";
import { excerptParts, excerptView, highlightParts } from "../src/lib/sourceText.ts";

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

// Night Desk release 3 (docs/superpowers/specs/2026-11-08-night-desk-excerpt-design.md).
const T = "Intro here. In 2025 revenue grew to €39bn, up 16%. Backlog hit €136bn. Outro.";
const at = (text: string, s: string) => [text.indexOf(s), text.indexOf(s) + s.length] as const;
const ex = (text: string, s: string) => excerptParts(text, ...at(text, s));

test("r3_ac1", () => assert.deepEqual(ex(T, "revenue grew to €39bn"),
  { lead: "Intro here.", before: "In 2025 ", mark: "revenue grew to €39bn", after: ", up 16%.", trail: "Backlog hit €136bn." }));
test("r3_ac2", () => assert.equal(ex(T, "Intro")!.lead, ""));
test("r3_ac3", () => assert.equal(ex(T, "Outro")!.trail, ""));
test("r3_ac4", () => assert.equal(ex("a".repeat(500) + ". X here. Z.", "X")!.lead, "a".repeat(239) + "."));
test("r3_ac5", () => assert.equal(ex("A. X here. " + "b".repeat(500) + ".", "X")!.trail, "b".repeat(240)));
test("r3_ac6", () => { const p = ex("L1\nIn X here\nL3", "X")!; assert.equal(p.lead, "L1"); assert.equal(p.trail, "L3"); });
test("r3_ac6b", () => { const p = ex(T, "Intro here. ")!; assert.equal(p.after, ""); assert.equal(p.trail, "In 2025 revenue grew to €39bn, up 16%."); });
test("r3_ac7", () => {
  assert.equal(excerptParts(T, 5, 5), null);
  assert.equal(excerptParts(T, -1, 3), null);
  assert.equal(excerptParts(T, 0, T.length + 1), null);
});
test("r3_ac8", () => {
  const cases: [string, string][] = [[T, "revenue grew to €39bn"], [T, "Intro"], [T, "Outro"], ["L1\nIn X here\nL3", "X"], [T, "Intro here. "]];
  for (const [text, s] of cases) {
    const p = ex(text, s)!;
    assert.ok(text.includes((p.before + p.mark + p.after).trim()), s);
    assert.ok(text.includes(p.lead) && text.includes(p.trail), s);
  }
});
const src = (o: object) => ({ title: "AR 2025", src: "", ...o }) as Parameters<typeof excerptView>[0];
const txt = (o: object) => ({ run_id: "r", item_key: "k", doc_id: "d", doc_type: "pdf", page: 34, page_start: 0, page_text: T, ...o });
test("r3_ac9", () => {
  const [s, e] = at(T, "revenue grew to €39bn");
  const v = excerptView(src({ text: txt({ char_start: s, char_end: e }) })) as { caption: string; parts: { mark: string } };
  assert.equal(v.caption, "AR 2025 · p. 34");
  assert.equal(v.parts.mark, "revenue grew to €39bn");
});
test("r3_ac9b", () => assert.deepEqual(excerptView(src({ quote: "Revenue was €39bn" })), { caption: "AR 2025", quote: "Revenue was €39bn" }));
test("r3_ac9c", () => {
  const v = excerptView(src({ quote: "Q", text: txt({ char_start: 0, char_end: T.length + 5 }) }));
  assert.deepEqual(v, { caption: "AR 2025 · p. 34", quote: "Q" });
});
test("r3_ac9d", () => assert.equal(excerptView(src({})), null));
test("crlf_lines", () => assert.equal(ex("L1\r\nIn X\r\nL3", "X")!.lead, "L1"));
test("blank_quote_is_null", () => assert.equal(excerptView(src({ quote: "  " })), null));
// Only ". " with a space splits, so "€39.0bn" stays whole (and "e.g. this" would split: accepted).
test("decimal_point_not_a_boundary", () => assert.equal(ex("Revenue was €39.0bn in 2025. Next.", "€39.0bn")!.before, "Revenue was "));
test("page_zero_has_no_suffix", () => assert.equal((excerptView(src({ quote: "Q", text: txt({ page: 0 }) })) as { caption: string }).caption, "AR 2025"));
