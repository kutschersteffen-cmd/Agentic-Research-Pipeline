import { useEffect, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { ConfidenceBadge, VerdictBadge, YesNoBadge } from "../components/ConfidenceBadge";
import type {
  CalibrationScheduleConfig,
  DriftFlag,
  RunManifest,
  Taxonomy,
  TaxonomyResearcherScheduleConfig,
  TaxonomyResearchFinding,
} from "../types";
import { BACKGROUND_AGENT_TABS as SUB_TABS } from "../nav";
import { useSubTab } from "../router";
import { Button, Field, PageHeader, StateBlock, TabPanel, Tabs } from "../ui";

export function BackgroundAgents() {
  const [sub, setSub] = useSubTab(SUB_TABS, "taxonomyResearcher");

  return (
    <div className="page">
      <PageHeader
        title="Background Agents"
        description={
          <>
            Two standing agents run continuously rather than on demand. Both only ever propose or flag --
            neither one auto-applies a change: a Taxonomy Researcher proposal still needs a human to ratify it,
            and a Calibration Agent drift flag still needs a human to decide whether to re-run classification.
          </>
        }
      />
      <Tabs
        id="backgroundAgents"
        tabs={SUB_TABS}
        active={sub}
        onChange={(id) => setSub(id as typeof sub)}
        label="Background agent"
      />
      <TabPanel id="backgroundAgents" active={sub}>
        {sub === "taxonomyResearcher" && <TaxonomyResearcherPanel />}
        {sub === "calibration" && <CalibrationPanel />}
      </TabPanel>
    </div>
  );
}

function TaxonomyResearcherPanel() {
  const [schedule, setSchedule] = useState<TaxonomyResearcherScheduleConfig | null>(null);
  const [taxonomies, setTaxonomies] = useState<Taxonomy[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [scopeAll, setScopeAll] = useState(true);
  const [pastRuns, setPastRuns] = useState<RunManifest[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<TaxonomyResearchFinding[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    const s = (await api.getTaxonomyResearcherSchedule()) as TaxonomyResearcherScheduleConfig;
    setSchedule(s);
    setScopeAll(s.taxonomy_ids == null);
    setSelectedIds(s.taxonomy_ids ?? []);
    const t = (await api.listTaxonomies()) as { taxonomies: Taxonomy[] };
    setTaxonomies(t.taxonomies);
    const r = (await api.listRuns("taxonomy_research")) as { runs: RunManifest[] };
    setPastRuns(r.runs);
  }

  async function saveSchedule() {
    if (!schedule) return;
    setBusy(true);
    setError(null);
    try {
      const saved = (await api.updateTaxonomyResearcherSchedule({
        ...schedule,
        taxonomy_ids: scopeAll ? null : selectedIds,
      })) as TaxonomyResearcherScheduleConfig;
      setSchedule(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    setBusy(true);
    setError(null);
    setResults([]);
    try {
      const res = await api.startTaxonomyResearcherRun({ taxonomy_ids: scopeAll ? null : selectedIds });
      setRunId(res.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getTaxonomyResearcherResults(runId)) as { results: TaxonomyResearchFinding[] };
    setResults(res.results);
    const r = (await api.listRuns("taxonomy_research")) as { runs: RunManifest[] };
    setPastRuns(r.runs);
  }

  function toggleId(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <div>
      <p className="help-text">
        Periodically re-derives every ratified taxonomy from current authority sources and proposes a new
        DRAFT version when genuinely new activities surface. Never ratifies -- review any proposal below in
        the Taxonomy Library before it's used by a run.
      </p>
      {error && <StateBlock kind="error" message={error} />}

      {schedule && (
        <section className="card">
          <h3>Automatic schedule</h3>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={schedule.enabled}
              onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
            />
            Enabled
          </label>
          <Field label="Interval (hours)">
            <input
              type="number"
              min={1}
              value={schedule.interval_hours}
              onChange={(e) => setSchedule({ ...schedule, interval_hours: Number(e.target.value) })}
            />
          </Field>
          <label className="checkbox-label">
            <input type="checkbox" checked={scopeAll} onChange={(e) => setScopeAll(e.target.checked)} />
            Scan all ratified taxonomies
          </label>
          {!scopeAll && (
            <div className="inline-fields">
              {taxonomies
                .filter((t) => t.status === "ratified")
                .map((t) => (
                  <label className="checkbox-label" key={t.taxonomy_id}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(t.taxonomy_id)}
                      onChange={() => toggleId(t.taxonomy_id)}
                    />
                    {t.name}
                  </label>
                ))}
              {taxonomies.filter((t) => t.status === "ratified").length === 0 && (
                <StateBlock kind="empty" message="No ratified taxonomies yet." />
              )}
            </div>
          )}
          <Button onClick={saveSchedule} disabled={busy}>
            Save schedule
          </Button>
          {schedule.last_run_id && <p className="muted">Last scheduled run: {schedule.last_run_id}</p>}
        </section>
      )}

      <section className="card">
        <h3>Run now</h3>
        <Button onClick={runNow} disabled={busy}>
          Scan now
        </Button>
        {runId && (
          <>
            <RunProgress runId={runId} runType="taxonomy_research" />
            <div className="toolbar">
              <Button onClick={refreshResults}>Refresh results</Button>
            </div>
          </>
        )}
        {results.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Taxonomy</th>
                  <th>Proposed</th>
                  <th>New version</th>
                  <th>Added activities</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {results.map((f, i) => (
                  <tr key={`${f.taxonomy_id}-${i}`}>
                    <td>{f.taxonomy_name}</td>
                    <td><YesNoBadge verdict={f.proposed ? "YES" : "NO"} /></td>
                    <td>{f.new_version ?? "--"}</td>
                    <td>{f.added_activity_names.join(", ") || "--"}</td>
                    <td>{f.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h3>Past runs</h3>
        {pastRuns.length === 0 && <StateBlock kind="empty" message="No taxonomy research runs yet." />}
        {pastRuns.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Scanned</th>
                  <th>Proposed</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {pastRuns.map((r) => (
                  <tr key={r.run_id}>
                    <td>{r.run_id}</td>
                    <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                    <td>{r.completed_count}/{r.company_count}</td>
                    <td>{r.review_count}</td>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function CalibrationPanel() {
  const [schedule, setSchedule] = useState<CalibrationScheduleConfig | null>(null);
  const [pastRuns, setPastRuns] = useState<RunManifest[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<DriftFlag[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    const s = (await api.getCalibrationSchedule()) as CalibrationScheduleConfig;
    setSchedule(s);
    const r = (await api.listRuns("calibration")) as { runs: RunManifest[] };
    setPastRuns(r.runs);
  }

  async function saveSchedule() {
    if (!schedule) return;
    setBusy(true);
    setError(null);
    try {
      const saved = (await api.updateCalibrationSchedule(schedule)) as CalibrationScheduleConfig;
      setSchedule(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    setBusy(true);
    setError(null);
    setResults([]);
    try {
      const res = await api.startCalibrationRun();
      setRunId(res.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getCalibrationResults(runId)) as { results: DriftFlag[] };
    setResults(res.results);
    const r = (await api.listRuns("calibration")) as { runs: RunManifest[] };
    setPastRuns(r.runs);
  }

  return (
    <div>
      <p className="help-text">
        Scans every completed thematic-universe run and flags a verdict as possibly stale when a company's
        currently-fetchable documents include one fetched after that verdict was generated. A flag is not a
        claim the verdict is wrong -- it never re-runs classification or edits a match itself.
      </p>
      {error && <StateBlock kind="error" message={error} />}

      {schedule && (
        <section className="card">
          <h3>Automatic schedule</h3>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={schedule.enabled}
              onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
            />
            Enabled
          </label>
          <Field label="Interval (hours)">
            <input
              type="number"
              min={1}
              value={schedule.interval_hours}
              onChange={(e) => setSchedule({ ...schedule, interval_hours: Number(e.target.value) })}
            />
          </Field>
          <Button onClick={saveSchedule} disabled={busy}>
            Save schedule
          </Button>
          {schedule.last_run_id && <p className="muted">Last scheduled run: {schedule.last_run_id}</p>}
        </section>
      )}

      <section className="card">
        <h3>Run now</h3>
        <Button onClick={runNow} disabled={busy}>
          Check now
        </Button>
        {runId && (
          <>
            <RunProgress runId={runId} runType="calibration" />
            <div className="toolbar">
              <Button onClick={refreshResults}>Refresh results</Button>
            </div>
          </>
        )}
        {results.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source run</th>
                  <th>Company</th>
                  <th>Activity</th>
                  <th>Old verdict</th>
                  <th>Old confidence</th>
                  <th>Old generated at</th>
                  <th>Newest document at</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {results.map((f, i) => (
                  <tr key={`${f.company_id}-${f.activity_id}-${i}`}>
                    <td>{f.source_run_id}</td>
                    <td>{f.company_id}</td>
                    <td>{f.activity_id}</td>
                    <td><VerdictBadge verdict={f.old_verdict} /></td>
                    <td><ConfidenceBadge value={f.old_confidence} /></td>
                    <td>{new Date(f.old_generated_at).toLocaleString()}</td>
                    <td>{new Date(f.newest_document_at).toLocaleString()}</td>
                    <td>{f.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h3>Past runs</h3>
        {pastRuns.length === 0 && <StateBlock kind="empty" message="No calibration runs yet." />}
        {pastRuns.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Scanned</th>
                  <th>Flags</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {pastRuns.map((r) => (
                  <tr key={r.run_id}>
                    <td>{r.run_id}</td>
                    <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                    <td>{r.completed_count}/{r.company_count}</td>
                    <td>{r.review_count}</td>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
