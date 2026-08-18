import { useEffect, useState } from "react";
import { EngagementIssuePanel } from "../components/EngagementIssuePanel";
import { api } from "../api/client";
import type { EngagementIssue, EngagementRecord, IssueSeverity, TriggerEvent } from "../types";

const DEFAULT_SIGNALS = `[
  { "company_id": "AAPL", "theme": "executive_compensation", "severity": "high", "detail": "Say-on-pay support fell below 70% at peers." }
]`;

export function EngagementDashboard() {
  const [records, setRecords] = useState<EngagementRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState<{ companyId: string; issueId: string } | null>(null);

  const [newCompanyId, setNewCompanyId] = useState("");
  const [newCompanyName, setNewCompanyName] = useState("");
  const [newCompanySector, setNewCompanySector] = useState("");
  const [newIssueTheme, setNewIssueTheme] = useState("");
  const [newIssueSeverity, setNewIssueSeverity] = useState<IssueSeverity>("medium");

  const [signalsJson, setSignalsJson] = useState(DEFAULT_SIGNALS);
  const [companiesJson, setCompaniesJson] = useState(`[ { "company_id": "AAPL", "name": "Apple Inc." } ]`);
  const [triggerResult, setTriggerResult] = useState<TriggerEvent[] | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const res = (await api.listEngagementRecords()) as { records: EngagementRecord[] };
      setRecords(res.records);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function applyUpdatedRecord(updated: EngagementRecord) {
    setRecords((prev) => {
      const exists = prev.some((r) => r.company_id === updated.company_id);
      return exists ? prev.map((r) => (r.company_id === updated.company_id ? updated : r)) : [...prev, updated];
    });
  }

  async function createRecordAndIssue() {
    if (!newCompanyId.trim() || !newCompanyName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createEngagementRecord({ company_id: newCompanyId, name: newCompanyName, sector: newCompanySector || null });
      if (newIssueTheme.trim()) {
        await api.openEngagementIssue(newCompanyId, newCompanyName, { theme: newIssueTheme, severity: newIssueSeverity });
      }
      setNewCompanyId("");
      setNewCompanyName("");
      setNewCompanySector("");
      setNewIssueTheme("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runTriggerScan() {
    setBusy(true);
    setError(null);
    setTriggerResult(null);
    try {
      const companies = JSON.parse(companiesJson);
      const signals = JSON.parse(signalsJson);
      const res = await api.triggerScan({ companies, signals });
      setTriggerResult(res.events);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const selectedRecord = selected ? records.find((r) => r.company_id === selected.companyId) ?? null : null;
  const selectedIssue: EngagementIssue | null = selectedRecord && selected ? selectedRecord.issues.find((i) => i.issue_id === selected.issueId) ?? null : null;

  return (
    <div className="page">
      <h2>Engagement</h2>
      <p className="help-text">
        The engagement record store: one entry per company, with per-issue milestone progression, an escalation
        ladder, correspondence, and commitments. Every send/decide checkpoint is a human action -- nothing here
        contacts a company or moves an escalation stage on its own.
      </p>
      {error && <p className="error-text">{error}</p>}

      <section className="card">
        <h3>Open a new issue</h3>
        <div className="inline-fields">
          <input placeholder="Company ID (e.g. AAPL)" value={newCompanyId} onChange={(e) => setNewCompanyId(e.target.value)} />
          <input placeholder="Company name" value={newCompanyName} onChange={(e) => setNewCompanyName(e.target.value)} />
          <input placeholder="Sector (optional)" value={newCompanySector} onChange={(e) => setNewCompanySector(e.target.value)} />
        </div>
        <div className="inline-fields">
          <input placeholder="Issue theme (e.g. executive_compensation)" value={newIssueTheme} onChange={(e) => setNewIssueTheme(e.target.value)} />
          <select value={newIssueSeverity} onChange={(e) => setNewIssueSeverity(e.target.value as IssueSeverity)}>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
          <button onClick={createRecordAndIssue} disabled={busy || !newCompanyId.trim() || !newCompanyName.trim()}>
            Create
          </button>
        </div>
      </section>

      <section className="card">
        <h3>Trigger &amp; detection scan</h3>
        <p className="help-text">
          Screens the given companies against caller-supplied controversy signals (no live data-provider feed is
          wired up -- see the architecture doc) and opens a new issue for every signal without an already-open issue
          on the same theme, plus an SLA sweep flagging stalled issues.
        </p>
        <label className="field-label">Companies (JSON array)</label>
        <textarea rows={2} value={companiesJson} onChange={(e) => setCompaniesJson(e.target.value)} />
        <label className="field-label">Controversy signals (JSON array)</label>
        <textarea rows={4} value={signalsJson} onChange={(e) => setSignalsJson(e.target.value)} />
        <button onClick={runTriggerScan} disabled={busy}>
          Run scan
        </button>
        {triggerResult && (
          <div className="review-item">
            <p className="muted">{triggerResult.length} event(s)</p>
            <ul className="timeline">
              {triggerResult.map((e) => (
                <li key={e.trigger_id}>
                  [{e.source}] {e.company_id} &middot; {e.theme} ({e.severity}) {e.raised_issue_id ? `-- issue ${e.raised_issue_id}` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="card">
        <div className="section-heading">
          <h3>Records</h3>
          <button className="link-button" onClick={load}>
            Refresh
          </button>
        </div>
        {records.length === 0 && <p className="muted">No engagement records yet.</p>}
        {records.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Sector</th>
                <th>Issues</th>
                <th>Open</th>
                <th>Escalated</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => {
                const openCount = r.issues.filter((i) => i.status === "open" || i.status === "stalled").length;
                const escalatedCount = r.issues.filter((i) => i.escalation_stage !== "private_engagement").length;
                return (
                  <tr key={r.company_id}>
                    <td>
                      {r.name} <span className="muted">({r.company_id})</span>
                    </td>
                    <td>{r.sector ?? "--"}</td>
                    <td>{r.issues.length}</td>
                    <td>{openCount}</td>
                    <td>{escalatedCount}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {records.map(
        (r) =>
          r.issues.length > 0 && (
            <section className="card" key={r.company_id}>
              <h3>
                {r.name} <span className="muted">({r.company_id})</span> issues
              </h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Theme</th>
                    <th>Status</th>
                    <th>Milestone</th>
                    <th>Escalation</th>
                    <th>Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {r.issues.map((issue) => (
                    <tr
                      key={issue.issue_id}
                      className="clickable-row issue-row"
                      onClick={() => setSelected({ companyId: r.company_id, issueId: issue.issue_id })}
                    >
                      <td>{issue.theme}</td>
                      <td>{issue.status}</td>
                      <td>{issue.milestone_stage.replace(/_/g, " ")}</td>
                      <td>{issue.escalation_stage.replace(/_/g, " ")}</td>
                      <td>{issue.severity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ),
      )}

      {selectedRecord && selectedIssue && (
        <EngagementIssuePanel
          record={selectedRecord}
          issue={selectedIssue}
          onUpdated={applyUpdatedRecord}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
