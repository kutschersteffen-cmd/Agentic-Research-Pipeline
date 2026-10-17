import test from "node:test";
import assert from "node:assert/strict";
import { modeOf, withMode } from "../src/lib/runModes.ts";

const defaults = { llm_model: "claude-sonnet-5-5", llm_verifier_model: "claude-opus-5-5", evidence_max_chunks: 12, xbrl_facts_enabled: true };
const modes = {
  cheap: { llm_model: "gemini-3.8-flash", llm_verifier_model: "claude-sonnet-5-5", evidence_max_chunks: 8 },
  normal: { llm_model: "claude-sonnet-5-5", llm_verifier_model: "claude-opus-5-5", evidence_max_chunks: 12 },
};

test("no overrides is the mode that equals the defaults", () => {
  assert.equal(modeOf(modes, {}, defaults), "normal");
});

test("picking a mode keeps other overrides and leaves out settings equal to the default", () => {
  const next = withMode(modes.cheap, { xbrl_facts_enabled: false, evidence_max_chunks: 30 }, defaults);
  assert.deepEqual(next, { xbrl_facts_enabled: false, llm_model: "gemini-3.8-flash", llm_verifier_model: "claude-sonnet-5-5", evidence_max_chunks: 8 });
  assert.equal(modeOf(modes, next, defaults), "cheap");
  assert.deepEqual(withMode(modes.normal, next, defaults), { xbrl_facts_enabled: false });
});

test("a hand-changed mode setting no longer matches any mode", () => {
  assert.equal(modeOf(modes, { ...withMode(modes.cheap, {}, defaults), evidence_max_chunks: 9 }, defaults), null);
});
