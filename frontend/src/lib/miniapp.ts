// Mini-apps (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, Phase 5): the page the stage puts in
// `<iframe sandbox="allow-scripts" srcdoc=...>`, and the one message the screen accepts from it.

export const MINIAPP_SANDBOX = "allow-scripts";
export const MINIAPP_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:";

/** JSON that cannot close the <script> it sits in, nor break a line in it. */
const scriptJson = (v: unknown) =>
  JSON.stringify(v ?? null).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");

/** The mini-app's HTML wrapped in a page whose CSP comes first, with `window.ARP_DATA` set before its scripts run. */
export const miniappDocument = (html: string, data: unknown): string =>
  `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${MINIAPP_CSP}">` +
  `<script>window.ARP_DATA = ${scriptJson(data)};</script></head><body>${html}</body></html>`;

/** The text of a `{"action": "ask", "text": str}` message; null for every other message. */
export function bridgeAsk(data: unknown): string | null {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const m = data as Record<string, unknown>;
  return m.action === "ask" && typeof m.text === "string" ? m.text : null;
}
