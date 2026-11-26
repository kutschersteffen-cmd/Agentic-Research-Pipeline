import { useState, type ReactNode } from "react";
import { Orb } from "../Orb";

interface Props {
  /** What the chat is about, shown over the Orb ("Research Desk"; an Argus step later). */
  context: string;
  /** The phase label beside the Orb: READY, WORKING or DONE. */
  phase: string;
  placeholder: string;
  /** False keeps the ask button off whatever is typed (e.g. nothing picked yet). */
  ready: boolean;
  /** Called with the trimmed question; the box empties when it resolves true. */
  onAction: (question: string) => Promise<boolean>;
  /** Shown between the Orb and the ask box (the question, a say line). */
  say?: ReactNode;
  /** Shown under the ask box (scope chips, mode toggle). */
  children?: ReactNode;
}

/** The Orb, a phase label and an ask box, shared by Research Desk and (later) the Argus steps. */
export function OrbChat({ context, phase, placeholder, ready, onAction, say, children }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const q = text.trim();
  return (
    <section className="orb-chat" aria-label="Ask ARP">
      <div className="hub-ask-stage orb-chat-stage">
        <span className="hub-ask-cap" aria-hidden="true">Ask ARP · {context}</span>
        <Orb place="workspace" working={phase === "WORKING"} />
        <span className="orb-label orb-chat-phase"><i aria-hidden="true" />{phase}</span>
      </div>
      <div className="orb-chat-body">
        {say}
        <form
          className="orb-chat-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!q || !ready || busy) return;
            setBusy(true);
            if (await onAction(q)) setText("");
            setBusy(false);
          }}
        >
          <input type="text" aria-label={placeholder} placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" enterKeyHint="send" />
          <button type="submit" disabled={!q || !ready || busy}>Ask</button>
        </form>
        {children}
      </div>
    </section>
  );
}
