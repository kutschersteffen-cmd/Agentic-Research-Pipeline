import { Fragment, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, GroundedBadge } from "../components/ConfidenceBadge";
import { ReviewControls } from "../components/ReviewControls";
import type { DataPointSchema, ExtractionRecord, FieldDefinition, ReviewDecision } from "../types";

const DEFAULT_CRITERIA =
  "Green capex: total green/sustainable capital expenditure in USD/EUR millions for the most recent fiscal " +
  "year, and as a % of total capex. Separately capture: (a) whether reported per the EU Taxonomy (eligible vs " +
  "aligned) vs. a self-defined/internal definition -- both if disclosed, clearly labeled; (b) breakdown by EU " +
  "Taxonomy environmental objective (climate mitigation, adaptation, water, circular economy, pollution, " +
  "biodiversity) where disclosed; (c) the company's own stated definition/methodology as a separate string " +
  "field with its own citation; (d) prior-year comparative figure; (e) forward-looking green capex " +
  "targets/guidance as a SEPARATE field from the actual reported figure -- extraction_instructions must " +
  "explicitly forbid conflating a target with an actual reported number.";

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

export function ExtractionBuilder({ pendingUniverse }: Props = {}) {
  const [criteria, setCriteria] = useState(DEFAULT_CRITERIA);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<ExtractionRecord[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [reviewer, setReviewer] = useState("");

  async function draft() {
    setBusy(true);
    setError(null);
    try {
      setSchema((await api.draftSchema(criteria)) as DataPointSchema);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function updateField(idx: number, patch: Partial<FieldDefinition>) {
    if (!schema) return;
    const fields = schema.fields.map((f, i) => (i === idx ? { ...f, ...patch } : f));
    setSchema({ ...schema, fields });
  }

  async function startRun() {
    if (!schema || !universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startExtractionRun({ datapoint_schema: schema, universe_path: universePath });
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
    const res = (await api.getExtractionResults(runId)) as { results: ExtractionRecord[] };
    setResults(res.results);
    const decisionsRes = (await api.getExtractionReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
    setReviewDecisions(decisionsRes.decisions);
  }

  return (
    <div className="page">
      <h2>Data-Point Extraction</h2>
      <p className="help-text">
        Extract specific, schema-defined data points (e.g. "green capex", forward-looking business outlook) from
        sustainability reports, annual reports, and earnings call transcripts, with an independent verifier pass and
        a hard programmatic grounding check on every citation.
      </p>

      <section className="card">
        <h3>1. Describe what to extract</h3>
        <label className="field-label">Research request</label>
        <textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
        <button onClick={draft} disabled={busy}>
          Draft extraction schema
        </button>
        <p className="help-text">Or skip this and build a schema entirely by hand before starting a run.</p>
      </section>

      {schema && (
        <section className="card">
          <h3>2. Review &amp; edit fields</h3>
          {schema.fields.map((f, idx) => (
            <div className="activity-editor" key={f.field_id}>
              <input value={f.name} onChange={(e) => updateField(idx, { name: e.target.value })} />
              <label className="field-label">Description</label>
              <textarea rows={2} value={f.description} onChange={(e) => updateField(idx, { description: e.target.value })} />
              <label className="field-label">Extraction instructions</label>
              <textarea
                rows={3}
                value={f.extraction_instructions}
                onChange={(e) => updateField(idx, { extraction_instructions: e.target.value })}
              />
              <label className="field-label">Data type / unit</label>
              <div className="inline-fields">
                <span>{f.data_type}</span>
                <input
                  placeholder="unit"
                  value={f.unit ?? ""}
                  onChange={(e) => updateField(idx, { unit: e.target.value })}
                />
              </div>
              <label className="field-label">Seed keywords (comma-separated)</label>
              <input
                value={f.seed_keywords.join(", ")}
                onChange={(e) => updateField(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              />
            </div>
          ))}
        </section>
      )}

      {schema && (
        <section className="card">
          <h3>3. Choose the company universe</h3>
          {pendingUniverse && universePath === pendingUniverse.path && (
            <p className="status-text">
              Using {pendingUniverse.count} companies sent from a Thematic Universe screen. Upload a different
              universe below to replace it.
            </p>
          )}
          <UniversePicker
            onResolved={(path, count) => {
              setUniversePath(path);
              setCompanyCount(count);
            }}
          />
          <button onClick={startRun} disabled={busy || !universePath}>
            Extract across {companyCount || "..."} companies
          </button>
        </section>
      )}

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>4. Run progress</h3>
          <RunProgress runId={runId} runType="extraction" />
          <div className="toolbar">
            <button onClick={refreshResults}>Refresh results</button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
            <label className="field-label" style={{ marginLeft: "auto" }}>
              Reviewing as
            </label>
            <input
              placeholder="your name"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              style={{ maxWidth: 160 }}
            />
          </div>
          {results.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Fields</th>
                  <th>Overall confidence</th>
                  <th>Needs review</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <Fragment key={r.company_id}>
                    <tr className="clickable-row" onClick={() => setExpanded(expanded === r.company_id ? null : r.company_id)}>
                      <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                      <td>{r.fields.map((f) => `${f.field_name}=${f.value ?? "—"}`).join(", ")}</td>
                      <td><ConfidenceBadge value={r.overall_confidence} /></td>
                      <td>{r.needs_review ? "⚑" : ""}</td>
                    </tr>
                    {expanded === r.company_id && (
                      <tr>
                        <td colSpan={4} className="detail-cell">
                          {r.fields.map((f) => {
                            const itemKey = `${r.company_id}:${f.field_id}`;
                            return (
                              <div key={f.field_id} className="field-detail">
                                <strong>{f.field_name}:</strong> {String(f.value ?? "not disclosed")}{" "}
                                <ConfidenceBadge value={f.confidence} /> <GroundedBadge grounded={f.grounded} />
                                {f.verifier_notes && <p className="muted">{f.verifier_notes}</p>}
                                <ul>
                                  {f.citations.map((c, ci) => (
                                    <li key={ci}>
                                      [{c.doc_type}] "{c.quote}"
                                      {c.grounded && c.company_id && c.source_filename && (
                                        <>
                                          {" "}
                                          <a
                                            href={`${api.documentRawUrl(c.company_id, c.doc_type, c.source_filename)}${
                                              c.page ? `#page=${c.page}` : ""
                                            }`}
                                            target="_blank"
                                            rel="noreferrer"
                                          >
                                            view source{c.page ? ` (p. ${c.page})` : c.sheet ? ` (${c.sheet})` : ""}
                                          </a>
                                        </>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                                <ReviewControls
                                  runId={runId}
                                  itemKey={itemKey}
                                  current={reviewDecisions[itemKey]}
                                  reviewer={reviewer}
                                  onDone={refreshResults}
                                />
                              </div>
                            );
                          })}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
