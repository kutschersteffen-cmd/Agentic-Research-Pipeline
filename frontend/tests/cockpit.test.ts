import { test } from "node:test";
import assert from "node:assert/strict";
import { ballotText, cockpitPath, fmtDate, fmtPct, gapText, isWeekend, monthLabel, pct } from "../src/lib/cockpit.ts";

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
