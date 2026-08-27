import { Fragment, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, GroundedBadge } from "../components/ConfidenceBadge";
import { ReviewControls } from "../components/ReviewControls";
import { CitationList } from "../components/CitationList";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { BusinessSegment, CompanyFinancialsRecord, ReviewDecision, SpendSummary } from "../types";

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

function fmtAmount(value?: number | null): string {
  return value == null ? "—" : value.toLocaleString();
}

function SegmentDetail({ segment, onOpenSource }: { segment: BusinessSegment; onOpenSource: (s: ActiveSource) => void }) {
  return (
    <div className="field-detail">
      <strong>{segment.name}</strong> <GroundedBadge grounded={segment.grounded} /> <ConfidenceBadge value={segment.confidence} />
      {segment.description && <p>{segment.description}</p>}
      <CitationList citations={segment.description_citations} onOpenSource={onOpenSource} />
      <table className="data-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
            <th>Grounded</th>
          </tr>
        </thead>
        <tbody>
          {(["revenue", "income", "assets"] as const).map((metric) => (
            <tr key={metric}>
              <td style={{ textTransform: "capitalize" }}>{metric}</td>
              <td>
                {fmtAmount(segment[metric].value)}
                {segment[metric].raw_value_text && <span className="muted"> ({segment[metric].raw_value_text})</span>}
              </td>
              <td><GroundedBadge grounded={segment[metric].grounded} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {(["revenue", "income", "assets"] as const).map((metric) =>
        segment[metric].citations.length > 0 ? (
          <div key={metric}>
            <span className="muted" style={{ textTransform: "capitalize" }}>{metric} citations:</span>
            <CitationList citations={segment[metric].citations} onOpenSource={onOpenSource} />
          </div>
        ) : null
      )}
      {segment.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

function SpendDetail({ label, spend, onOpenSource }: { label: string; spend: SpendSummary; onOpenSource: (s: ActiveSource) => void }) {
  return (
    <div className="field-detail">
      <strong>{label} total:</strong> {fmtAmount(spend.total.value)}
      {spend.total.raw_value_text && <span className="muted"> ({spend.total.raw_value_text})</span>}{" "}
      <GroundedBadge grounded={spend.grounded} /> <ConfidenceBadge value={spend.confidence} />
      <CitationList citations={spend.total.citations} onOpenSource={onOpenSource} />
      {spend.description && (
        <>
          <p>{spend.description}</p>
          <CitationList citations={spend.description_citations} onOpenSource={onOpenSource} />
        </>
      )}
      {spend.categories.length > 0 && (
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
              {spend.categories.map((c, ci) => (
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
      {spend.verifier_notes && <p className="muted">{spend.verifier_notes}</p>}
      {spend.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

export function CompanyFinancials({ pendingUniverse }: Props = {}) {
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<CompanyFinancialsRecord[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [reviewer, setReviewer] = useState("");
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  async function startRun() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startFinancialsRun({ universe_path: universePath });
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
    const res = (await api.getFinancialsResults(runId)) as { results: CompanyFinancialsRecord[] };
    setResults(res.results);
    const decisionsRes = (await api.getFinancialsReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
    setReviewDecisions(decisionsRes.decisions);
  }

  return (
    <div className="page">
      <h2>Company Financials</h2>
      <p className="help-text">
        Extract a company's disclosed business segments (name, description, revenue, operating income, assets),
        total CapEx, and total R&amp;D -- each with a grounded description and any disclosed category breakdown --
        in a single combined pass per company. These are almost always wanted together, so this fetches each
        company's documents once and makes one extractor + one independent verifier call instead of three separate
        pipelines, with the same programmatic grounding check on every citation.
      </p>

      <section className="card">
        <h3>1. Choose the company universe</h3>
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
          Extract financials across {companyCount || "..."} companies
        </button>
      </section>

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>2. Run progress</h3>
          <RunProgress runId={runId} runType="financials" />
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
            <div className="split-review">
              <div className="split-review-main">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Segments</th>
                      <th>CapEx</th>
                      <th>R&amp;D</th>
                      <th>Confidence</th>
                      <th>Needs review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r) => (
                      <Fragment key={r.company_id}>
                        <tr className="clickable-row" onClick={() => setExpanded(expanded === r.company_id ? null : r.company_id)}>
                          <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                          <td>{r.segments.length === 0 ? "none found" : `${r.segments.length} segment(s)`}</td>
                          <td>{fmtAmount(r.capex.total.value)} {r.currency ?? ""}</td>
                          <td>{fmtAmount(r.rnd.total.value)} {r.currency ?? ""}</td>
                          <td><ConfidenceBadge value={r.overall_confidence} /></td>
                          <td>{r.needs_review ? "⚑" : ""}</td>
                        </tr>
                        {expanded === r.company_id && (
                          <tr>
                            <td colSpan={6} className="detail-cell">
                              <h4>Business Segments</h4>
                              {r.segments.length === 0 && <p className="muted">No segment reporting evidence found.</p>}
                              {r.segments.map((s, si) => (
                                <SegmentDetail key={si} segment={s} onOpenSource={setActiveSource} />
                              ))}
                              {r.segments_verifier_notes && <p className="muted">{r.segments_verifier_notes}</p>}

                              <h4>CapEx</h4>
                              <SpendDetail label="CapEx" spend={r.capex} onOpenSource={setActiveSource} />

                              <h4>R&amp;D</h4>
                              <SpendDetail label="R&D" spend={r.rnd} onOpenSource={setActiveSource} />

                              <ReviewControls
                                runId={runId}
                                itemKey={r.company_id}
                                current={reviewDecisions[r.company_id]}
                                reviewer={reviewer}
                                onDone={refreshResults}
                                submitFn={api.submitFinancialsReview}
                                historyFn={api.getFinancialsReviewHistory}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}
