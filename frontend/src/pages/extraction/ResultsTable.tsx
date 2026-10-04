import { ExtractionResultsTable, FinancialsResultsTable } from "../../components/ExtractionResults";
import type { ActiveSource } from "../../components/SourcePanel";
import { TnfdResultsTable } from "../../components/TnfdResults";
import { TransitionPlanResultsTable } from "../../components/TransitionPlanResults";
import type { ReviewTileCounts } from "../../lib/stagedFlow";
import type { CompanyFinancialsRecord, ExtractionProfile, ExtractionRecord, ReviewDecision, ReviewStates, TnfdRecord, TransitionPlanAssessmentRecord } from "../../types";

type Decisions = Record<string, ReviewDecision>;

/** The profile's results table with its review controls. */
export function ResultsTable(p: {
  mode: ExtractionProfile;
  runId: string;
  results: { custom: ExtractionRecord[]; financials: CompanyFinancialsRecord[]; tnfd: TnfdRecord[]; transition_plan: TransitionPlanAssessmentRecord[] };
  decisions: { custom: Decisions; financials: Decisions; transition_plan: Decisions };
  states: ReviewStates;
  expanded: string | null;
  onToggleExpanded: (companyId: string) => void;
  reviewer: string;
  onReviewed: () => void;
  onOpenSource: (s: ActiveSource) => void;
  filter?: keyof ReviewTileCounts | null;
  trial?: boolean;
}) {
  const { runId, expanded, onToggleExpanded, reviewer, onOpenSource, filter } = p;
  switch (p.mode) {
    case "custom":
      return (
        <ExtractionResultsTable
          results={p.results.custom}
          runId={runId}
          expanded={expanded}
          onToggleExpanded={onToggleExpanded}
          reviewDecisions={p.decisions.custom}
          states={p.states}
          reviewer={reviewer}
          onReviewDone={p.onReviewed}
          onOpenSource={onOpenSource}
          filter={filter}
          trial={p.trial}
        />
      );
    case "financials":
      return (
        <FinancialsResultsTable
          results={p.results.financials}
          runId={runId}
          expanded={expanded}
          onToggleExpanded={onToggleExpanded}
          reviewDecisions={p.decisions.financials}
          reviewer={reviewer}
          onReviewDone={p.onReviewed}
          onOpenSource={onOpenSource}
          filter={filter}
        />
      );
    case "tnfd":
      return <TnfdResultsTable results={p.results.tnfd} expanded={expanded} onToggleExpanded={onToggleExpanded} onOpenSource={onOpenSource} />;
    default:
      return (
        <TransitionPlanResultsTable
          runId={runId}
          results={p.results.transition_plan}
          reviewDecisions={p.decisions.transition_plan}
          reviewer={reviewer}
          onReviewed={p.onReviewed}
          onOpenSource={onOpenSource}
          expanded={expanded}
          onToggleExpanded={onToggleExpanded}
          filter={filter}
        />
      );
  }
}
