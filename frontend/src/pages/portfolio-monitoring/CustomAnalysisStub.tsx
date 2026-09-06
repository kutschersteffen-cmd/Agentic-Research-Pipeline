/** Spec §7: a managed, governed Jupyter environment against the same data
 * model the rest of this tool uses, with a promotion path back into saved
 * pivots/monitors. None of this is built yet -- see
 * docs/SPEC_GAP_ANALYSIS.md §7. The one precondition the spec calls for,
 * API-first access to the governed data model, already exists
 * (backend/arp/api/routers/{portfolio,climate}.py); the notebook
 * environment itself does not. */
export function CustomAnalysisStub() {
  return (
    <div className="stub-panel">
      <h3>Custom Analysis -- not yet built</h3>
      <p>
        No managed notebook environment exists yet. The governed REST API it would query already does (see{" "}
        <code>backend/arp/api/routers/portfolio.py</code>) -- see <code>docs/SPEC_GAP_ANALYSIS.md</code> §7 for what
        the notebook layer itself would still need.
      </p>
    </div>
  );
}
