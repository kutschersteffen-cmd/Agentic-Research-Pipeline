import { Fragment, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, VerdictBadge, GroundedBadge } from "../components/ConfidenceBadge";
import type { ActivityDefinition, CompanyMatch, ThemeDefinition } from "../types";

export function ThemeBuilder() {
  const [name, setName] = useState("Electrification");
  const [description, setDescription] = useState(
    "The shift of energy generation, transport, industry, and buildings from fossil fuels to electricity."
  );
  const [theme, setTheme] = useState<ThemeDefinition | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<CompanyMatch[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [useSampleIcio, setUseSampleIcio] = useState(false);

  async function decompose() {
    setBusy(true);
    setError(null);
    try {
      const drafted = (await api.decomposeTheme(name, description)) as ThemeDefinition;
      setTheme(drafted);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function updateActivity(idx: number, patch: Partial<ActivityDefinition>) {
    if (!theme) return;
    const activities = theme.activities.map((a, i) => (i === idx ? { ...a, ...patch } : a));
    setTheme({ ...theme, activities });
  }

  function removeActivity(idx: number) {
    if (!theme) return;
    setTheme({ ...theme, activities: theme.activities.filter((_, i) => i !== idx) });
  }

  async function startRun() {
    if (!theme || !universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startThemeRun({ theme, universe_path: universePath, use_sample_icio: useSampleIcio });
      setRunId(res.run_id);
      setResults([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getThemeResults(runId)) as { results: CompanyMatch[] };
    setResults(res.results);
  }

  return (
    <div className="page">
      <h2>Thematic Investment Universe Builder</h2>
      <p className="help-text">
        Decompose a macro theme into checkable activities, then screen a company universe against each one using an
        Advocate / Opposing / Adjudicator agent pipeline with programmatically grounded citations.
      </p>

      <section className="card">
        <h3>1. Define the theme</h3>
        <label className="field-label">Macro theme name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <label className="field-label">Description</label>
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        <button onClick={decompose} disabled={busy}>
          Decompose into activities
        </button>
      </section>

      {theme && (
        <section className="card">
          <h3>2. Review &amp; edit activities</h3>
          {theme.activities.map((a, idx) => (
            <div className="activity-editor" key={a.activity_id}>
              <input value={a.name} onChange={(e) => updateActivity(idx, { name: e.target.value })} />
              <label className="field-label">In scope</label>
              <textarea
                rows={2}
                value={a.in_scope_description}
                onChange={(e) => updateActivity(idx, { in_scope_description: e.target.value })}
              />
              <label className="field-label">Out of scope</label>
              <textarea
                rows={2}
                value={a.out_of_scope_description}
                onChange={(e) => updateActivity(idx, { out_of_scope_description: e.target.value })}
              />
              <label className="field-label">Seed keywords (comma-separated)</label>
              <input
                value={a.seed_keywords.join(", ")}
                onChange={(e) => updateActivity(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              />
              <button className="link-button" onClick={() => removeActivity(idx)}>
                Remove activity
              </button>
            </div>
          ))}
        </section>
      )}

      {theme && (
        <section className="card">
          <h3>3. Choose the company universe</h3>
          <UniversePicker
            onResolved={(path, count) => {
              setUniversePath(path);
              setCompanyCount(count);
            }}
          />
          <label className="checkbox-label">
            <input type="checkbox" checked={useSampleIcio} onChange={(e) => setUseSampleIcio(e.target.checked)} />
            Enable indirect (input-output) exposure tier using the bundled sample dataset
          </label>
          <p className="help-text">
            Structural supply-chain exposure via OECD ICIO input-output propagation -- catches companies with no
            direct textual evidence but real economic linkage to the theme's core sectors. The sample dataset is
            illustrative only; for a real run, configure ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH on the
            backend instead and leave this off.
          </p>
          <button onClick={startRun} disabled={busy || !universePath}>
            Run screen against {companyCount || "..."} companies
          </button>
        </section>
      )}

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>4. Run progress</h3>
          <RunProgress runId={runId} />
          <div className="toolbar">
            <button onClick={refreshResults}>Refresh results</button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
          </div>
          {results.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Activity</th>
                  <th>Verdict</th>
                  <th>Exposure</th>
                  <th>Confidence</th>
                  <th>Structural</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {results.map((m) => {
                  const key = `${m.company_id}:${m.activity_id}`;
                  const io = m.indirect_exposure;
                  return (
                    <Fragment key={key}>
                      <tr onClick={() => setExpanded(expanded === key ? null : key)} className="clickable-row">
                        <td>{m.name} {m.ticker && <span className="muted">({m.ticker})</span>}</td>
                        <td>{m.activity_name}</td>
                        <td><VerdictBadge verdict={m.verdict} /></td>
                        <td>{m.exposure_estimate}</td>
                        <td><ConfidenceBadge value={m.confidence} /></td>
                        <td>
                          {io ? (
                            <span className="muted">
                              &uarr;{Math.round(io.upstream_exposure * 100)}% &darr;{Math.round(io.downstream_exposure * 100)}%
                            </span>
                          ) : (
                            ""
                          )}
                        </td>
                        <td>{m.flagged_for_review ? "⚑" : ""}</td>
                      </tr>
                      {expanded === key && (
                        <tr>
                          <td colSpan={7} className="detail-cell">
                            <p><strong>Rationale:</strong> {m.adjudicator_rationale}</p>
                            <p><strong>Citations:</strong></p>
                            <ul>
                              {m.citations.map((c, ci) => (
                                <li key={ci}>
                                  <GroundedBadge grounded={c.grounded} /> [{c.doc_type}] "{c.quote}"
                                </li>
                              ))}
                            </ul>
                            {io && (
                              <>
                                <p>
                                  <strong>Indirect (structural) exposure:</strong> {io.isic_label ?? io.isic_code}{" "}
                                  {io.core_sector && <span className="badge badge-high">core sector</span>}
                                </p>
                                <ul>
                                  <li>Upstream exposure: {(io.upstream_exposure * 100).toFixed(1)}% -- share of this industry's total input requirement traceable to the activity's core sectors</li>
                                  <li>Downstream exposure: {(io.downstream_exposure * 100).toFixed(1)}% -- share of this industry's output propagation landing in the activity's core sectors</li>
                                  <li className="muted">Computed from {io.icio_edition}</li>
                                </ul>
                              </>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
