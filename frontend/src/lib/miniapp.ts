// Mini-apps (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, Phase 5, D14): script-free HTML, cleaned by
// the backend, in `<iframe sandbox="" srcdoc=...>`. Nothing in the frame runs, so it has no fetch, WebRTC or messages.

export const MINIAPP_SANDBOX = "";
export const MINIAPP_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:";

/** The frame's `srcdoc`, exactly as the spec writes it. */
export const miniappDocument = (html: string): string =>
  `<!doctype html><meta http-equiv="Content-Security-Policy" content="${MINIAPP_CSP}"><body>${html}</body>`;

/** The exploration's action: it reads `Regenerate mini-app` once one is stored. */
export const miniappAction = (e: { miniapp_html: string | null }): string =>
  e.miniapp_html == null ? "Show as mini-app" : "Regenerate mini-app";
