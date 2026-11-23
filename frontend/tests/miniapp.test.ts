import test from "node:test";
import assert from "node:assert/strict";
import { MINIAPP_SANDBOX, miniappAction, miniappDocument } from "../src/lib/miniapp.ts";

// Mini-apps (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, slice 11, D14).

test("the frame runs nothing: its sandbox is empty (AC-54c)", () => {
  assert.equal(MINIAPP_SANDBOX, "");
});

test("srcdoc is the spec's wrapper, exactly", () => {
  assert.equal(miniappDocument("<p>x</p>"),
    `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:"><body><p>x</p></body>`);
});

test("the action reads Show as mini-app until one is stored, then Regenerate mini-app (AC-55e, AC-55f)", () => {
  assert.equal(miniappAction({ miniapp_html: null }), "Show as mini-app");
  assert.equal(miniappAction({ miniapp_html: "" }), "Regenerate mini-app");
  assert.equal(miniappAction({ miniapp_html: "<p>x</p>" }), "Regenerate mini-app");
});
