import { useRef } from "react";
import { MINIAPP_SANDBOX, miniappDocument } from "../lib/miniapp";

/** A mini-app on the stage (spec agent-panel-code-mode, Phase 5, D14): its script-free HTML in a frame where nothing
 * runs, and below it, outside the frame, one `Ask` chip per follow-up question. A chip puts its question in the
 * composer in `Ask` mode, unsent.
 *
 * With nothing focusable inside, Chromium leaves the frame out of the tab order, so a page taller than the frame could
 * not be scrolled from the keyboard. The button before it (shown when focused) moves focus into the frame, where the
 * arrow and Page keys scroll it and Tab leaves it. */
export function MiniAppFrame({ title, html, asks, onAsk }: { title: string; html: string; asks: string[]; onAsk: (text: string) => void }) {
  const frame = useRef<HTMLIFrameElement>(null);
  return (
    <>
      <button type="button" className="secondary agent-miniapp-enter" onClick={() => frame.current?.focus()}>Scroll the mini-app</button>
      <iframe ref={frame} className="agent-miniapp" title={title} sandbox={MINIAPP_SANDBOX} srcDoc={miniappDocument(html)} />
      {asks.length > 0 && (
        <div className="agent-miniapp-asks" role="group" aria-label="Ask a follow-up">
          {asks.map((q, i) => <button key={i} type="button" className="secondary" onClick={() => onAsk(q)}>{q}</button>)}
        </div>
      )}
    </>
  );
}
