import test from "node:test";
import assert from "node:assert/strict";
import { drawdownDepthSeries, tickersAfterUpload, uploadErrorText, uploadSummary } from "../src/lib/replication.ts";

// Strategy Replication screen, slice 3 (docs/superpowers/specs/2026-11-23-strategy-replication-fixes.md).

const answer = { tickers: ["T0", "T1", "T2"], rows: 24, first_date: "1965-01-01", last_date: "1966-12-01" };

test("the upload summary names the file, counts and dates", () => {
  assert.equal(uploadSummary("p48.csv", answer), "Uploaded p48.csv: 3 tickers, 24 rows, 1965-01-01 to 1966-12-01.");
});

test("the upload summary uses the singular for one ticker and one row", () => {
  assert.equal(
    uploadSummary("f.csv", { tickers: ["T0"], rows: 1, first_date: "1965-01-01", last_date: "1965-01-01" }),
    "Uploaded f.csv: 1 ticker, 1 row, 1965-01-01 to 1965-01-01.",
  );
});

test("an error with a status keeps the client's text, anything else reads as no answer", () => {
  assert.equal(uploadErrorText(new Error("413: File is larger than the 100 MB upload limit.")), "413: File is larger than the 100 MB upload limit.");
  assert.equal(uploadErrorText(new TypeError("Failed to fetch")), "Upload failed: no answer from the server.");
  assert.equal(uploadErrorText("boom"), "Upload failed: no answer from the server.");
});

test("an empty or blank tickers box takes the file's tickers, a filled one stays", () => {
  assert.equal(tickersAfterUpload("", ["T0", "T1", "T2"]), "T0, T1, T2");
  assert.equal(tickersAfterUpload("  \n ", ["T0", "T1"]), "T0, T1");
  assert.equal(tickersAfterUpload("T1", ["T0", "T1", "T2"]), "T1");
});

test("drawdown depth is 0 while the peak is 0 or below, never NaN", () => {
  assert.deepEqual(drawdownDepthSeries([0, 0]), [0, 0]);
  assert.ok(drawdownDepthSeries([0, 0, 5]).every(Number.isFinite));
});

test("drawdown depth after a positive peak reads as before", () => {
  const depth = drawdownDepthSeries([110, 55, 66]);
  assert.equal(depth[0], 0);
  assert.equal(depth[2].toFixed(1), "40.0");
});
