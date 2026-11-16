import test from "node:test";
import assert from "node:assert/strict";
import { reviewSlide } from "../src/lib/findings.ts";

test("reviewSlide reads the slide number from the download gate's 409", () => {
  assert.equal(reviewSlide("409: Slide 2 needs review"), 2);
  assert.equal(reviewSlide("409: Slide 12 needs review"), 12);
  assert.equal(reviewSlide("404: Report not found"), null);
  assert.equal(reviewSlide("500: Slide 2 needs review"), null);
  assert.equal(reviewSlide(""), null);
});
