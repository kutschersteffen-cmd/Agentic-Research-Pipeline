import { useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ExtractionResultsTable, FinancialsResultsTable } from "../components/ExtractionResults";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { BarChart } from "../components/BarChart";
import type { CompanyFinancialsRecord, DataPointSchema, ExtractionProfile, ExtractionRecord, FieldDefinition, ReviewDecision, RunScoringKind, TnfdRecord, TransitionPlanAssessmentRecord, UniverseHandoff } from "../types";
import { useReviewer } from "../lib/reviewer";
import { ReviewerField } from "../components/ReviewerField";
import { RunScoringPanel, ScoringTemplatePicker } from "../components/RunScoring";
import { TransitionPlanBatchOverview, TransitionPlanMethodology, TransitionPlanResultsTable } from "../components/TransitionPlanResults";
import { TnfdResultsTable } from "../components/TnfdResults";

const DEFAULT_CRITERIA =
  "Green capex: total green/sustainable capital expenditure in USD/EUR millions for the most recent fiscal " +
  "year, and as a % of total capex. Separately capture: (a) whether reported per the EU Taxonomy (eligible vs " +
  "aligned) vs. a self-defined/internal definition -- both if disclosed, clearly labeled; (b) breakdown by EU " +
  "Taxonomy environmental objective (climate mitigation, adaptation, water, circular economy, pollution, " +
  "biodiversity) where disclosed; (c) the company's own stated definition/methodology as a separate string " +
  "field with its own citation; (d) prior-year comparative figure; (e) forward-looking green capex " +
  "targets/guidance as a SEPARATE field from the actual reported figure -- extraction_instructions must " +
  "explicitly forbid conflating a target with an actual reported number.";

type Mode = ExtractionProfile;

const PROFILES: { id: Mode; label: string; runType: RunScoringKind; about: string }[] = [
  { id: "custom", label: "Custom schema", runType: "extraction", about: "" },
  {
    id: "financials",
    label: "Financials",
    runType: "financials",
    about:
      "Pulls disclosed business segments (name, description, revenue, operating income, assets), total CapEx, and total R&D — each with a grounded description and any disclosed category breakdown — in a single combined pass per company: one document fetch, one extractor call, one independent verifier call.",
  },
  {
    id: "tnfd",
    label: "TNFD",
    runType: "tnfd",
    about:
      "Checks each of the 14 TNFD recommendations for a disclosure and extracts the core global metrics, each with citations re-verified against the source. Rules can read each recommendation as a Yes/No column (e.g. Governance_A_Disclosed).",
  },
  {
    id: "transition_plan",
    label: "Transition Plan",
    runType: "transition_plan",
    about:
      "Scores each company’s climate transition disclosures against the 64 indicators of Colesanti Senni et al. (2024), separating “talk” (targets) from “walk” (verifiable activity). Rules can read each indicator as a Yes/No column (Ind_<identifier>_Disclosed).",
  },
];

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
      <h3>Batch overview ({results.length} companies)</h3>
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
        {currencies.size > 1 && " Figures are shown exactly as each company reports them — currencies are not converted; see the table below for each company's currency."}
      </p>
      <BarChart data={chartData} valueFormatter={(v) => v.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
    </section>
  );
}

interface Props {
  pendingUniverse?: UniverseHandoff | null;
  /** The profile the screen opens on, e.g. the Transition Plan menu item. */
  initialProfile?: Mode;
}

