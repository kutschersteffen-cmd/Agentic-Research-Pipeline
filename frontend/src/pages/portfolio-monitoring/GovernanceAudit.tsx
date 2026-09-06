import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ConfidenceBadge } from "../../components/ConfidenceBadge";
import type {
  DataPointObservation,
  GovernanceDecision,
  PolicyChange,
  PolicySettingName,
  RiskCategoryOwner,
  SecurityResolution,
} from "../../types";

const SUGGESTED_CATEGORIES = ["entity_resolution", "climate_conflict", "threshold_breach", "news_controversy"];
const POLICY_SETTINGS: { id: PolicySettingName; label: string }[] = [
  { id: "portfolio_confidence_review_threshold", label: "Entity-resolution confidence review threshold" },
  { id: "climate_validation_tolerance_pct", label: "Climate validation tolerance (%)" },
];

/** Ownership, methodology, and audit trail (spec §5 / §9 sub-tab 7). This
 * is the one sub-tab where the pane's selection is informational context
 * rather than a hard filter -- both review tables below are issuer/
 * security-level facts, not portfolio-scoped queries.
 *
 * `accept`/`reject` are pure audit annotations -- the underlying flag
 * (`needs_review` / `conflicting_sources`) is never mutated, only the
 * decision log grows (see arp/portfolio/governance.py::list_pending_
 * reviews for how that's still enough for an item to drop off "pending").
 * `override` has real effect: it writes a corrected SecurityRef/company_id
 * or a fresh, non-conflicting DataPointObservation, so it clears the flag
 * entirely -- not just from "pending" but from the raw flagged list too.
 *
 * Methodology settings are live-configurable here (not just env-var
 * config); the current value and its full change history are both folded
 * from the same append-only governance event log. Changing a setting only
 * affects future demo-seeds, not already-resolved securities/observations
 * -- entity resolution and climate cross-checking each only run once, at
 * seed time (see docs/SPEC_GAP_ANALYSIS.md §5). */
