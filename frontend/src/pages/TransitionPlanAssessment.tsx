import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, GroundedBadge, YesNoBadge } from "../components/ConfidenceBadge";
import { ReviewControls } from "../components/ReviewControls";
import { CitationList } from "../components/CitationList";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { IndicatorAssessment, IndicatorCategory, ReviewDecision, TransitionPlanAssessmentRecord, TransitionPlanIndicatorDef } from "../types";

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

const CATEGORY_LABELS: Record<IndicatorCategory, string> = {
  target: "Target",
  governance: "Governance",
  strategy: "Strategy",
  tracking: "Tracking",
};

function IndicatorDetail({
  indicator,
  runId,
  reviewer,
  reviewDecisions,
  onReviewed,
  onOpenSource,
}: {
  indicator: IndicatorAssessment;
  runId: string;
  reviewer: string;
  reviewDecisions: Record<string, ReviewDecision>;
  onReviewed: () => void;
  onOpenSource: (s: ActiveSource) => void;
}) {
  const itemKey = `${indicator.identifier}`;
  return (
    <div className="field-detail">
      <p>{indicator.answer}</p>
      <CitationList citations={indicator.citations} onOpenSource={onOpenSource} />
      <ReviewControls
        runId={runId}
        itemKey={itemKey}
        current={reviewDecisions[itemKey]}
        reviewer={reviewer}
        onDone={onReviewed}
        submitFn={api.submitTransitionPlanReview}
        historyFn={api.getTransitionPlanReviewHistory}
      />
    </div>
  );
}

