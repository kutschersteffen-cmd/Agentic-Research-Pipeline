import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfidenceBadge, GroundedBadge, YesNoBadge } from "./ConfidenceBadge";
import { ReviewControls } from "./ReviewControls";
import { CitationList } from "./CitationList";
import type { ActiveSource } from "./SourcePanel";
import { BarChart } from "./BarChart";
import type { IndicatorAssessment, IndicatorCategory, ReviewDecision, TransitionPlanAssessmentRecord, TransitionPlanIndicatorDef } from "../types";
import { activatable } from "../lib/activatable";
import { ProposedTag } from "./ProposedTag";
import { OriginTag } from "./ReviewTiles";
import { editedText, matchesTile, type ReviewTileCounts } from "../lib/stagedFlow";

type TileFilter = keyof ReviewTileCounts | null;
// Items are indicators; flagged = needs_review.
const indicatorShown = (i: IndicatorAssessment, d: Record<string, ReviewDecision>, filter: TileFilter) =>
  matchesTile(filter, i.needs_review, d[i.identifier]);

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
      <p>{editedText(reviewDecisions[itemKey]) ?? indicator.answer}</p>
      <OriginTag decision={reviewDecisions[itemKey]} systemValue={indicator.answer} />
      {indicator.verifier_notes && <p className="muted">{indicator.verifier_notes}</p>}
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
  filter,
}: {
  filter: TileFilter;
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
        const rows = record.indicators.filter((i) => i.category === cat && indicatorShown(i, reviewDecisions, filter));
        if (rows.length === 0) return null;
        return (
          <div key={cat}>
            <h3>{CATEGORY_LABELS[cat]}</h3>
            <div className="table-wrap">
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
                        {...activatable(() => setExpandedIndicator(expandedIndicator === ind.identifier ? null : ind.identifier), expandedIndicator === ind.identifier)}
                      >
                        <td>{ind.number}</td>
                        <td>{ind.question}</td>
                        <td>{ind.walk_or_talk}</td>
                        <td><YesNoBadge verdict={ind.verdict} /></td>
                        <td><GroundedBadge grounded={ind.grounded} /></td>
                        <td>{ind.needs_review ? <ProposedTag /> : ""}</td>
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
          </div>
        );
      })}
    </>
  );
}

/** Batch-level view across every company in the run: the paper's own
 * headline finding is an aggregate walk-vs-talk disclosure gap, not a
 * single company's score, so that comparison is surfaced here rather than
 * making a reviewer add up 64-indicator rows per company by hand. The bar
 * chart ranks companies by overall disclosure completeness -- the same
 * BarChart used for magnitude comparisons elsewhere in the app. */
export function TransitionPlanBatchOverview({ results }: { results: TransitionPlanAssessmentRecord[] }) {
  const walkDisclosed = results.reduce((sum, r) => sum + r.walk_disclosed_count, 0);
  const walkTotal = results.reduce((sum, r) => sum + r.walk_total_count, 0);
  const talkDisclosed = results.reduce((sum, r) => sum + r.talk_disclosed_count, 0);
  const talkTotal = results.reduce((sum, r) => sum + r.talk_total_count, 0);
  const chartData = [...results]
    .sort((a, b) => b.disclosed_count - a.disclosed_count)
    .map((r) => ({ label: r.name, value: r.disclosed_count }));

  return (
    <section className="card">
      <h2>Batch overview ({results.length} companies)</h2>
      <div className="stat-tile-grid">
        <div className="stat-tile">
          <div className="stat-value">{walkTotal > 0 ? `${Math.round((walkDisclosed / walkTotal) * 100)}%` : "—"}</div>
          <div className="stat-label">Aggregate "walk" disclosed ({walkDisclosed}/{walkTotal} indicators)</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{talkTotal > 0 ? `${Math.round((talkDisclosed / talkTotal) * 100)}%` : "—"}</div>
          <div className="stat-label">Aggregate "talk" disclosed ({talkDisclosed}/{talkTotal} indicators)</div>
        </div>
      </div>
      <p className="help-text">Companies ranked by total indicators disclosed (out of 64):</p>
      <BarChart data={chartData} valueFormatter={(v) => `${v}/64`} />
    </section>
  );
}

/** The 64 indicators the Transition Plan profile assesses, behind a toggle. */
export function TransitionPlanMethodology() {
  const [indicators, setIndicators] = useState<TransitionPlanIndicatorDef[]>([]);
  const [show, setShow] = useState(false);

  useEffect(() => {
    api.getTransitionPlanIndicators().then(setIndicators).catch(() => {});
  }, []);

  return (
    <>
      <button className="link-button" onClick={() => setShow((s) => !s)}>
        {show ? "Hide" : "Show"} the 64 indicators
      </button>
      {show && (
        <div className="table-wrap">
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
        </div>
      )}
    </>
  );
}

interface ResultsProps {
  runId: string;
  results: TransitionPlanAssessmentRecord[];
  reviewDecisions: Record<string, ReviewDecision>;
  reviewer: string;
  onReviewed: () => void;
  onOpenSource: (s: ActiveSource) => void;
  expanded: string | null;
  onToggleExpanded: (companyId: string) => void;
  filter?: TileFilter;
}

/** One row per company; expanding a row shows its 64 indicators by category. */
export function TransitionPlanResultsTable({ runId, results, reviewDecisions, reviewer, onReviewed, onOpenSource, expanded, onToggleExpanded, filter = null }: ResultsProps) {
  const shown = results.filter((r) => r.indicators.some((i) => indicatorShown(i, reviewDecisions, filter)));
  if (results.length > 0 && shown.length === 0) return <p className="muted">No items match this filter.</p>;
  return (
    <div className="table-wrap">
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
          {shown.map((r) => (
            <Fragment key={r.company_id}>
              <tr className="clickable-row" {...activatable(() => onToggleExpanded(r.company_id), expanded === r.company_id)}>
                <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                <td>{r.disclosed_count}/64</td>
                <td>{r.walk_disclosed_count}/{r.walk_total_count}</td>
                <td>{r.talk_disclosed_count}/{r.talk_total_count}</td>
                <td><ConfidenceBadge value={r.overall_confidence} /></td>
                <td>{r.needs_review ? <ProposedTag /> : ""}</td>
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
                      onReviewed={onReviewed}
                      onOpenSource={onOpenSource}
                      filter={filter}
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
}
