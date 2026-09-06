/** Spec §3: threshold/breach monitoring, event- and calendar-driven
 * triggers, trade-caused-vs-data-caused drift detection, and an
 * escalation/audit record. None of this is built yet -- see
 * docs/SPEC_GAP_ANALYSIS.md §3. This is a clearly-labeled placeholder
 * rather than a control surface with nothing behind it. */
export function MonitoringAlertsStub() {
  return (
    <div className="stub-panel">
      <h3>Monitoring &amp; Alerts -- not yet built</h3>
      <p>
        No threshold/breach rules, event- or calendar-driven triggers, or drift detection exist yet. See{" "}
        <code>docs/SPEC_GAP_ANALYSIS.md</code> §3 for what this would need.
      </p>
    </div>
  );
}