function IndicatorTable({
  record,
  runId,
  reviewer,
  reviewDecisions,
  onReviewed,
  onOpenSource,
}: {
  record: TransitionPlanAssessmentRecord;
  runId: string;
  reviewer: string;
  reviewDecisions: Record<string, ReviewDecision>;
  onReviewed: () => void;
  onOpenSource: (s: ActiveSource) => void;
}) {
  const [expandedIndicator, setExpandedIndicator] = useState<string | null>(null);
  const categories: IndicatorCategory[] = ["target", "governance", "strategy", "tracking"];

  return (
    <>
      <div className="run-progress-stats">
        {record.by_category.map((c) => (
          <span key={c.category}>
            {CATEGORY_LABELS[c.category]}: {c.disclosed_count}/{c.total_count}
          </span>
        ))}
      </div>
      {categories.map((cat) => {
        const rows = record.indicators.filter((i) => i.category === cat);
        if (rows.length === 0) return null;
        return (
          <div key={cat}>
            <h4>{CATEGORY_LABELS[cat]}</h4>
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Question</th>
                  <th>Walk/Talk</th>
                  <th>Verdict</th>
                  <th>Grounded</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((ind) => (
                  <Fragment key={ind.identifier}>
                    <tr
                      className="clickable-row"
                      onClick={() => setExpandedIndicator(expandedIndicator === ind.identifier ? null : ind.identifier)}
                    >
                      <td>{ind.number}</td>
                      <td>{ind.question}</td>
                      <td>{ind.walk_or_talk}</td>
                      <td><YesNoBadge verdict={ind.verdict} /></td>
                      <td><GroundedBadge grounded={ind.grounded} /></td>
                      <td>{ind.needs_review ? "⚑" : ""}</td>
                    </tr>
                    {expandedIndicator === ind.identifier && (
                      <tr>
                        <td colSpan={6} className="detail-cell">
                          <IndicatorDetail
                            indicator={ind}
                            runId={runId}
                            reviewer={reviewer}
                            reviewDecisions={reviewDecisions}
                            onReviewed={onReviewed}
                            onOpenSource={onOpenSource}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}

export function TransitionPlanAssessment({ pendingUniverse }: Props = {}) {
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<TransitionPlanAssessmentRecord[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [reviewer, setReviewer] = useState("");
  const [indicators, setIndicators] = useState<TransitionPlanIndicatorDef[]>([]);
  const [showMethodology, setShowMethodology] = useState(false);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  useEffect(() => {
    api.getTransitionPlanIndicators().then(setIndicators).catch(() => {});
  }, []);

  async function startRun() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startTransitionPlanRun({ universe_path: universePath });
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
    const res = await api.getTransitionPlanResults(runId);
    setResults(res.results);
    const decisionsRes = (await api.getTransitionPlanReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
    setReviewDecisions(decisionsRes.decisions);
  }

  return (
    <div className="page">
      <h2>Transition Plan Assessment</h2>
      <p className="help-text">
        Assesses each company's climate transition disclosures against the 64 indicators from Colesanti Senni,
        Schimanski, Bingler, Ni &amp; Leippold (2024), <em>"Using AI to assess corporate climate transition
        disclosures"</em> (Environmental Research Communications). Each indicator gets a grounded RAG verdict --
        disclosed (YES), not disclosed (NO), or not applicable (NA) -- with a critical, greenwashing-aware
        explanation and citations independently verified against the source document (never LLM-self-reported).
        Indicators are classified as "talk" (future targets / general management approach) or "walk" (concrete,
        already-verifiable activity), mirroring the paper's headline finding that companies over-disclose talk and
        under-disclose walk.
      </p>
      <button className="link-button" onClick={() => setShowMethodology((s) => !s)}>
        {showMethodology ? "Hide" : "Show"} the 64 indicators
      </button>
      {showMethodology && (
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Category</th>
              <th>Walk/Talk</th>
              <th>Question</th>
            </tr>
          </thead>
          <tbody>
            {indicators.map((i) => (
              <tr key={i.identifier}>
                <td>{i.number}</td>
                <td>{CATEGORY_LABELS[i.category]}</td>
                <td>{i.walk_or_talk}</td>
                <td>{i.question}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="card">
        <h3>1. Choose the company universe</h3>
        {pendingUniverse && universePath === pendingUniverse.path && (
          <p className="status-text">
            Using {pendingUniverse.count} companies sent from another screen. Upload a different universe below to
            replace it.
          </p>
        )}
        <UniversePicker
          onResolved={(path, count) => {
            setUniversePath(path);
            setCompanyCount(count);
          }}
        />
        <button onClick={startRun} disabled={busy || !universePath}>
          Assess transition plans across {companyCount || "..."} companies
        </button>
      </section>

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>2. Run progress</h3>
          <RunProgress runId={runId} runType="transition_plan" />
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
                      <th>Disclosed</th>
                      <th>Walk</th>
                      <th>Talk</th>
                      <th>Confidence</th>
                      <th>Needs review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r) => (
                      <Fragment key={r.company_id}>
                        <tr className="clickable-row" onClick={() => setExpanded(expanded === r.company_id ? null : r.company_id)}>
                          <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                          <td>{r.disclosed_count}/64</td>
                          <td>{r.walk_disclosed_count}/{r.walk_total_count}</td>
                          <td>{r.talk_disclosed_count}/{r.talk_total_count}</td>
                          <td><ConfidenceBadge value={r.overall_confidence} /></td>
                          <td>{r.needs_review ? "⚑" : ""}</td>
                        </tr>
                        {expanded === r.company_id && (
                          <tr>
                            <td colSpan={6} className="detail-cell">
                              {(r.company_sector || r.company_location) && (
                                <p className="muted">
                                  {r.company_sector && `Sector: ${r.company_sector}`}
                                  {r.company_sector && r.company_location && " · "}
                                  {r.company_location && `Headquarters: ${r.company_location}`}
                                </p>
                              )}
                              <IndicatorTable
                                record={r}
                                runId={runId}
                                reviewer={reviewer}
                                reviewDecisions={reviewDecisions}
                                onReviewed={refreshResults}
                                onOpenSource={setActiveSource}
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
