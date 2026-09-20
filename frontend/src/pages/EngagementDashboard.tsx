import { useEffect, useState } from "react";
import { EngagementIssuePanel } from "../components/EngagementIssuePanel";
import { api } from "../api/client";
import type { EngagementIssue, EngagementRecord, IssueSeverity, TriggerEvent } from "../types";
import { Button, PageHeader, StateBlock } from "../ui";

interface ScanCompanyRow {
  company_id: string;
  name: string;
}
interface ScanSignalRow {
  company_id: string;
  theme: string;
  severity: IssueSeverity;
  detail: string;
}

const DEFAULT_SCAN_COMPANIES: ScanCompanyRow[] = [{ company_id: "AAPL", name: "Apple Inc." }];
const DEFAULT_SCAN_SIGNALS: ScanSignalRow[] = [
  { company_id: "AAPL", theme: "executive_compensation", severity: "high", detail: "Say-on-pay support fell below 70% at peers." },
];

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

  const [companyRows, setCompanyRows] = useState<ScanCompanyRow[]>(DEFAULT_SCAN_COMPANIES);
  const [signalRows, setSignalRows] = useState<ScanSignalRow[]>(DEFAULT_SCAN_SIGNALS);
  const [triggerResult, setTriggerResult] = useState<TriggerEvent[] | null>(null);

  function updateCompanyRow(idx: number, patch: Partial<ScanCompanyRow>) {
    setCompanyRows((prev) => prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)));
  }
  function updateSignalRow(idx: number, patch: Partial<ScanSignalRow>) {
    setSignalRows((prev) => prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)));
  }

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
    const companies = companyRows.filter((c) => c.company_id.trim() && c.name.trim());
    const signals = signalRows.filter((s) => s.company_id.trim() && s.theme.trim());
    if (companies.length === 0 || signals.length === 0) {
      setError("Add at least one company and one signal with a company ID/name and theme filled in.");
      return;
    }
    setBusy(true);
    setError(null);
    setTriggerResult(null);
    try {
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
      <PageHeader
        title="Engagement"
        description={
          <>
            The engagement record store: one entry per company, with per-issue milestone progression, an escalation
            ladder, correspondence, and commitments. Every send/decide checkpoint is a human action -- nothing here
            contacts a company or moves an escalation stage on its own.
          </>
        }
      />
      {error && <StateBlock kind="error" message={error} />}

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
          <Button onClick={createRecordAndIssue} disabled={busy || !newCompanyId.trim() || !newCompanyName.trim()}>
            Create
          </Button>
        </div>
      </section>

      <section className="card">
        <h3>Trigger &amp; detection scan</h3>
        <p className="help-text">
          Screens the given companies against caller-supplied controversy signals (no live data-provider feed is
          wired up -- see the architecture doc) and opens a new issue for every signal without an already-open issue
          on the same theme, plus an SLA sweep flagging stalled issues.
        </p>
        <span className="field-label">Companies to screen</span>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Company ID</th>
                <th>Name</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {companyRows.map((row, idx) => (
                <tr key={idx}>
                  <td>
                    <input placeholder="e.g. AAPL" value={row.company_id} onChange={(e) => updateCompanyRow(idx, { company_id: e.target.value })} />
                  </td>
                  <td>
                    <input placeholder="e.g. Apple Inc." value={row.name} onChange={(e) => updateCompanyRow(idx, { name: e.target.value })} />
                  </td>
                  <td>
                    <Button variant="ghost" onClick={() => setCompanyRows((prev) => prev.filter((_, i) => i !== idx))}>
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button variant="ghost" onClick={() => setCompanyRows((prev) => [...prev, { company_id: "", name: "" }])}>
          + Add company
        </Button>

        <span className="field-label mt-4">
          Controversy signals
        </span>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Company ID</th>
                <th>Theme</th>
                <th>Severity</th>
                <th>Detail</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {signalRows.map((row, idx) => (
                <tr key={idx}>
                  <td>
                    <input placeholder="e.g. AAPL" value={row.company_id} onChange={(e) => updateSignalRow(idx, { company_id: e.target.value })} />
                  </td>
                  <td>
                    <input
                      placeholder="e.g. executive_compensation"
                      value={row.theme}
                      onChange={(e) => updateSignalRow(idx, { theme: e.target.value })}
                    />
                  </td>
                  <td>
                    <select value={row.severity} onChange={(e) => updateSignalRow(idx, { severity: e.target.value as IssueSeverity })}>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </td>
                  <td>
                    <input placeholder="What happened" value={row.detail} onChange={(e) => updateSignalRow(idx, { detail: e.target.value })} />
                  </td>
                  <td>
                    <Button variant="ghost" onClick={() => setSignalRows((prev) => prev.filter((_, i) => i !== idx))}>
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="toolbar">
          <Button variant="ghost" onClick={() => setSignalRows((prev) => [...prev, { company_id: "", theme: "", severity: "medium", detail: "" }])}>
            + Add signal
          </Button>
        </div>
        <Button onClick={runTriggerScan} disabled={busy}>
          Run scan
        </Button>
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
          <Button variant="ghost" onClick={load}>
            Refresh
          </Button>
        </div>
        {records.length === 0 && <StateBlock kind="empty" message="No engagement records yet." />}
        {records.length > 0 && (
          <div className="table-wrap">
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
          </div>
        )}
      </section>

      {records.map(
        (r) =>
          r.issues.length > 0 && (
            <section className="card" key={r.company_id}>
              <h3>
                {r.name} <span className="muted">({r.company_id})</span> issues
              </h3>
              <div className="table-wrap">
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
              </div>
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
