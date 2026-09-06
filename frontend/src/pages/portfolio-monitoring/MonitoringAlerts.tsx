import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { usePortfolioPane } from "../../context/usePortfolioPane";
import { PortfolioFilterPicker } from "../../components/PortfolioFilterPicker";
import type { Alert, AlertComparator, AlertRule, AlertRuleType, AlertStatus } from "../../types";

const RULE_TYPES: { id: AlertRuleType; label: string }[] = [
  { id: "field_threshold", label: "Company field threshold" },
  { id: "concentration_threshold", label: "Single-name concentration" },
  { id: "portfolio_aggregate_threshold", label: "Portfolio aggregate (WACI-style)" },
];

const COMPARATORS: { id: AlertComparator; label: string }[] = [
  { id: "gt", label: "> greater than" },
  { id: "gte", label: ">= at least" },
  { id: "lt", label: "< less than" },
  { id: "lte", label: "<= at most" },
];

const STATUS_FILTERS: (AlertStatus | "all")[] = ["open", "acknowledged", "escalated", "resolved", "false_positive", "all"];
const TERMINAL_STATUSES: AlertStatus[] = ["resolved", "false_positive"];

function BreachTypeBadge({ type }: { type: Alert["breach_type"] }) {
  const label = { holdings_caused: "Holdings-caused", data_caused: "Data-caused", mixed: "Mixed", unknown: "Unknown" }[type];
  return <span className={type === "unknown" ? "badge badge-neutral" : "badge badge-mid"}>{label}</span>;
}

function StatusBadge({ status }: { status: AlertStatus }) {
  const cls = status === "open" ? "badge badge-low" : TERMINAL_STATUSES.includes(status) ? "badge badge-high" : "badge badge-mid";
  return <span className={cls}>{status.replace("_", " ")}</span>;
}

/** Continuous monitoring & alerting (spec §3 / §9 sub-tab 3): threshold
 * rules over the same deterministic aggregation/data-point engine every
 * other sub-tab uses (see arp/portfolio/monitoring/evaluator.py) -- no
 * factor/PAI/benchmark-relative rules, since that data model doesn't
 * exist yet (docs/SPEC_GAP_ANALYSIS.md §1). Event-driven triggers are
 * NewsRiskFlags only; calendar-driven triggers are a fixed-interval
 * background re-evaluation, not true calendar windows (proxy season,
 * PAI deadlines) -- see the scheduler's docstring for why. Alert
 * *raising* is system-generated; every status change requires a human
 * (`decided_by`), mirroring the engagement module's escalation ladder.
 * Company/news alerts always show regardless of the pane's selection
 * (an analyst monitoring the whole book shouldn't lose visibility by
 * having a portfolio selected) -- portfolio-aggregate alerts do respect
 * it, since those are inherently portfolio-scoped already. */
