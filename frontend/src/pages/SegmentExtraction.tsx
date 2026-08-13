import { Fragment, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, GroundedBadge } from "../components/ConfidenceBadge";
import { ReviewControls } from "../components/ReviewControls";
import type { BusinessSegment, Citation, ReviewDecision, SegmentExtractionRecord } from "../types";

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

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

function SegmentDetail({ segment }: { segment: BusinessSegment }) {
  return (
    <div className="field-detail">
      <strong>{segment.name}</strong> <GroundedBadge grounded={segment.grounded} /> <ConfidenceBadge value={segment.confidence} />
      {segment.currency && segment.fiscal_period && (
        <span className="muted"> · {segment.currency} · {segment.fiscal_period}</span>
      )}
      {segment.description && <p>{segment.description}</p>}
      <CitationList citations={segment.description_citations} />
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
            <CitationList citations={segment[metric].citations} />
          </div>
        ) : null
      )}
      {segment.verifier_notes && <p className="muted">{segment.verifier_notes}</p>}
      {segment.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

export function SegmentExtraction({ pendingUniverse }: Props = {}) {
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<SegmentExtractionRecord[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [reviewer, setReviewer] = useState("");

  async function startRun() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startSegmentRun({ universe_path: universePath });
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
    const res = (await api.getSegmentResults(runId)) as { results: SegmentExtractionRecord[] };
    setResults(res.results);
    const decisionsRes = (await api.getSegmentReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
    setReviewDecisions(decisionsRes.decisions);
  }

  return (
    <div className="page">
      <h2>Business Segment Extraction</h2>
      <p className="help-text">
        Extract each company's disclosed reportable/operating segments -- name, description, revenue, operating
        income, and assets -- from the annual report's "Segment Reporting" note, with an independent verifier pass
        and a hard programmatic grounding check on every citation. A segment/figure not explicitly disclosed is
        left blank rather than estimated.
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
          Extract segments across {companyCount || "..."} companies
        </button>
      </section>

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>2. Run progress</h3>
          <RunProgress runId={runId} runType="segments" />
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
                  <th>Segments</th>
                  <th>Overall confidence</th>
                  <th>Needs review</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <Fragment key={r.company_id}>
                    <tr className="clickable-row" onClick={() => setExpanded(expanded === r.company_id ? null : r.company_id)}>
                      <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                      <td>{r.segments.length === 0 ? "none found" : r.segments.map((s) => s.name).join(", ")}</td>
                      <td><ConfidenceBadge value={r.overall_confidence} /></td>
                      <td>{r.needs_review ? "⚑" : ""}</td>
                    </tr>
                    {expanded === r.company_id && (
                      <tr>
                        <td colSpan={4} className="detail-cell">
                          {r.segments.length === 0 && <p className="muted">No segment reporting evidence found.</p>}
                          {r.segments.map((s, si) => (
                            <SegmentDetail key={si} segment={s} />
                          ))}
                          <ReviewControls
                            runId={runId}
                            itemKey={r.company_id}
                            current={reviewDecisions[r.company_id]}
                            reviewer={reviewer}
                            onDone={refreshResults}
                            submitFn={api.submitSegmentReview}
                            historyFn={api.getSegmentReviewHistory}
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
