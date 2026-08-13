import { Fragment, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, GroundedBadge } from "../components/ConfidenceBadge";
import { ReviewControls } from "../components/ReviewControls";
import type { Citation, ReviewDecision, SpendExtractionRecord, SpendTopic } from "../types";

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

const TOPICS: { id: SpendTopic; label: string; help: string }[] = [
  {
    id: "capex",
    label: "CapEx",
    help: "Total capital expenditure for the most recent fiscal year, what it's funding, and any disclosed category breakdown (maintenance vs. growth, capitalized software, green capex, etc.).",
  },
  {
    id: "rnd",
    label: "R&D",
    help: "Total R&D expense for the most recent fiscal year, what it's funding, and any disclosed program/focus-area breakdown.",
  },
];

function fmtAmount(value?: number | null): string {
  return value == null ? "—" : value.toLocaleString();
}

function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <ul>
      {citations.map((c, ci) => (
        <li key={ci}>
          [{c.doc_type}] "{c.quote}"
          {c.grounded && c.company_id && c.source_filename && (
            <>
              {" "}
              <a
                href={`${api.documentRawUrl(c.company_id, c.doc_type, c.source_filename)}${c.page ? `#page=${c.page}` : ""}`}
                target="_blank"
                rel="noreferrer"
              >
                view source{c.page ? ` (p. ${c.page})` : c.sheet ? ` (${c.sheet})` : ""}
              </a>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

function SpendDetail({ record }: { record: SpendExtractionRecord }) {
  return (
    <div className="field-detail">
      <strong>Total:</strong> {fmtAmount(record.total.value)}
      {record.total.raw_value_text && <span className="muted"> ({record.total.raw_value_text})</span>}{" "}
      <GroundedBadge grounded={record.total.grounded} /> <ConfidenceBadge value={record.confidence} />
      {record.currency && record.fiscal_period && (
        <span className="muted"> · {record.currency} · {record.fiscal_period}</span>
      )}
      <CitationList citations={record.total.citations} />
      {record.description && (
        <>
          <p>{record.description}</p>
          <CitationList citations={record.description_citations} />
        </>
      )}
      {record.categories.length > 0 && (
        <>
          <p className="muted">Category breakdown:</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Grounded</th>
              </tr>
            </thead>
            <tbody>
              {record.categories.map((c, ci) => (
                <tr key={ci}>
                  <td>{c.name}</td>
                  <td>{c.description ?? "—"}</td>
                  <td>{fmtAmount(c.amount.value)}</td>
                  <td><GroundedBadge grounded={c.grounded} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {record.verifier_notes && <p className="muted">{record.verifier_notes}</p>}
      {record.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

export function SpendExtraction({ pendingUniverse }: Props = {}) {
  const [topic, setTopic] = useState<SpendTopic>("capex");
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<SpendExtractionRecord[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [reviewer, setReviewer] = useState("");

  const activeTopic = TOPICS.find((t) => t.id === topic)!;

  async function startRun() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startSpendRun(topic, { universe_path: universePath });
      setRunId(res.run_id);
      setResults([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getSpendResults(runId)) as { results: SpendExtractionRecord[] };
    setResults(res.results);
    const decisionsRes = (await api.getSpendReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
    setReviewDecisions(decisionsRes.decisions);
  }

  return (
    <div className="page">
      <h2>CapEx / R&amp;D Extraction</h2>
      <p className="help-text">
        Extract total capital expenditure or R&amp;D spend, a plain-language description of what it's funding, and
        any disclosed category breakdown -- from annual reports, sustainability reports, investor decks, and
        earnings call transcripts -- with the same independent-verifier and grounding-check precision controls as
        the other extraction pipelines.
      </p>

      <section className="card">
        <h3>1. Choose topic and company universe</h3>
        <div className="sub-nav">
          {TOPICS.map((t) => (
            <button
              key={t.id}
              className={t.id === topic ? "nav-tab active" : "nav-tab"}
              onClick={() => {
                setTopic(t.id);
                setRunId(null);
                setResults([]);
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <p className="help-text">{activeTopic.help}</p>
        {pendingUniverse && universePath === pendingUniverse.path && (
          <p className="status-text">
            Using {pendingUniverse.count} companies sent from a Thematic Universe screen. Upload a different
            universe below to replace it.
          </p>
        )}
        <UniversePicker
          onResolved={(path, count) => {
            setUniversePath(path);
            setCompanyCount(count);
          }}
        />
        <button onClick={startRun} disabled={busy || !universePath}>
          Extract {activeTopic.label} across {companyCount || "..."} companies
        </button>
      </section>

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>2. Run progress</h3>
          <RunProgress runId={runId} runType="spend" />
          <div className="toolbar">
            <button onClick={refreshResults}>Refresh results</button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
            <label className="field-label" style={{ marginLeft: "auto" }}>
              Reviewing as
            </label>
            <input placeholder="your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} style={{ maxWidth: 160 }} />
          </div>
          {results.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Total</th>
                  <th>Confidence</th>
                  <th>Needs review</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <Fragment key={r.company_id}>
                    <tr className="clickable-row" onClick={() => setExpanded(expanded === r.company_id ? null : r.company_id)}>
                      <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                      <td>{fmtAmount(r.total.value)} {r.currency ?? ""}</td>
                      <td><ConfidenceBadge value={r.confidence} /></td>
                      <td>{r.needs_review ? "⚑" : ""}</td>
                    </tr>
                    {expanded === r.company_id && (
                      <tr>
                        <td colSpan={4} className="detail-cell">
                          <SpendDetail record={r} />
                          <ReviewControls
                            runId={runId}
                            itemKey={r.company_id}
                            current={reviewDecisions[r.company_id]}
                            reviewer={reviewer}
                            onDone={refreshResults}
                            submitFn={api.submitSpendReview}
                            historyFn={api.getSpendReviewHistory}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
