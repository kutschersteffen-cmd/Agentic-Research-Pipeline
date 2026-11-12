import { useState } from "react";
import { api } from "../../api/client";
import { usePortfolioPane } from "../../context/usePortfolioPane";
import { AggregationView } from "../../components/ResultView";
import { askBody, snapshotLine, trendTable } from "../../lib/askPortfolio";
import type { QAAnswer } from "../../types";

const EXAMPLE_QUESTIONS = [
  "How many EUR million is our exposure to BMW?",
  "What's our total equity exposure by sector?",
  "How much do we hold in TotalEnergies across all portfolios?",
];

/** The AI Q&A interface (spec §8 / §9 sub-tab 6), pre-scoped to the pane's
 * current selection so "what's our WACI" doesn't require naming the
 * portfolio in the question: the selected portfolios and dates travel as
 * request fields next to the typed question, and are shown back to the
 * user. The LLM still only drafts the query; the deterministic engine
 * computes the number (see portfolio/qa_agent.py). */
export function AskThePortfolio() {
  const { selectionLabel, selectedPortfolioIds, effectiveAsOf, effectiveDateRange } = usePortfolioPane();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QAAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  async function ask(q: string) {
    setAsking(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await api.askPortfolio(askBody(q, selectedPortfolioIds, effectiveAsOf, effectiveDateRange)));
    } catch (e) {
      setError(String(e));
    } finally {
      setAsking(false);
    }
  }

  const trend = answer?.resolvable && answer.trend && answer.spec ? trendTable(answer.trend, answer.spec.metric, answer.scale) : null;
  const snapshots = answer?.result ? snapshotLine(answer.snapshot_dates ?? []) : null;

  return (
    <section className="card">
      <h2>Ask the Portfolio</h2>
      <p className="help-text">
        The LLM only drafts the underlying query (portfolios, filters, grouping, metric) — the deterministic
        aggregation engine computes the real number. Requires <code>ARP_ANTHROPIC_API_KEY</code> to be configured on
        the server.
      </p>
      <p className="selection-summary">Scoped to: {selectionLabel}</p>
      <textarea aria-label="Question" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about portfolio exposure..." />
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
      {error && <p className="error-text" role="alert">{error}</p>}
      {answer && !answer.resolvable && <p className="help-text">Could not resolve the question: {answer.clarification_needed}</p>}
      {answer && answer.resolvable && (
        <>
          <p className="answer-text">{answer.answer_text}</p>
          {answer.result && <AggregationView result={answer.result} scale={answer.scale} unit={answer.unit} />}
          {snapshots && <p className="muted">{snapshots}</p>}
          {trend && (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>{trend.headers.map((h) => <th key={h}>{h}</th>)}</tr>
                </thead>
                <tbody>
                  {trend.rows.map((row) => (
                    <tr key={row[0]}>{row.map((cell, i) => <td key={trend.headers[i]}>{cell}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
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
