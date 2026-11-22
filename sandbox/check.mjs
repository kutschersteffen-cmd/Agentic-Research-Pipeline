// Code checks before a run (spec agent-panel-code-mode, Phase 4): first the line limit, then a parse.
import { parse } from "acorn";

export const LINE_LIMIT = 400;

export function checkCode(code) {
  if (typeof code !== "string") return { ok: false, error: "code must be a string" };
  if (code.split("\n").length > LINE_LIMIT) return { ok: false, error: `code exceeds ${LINE_LIMIT} lines` };
  try {
    // The code is the body of an async function, as the executor runs it; a bare arrow function also parses here.
    parse(`(async () => {\n${code}\n})`, { ecmaVersion: "latest", sourceType: "module" });
  } catch (err) {
    return { ok: false, error: `code does not parse: ${err.message}` };
  }
  return { ok: true, error: null };
}
