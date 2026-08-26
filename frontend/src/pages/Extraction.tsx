import { useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ExtractionResultsTable, FinancialsResultsTable } from "../components/ExtractionResults";
import type {
  CompanyFinancialsRecord,
  DataPointSchema,
  ExtractionRecord,
  FieldDefinition,
  ReviewDecision,
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

          {mode === "custom" && (
            <ExtractionResultsTable
              results={extractionResults}
              runId={runId}
              expanded={expanded}
              onToggleExpanded={(companyId) => setExpanded(expanded === companyId ? null : companyId)}
              reviewDecisions={extractionReviewDecisions}
              reviewer={reviewer}
              onReviewDone={refreshResults}
            />
          )}

          {mode === "financials" && (
            <FinancialsResultsTable
              results={financialsResults}
              runId={runId}
              expanded={expanded}
              onToggleExpanded={(companyId) => setExpanded(expanded === companyId ? null : companyId)}
              reviewDecisions={financialsReviewDecisions}
              reviewer={reviewer}
              onReviewDone={refreshResults}
            />
          )}
        </section>
      )}
    </div>
  );
}
