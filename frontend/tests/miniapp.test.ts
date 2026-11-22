import test from "node:test";
import assert from "node:assert/strict";
import { bridgeAsk, MINIAPP_CSP, MINIAPP_SANDBOX, miniappDocument } from "../src/lib/miniapp.ts";

// Mini-apps (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, slice 11).

test("the frame may run scripts and nothing else (AC-54c)", () => {
  assert.equal(MINIAPP_SANDBOX, "allow-scripts");
});

test("the page's CSP is the spec's, ahead of the data and the mini-app (AC-55)", () => {
  assert.equal(MINIAPP_CSP, "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:");
  const doc = miniappDocument("<p id=x>hi</p>", [{ a: 1 }]);
  const csp = doc.indexOf(`<meta http-equiv="Content-Security-Policy" content="${MINIAPP_CSP}">`);
  assert.ok(csp > 0);
  assert.ok(csp < doc.indexOf("window.ARP_DATA = [{\"a\":1}];"));
  assert.ok(doc.indexOf("window.ARP_DATA") < doc.indexOf("<p id=x>hi</p>"));
});

test("the data cannot close its script tag", () => {
  const doc = miniappDocument("", { s: "</script><script>alert(1)</script>\u2028" });
  assert.equal(doc.split("</script>").length, 2); // only the data script's own closing tag
  assert.ok(doc.includes('"\\u003c/script>\\u003cscript>alert(1)\\u003c/script>\\u2028"'));
  assert.ok(miniappDocument("", undefined).includes("window.ARP_DATA = null;"));
});

test("only {action: ask, text: string} is taken from the frame (AC-56, AC-57)", () => {
  assert.equal(bridgeAsk({ action: "ask", text: "why sector X?" }), "why sector X?");
  for (const m of [{ action: "run", plan_id: "p" }, { action: "ask" }, { action: "ask", text: 1 }, "ask", null, [], { text: "t" }]) {
    assert.equal(bridgeAsk(m), null);
  }
});
