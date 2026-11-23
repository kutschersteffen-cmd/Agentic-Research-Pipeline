import { useEffect, useRef } from "react";
import { bridgeAsk, MINIAPP_SANDBOX, miniappDocument, type Theme } from "../lib/miniapp";

/** A mini-app on the stage (spec agent-panel-code-mode, Phase 5): its HTML in a frame that may run scripts and reach
 * nothing, with the exploration's result as `window.ARP_DATA`. Of its messages, only `{action: "ask", text}` counts:
 * `onAsk` gets the text, which goes in the composer unsent. */
export function MiniAppFrame({ title, html, data, theme, onAsk }: { title: string; html: string; data: unknown; theme: Theme; onAsk: (text: string) => void }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const ask = useRef(onAsk);
  ask.current = onAsk;
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (!frame.current || e.source !== frame.current.contentWindow) return;
      const text = bridgeAsk(e.data);
      if (text !== null) ask.current(text);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);
  return <iframe ref={frame} className="agent-miniapp" title={title} sandbox={MINIAPP_SANDBOX} srcDoc={miniappDocument(html, data, theme)} />;
}