export function MonitoringAlerts() {
  const { portfolios, climateSchema, selectedPortfolioIds } = usePortfolioPane();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [statusFilter, setStatusFilter] = useState<AlertStatus | "all">("open");
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [decidedBy, setDecidedBy] = useState("");

  const [name, setName] = useState("");
  const [ruleType, setRuleType] = useState<AlertRuleType>("field_threshold");
  const [fieldId, setFieldId] = useState("");
  const [comparator, setComparator] = useState<AlertComparator>("gt");
  const [thresholdValue, setThresholdValue] = useState("");
  const [scopePortfolioIds, setScopePortfolioIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);

  function loadAll() {
    Promise.all([api.listMonitoringRules(), api.listAlerts(statusFilter === "all" ? undefined : statusFilter)])
      .then(([r, a]) => {
        setRules(r);
        setAlerts(a);
      })
      .catch((e) => setError(String(e)));
  }

  useEffect(loadAll, [statusFilter]);

  useEffect(() => {
    if (!fieldId && climateSchema?.fields.length) setFieldId(climateSchema.fields[0].field_id);
  }, [climateSchema, fieldId]);

  async function createRule() {
    if (!name.trim() || !thresholdValue) return;
    setCreating(true);
    setError(null);
    try {
      await api.createMonitoringRule({
        name: name.trim(),
        rule_type: ruleType,
        field_id: ruleType === "concentration_threshold" ? null : fieldId,
        comparator,
        threshold_value: Number(thresholdValue),
        company_ids: [],
        portfolio_ids: scopePortfolioIds,
        severity: "medium",
        enabled: true,
      });
      setName("");
      setThresholdValue("");
      loadAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  async function evaluateNow() {
    setEvaluating(true);
    setError(null);
    try {
      await api.evaluateMonitoringNow();
      loadAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setEvaluating(false);
    }
  }

  async function transition(alert: Alert, status: AlertStatus) {
    if (!decidedBy.trim()) {
      setError("Enter who's making this decision (top right) before acting on an alert.");
      return;
    }
    setError(null);
    try {
      await api.transitionAlert(alert.scope_id, alert.alert_id, { status, decided_by: decidedBy.trim() });
      loadAll();
    } catch (e) {
      setError(String(e));
    }
  }

  const visibleAlerts = alerts.filter(
    (a) => !(a.portfolio_id && selectedPortfolioIds.length > 0) || selectedPortfolioIds.includes(a.portfolio_id)
  );

  return (
    <>
      <section className="card">
        <h3>Add a monitoring rule</h3>
        <p className="help-text">
          Threshold-based breach monitoring over the same deterministic engine Pivot Explorer uses -- no new data
          model. Factor/PAI/benchmark-relative rules aren't available yet (see{" "}
          <code>docs/SPEC_GAP_ANALYSIS.md</code> §1).
        </p>
        <div className="toolbar">
          <input placeholder="Rule name" value={name} onChange={(e) => setName(e.target.value)} />
          <select value={ruleType} onChange={(e) => setRuleType(e.target.value as AlertRuleType)}>
            {RULE_TYPES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          {ruleType !== "concentration_threshold" && (
            <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
              {(climateSchema?.fields ?? []).map((f) => (
                <option key={f.field_id} value={f.field_id}>
                  {f.name}
                </option>
              ))}
            </select>
          )}
          <select value={comparator} onChange={(e) => setComparator(e.target.value as AlertComparator)}>
            {COMPARATORS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
          <input
            type="number"
            step="any"
            placeholder={ruleType === "concentration_threshold" ? "e.g. 0.1 (10%)" : "threshold value"}
            value={thresholdValue}
            onChange={(e) => setThresholdValue(e.target.value)}
          />
          <button onClick={createRule} disabled={creating || !name.trim() || !thresholdValue}>
            {creating ? "Adding..." : "Add rule"}
          </button>
        </div>
        {ruleType !== "field_threshold" && (
          <PortfolioFilterPicker portfolios={portfolios} selected={scopePortfolioIds} onChange={setScopePortfolioIds} />
        )}
      </section>

      <section className="card">
        <h3>Rules ({rules.length})</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Condition</th>
              <th>Scope</th>
              <th>Enabled</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.rule_id}>
                <td>{r.name}</td>
                <td>{r.rule_type}</td>
                <td>
                  {r.field_id ? `${r.field_id} ` : ""}
                  {r.comparator} {r.threshold_value}
                </td>
                <td>{r.portfolio_ids.length ? r.portfolio_ids.join(", ") : r.company_ids.length ? r.company_ids.join(", ") : "all"}</td>
                <td>{r.enabled ? "yes" : "no"}</td>
              </tr>
            ))}
            {rules.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No rules configured yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Alerts ({visibleAlerts.length})</h3>
        <div className="toolbar">
          {STATUS_FILTERS.map((s) => (
            <button key={s} className={s === statusFilter ? "nav-tab active" : "nav-tab"} onClick={() => setStatusFilter(s)}>
              {s.replace("_", " ")}
            </button>
          ))}
          <button onClick={evaluateNow} disabled={evaluating}>
            {evaluating ? "Evaluating..." : "Evaluate now"}
          </button>
          <input placeholder="Decided by (required to act on an alert)" value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} />
        </div>
        {error && <p className="error-text">{error}</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>Scope</th>
              <th>Category</th>
              <th>Breach type</th>
              <th>Observed</th>
              <th>Threshold</th>
              <th>Status</th>
              <th>Rationale</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visibleAlerts.map((a) => (
              <tr key={a.alert_id}>
                <td>{a.scope_id}</td>
                <td>{a.category.replace("_", " ")}</td>
                <td>
                  <BreachTypeBadge type={a.breach_type} />
                </td>
                <td>{a.observed_value ?? "--"}</td>
                <td>{a.threshold_value ?? "--"}</td>
                <td>
                  <StatusBadge status={a.status} />
                </td>
                <td>{a.rationale}</td>
                <td className="toolbar">
                  {!TERMINAL_STATUSES.includes(a.status) && a.status !== "acknowledged" && (
                    <button className="link-button" onClick={() => transition(a, "acknowledged")}>
                      Ack
                    </button>
                  )}
                  {!TERMINAL_STATUSES.includes(a.status) && a.status !== "escalated" && (
                    <button className="link-button" onClick={() => transition(a, "escalated")}>
                      Escalate
                    </button>
                  )}
                  {a.status !== "resolved" && (
                    <button className="link-button" onClick={() => transition(a, "resolved")}>
                      Resolve
                    </button>
                  )}
                  {a.status !== "false_positive" && (
                    <button className="link-button" onClick={() => transition(a, "false_positive")}>
                      False positive
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {visibleAlerts.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No alerts.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
