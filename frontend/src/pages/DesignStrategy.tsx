import { WORKSPACES } from "../lib/processes";
import { HandoffLegend, ProcessFlow, useActivity, useHouseFlow, useRuns } from "./ProcessHub";

const DESIGN = WORKSPACES.find((w) => w.id === "rdLab")!.processes.find((p) => p.id === "thematic")!;

/** Strategy · Design a strategy: the flow from an idea (a theme or a research paper) to a portfolio you can report on. */
export function DesignStrategy() {
  const { runs } = useRuns();
  const { flow } = useHouseFlow();
  const activity = useActivity();
  return (
    <div className="page">
      <h1>Design a strategy</h1>
      <p className="help-text">From an idea to a portfolio you can report on.</p>
      <div className="toolbar">
        <a className="button-link" href="#/themes">Start from a theme</a>
        <a className="button-link" href="#/strategyReplication">Start from a research paper</a>
      </div>
      <ProcessFlow p={DESIGN} runs={runs} flow={flow} activity={activity} foldable={false} />
      <HandoffLegend />
    </div>
  );
}
