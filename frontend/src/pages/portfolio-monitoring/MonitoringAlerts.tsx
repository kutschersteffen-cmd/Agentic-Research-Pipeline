import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { SIGN_IN_REQUIRED, useMe } from "../../lib/reviewer";
import { errorDetail } from "../../lib/themeLayers";
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
const LIVE_STATUSES: AlertStatus[] = ["open", "acknowledged", "escalated"];

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
  const decidedBy = useMe()?.name ?? "";

  const [name, setName] = useState("");
  const [ruleType, setRuleType] = useState<AlertRuleType>("field_threshold");
  const [fieldId, setFieldId] = useState("");
  const [comparator, setComparator] = useState<AlertComparator>("gt");
  const [thresholdValue, setThresholdValue] = useState("");
  const [scopePortfolioIds, setScopePortfolioIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  /** The stored rule the form is editing; null while it adds a new one. */
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const [clearingRuleId, setClearingRuleId] = useState<string | null>(null);
  const [ruleError, setRuleError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  // Every alert, whatever the filter shows: a rule's live count and a deleted rule's alerts need them all.
  function loadAll() {
    Promise.all([api.listMonitoringRules(), api.listAlerts()])
      .then(([r, a]) => {
        setRules(r);
        setAlerts(a);
      })
      .catch((e) => setError(String(e)));
  }

  useEffect(loadAll, []);

  useEffect(() => {
    if (!fieldId && climateSchema?.fields.length) setFieldId(climateSchema.fields[0].field_id);
  }, [climateSchema, fieldId]);

  async function createRule() {
    if (!name.trim() || !thresholdValue) return;
    setCreating(true);
    setError(null);
    try {
      await api.createMonitoringRule({
        // an edit keeps what the form does not show (company scope, severity, enabled) and replaces the rule by id
        ...(editing ?? { company_ids: [], severity: "medium" as const, enabled: true }),
        name: name.trim(),
        rule_type: ruleType,
        field_id: ruleType === "concentration_threshold" ? null : fieldId,
        comparator,
        threshold_value: Number(thresholdValue),
        portfolio_ids: ruleType === "field_threshold" ? [] : scopePortfolioIds,
      });
      resetForm();
      loadAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  function resetForm() {
    setEditing(null);
    setName("");
    setThresholdValue("");
  }

  function startEdit(rule: AlertRule) {
    nameRef.current?.focus(); // the form is above the table: take the keyboard (and the view) there
    setEditing(rule);
    setName(rule.name);
    setRuleType(rule.rule_type);
    if (rule.field_id) setFieldId(rule.field_id);
    setComparator(rule.comparator);
    setThresholdValue(String(rule.threshold_value));
    setScopePortfolioIds(rule.portfolio_ids);
  }

  async function ruleAction(action: () => Promise<unknown>) {
    setRuleError(null);
    try {
      await action();
      loadAll();
    } catch (e) {
      setRuleError(errorDetail(e));
    }
  }

  function deleteRule(rule: AlertRule) {
    if (!window.confirm(`Delete rule '${rule.name}'?`)) return;
    ruleAction(async () => {
      await api.deleteMonitoringRule(rule.rule_id);
      if (editing?.rule_id === rule.rule_id) resetForm();
    });
  }

  function clearAlerts(rule: AlertRule, status: "resolved" | "false_positive") {
    setClearingRuleId(null);
    ruleAction(() => api.clearRuleAlerts(rule.rule_id, status));
  }

  const liveCount = (ruleId: string) => alerts.filter((a) => a.rule_id === ruleId && LIVE_STATUSES.includes(a.status)).length;

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
      setError(SIGN_IN_REQUIRED);
      return;
    }
    setError(null);
    try {
      await api.transitionAlert(alert.scope_id, alert.alert_id, { status });
      loadAll();
    } catch (e) {
      setError(String(e));
    }
  }

  const visibleAlerts = alerts.filter(
    (a) =>
      (statusFilter === "all" || a.status === statusFilter) &&
      (!(a.portfolio_id && selectedPortfolioIds.length > 0) || selectedPortfolioIds.includes(a.portfolio_id))
  );

  return (
    <>
      <section className="card">
        <h2>{editing ? "Edit monitoring rule" : "Add a monitoring rule"}</h2>
        <p className="help-text">
          Flag a breach when a figure crosses a threshold, computed by the portfolio aggregation engine. Factor, PAI
          and benchmark-relative rules are not available yet.
        </p>
        <div className="toolbar">
          <input ref={nameRef} aria-label="Rule name" placeholder="Rule name" value={name} onChange={(e) => setName(e.target.value)} />
          <select aria-label="Rule type" value={ruleType} onChange={(e) => setRuleType(e.target.value as AlertRuleType)}>
            {RULE_TYPES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          {ruleType !== "concentration_threshold" && (
            <select aria-label="Field" value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
              {(climateSchema?.fields ?? []).map((f) => (
                <option key={f.field_id} value={f.field_id}>
                  {f.name}
                </option>
              ))}
            </select>
          )}
          <select aria-label="Comparator" value={comparator} onChange={(e) => setComparator(e.target.value as AlertComparator)}>
            {COMPARATORS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
          <input aria-label="Threshold value"
            type="number"
            step="any"
            placeholder={ruleType === "concentration_threshold" ? "e.g. 0.1 (10%)" : "threshold value"}
            value={thresholdValue}
            onChange={(e) => setThresholdValue(e.target.value)}
          />
          <button onClick={createRule} disabled={creating || !name.trim() || !thresholdValue}>
            {editing ? (creating ? "Saving..." : "Save rule") : creating ? "Adding..." : "Add rule"}
          </button>
          {editing && <button onClick={resetForm}>Cancel</button>}
        </div>
        {ruleType !== "field_threshold" && (
          <PortfolioFilterPicker portfolios={portfolios} selected={scopePortfolioIds} onChange={setScopePortfolioIds} />
        )}
      </section>

      <section className="card">
        <h2>Rules ({rules.length})</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Condition</th>
                <th>Scope</th>
                <th>Enabled</th>
                <th>Alerts</th>
                <th>Actions</th>
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
                  <td>{liveCount(r.rule_id)}</td>
                  <td className="toolbar">
                    <button className="link-button" onClick={() => ruleAction(() => api.createMonitoringRule({ ...r, enabled: !r.enabled }))}>
                      {r.enabled ? "Disable" : "Enable"}
                    </button>
                    <button className="link-button" onClick={() => startEdit(r)}>
                      Edit
                    </button>
                    {clearingRuleId === r.rule_id ? (
                      <>
                        {/* autoFocus: these replace the button that had focus */}
                        <button className="link-button" autoFocus onClick={() => clearAlerts(r, "resolved")}>
                          Resolve
                        </button>
                        <button className="link-button" onClick={() => clearAlerts(r, "false_positive")}>
                          False positive
                        </button>
                      </>
                    ) : (
                      <button className="link-button" onClick={() => setClearingRuleId(r.rule_id)}>
                        Clear alerts
                      </button>
                    )}
                    <button className="link-button" onClick={() => deleteRule(r)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {rules.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    No rules configured yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {ruleError && <p className="error-text" role="alert">{ruleError}</p>}
      </section>

      <section className="card">
        <h2>Alerts ({visibleAlerts.length})</h2>
        <div className="toolbar">
          {STATUS_FILTERS.map((s) => (
            <button key={s} className={s === statusFilter ? "nav-tab active" : "nav-tab"} aria-pressed={s === statusFilter} onClick={() => setStatusFilter(s)}>
              {s.replace("_", " ")}
            </button>
          ))}
          <button onClick={evaluateNow} disabled={evaluating}>
            {evaluating ? "Evaluating..." : "Evaluate now"}
          </button>
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="table-wrap">
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
        </div>
      </section>
    </>
  );
}
