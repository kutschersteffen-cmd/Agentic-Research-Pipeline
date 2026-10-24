import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { SmartSearchAnswer } from "../types";
import { SmartSearchRows } from "../components/SmartSearchRows";

const EXAMPLES = ["unmatched holdings in PF-1", "outputs nobody uses", "which feeds are behind?", "blocking data checks for Acme"];

/** Data Hub · Smart Search: a plain-language question becomes a filter over issues, outputs or feeds. The model only
 * picks the filter (shown under the answer); the rows and the count come from code. */
export function SmartSearch() {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<SmartSearchAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(e?: FormEvent, question = q) {
    e?.preventDefault();
    if (!question.trim()) return;
    setQ(question);
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.smartSearch(question));
    } catch (err) {
      setAnswer(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const a = answer;
  return (
    <div className="page">
      <h1>Smart Search</h1>
      <p className="help-text">
        Ask about open data issues, stored outputs or input feeds. The question is turned into a filter, shown with the
        answer; the rows and the count are computed, never written by the model.
      </p>
      <form className="inline-fields" onSubmit={(e) => void ask(e)}>
        <input type="text" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" placeholder="e.g. unmatched holdings in PF-1" />
        <button type="submit" disabled={busy || !q.trim()}>{busy ? "Searching…" : "Search"}</button>
      </form>
      <p className="muted">
        Try:{" "}
        {EXAMPLES.map((x, i) => (
          <span key={x}>
            {i > 0 && " · "}
            <button className="link-button" onClick={() => void ask(undefined, x)} disabled={busy}>
              {x}
            </button>
          </span>
        ))}
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {a && !a.resolvable && <p role="status">Smart Search can't answer that. {a.clarification_needed}</p>}
      {a?.resolvable && a.filter && (
        <>
          <p role="status"><strong>{a.answer_text}</strong></p>
          <SmartSearchRows answer={a} />
        </>
      )}
    </div>
  );
}
