import { useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ExtractionResultsTable, FinancialsResultsTable } from "../components/ExtractionResults";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { BarChart } from "../components/BarChart";
import type { CompanyFinancialsRecord, DataPointSchema, ExtractionRecord, FieldDefinition, ReviewDecision } from "../types";
import { Button, Field, PageHeader, StateBlock, StepCard, Steps } from "../ui";
import type { Step } from "../ui";

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

/** Batch-level CapEx/R&D comparison across every company in the run --
 * companies with no disclosed value for the chosen metric are left out of
 * the chart (never charted as 0, which would misreport "no disclosure" as
 * "zero spend") and counted separately instead. Figures are charted exactly
 * as reported per company, in whatever currency each company discloses in
 * -- same as the table below -- rather than fabricating an FX conversion. */
function BatchSpendChart({ results }: { results: CompanyFinancialsRecord[] }) {
  const [metric, setMetric] = useState<"capex" | "rnd">("capex");
  const withValue = results.filter((r) => r[metric].total.value != null);
  const currencies = new Set(withValue.map((r) => r.currency ?? "unknown"));
  const chartData = [...withValue]
    .sort((a, b) => (b[metric].total.value ?? 0) - (a[metric].total.value ?? 0))
    .map((r) => ({ label: r.name, value: r[metric].total.value ?? 0 }));

  return (
    <section className="card">
      <h2>Batch overview ({results.length} companies)</h2>
      <div className="view-toggle">
        <button className={metric === "capex" ? "active" : ""} onClick={() => setMetric("capex")}>
          CapEx
        </button>
        <button className={metric === "rnd" ? "active" : ""} onClick={() => setMetric("rnd")}>
          R&amp;D
        </button>
      </div>
      <p className="help-text">
        {withValue.length} of {results.length} companies disclosed a {metric === "capex" ? "CapEx" : "R&D"} total
        {results.length > withValue.length && ` (${results.length - withValue.length} not disclosed, excluded from the chart)`}.
        {currencies.size > 1 && " Figures are shown exactly as each company reports them -- currencies are not converted; see the table below for each company's currency."}
      </p>
      <BarChart data={chartData} valueFormatter={(v) => v.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
    </section>
  );
}

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
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

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
    setActiveSource(null);
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
    try {
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
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const universeStepNumber = mode === "custom" ? 3 : 1;
  const readyForUniverseStep = mode === "financials" || (mode === "custom" && schema != null);

  // The page's spine: what this run needs, in order, and where it has got
  // to. Without it the analyst infers the sequence from which cards happen
  // to be on screen.
  const steps: Step[] = [
    ...(mode === "custom"
      ? ([
          { id: "describe", label: "Describe", state: schema ? "done" : "current" },
          { id: "fields", label: "Review fields", state: !schema ? "todo" : runId ? "done" : "current" },
        ] as Step[])
      : []),
    { id: "universe", label: "Company universe", state: !readyForUniverseStep ? "todo" : runId ? "done" : "current" },
    { id: "run", label: "Run & review", state: runId ? "current" : "todo" },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Extraction"
        description={
          <>
            Extract data from company disclosures with an independent verifier pass and a hard programmatic grounding
            check on every citation. Either draft a custom schema for any research question (e.g. "green capex"), or run
            the built-in combined pass for business segments, CapEx, and R&amp;D.
          </>
        }
      />

      <div className="view-toggle">
        <button className={mode === "custom" ? "active" : ""} onClick={() => switchMode("custom")}>
          Custom schema
        </button>
        <button className={mode === "financials" ? "active" : ""} onClick={() => switchMode("financials")}>
          Financials (segments / CapEx / R&amp;D)
        </button>
      </div>

      <Steps steps={steps} label="Extraction run" />

      {mode === "custom" && (
        <StepCard step={1} title="Describe what to extract" state={schema ? "done" : "current"}>
          <Field label="Research request">
            <textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
          </Field>
          <Button onClick={draft} disabled={busy}>
            Draft extraction schema
          </Button>
          <p className="help-text">Or skip this and build a schema entirely by hand before starting a run.</p>
        </StepCard>
      )}

      {mode === "custom" && schema && (
        <StepCard
          step={2}
          title="Review & edit fields"
          state={runId ? "done" : "current"}
          summary={`${schema.fields.length} field${schema.fields.length === 1 ? "" : "s"}`}
        >
          {schema.fields.map((f, idx) => (
            <div className="activity-editor" key={f.field_id}>
              <input value={f.name} onChange={(e) => updateField(idx, { name: e.target.value })} />
              <Field label="Description">
                <textarea rows={2} value={f.description} onChange={(e) => updateField(idx, { description: e.target.value })} />
              </Field>
              <Field label="Extraction instructions">
                <textarea
                  rows={3}
                  value={f.extraction_instructions}
                  onChange={(e) => updateField(idx, { extraction_instructions: e.target.value })}
                />
              </Field>
              <span className="field-label">Data type / unit</span>
              <div className="inline-fields">
                <span>{f.data_type}</span>
                <input
                  placeholder="unit"
                  value={f.unit ?? ""}
                  onChange={(e) => updateField(idx, { unit: e.target.value })}
                />
              </div>
              <Field label="Seed keywords (comma-separated)">
                <input
                  value={f.seed_keywords.join(", ")}
                  onChange={(e) => updateField(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                />
              </Field>
            </div>
          ))}
        </StepCard>
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
        <StepCard
          step={universeStepNumber}
          title="Choose the company universe"
          state={runId ? "done" : "current"}
          summary={universePath ? `${companyCount || "?"} companies` : undefined}
        >
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
          <Button onClick={startRun} disabled={busy || !universePath}>
            {mode === "custom"
              ? `Extract across ${companyCount || "..."} companies`
              : `Extract financials across ${companyCount || "..."} companies`}
          </Button>
        </StepCard>
      )}

      {error && <StateBlock kind="error" message={error} />}

      {runId && (
        <StepCard step={universeStepNumber + 1} title="Run progress">
          {/* Sticky: a run takes minutes and its results run long, so progress
              stays in view instead of scrolling away above the table. */}
          <div className="run-strip">
            <RunProgress runId={runId} runType={mode === "custom" ? "extraction" : "financials"} />
          </div>
          <div className="toolbar">
            <Button onClick={refreshResults}>Refresh results</Button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
            <Field label="Reviewing as" className="field-inline field-push">
              <input placeholder="your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </Field>
          </div>

          {mode === "financials" && financialsResults.length > 0 && <BatchSpendChart results={financialsResults} />}

          {((mode === "custom" && extractionResults.length > 0) || (mode === "financials" && financialsResults.length > 0)) && (
            <div className="split-review">
              <div className="split-review-main">
                {mode === "custom" && (
                  <ExtractionResultsTable
                    results={extractionResults}
                    runId={runId}
                    expanded={expanded}
                    onToggleExpanded={(companyId) => setExpanded(expanded === companyId ? null : companyId)}
                    reviewDecisions={extractionReviewDecisions}
                    reviewer={reviewer}
                    onReviewDone={refreshResults}
                    onOpenSource={setActiveSource}
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
                    onOpenSource={setActiveSource}
                  />
                )}
              </div>
              <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
            </div>
          )}
        </StepCard>
      )}
    </div>
  );
}
