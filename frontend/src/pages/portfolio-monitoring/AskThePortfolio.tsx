import { useState } from "react";
import { api } from "../../api/client";
import { usePortfolioPane } from "../../context/usePortfolioPane";
import { AggregationView } from "../../components/ResultView";
import type { QAAnswer } from "../../types";

const EXAMPLE_QUESTIONS = [
  "How many EUR million is our exposure to BMW?",
  "What's our total equity exposure by sector?",
  "How much do we hold in TotalEnergies across all portfolios?",
];

/** The AI Q&A interface (spec §8 / §9 sub-tab 6), pre-scoped to the pane's
 * current selection so "what's our WACI" doesn't require naming the
 * portfolio in the question -- done without any backend change by
 * prepending the pane's selection as plain-language context onto the
 * question text, and always shown back to the user so it's never a silent
 * rewrite. The LLM still only drafts the query; the deterministic engine
 * computes the number (see portfolio/qa_agent.py). */
export function AskThePortfolio() {
  const { selectionLabel } = usePortfolioPane();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QAAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  async function ask(q: string) {
    setAsking(true);
    setError(null);
    setAnswer(null);
    try {
      const scoped = `Regarding ${selectionLabel} (override this scope if the question below says otherwise): ${q}`;
      setAnswer(await api.askPortfolio(scoped));
    } catch (e) {
      setError(String(e));
    } finally {
      setAsking(false);
    }
  }

  return (
    <section className="card">
      <h3>Ask the Portfolio</h3>
      <p className="help-text">
        The LLM only drafts the underlying query (portfolios, filters, grouping, metric) -- the deterministic
        aggregation engine computes the real number. Requires <code>ARP_ANTHROPIC_API_KEY</code> to be configured on
        the server.
      </p>
      <p className="selection-summary">Scoped to: {selectionLabel}</p>
      <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about portfolio exposure..." />
      <div className="toolbar">
        <button onClick={() => ask(question)} disabled={asking || !question.trim()}>
          {asking ? "Asking..." : "Ask"}
        </button>
        {EXAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            className="link-button"
            onClick={() => {
              setQuestion(q);
              ask(q);
            }}
            disabled={asking}
          >
            {q}
          </button>
        ))}
      </div>
      {error && <p className="error-text">{error}</p>}
      {answer && !answer.resolvable && <p className="help-text">Could not resolve the question: {answer.clarification_needed}</p>}
      {answer && answer.resolvable && (
        <>
          <p className="answer-text">{answer.answer_text}</p>
          {answer.result && <AggregationView result={answer.result} />}
          {answer.spec && (
            <p className="muted">
              Query: group_by={answer.spec.group_by}, metric={answer.spec.metric}, filter=
              {JSON.stringify(answer.spec.security_filter)}, portfolios={answer.spec.portfolio_filter?.join(", ") || "all"}
            </p>
          )}
        </>
      )}
    </section>
  );
}
