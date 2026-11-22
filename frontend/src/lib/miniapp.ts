// Mini-apps (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, Phase 5): the page the stage puts in
// `<iframe sandbox="allow-scripts" srcdoc=...>`, and the one message the screen accepts from it.

export const MINIAPP_SANDBOX = "allow-scripts";
export const MINIAPP_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:";
/** The shell page's CSP. A frame's own navigation is checked against its parent's `frame-src`, which no CSP inside
 * the mini-app can set, so the mini-app sits one frame down, under a parent that frames nothing. */
export const MINIAPP_SHELL_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'none'";
/** As long as an Ask question may be. */
const ASK_MAX = 1000;

/** JSON that cannot close the <script> it sits in, nor break a line in it. */
const scriptJson = (v: unknown) =>
  JSON.stringify(v ?? null).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
const attr = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");

/** The mini-app's HTML wrapped in a page whose CSP comes first, with `window.ARP_DATA` set before its scripts run. */
export const miniappPage = (html: string, data: unknown): string =>
  `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${MINIAPP_CSP}">` +
  `<script>window.ARP_DATA = ${scriptJson(data)};</script></head><body>${html}</body></html>`;

// Passes on the inner frame's messages, so a mini-app's `parent.postMessage` reaches the screen.
const RELAY = `var f=document.querySelector("iframe");addEventListener("message",function(e){if(e.source===f.contentWindow)parent.postMessage(e.data,"*")});`;

/** The frame's srcdoc: a shell that frames nothing, holding the mini-app page in its own `allow-scripts` frame. The
 * shell has no script but the relay, and a sandboxed frame cannot navigate its parent, so neither page can leave. */
export const miniappDocument = (html: string, data: unknown): string =>
  `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${MINIAPP_SHELL_CSP}">` +
  `<style>html,body{margin:0;height:100%}iframe{display:block;border:0;width:100%;height:100%}</style></head><body>` +
  `<iframe sandbox="${MINIAPP_SANDBOX}" title="Mini-app" srcdoc="${attr(miniappPage(html, data))}"></iframe>` +
  `<script>${RELAY}</script></body></html>`;

/** The text of a `{"action": "ask", "text": str}` message, cut to an Ask question's length; null for every other message. */
export function bridgeAsk(data: unknown): string | null {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const m = data as Record<string, unknown>;
  return m.action === "ask" && typeof m.text === "string" ? m.text.slice(0, ASK_MAX) : null;
}
