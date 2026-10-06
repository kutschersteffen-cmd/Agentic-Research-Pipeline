import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { SIGN_IN_REQUIRED, useMe } from "../../lib/reviewer";
import type { Alert, AlertStatus, CompanyRef, TrackedEngagement, UnifiedTrigger } from "../../types";

const CLOSED_ALERTS: AlertStatus[] = ["resolved", "false_positive"];

/** The fixed, native part of the Company Profile (spec §6): the issuer picker, an as-of month,
 * and the issuer's open engagements, stored triggers and open alerts with their actions.
 * The as-of month hides triggers first seen and alerts raised after it; empty means latest. */
export function ProfileActionStrip({ companyId, onCompany }: { companyId: string; onCompany: (id: string) => void }) {
  const decidedBy = useMe()?.name ?? "";
  const [companies, setCompanies] = useState<CompanyRef[]>([]);
  const [month, setMonth] = useState("");
  const [engagements, setEngagements] = useState<TrackedEngagement[]>([]);
  const [triggers, setTriggers] = useState<UnifiedTrigger[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = () =>
    Promise.all([
      api.getTracking().then((r) => setEngagements(r.engagements)),
      api.listTriggers().then((r) => setTriggers(r.triggers)),
      api.listAlerts().then(setAlerts),
    ]).catch((e) => setError(String(e)));

  useEffect(() => {
    api.listPortfolioCompanies().then(setCompanies, () => setCompanies([]));
    void load();
  }, []);

  async function act(key: string, action: () => Promise<unknown>) {
    if (!decidedBy.trim()) {
      setError(SIGN_IN_REQUIRED);
      return;
    }
    setBusy(key);
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const upTo = (m: string) => !month || m <= month;
  const myEngagements = engagements.filter((e) => e.company_id === companyId && (e.status === "open" || e.status === "stalled"));
  const myTriggers = triggers.filter((t) => t.issuer_id === companyId && t.status !== "resolved" && upTo(t.first_seen_month));
  const myAlerts = alerts.filter((a) => a.company_id === companyId && !CLOSED_ALERTS.includes(a.status) && upTo(a.triggered_at.slice(0, 7)));

  return (
    <section className="card">
      <h2>Company Profiles</h2>
      <div className="toolbar">
        <label className="field-label inline-label">
          Issuer
          <select value={companyId} onChange={(e) => onCompany(e.target.value)}>
            <option value="">-- select an issuer --</option>
            {companies.map((c) => (
              <option key={c.company_id} value={c.company_id}>
                {c.name} ({c.company_id})
              </option>
            ))}
          </select>
        </label>
        <label className="field-label inline-label">
          As of month
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        </label>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}

      {companyId && (
        <>
          <h3>Engagements ({myEngagements.length})</h3>
          {myEngagements.length === 0 ? (
            <p className="muted">No open or stalled engagements for this issuer.</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Theme</th><th>Step</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {myEngagements.map((e) => (
                    <tr key={e.issue_id}><td>{e.theme}</td><td>{e.step}</td><td>{e.status}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Triggers ({myTriggers.length})</h3>
          {myTriggers.length === 0 ? (
            <p className="muted">No open stewardship triggers for this issuer.</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Type</th><th>Severity</th><th>Reason</th><th>Status</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {myTriggers.map((t) => (
                    <tr key={t.trigger_id}>
                      <td>{t.type} {t.is_new && <span className="badge badge-mid">New since last run</span>}</td>
                      <td>{t.severity}</td>
                      <td>{t.reason}</td>
                      <td>{t.status}</td>
                      <td className="toolbar">
                        {t.status === "open" && (
                          <button className="link-button" disabled={busy !== null}
                            onClick={() => act(t.trigger_id, () => api.transitionTrigger(t.trigger_id, { status: "acknowledged", decided_by: decidedBy }))}>
                            Acknowledge
                          </button>
                        )}
                        <button className="link-button" disabled={busy !== null}
                          onClick={() => act(t.trigger_id, () => api.transitionTrigger(t.trigger_id, { status: "resolved", decided_by: decidedBy }))}>
                          Resolve
                        </button>
                        {t.rule && (
                          <button className="link-button" disabled={busy !== null}
                            onClick={() => act(t.trigger_id, () => api.openEngagementFromTrigger({ issuer_id: t.issuer_id, rule: t.rule }))}>
                            Open engagement
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Alerts ({myAlerts.length})</h3>
          {myAlerts.length === 0 ? (
            <p className="muted">No open alerts for this issuer.</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Category</th><th>Raised</th><th>Rationale</th><th>Status</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {myAlerts.map((a) => (
                    <tr key={a.alert_id}>
                      <td>{a.category}</td>
                      <td>{a.triggered_at.slice(0, 10)}</td>
                      <td>{a.rationale}</td>
                      <td>{a.status}</td>
                      <td className="toolbar">
                        {(["acknowledged", "escalated", "resolved", "false_positive"] as AlertStatus[])
                          .filter((s) => s !== a.status)
                          .map((s) => (
                            <button key={s} className="link-button" disabled={busy !== null}
                              onClick={() => act(a.alert_id, () => api.transitionAlert(a.scope_id, a.alert_id, { status: s }))}>
                              {s.replace("_", " ")}
                            </button>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
