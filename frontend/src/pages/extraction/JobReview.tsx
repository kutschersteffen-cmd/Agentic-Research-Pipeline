import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { ReviewTiles } from "../../components/ReviewTiles";
import { RunScoringPanel } from "../../components/RunScoring";
import { SourcePanel, type ActiveSource } from "../../components/SourcePanel";
import { TransitionPlanBatchOverview } from "../../components/TransitionPlanResults";
import { jobRunType, type Job } from "../../lib/jobs";
import { reviewCounts, type ReviewTileCounts } from "../../lib/stagedFlow";
import type { CompanyFinancialsRecord, ExtractionRecord, ReviewDecision, TnfdRecord, TransitionPlanAssessmentRecord } from "../../types";
import { BatchSpendChart } from "./BatchSpendChart";
import { ResultsTable } from "./ResultsTable";
import { isTrialRun } from "../../lib/runs";
import { useRunManifest } from "./useRunManifest";

type Decisions = Record<string, ReviewDecision>;

/** One job's review side: tiles, results with decisions, charts, source panel and scoring. */
export function JobReview(p: {
  job: Job;
  runId: string;
  reviewer: string;
  onSourceOpen: (s: ActiveSource) => void;
  /** Reports the number of items still awaiting a decision. */
  onPending?: (n: number) => void;
}) {
  const { job, runId, reviewer, onSourceOpen, onPending } = p;
  const mode = job.profile;
  const [tileFilter, setTileFilter] = useState<keyof ReviewTileCounts | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const [extractionResults, setExtractionResults] = useState<ExtractionRecord[]>([]);
  const [financialsResults, setFinancialsResults] = useState<CompanyFinancialsRecord[]>([]);
  const [tnfdResults, setTnfdResults] = useState<TnfdRecord[]>([]);
  const [transitionResults, setTransitionResults] = useState<TransitionPlanAssessmentRecord[]>([]);
  const [extractionDecisions, setExtractionDecisions] = useState<Decisions>({});
  const [financialsDecisions, setFinancialsDecisions] = useState<Decisions>({});
  const [transitionDecisions, setTransitionDecisions] = useState<Decisions>({});

  const refresh = useCallback(async () => {
    if (mode === "custom") {
      setExtractionResults(((await api.getExtractionResults(runId)) as { results: ExtractionRecord[] }).results);
      setExtractionDecisions(((await api.getExtractionReviewDecisions(runId)) as { decisions: Decisions }).decisions);
    } else if (mode === "financials") {
      setFinancialsResults(((await api.getFinancialsResults(runId)) as { results: CompanyFinancialsRecord[] }).results);
      setFinancialsDecisions(((await api.getFinancialsReviewDecisions(runId)) as { decisions: Decisions }).decisions);
    } else if (mode === "tnfd") {
      setTnfdResults((await api.getTnfdResults(runId)).results);
    } else {
      setTransitionResults((await api.getTransitionPlanResults(runId)).results);
      setTransitionDecisions(((await api.getTransitionPlanReviewDecisions(runId)) as { decisions: Decisions }).decisions);
    }
  }, [mode, runId]);

  // A new run starts empty; the poll loads the results once the run ends.
  useEffect(() => {
    setExtractionResults([]);
    setFinancialsResults([]);
    setTnfdResults([]);
    setTransitionResults([]);
    setExtractionDecisions({});
    setFinancialsDecisions({});
    setTransitionDecisions({});
    setExpanded(null);
    setActiveSource(null);
    refresh().catch(() => {});
  }, [refresh]);
  const run = useRunManifest(runId, () => refresh().catch(() => {}));

  const results = { custom: extractionResults, financials: financialsResults, tnfd: tnfdResults, transition_plan: transitionResults };
  const decisionMaps = { custom: extractionDecisions, financials: financialsDecisions, transition_plan: transitionDecisions };
  const decisions = mode === "tnfd" ? [] : Object.values(decisionMaps[mode]);
  const tiles = reviewCounts(Math.max(0, (run?.review_count ?? 0) - decisions.length), decisions, run?.review_count ?? 0);
  const report = useRef(onPending);
  report.current = onPending;
  useEffect(() => report.current?.(tiles.pending), [tiles.pending]);
  const openSource = (s: ActiveSource) => {
    setActiveSource(s);
    onSourceOpen(s);
  };

  return (
    <>
      {/* TNFD has no review decisions, so no tiles. */}
      {mode !== "tnfd" && <ReviewTiles counts={tiles} active={tileFilter} onSelect={setTileFilter} />}
      {mode === "financials" && financialsResults.length > 0 && <BatchSpendChart results={financialsResults} />}
      {mode === "transition_plan" && transitionResults.length > 0 && <TransitionPlanBatchOverview results={transitionResults} />}

      {results[mode].length > 0 && (
        <section className="card">
          <div className="split-review">
            <div className="split-review-main">
              <ResultsTable
                mode={mode}
                runId={runId}
                results={results}
                decisions={decisionMaps}
                expanded={expanded}
                onToggleExpanded={(id) => setExpanded(expanded === id ? null : id)}
                reviewer={reviewer}
                onReviewed={refresh}
                onOpenSource={openSource}
                filter={tileFilter}
                trial={isTrialRun(run)}
              />
            </div>
            <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
          </div>
        </section>
      )}

      <div className="toolbar">
        <button onClick={() => refresh().catch(() => {})}>Refresh results</button>
      </div>
      <RunScoringPanel key={runId} runId={runId} runType={jobRunType(job)} fieldNames={job.profile === "custom" ? job.schema?.fields.map((f) => f.name) : undefined} />
    </>
  );
}