export function Extraction({ pendingUniverse, initialProfile = "custom" }: Props = {}) {
  const [mode, setMode] = useState<Mode>(initialProfile);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [universePath, setUniversePath] = useState<string | null>(pendingUniverse?.path ?? null);
  const [companyCount, setCompanyCount] = useState(pendingUniverse?.count ?? 0);
  const [runId, setRunId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewer] = useReviewer();
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  // Custom-schema mode only
  const [criteria, setCriteria] = useState(DEFAULT_CRITERIA);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [extractionResults, setExtractionResults] = useState<ExtractionRecord[]>([]);
  const [extractionReviewDecisions, setExtractionReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [templateId, setTemplateId] = useState<string | null>(null);

  // Financials mode only
  const [financialsResults, setFinancialsResults] = useState<CompanyFinancialsRecord[]>([]);
  const [financialsReviewDecisions, setFinancialsReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  // TNFD profile only
  const [asOf, setAsOf] = useState(`FY${new Date().getFullYear() - 1}`);
  const [tnfdResults, setTnfdResults] = useState<TnfdRecord[]>([]);

  // Transition Plan profile only
  const [transitionResults, setTransitionResults] = useState<TransitionPlanAssessmentRecord[]>([]);
  const [transitionReviewDecisions, setTransitionReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  const profile = PROFILES.find((p) => p.id === mode)!;

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setRunId(null);
    setError(null);
    setTemplateId(null);
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
      const res = await api.startExtraction({
        profile: mode,
        datapoint_schema: mode === "custom" ? schema : undefined,
        as_of: mode === "tnfd" ? asOf : undefined,
        universe_path: universePath,
        decision_framework_id: templateId ?? undefined,
      });
      setRunId(res.run_id);
      setExtractionResults([]);
      setFinancialsResults([]);
      setTnfdResults([]);
      setTransitionResults([]);
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
    } else if (mode === "financials") {
      const res = (await api.getFinancialsResults(runId)) as { results: CompanyFinancialsRecord[] };
      setFinancialsResults(res.results);
      const decisionsRes = (await api.getFinancialsReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
      setFinancialsReviewDecisions(decisionsRes.decisions);
    } else if (mode === "tnfd") {
      setTnfdResults((await api.getTnfdResults(runId)).results);
    } else {
      setTransitionResults((await api.getTransitionPlanResults(runId)).results);
      const decisionsRes = (await api.getTransitionPlanReviewDecisions(runId)) as { decisions: Record<string, ReviewDecision> };
      setTransitionReviewDecisions(decisionsRes.decisions);
    }
  }

  const scoringStepNumber = mode === "custom" ? 3 : 1;
  const universeStepNumber = scoringStepNumber + 1;
  const fieldNames = schema?.fields.map((f) => f.name) ?? [];
  const readyForUniverseStep = mode !== "custom" || schema != null;
  const resultCount = { custom: extractionResults, financials: financialsResults, tnfd: tnfdResults, transition_plan: transitionResults }[mode].length;
  const toggleExpanded = (companyId: string) => setExpanded(expanded === companyId ? null : companyId);

  return (
    <div className="page">
      <h2>Extraction</h2>
      <p className="help-text">Extract data points from company disclosures, each checked by a verifier and every citation re-verified against its source. Pick a profile: draft a custom schema, or run one of the built-in ones — Financials, TNFD or Transition Plan.</p>

      <div className="view-toggle" role="group" aria-label="Extraction profile">
        {PROFILES.map((p) => (
          <button key={p.id} className={mode === p.id ? "active" : ""} aria-pressed={mode === p.id} onClick={() => switchMode(p.id)}>
            {p.label}
          </button>
        ))}
      </div>
      {profile.about && <p className="help-text">{profile.about}</p>}
      {mode === "transition_plan" && <TransitionPlanMethodology />}

      {mode === "custom" && (
        <section className="card">
          <h3>1. Describe what to extract</h3>
          <label className="field-label">
            Research request
            <textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
          </label>
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
              <label className="field-label">
                Description
                <textarea rows={2} value={f.description} onChange={(e) => updateField(idx, { description: e.target.value })} />
              </label>
              <label className="field-label">
                Extraction instructions
                <textarea
                  rows={3}
                  value={f.extraction_instructions}
                  onChange={(e) => updateField(idx, { extraction_instructions: e.target.value })}
                />
              </label>
              <div className="field-label">Data type / unit</div>
              <div className="inline-fields">
                <span>{f.data_type}</span>
                <input
                  aria-label="Unit"
                  placeholder="unit"
                  value={f.unit ?? ""}
                  onChange={(e) => updateField(idx, { unit: e.target.value })}
                />
              </div>
              <label className="field-label">
                Seed keywords (comma-separated)
                <input
                  value={f.seed_keywords.join(", ")}
                  onChange={(e) => updateField(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                />
              </label>
            </div>
          ))}
        </section>
      )}

      {readyForUniverseStep && (
        <section className="card">
          <h3>{scoringStepNumber}. Score the results (optional)</h3>
          <p className="help-text">
            Attach a Decision Studio framework: once every company is extracted, the run applies its rules as the last step
            and stores the scores and tiers with the run. You can also attach one after the run.
          </p>
          <ScoringTemplatePicker
            runType={profile.runType}
            fieldNames={mode === "custom" ? fieldNames : undefined}
            value={templateId}
            onChange={setTemplateId}
          />
        </section>
      )}


      {readyForUniverseStep && (
        <section className="card">
          <h3>{universeStepNumber}. Choose the company universe</h3>
          {pendingUniverse && universePath === pendingUniverse.path && (
            <p className="status-text">
              Using {pendingUniverse.count} companies sent from {pendingUniverse.from}. Upload a different
              universe below to replace it.
            </p>
          )}
          {mode === "tnfd" && (
            <label className="field-label">
              Reporting period
              <input value={asOf} onChange={(e) => setAsOf(e.target.value)} placeholder="FY2025" />
            </label>
          )}
          <UniversePicker
            onResolved={(path, count) => {
              setUniversePath(path);
              setCompanyCount(count);
            }}
          />
          <button onClick={startRun} disabled={busy || !universePath || (mode === "tnfd" && !asOf.trim())}>
            {`Extract ${mode === "custom" ? "" : `${profile.label} `}across ${companyCount || "..."} companies`}
          </button>
        </section>
      )}

      {error && <p className="error-text">{error}</p>}

      {runId && (
        <section className="card">
          <h3>{universeStepNumber + 1}. Run progress</h3>
          <RunProgress runId={runId} runType={profile.runType} />
          <div className="toolbar">
            <button onClick={refreshResults}>Refresh results</button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
            <ReviewerField compact />
          </div>

          {mode === "financials" && financialsResults.length > 0 && <BatchSpendChart results={financialsResults} />}
          {mode === "transition_plan" && transitionResults.length > 0 && <TransitionPlanBatchOverview results={transitionResults} />}

          {resultCount > 0 && (
            <div className="split-review">
              <div className="split-review-main">
                {mode === "custom" && (
                  <ExtractionResultsTable
                    results={extractionResults}
                    runId={runId}
                    expanded={expanded}
                    onToggleExpanded={toggleExpanded}
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
                    onToggleExpanded={toggleExpanded}
                    reviewDecisions={financialsReviewDecisions}
                    reviewer={reviewer}
                    onReviewDone={refreshResults}
                    onOpenSource={setActiveSource}
                  />
                )}

                {mode === "tnfd" && (
                  <TnfdResultsTable results={tnfdResults} expanded={expanded} onToggleExpanded={toggleExpanded} onOpenSource={setActiveSource} />
                )}

                {mode === "transition_plan" && (
                  <TransitionPlanResultsTable
                    runId={runId}
                    results={transitionResults}
                    reviewDecisions={transitionReviewDecisions}
                    reviewer={reviewer}
                    onReviewed={refreshResults}
                    onOpenSource={setActiveSource}
                    expanded={expanded}
                    onToggleExpanded={toggleExpanded}
                  />
                )}
              </div>
              <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
            </div>
          )}
        </section>
      )}

      {runId && (
        <RunScoringPanel
          key={runId}
          runId={runId}
          runType={profile.runType}
          fieldNames={mode === "custom" ? fieldNames : undefined}
        />
      )}
    </div>
  );
}
