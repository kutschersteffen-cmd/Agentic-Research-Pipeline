import { Fragment, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, GroundedBadge } from "../components/ConfidenceBadge";
import { ReviewControls } from "../components/ReviewControls";
import type {
  BusinessSegment,
  Citation,
  CompanyFinancialsRecord,
  DataPointSchema,
  ExtractionRecord,
  FieldDefinition,
  ReviewDecision,
  SpendSummary,
} from "../types";

const DEFAULT_CRITERIA =
  "Green capex: total green/sustainable capital expenditure in USD/EUR millions for the most recent fiscal " +
  "year, and as a % of total capex. Separately capture: (a) whether reported per the EU Taxonomy (eligible vs " +
  "aligned) vs. a self-defined/internal definition -- both if disclosed, clearly labeled; (b) breakdown by EU " +
  "Taxonomy environmental objective (climate mitigation, adaptation, water, circular economy, pollution, " +
  "biodiversity) where disclosed; (c) the company's own stated definition/methodology as a separate string " +
  "field with its own citation; (d) prior-year comparative figure; (e) forward-looking green capex " +
  "targets/guidance as a SEPARATE field from the actual reported figure -- extraction_instructions must " +
  "explicitly forbid conflating a target with an actual reported number.";

type Mode = "custom" | "financials";

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

function fmtAmount(value?: number | null): string {
  return value == null ? "—" : value.toLocaleString();
}

