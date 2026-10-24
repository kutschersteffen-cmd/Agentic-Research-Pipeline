import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { historyFor, type AskTurn } from "../lib/askHistory";
import { AskCard } from "./AskCards";

const ERROR_TEXT = "Ask could not answer this question. Try again.";

/** Ask ARP: a side panel where a plain-language question goes to one read-only tool and comes back as a sourced card.
 * The conversation (`turns`) belongs to the app shell, so it survives moving between pages. */
export function AskPanel({ turns, setTurns, onClose, onClear }: {
  turns: AskTurn[];
  setTurns: (update: (turns: AskTurn[]) => AskTurn[]) => void;
  onClose: () => void;
  onClear: () => void;
}) {
  const [q, setQ] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const working = turns.some((t) => t.status === "working");

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Braces: newer browsers return a Promise from scrollIntoView, which React would call as the cleanup.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const question = q.trim();
    if (!question || working) return;
    const id = `${Date.now()}`;
    const history = historyFor(turns);
    setTurns((ts) => [...ts, { id, question, status: "working" }]);
    setQ("");
    try {
      const response = await api.ask(question, history);
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: "answered", response } : t)));
    } catch (err) {
      const error = err instanceof Error && err.message ? err.message : ERROR_TEXT;
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: "error", error } : t)));
    }
    input.current?.focus();
  }

  return (
    <aside className="ask-panel" role="dialog" aria-label="Ask ARP">
      <header className="ask-head">
        <h2>Ask ARP</h2>
        <div className="ask-head-actions">
          {turns.length > 0 && <button type="button" className="link-button" onClick={onClear}>Clear</button>}
          <button type="button" className="ask-close" aria-label="Close Ask ARP" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </header>
      <div className="ask-thread" aria-live="polite">
        {turns.length === 0 && (
          <p className="help-text">
            Ask about portfolio exposure, data issues and feeds, a company's newest transition plan assessment, or a
            benchmark's sector weights. Every figure is computed by code and shows its source.
          </p>
        )}
        {turns.map((t) => (
          <section key={t.id} className="ask-turn">
            <p className="ask-question">{t.question}</p>
            {t.status === "working" && <p className="ask-card muted">Working…</p>}
            {t.status === "error" && <p className="ask-card error-text" role="alert">{t.error || ERROR_TEXT}</p>}
            {t.status === "answered" && t.response && <AskCard response={t.response} />}
          </section>
        ))}
        <div ref={end} />
      </div>
      <form className="ask-form" onSubmit={send}>
        <label htmlFor="ask-input" className="visually-hidden">Your question</label>
        <input id="ask-input" ref={input} value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000} disabled={working}
          placeholder="What is our exposure to BMW?" autoComplete="off" />
        <button type="submit" disabled={working || !q.trim()}>Send</button>
      </form>
    </aside>
  );
}
