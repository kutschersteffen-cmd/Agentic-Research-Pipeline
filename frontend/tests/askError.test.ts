import test from "node:test";
import assert from "node:assert/strict";
import { askErrorText } from "../src/lib/askError.ts";

test("an error card shows the API's detail without the status code", () => {  // review M1, AC-44
  assert.equal(askErrorText(new Error("502: Ask could not answer this question. Try again.")), "Ask could not answer this question. Try again.");
  assert.equal(askErrorText(new Error("Failed to fetch")), "Failed to fetch");
  assert.equal(askErrorText(new Error("422: as_of must be YYYY-MM-DD")), "as_of must be YYYY-MM-DD");
  assert.equal(askErrorText("boom"), "Ask could not answer this question. Try again.");
});