function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <ul>
      {citations.map((c, ci) => (
        <li key={ci}>
          [{c.doc_type}] "{c.quote}"
          {c.grounded && c.company_id && c.source_filename && (
            <>
              {" "}
              <a
                href={`${api.documentRawUrl(c.company_id, c.doc_type, c.source_filename)}${c.page ? `#page=${c.page}` : ""}`}
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
  );
}

function SegmentDetail({ segment }: { segment: BusinessSegment }) {
  return (
    <div className="field-detail">
      <strong>{segment.name}</strong> <GroundedBadge grounded={segment.grounded} /> <ConfidenceBadge value={segment.confidence} />
      {segment.description && <p>{segment.description}</p>}
      <CitationList citations={segment.description_citations} />
      <table className="data-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
            <th>Grounded</th>
          </tr>
        </thead>
        <tbody>
          {(["revenue", "income", "assets"] as const).map((metric) => (
            <tr key={metric}>
              <td style={{ textTransform: "capitalize" }}>{metric}</td>
              <td>
                {fmtAmount(segment[metric].value)}
                {segment[metric].raw_value_text && <span className="muted"> ({segment[metric].raw_value_text})</span>}
              </td>
              <td><GroundedBadge grounded={segment[metric].grounded} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {(["revenue", "income", "assets"] as const).map((metric) =>
        segment[metric].citations.length > 0 ? (
          <div key={metric}>
            <span className="muted" style={{ textTransform: "capitalize" }}>{metric} citations:</span>
            <CitationList citations={segment[metric].citations} />
          </div>
        ) : null
      )}
      {segment.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

function SpendDetail({ label, spend }: { label: string; spend: SpendSummary }) {
  return (
    <div className="field-detail">
      <strong>{label} total:</strong> {fmtAmount(spend.total.value)}
      {spend.total.raw_value_text && <span className="muted"> ({spend.total.raw_value_text})</span>}{" "}
      <GroundedBadge grounded={spend.grounded} /> <ConfidenceBadge value={spend.confidence} />
      <CitationList citations={spend.total.citations} />
      {spend.description && (
        <>
          <p>{spend.description}</p>
          <CitationList citations={spend.description_citations} />
        </>
      )}
      {spend.categories.length > 0 && (
        <>
          <p className="muted">Category breakdown:</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Grounded</th>
              </tr>
            </thead>
            <tbody>
              {spend.categories.map((c, ci) => (
                <tr key={ci}>
                  <td>{c.name}</td>
                  <td>{c.description ?? "—"}</td>
                  <td>{fmtAmount(c.amount.value)}</td>
                  <td><GroundedBadge grounded={c.grounded} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {spend.verifier_notes && <p className="muted">{spend.verifier_notes}</p>}
      {spend.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

export function Extraction({ pendingUniverse }: Props = {}) {
  const [mode, setMode] = useState<Mode>("custom");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [runId, setRunId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("");

  // Custom-schema mode only
  const [criteria, setCriteria] = useState(DEFAULT_CRITERIA);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [extractionResults, setExtractionResults] = useState<ExtractionRecord[]>([]);
  const [extractionReviewDecisions, setExtractionReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  // Financials mode only
  const [financialsResults, setFinancialsResults] = useState<CompanyFinancialsRecord[]>([]);
  const [financialsReviewDecisions, setFinancialsReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setRunId(null);
    setError(null);
    setExpanded(null);
  }

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
    if (!universePath) return;
    if (mode === "custom" && !schema) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "custom") {
        const res = await api.startExtractionRun({ datapoint_schema: schema!, universe_path: universePath });
        setRunId(res.run_id);
        setExtractionResults([]);
      } else {
        const res = await api.startFinancialsRun({ universe_path: universePath });
        setRunId(res.run_id);
        setFinancialsResults([]);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshResults() {
    if (!runId) return;
    if (mode === "custom") {
      const res = (await api.getExtractionResults(runId)) as { results: ExtractionRecord[] };
      setExtractionResults(res.results);
      const decisionsRes = (await api.getExtractionReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
      setExtractionReviewDecisions(decisionsRes.decisions);
    } else {
      const res = (await api.getFinancialsResults(runId)) as { results: CompanyFinancialsRecord[] };
      setFinancialsResults(res.results);
      const decisionsRes = (await api.getFinancialsReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
      setFinancialsReviewDecisions(decisionsRes.decisions);
    }
  }

  const universeStepNumber = mode === "custom" ? 3 : 1;
  const readyForUniverseStep = mode === "financials" || (mode === "custom" && schema != null);

  return (
    <div className="page">
      <h2>Extraction</h2>
      <p className="help-text">
        Extract data from company disclosures with an independent verifier pass and a hard programmatic grounding
        check on every citation. Either draft a custom schema for any research question (e.g. "green capex"), or run
        the built-in combined pass for business segments, CapEx, and R&amp;D.
      </p>

      <div className="view-toggle">
        <button className={mode === "custom" ? "active" : ""} onClick={() => switchMode("custom")}>
          Custom schema
        </button>
        <button className={mode === "financials" ? "active" : ""} onClick={() => switchMode("financials")}>
          Financials (segments / CapEx / R&amp;D)
        </button>
      </div>

      {mode === "custom" && (
        <section className="card">
          <h3>1. Describe what to extract</h3>
          <label className="field-label">Research request</label>
          <textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
          <button onClick={draft} disabled={busy}>
            Draft extraction schema
          </button>
          <p className="help-text">Or skip this and build a schema entirely by hand before starting a run.</p>
        </section>
      )}

      {mode === "custom" && schema && (
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

      {mode === "financials" && (
        <p className="help-text">
          Pulls disclosed business segments (name, description, revenue, operating income, assets), total CapEx, and
          total R&amp;D -- each with a grounded description and any disclosed category breakdown -- in a single
          combined pass per company: one document fetch, one extractor call, one independent verifier call, instead
          of three separate pipelines.
        </p>
      )}

      {readyForUniverseStep && (
        <section className="card">
          <h3>{universeStepNumber}. Choose the company universe</h3>
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
            {mode === "custom"
              ? `Extract across ${companyCount || "..."} companies`
              : `Extract financials across ${companyCount || "..."} companies`}
          </button>
        </section>
      )}

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>{universeStepNumber + 1}. Run progress</h3>
          <RunProgress runId={runId} runType={mode === "custom" ? "extraction" : "financials"} />
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

          {mode === "custom" && extractionResults.length > 0 && (
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
                {extractionResults.map((r) => (
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
                                <CitationList citations={f.citations} />
                                <ReviewControls
                                  runId={runId}
                                  itemKey={itemKey}
                                  current={extractionReviewDecisions[itemKey]}
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

          {mode === "financials" && financialsResults.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Segments</th>
                  <th>CapEx</th>
                  <th>R&amp;D</th>
                  <th>Confidence</th>
                  <th>Needs review</th>
                </tr>
              </thead>
              <tbody>
                {financialsResults.map((r) => (
                  <Fragment key={r.company_id}>
                    <tr className="clickable-row" onClick={() => setExpanded(expanded === r.company_id ? null : r.company_id)}>
                      <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                      <td>{r.segments.length === 0 ? "none found" : `${r.segments.length} segment(s)`}</td>
                      <td>{fmtAmount(r.capex.total.value)} {r.currency ?? ""}</td>
                      <td>{fmtAmount(r.rnd.total.value)} {r.currency ?? ""}</td>
                      <td><ConfidenceBadge value={r.overall_confidence} /></td>
                      <td>{r.needs_review ? "⚑" : ""}</td>
                    </tr>
                    {expanded === r.company_id && (
                      <tr>
                        <td colSpan={6} className="detail-cell">
                          <h4>Business Segments</h4>
                          {r.segments.length === 0 && <p className="muted">No segment reporting evidence found.</p>}
                          {r.segments.map((s, si) => (
                            <SegmentDetail key={si} segment={s} />
                          ))}
                          {r.segments_verifier_notes && <p className="muted">{r.segments_verifier_notes}</p>}

                          <h4>CapEx</h4>
                          <SpendDetail label="CapEx" spend={r.capex} />

                          <h4>R&amp;D</h4>
                          <SpendDetail label="R&D" spend={r.rnd} />

                          <ReviewControls
                            runId={runId}
                            itemKey={r.company_id}
                            current={financialsReviewDecisions[r.company_id]}
                            reviewer={reviewer}
                            onDone={refreshResults}
                            submitFn={api.submitFinancialsReview}
                            historyFn={api.getFinancialsReviewHistory}
                          />
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
