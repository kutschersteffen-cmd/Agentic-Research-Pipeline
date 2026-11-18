import { test } from "node:test";
import assert from "node:assert/strict";
import { ballotText, cockpitPath, fmtDate, fmtPct, gapText, isWeekend, monthLabel, pct, themeLabel, themeScale, topicNote } from "../src/lib/cockpit.ts";

// The page passes route params[1] of `#/stewardiq/cockpit/<as_of>` as `asOf` (AC-73).
const segment = (hash: string) => hash.replace(/^#\/?/, "").split("/").filter(Boolean)[2];

test("AC-73: the as_of path segment is sent; without it no as_of is sent", () => {
  assert.equal(cockpitPath(segment("#/stewardiq/cockpit/2026-11-17")), "/api/stewardship/cockpit?as_of=2026-11-17");
  assert.equal(cockpitPath(segment("#/stewardiq/cockpit")), "/api/stewardship/cockpit");
  assert.equal(cockpitPath(undefined, "P 1"), "/api/stewardship/cockpit?portfolio_id=P+1");
});

test("percentages are whole numbers rounded half up, dash without a base", () => {
  assert.equal(pct(1, 8), 13);
  assert.equal(pct(29, 200), 15); // 14.5 -> 15, no float drift
  assert.equal(pct(1, 3), 33);
  assert.equal(fmtPct(0, 0), "–");
  assert.equal(fmtPct(34, 120), "28%");
});

test("ballot wording, due ones by days left", () => {
  assert.equal(ballotText("not_started", true, 0), "Decision due today");
  assert.equal(ballotText("awaiting", true, 1), "Decision due in 1 day");
  assert.equal(ballotText("not_started", true, 6), "Decision due in 6 days");
  assert.equal(ballotText("not_started", false, 9), "Not started");
  assert.equal(ballotText("decided", false, 2), "Decided, not cast");
  assert.equal(ballotText("cast", false, 2), "Cast");
  assert.equal(ballotText("awaiting", false, 12), "Awaiting decision");
});

test("gap text, dates, weekends and month labels", () => {
  assert.equal(gapText(["no_objective", "no_next_meeting"]), "No objective · No next meeting");
  assert.equal(fmtDate("2026-11-27"), "27 Nov 2026");
  assert.deepEqual(["2026-11-21", "2026-11-22", "2026-11-23"].map(isWeekend), [true, true, false]);
  assert.deepEqual([monthLabel("2026-11-17", true), monthLabel("2026-11-18", false), monthLabel("2026-12-01", false)], ["Nov", "", "Dec"]);
});

test("index.css braces balance: a lost } would nest every later rule inside the cockpit's media query", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.equal(css.split("{").length, css.split("}").length);
});

// spec cockpit-review-fixes: the page styles a ballot with the signal colour exactly when `action_due` is true
test("AC-7: a declined ballot keeps its word, due or not", () => {
  assert.equal(ballotText("declined", false, 9), "Declined");
  assert.equal(ballotText("declined", true, 0), "Declined · decision due today");
  assert.equal(ballotText("declined", true, 1), "Declined · decision due in 1 day");
  assert.equal(ballotText("declined", true, 3), "Declined · decision due in 3 days");
});

const width = (s: number, max: number) => (s / max) * 100;

test("AC-8: named themes on their own scale, All themes and No theme yet on the total", () => {
  const themes = [{ theme: "Climate", selected: 120 }, { theme: "Nature", selected: 25 }, { theme: "Other", selected: 2181 }];
  const { maxOf } = themeScale(themes, 2300);
  assert.equal(width(120, maxOf("Climate")), 100);
  assert.ok(Math.abs(width(25, maxOf("Nature")) - 20.8) <= 0.1);
  assert.equal(width(2300, maxOf(null)), 100);
  assert.ok(Math.abs(width(2181, maxOf("Other")) - 94.8) <= 0.1);
  assert.equal(themeLabel("Other"), "No theme yet");
  assert.equal(themeLabel("Climate"), "Climate");
});

test("AC-15, AC-16: the scale line names only the rows that exist", () => {
  assert.equal(
    themeScale([{ theme: "Climate", selected: 10 }, { theme: "Nature", selected: 0 }], 40).note,
    "Theme rows: a full bar is 10 companies. All themes: a full bar is 40 companies.",
  );
  assert.equal(themeScale([{ theme: "Climate", selected: 0 }, { theme: "Other", selected: 40 }], 40).note, "All themes and No theme yet: a full bar is 40 companies.");
  assert.equal(
    themeScale([{ theme: "Climate", selected: 1200 }, { theme: "Other", selected: 2181 }], 2300).note,
    "Theme rows: a full bar is 1,200 companies. All themes and No theme yet: a full bar is 2,300 companies.",
  );
});

test("topic row with and without votes (spec vote-abstain-and-seed-fixes AC-18, AC-21)", () => {
  const row = (t: { votes: number; against_management: number; abstain: number }) => `${fmtPct(t.against_management, t.votes)} ${topicNote(t)}`;
  assert.equal(row({ votes: 0, against_management: 0, abstain: 0 }), "– · 0 of 0 · – abstained or withheld");
  assert.equal(row({ votes: 3, against_management: 1, abstain: 3 }), "33% · 1 of 3 · 100% abstained or withheld");
  assert.equal(row({ votes: 1200, against_management: 30, abstain: 6 }), "3% · 30 of 1,200 · 1% abstained or withheld");
});