export function GovernanceAudit() {
  const [pending, setPending] = useState<{ entity_resolution: SecurityResolution[]; climate_conflict: DataPointObservation[] }>({
    entity_resolution: [],
    climate_conflict: [],
  });
  const [allResolutions, setAllResolutions] = useState<SecurityResolution[]>([]);
  const [allConflicts, setAllConflicts] = useState<DataPointObservation[]>([]);
  const [decisions, setDecisions] = useState<GovernanceDecision[]>([]);
  const [view, setView] = useState<"pending" | "all">("pending");

  const [policyValues, setPolicyValues] = useState<Record<PolicySettingName, number> | null>(null);
  const [policyHistory, setPolicyHistory] = useState<PolicyChange[]>([]);
  const [policySetting, setPolicySetting] = useState<PolicySettingName>(POLICY_SETTINGS[0].id);
  const [policyNewValue, setPolicyNewValue] = useState("");
  const [policyReason, setPolicyReason] = useState("");

  const [owners, setOwners] = useState<RiskCategoryOwner[]>([]);
  const [ownerInputs, setOwnerInputs] = useState<Record<string, string>>({});

  const [decidedBy, setDecidedBy] = useState("");
  const [overrideInputs, setOverrideInputs] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  function loadAll() {
    Promise.all([
      api.listPendingGovernanceReviews(),
      api.listSecuritiesNeedingReview(),
      api.listConflictingObservations(),
      api.listGovernanceDecisions(),
      api.getGovernancePolicy(),
      api.listGovernanceOwners(),
    ])
      .then(([p, r, c, d, policy, o]) => {
        setPending(p);
        setAllResolutions(r);
        setAllConflicts(c);
        setDecisions(d);
        setPolicyValues(policy.values);
        setPolicyHistory(policy.history);
        setOwners(o);
      })
      .catch((e) => setError(String(e)));
  }

  useEffect(loadAll, []);

  function decisionFor(itemKey: string): GovernanceDecision | undefined {
    return decisions.filter((d) => d.item_key === itemKey).sort((a, b) => (a.decided_at < b.decided_at ? 1 : -1))[0];
  }

  async function decide(itemType: "entity_resolution" | "climate_conflict", itemKey: string, decision: "accept" | "override" | "reject") {
    if (!decidedBy.trim()) {
      setError("Enter who's making this decision (top right) before acting on an item.");
      return;
    }
    const overrideValue = overrideInputs[itemKey];
    if (decision === "override" && !overrideValue?.trim()) {
      setError("Enter an override value before overriding this item.");
      return;
    }
    setError(null);
    try {
      await api.recordGovernanceDecision({
        item_type: itemType,
        item_key: itemKey,
        decision,
        decided_by: decidedBy.trim(),
        override_value: decision === "override" ? (itemType === "climate_conflict" ? Number(overrideValue) : overrideValue) : undefined,
      });
      loadAll();
    } catch (e) {
      setError(String(e));
    }
  }

  async function submitPolicyChange() {
    if (!decidedBy.trim() || !policyNewValue) return;
    setError(null);
    try {
      await api.updateGovernancePolicy({ setting_name: policySetting, new_value: Number(policyNewValue), changed_by: decidedBy.trim(), reason: policyReason });
      setPolicyNewValue("");
      setPolicyReason("");
      loadAll();
    } catch (e) {
      setError(String(e));
    }
  }

  async function assignOwner(category: string) {
    const owner = ownerInputs[category];
    if (!decidedBy.trim() || !owner?.trim()) return;
    setError(null);
    try {
      await api.assignGovernanceOwner(category, { owner: owner.trim(), assigned_by: decidedBy.trim() });
      loadAll();
    } catch (e) {
      setError(String(e));
    }
  }

  const resolutionRows = view === "pending" ? pending.entity_resolution : allResolutions;
  const conflictRows = view === "pending" ? pending.climate_conflict : allConflicts;
  const ownersByCategory = Object.fromEntries(owners.map((o) => [o.category, o]));
  const categories = Array.from(new Set([...SUGGESTED_CATEGORIES, ...owners.map((o) => o.category)]));

  return (
    <>
      <section className="card">
        <h3>Methodology</h3>
        <p className="help-text">
          Live-configurable governance settings -- the current value and full change history are both derived from
          the same append-only event log, never a separate mutable snapshot. Changing a setting only affects future
          demo-seeds, not already-resolved securities/observations (see <code>docs/SPEC_GAP_ANALYSIS.md</code> §5).
        </p>
        {policyValues && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Setting</th>
                <th>Current value</th>
              </tr>
            </thead>
            <tbody>
              {POLICY_SETTINGS.map((s) => (
                <tr key={s.id}>
                  <td>{s.label}</td>
                  <td>{policyValues[s.id]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="toolbar">
          <select value={policySetting} onChange={(e) => setPolicySetting(e.target.value as PolicySettingName)}>
            {POLICY_SETTINGS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <input type="number" step="any" placeholder="new value" value={policyNewValue} onChange={(e) => setPolicyNewValue(e.target.value)} />
          <input placeholder="reason" value={policyReason} onChange={(e) => setPolicyReason(e.target.value)} />
          <button onClick={submitPolicyChange} disabled={!policyNewValue}>
            Change setting
          </button>
        </div>
        {policyHistory.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Setting</th>
                <th>Old value</th>
                <th>New value</th>
                <th>Changed by</th>
                <th>Reason</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {[...policyHistory].reverse().map((h, i) => (
                <tr key={i}>
                  <td>{h.setting_name}</td>
                  <td>{h.old_value}</td>
                  <td>{h.new_value}</td>
                  <td>{h.changed_by}</td>
                  <td>{h.reason}</td>
                  <td>{h.changed_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h3>Risk category ownership</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Category</th>
              <th>Owner</th>
              <th>Assign</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <tr key={cat}>
                <td>{cat}</td>
                <td>{ownersByCategory[cat]?.owner ?? <span className="muted">unassigned</span>}</td>
                <td className="toolbar">
                  <input
                    placeholder="owner name"
                    value={ownerInputs[cat] ?? ""}
                    onChange={(e) => setOwnerInputs((prev) => ({ ...prev, [cat]: e.target.value }))}
                  />
                  <button onClick={() => assignOwner(cat)}>Assign</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="toolbar">
        <button className={view === "pending" ? "nav-tab active" : "nav-tab"} onClick={() => setView("pending")}>
          pending
        </button>
        <button className={view === "all" ? "nav-tab active" : "nav-tab"} onClick={() => setView("all")}>
          all
        </button>
        <input placeholder="Decided by (required to act on an item)" value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} />
      </div>
      {error && <p className="error-text">{error}</p>}

      <section className="card">
        <h3>
          Entity-resolution review queue ({resolutionRows.length})
        </h3>
        <p className="help-text">
          Securities whose issuer match fell below the confidence threshold -- never auto-matched, always surfaced
          here instead (see <code>entity_resolution.py</code>).
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Security</th>
              <th>Best-guess issuer</th>
              <th>Confidence</th>
              <th>Method</th>
              <th>Last decision</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {resolutionRows.map((r) => {
              const decision = decisionFor(r.security_id);
              return (
                <tr key={r.security_id}>
                  <td>{r.security_id}</td>
                  <td>{r.company_id ?? "(none)"}</td>
                  <td>
                    <ConfidenceBadge value={r.confidence} />
                  </td>
                  <td>{r.method}</td>
                  <td>{decision ? `${decision.decision} by ${decision.decided_by}` : <span className="muted">none</span>}</td>
                  <td className="toolbar">
                    <button className="link-button" onClick={() => decide("entity_resolution", r.security_id, "accept")}>
                      Accept
                    </button>
                    <input
                      placeholder="correct company_id"
                      value={overrideInputs[r.security_id] ?? ""}
                      onChange={(e) => setOverrideInputs((prev) => ({ ...prev, [r.security_id]: e.target.value }))}
                    />
                    <button className="link-button" onClick={() => decide("entity_resolution", r.security_id, "override")}>
                      Override
                    </button>
                    <button className="link-button" onClick={() => decide("entity_resolution", r.security_id, "reject")}>
                      Reject
                    </button>
                  </td>
                </tr>
              );
            })}
            {resolutionRows.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  {view === "pending" ? "Nothing pending review." : "Nothing flagged."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Climate data conflicts ({conflictRows.length})</h3>
        <p className="help-text">
          Values where the internal ESG API disagreed with an independent extraction from company disclosures beyond
          tolerance. The internal-API value is still the one used for computation, but it's flagged rather than
          silently reconciled (see <code>climate/validation.py</code>).
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Field</th>
              <th>Value used</th>
              <th>Conflicting value</th>
              <th>Source</th>
              <th>Last decision</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {conflictRows.map((c) => {
              const itemKey = `${c.company_id}:${c.field_id}`;
              const decision = decisionFor(itemKey);
              return (
                <tr key={itemKey}>
                  <td>{c.company_id}</td>
                  <td>{c.field_name}</td>
                  <td>{String(c.value)}</td>
                  <td>{String(c.conflicting_value)}</td>
                  <td>{c.conflicting_source_label}</td>
                  <td>{decision ? `${decision.decision} by ${decision.decided_by}` : <span className="muted">none</span>}</td>
                  <td className="toolbar">
                    <button className="link-button" onClick={() => decide("climate_conflict", itemKey, "accept")}>
                      Accept
                    </button>
                    <input
                      type="number"
                      step="any"
                      placeholder="correct value"
                      value={overrideInputs[itemKey] ?? ""}
                      onChange={(e) => setOverrideInputs((prev) => ({ ...prev, [itemKey]: e.target.value }))}
                    />
                    <button className="link-button" onClick={() => decide("climate_conflict", itemKey, "override")}>
                      Override
                    </button>
                    <button className="link-button" onClick={() => decide("climate_conflict", itemKey, "reject")}>
                      Reject
                    </button>
                  </td>
                </tr>
              );
            })}
            {conflictRows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  {view === "pending" ? "Nothing pending review." : "No conflicts flagged."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
