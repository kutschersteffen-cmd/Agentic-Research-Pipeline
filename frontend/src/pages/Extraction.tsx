import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { CompanyFinancialsRecord, DataPointSchema, ExtractionProfile, ExtractionRecord, ReviewDecision, RunManifest, StepSettings, TnfdRecord, TransitionPlanAssessmentRecord, UniverseHandoff } from "../types";
import { useReviewer } from "../lib/reviewer";
import { ReviewerField } from "../components/ReviewerField";
import { RunScoringPanel, ScoringTemplatePicker } from "../components/RunScoring";
import { TransitionPlanBatchOverview, TransitionPlanMethodology } from "../components/TransitionPlanResults";
import { PipelineEditor } from "../components/PipelineEditor";
import { SchemaFieldsEditor } from "../components/SchemaFieldsEditor";
import { StepTabs, type StepTab } from "../components/StepTabs";
import { StageFlowChart, schemaLabel } from "../components/StageFlowChart";
import { FlowRuns } from "../components/FlowRuns";
import { ReviewTiles } from "../components/ReviewTiles";
import { IdentityStage } from "../components/IdentityStage";
import { DocumentsStage } from "../components/DocumentsStage";
import { ACTIVE_STATUSES } from "../lib/runs";
import { PROFILE_META } from "../lib/jobs";
import {
  STAGES,
  extractInputs,
  pendingOnboard,
  flowReducer,
  initialFlow,
  mergeCompanies,
  reviewCounts,
  stageInput,
  type FlowStep,
  type ReviewTileCounts,
  type Stage,
  type StageHandle,
  type StageId,
  type StageState,
} from "../lib/stagedFlow";
import { BatchSpendChart } from "./extraction/BatchSpendChart";
import { CompaniesPanel } from "./extraction/CompaniesPanel";
import { ResultsTable } from "./extraction/ResultsTable";

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

type Sub = "setup" | "run" | "review";
type Inner = "identify" | "documents" | "extract";

const MARK: Partial<Record<StageState, StepTab["mark"]>> = { done: "done", ready: "waiting", review: "waiting", failed: "attention", stale: "attention" };

const stageTabs = (st: Stage): StepTab[] => [
  { id: "run", label: "Run" },
  { id: "review", label: "Review", badge: st.state === "review" ? st.flagged : null, mark: st.state === "review" ? "waiting" : null },
];

interface Props {
  pendingUniverse?: UniverseHandoff | null;
  /** The profile the screen opens on, e.g. the Transition Plan menu item. */
  initialProfile?: Mode;
}

export function Extraction({ pendingUniverse, initialProfile = "custom" }: Props = {}) {
  const [mode, setMode] = useState<Mode>(initialProfile);
  const [busy, setBusy] = useState(false);
  const [tileFilter, setTileFilter] = useState<keyof ReviewTileCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flow, dispatch] = useReducer(flowReducer, initialFlow, (init) =>
    pendingUniverse ? flowReducer(init, { type: "companies", output: { path: pendingUniverse.path, count: pendingUniverse.count } }) : init,
  );
  const [tab, setTab] = useState<FlowStep>("companies");
  const [sub, setSub] = useState<Record<Inner, Sub>>({ identify: "run", documents: "run", extract: "setup" });
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewer] = useReviewer();
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const identifyRef = useRef<StageHandle>(null);
  const documentsRef = useRef<StageHandle>(null);
  const runId = flow.extractRunId;

  // Custom-schema mode only
  const [criteria, setCriteria] = useState(DEFAULT_CRITERIA);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [extractionResults, setExtractionResults] = useState<ExtractionRecord[]>([]);
  const [extractionReviewDecisions, setExtractionReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [stepSettings, setStepSettings] = useState<StepSettings>({});

  // Financials mode only
  const [financialsResults, setFinancialsResults] = useState<CompanyFinancialsRecord[]>([]);
  const [financialsReviewDecisions, setFinancialsReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  // TNFD profile only
  const [asOf, setAsOf] = useState(`FY${new Date().getFullYear() - 1}`);
  const [tnfdResults, setTnfdResults] = useState<TnfdRecord[]>([]);

  // Transition Plan profile only
  const [transitionResults, setTransitionResults] = useState<TransitionPlanAssessmentRecord[]>([]);
  const [transitionReviewDecisions, setTransitionReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  const profile = PROFILE_META[mode];

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    dispatch({ type: "profileChanged" });
    setTab("companies");
    setSub((s) => ({ ...s, extract: "setup" }));
    setError(null);
    setTemplateId(null);
    setStepSettings({});
    setExpanded(null);
    setActiveSource(null);
  }

  function clearResults() {
    setExtractionResults([]);
    setFinancialsResults([]);
    setTnfdResults([]);
    setTransitionResults([]);
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

  const inputs = extractInputs(flow);
  const leftOut = pendingOnboard(flow);
  const inputCount = inputs.length === 1 ? inputs[0].count : mergeCompanies(inputs).length;
  const schemaInfo = schemaLabel(mode, schema);
  const canStart = inputs.length > 0 && schemaInfo.ready && (mode !== "tnfd" || !!asOf.trim());

  async function startRun() {
    if (!canStart) {
      setError(inputs.length ? "Finish the schema (and the TNFD reporting period) first." : "Nothing to extract yet: carry the companies through Identify and Documents, or skip those stages.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Identify and Documents ran as checkpoints, so the run must not repeat them; a skipped stage keeps the user's setting.
      const settings: StepSettings = {
        ...stepSettings,
        ...(flow.identify.state !== "skipped" ? { pre_identity_enabled: false } : {}),
        ...(flow.documents.state !== "skipped" ? { pre_content_search_enabled: false, pre_document_mgmt_enabled: false } : {}),
      };
      const res = await api.startExtraction({
        profile: mode,
        datapoint_schema: mode === "custom" ? schema : undefined,
        as_of: mode === "tnfd" ? asOf : undefined,
        ...(inputs.length === 1 ? { universe_path: inputs[0].path } : { companies: mergeCompanies(inputs) }),
        decision_framework_id: templateId ?? undefined,
        step_settings: Object.keys(settings).length ? settings : undefined,
      });
      dispatch({ type: "extractStarted", runId: res.run_id });
      clearResults();
      setTab("extract");
      setSub((s) => ({ ...s, extract: "run" }));
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

  // The chart and the review tiles need the extract run's status; load the results once it ends.
  const startRef = useRef(startRun);
  startRef.current = startRun;
  const flowRef = useRef(flow);
  flowRef.current = flow;
  const refreshRef = useRef(refreshResults);
  refreshRef.current = refreshResults;
  useEffect(() => {
    if (!runId) return;
    let live = true;
    let timer: number | undefined;
    async function poll() {
      try {
        const m = (await api.getRun(runId!)) as RunManifest;
        if (!live) return;
        setManifest(m);
        if (!ACTIVE_STATUSES.has(m.status)) {
          refreshRef.current().catch(() => {});
          return;
        }
      } catch {
        // keep polling; RunProgress shows the load error
      }
      if (live) timer = window.setTimeout(poll, 2500);
    }
    poll();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [runId]);

  const run = manifest && manifest.run_id === runId ? manifest : null;
  const results = { custom: extractionResults, financials: financialsResults, tnfd: tnfdResults, transition_plan: transitionResults };
  const decisionMaps = { custom: extractionReviewDecisions, financials: financialsReviewDecisions, transition_plan: transitionReviewDecisions };
  const decisions = mode === "tnfd" ? [] : Object.values(decisionMaps[mode]);
  const tiles = reviewCounts(Math.max(0, (run?.review_count ?? 0) - decisions.length), decisions, run?.review_count ?? 0);
  const extractStatus: StageState =
    !runId ? "idle"
    : !run || ACTIVE_STATUSES.has(run.status) ? "running"
    : flow.extractStale ? "stale"
    : run.status === "failed" ? "failed"
    : run.status === "completed" && tiles.pending === 0 ? "done"
    : "review";
  const extractCounts = run ? `${run.completed_count} of ${run.company_count} extracted` : null;

  const extract = useMemo(
    () => ({ schemaLabel: schemaInfo.label, ready: schemaInfo.ready, status: extractStatus, counts: extractCounts }),
    [schemaInfo.label, schemaInfo.ready, extractStatus, extractCounts],
  );
  const counts = useMemo(() => {
    const out: Partial<Record<StageId | "companies", string>> = {};
    if (flow.ready || flow.onboard) out.companies = `${flow.ready?.count ?? 0} ready · ${flow.onboard?.count ?? 0} to onboard`;
    else if (flow.companies) out.companies = `${flow.companies.count} companies`;
    for (const id of STAGES) {
      const st = flow[id];
      const input = stageInput(flow, id);
      if (st.state === "done" && st.output) out[id] = `${st.output.count} carried forward`;
      else if (input && st.state !== "skipped") out[id] = `${input.count} companies`;
    }
    return out;
  }, [flow]);

  const openTab = useCallback(
    (step: FlowStep, s?: Sub) => {
      setTab(step);
      if (!s || (step !== "identify" && step !== "documents" && step !== "extract")) return;
      setSub((prev) => ({ ...prev, [step]: step === "extract" && s !== "setup" && !runId ? "setup" : s }));
    },
    [runId],
  );
  const onStart = useCallback((step: StageId | "extract") => {
    if (step === "extract") startRef.current();
    // Skip means the stage does not run.
    else if (flowRef.current[step].state !== "skipped") (step === "identify" ? identifyRef : documentsRef).current?.start();
  }, []);

  // Automatic handover advances the tab once, when the stage turns done; a later manual tab change stays.
  const { identify, documents } = flow;
  const prevState = useRef({ identify: identify.state, documents: documents.state });
  useEffect(() => {
    const now = { identify, documents };
    for (const id of STAGES) {
      if (now[id].state === "done" && prevState.current[id] !== "done" && now[id].handover === "auto") {
        setTab(id === "identify" ? "documents" : mode === "custom" ? "schema" : "extract");
      }
    }
    prevState.current = { identify: identify.state, documents: documents.state };
  }, [identify, documents, mode]);
  const onStop = useCallback((id: string) => {
    api.cancelRun(id).catch((err) => setError(`Run could not be stopped: ${(err as Error).message}`));
  }, []);
  const onContinue = useCallback((stage: StageId) => (stage === "identify" ? identifyRef : documentsRef).current?.carryOn(), []);

  const fieldNames = schema?.fields.map((f) => f.name) ?? [];
  const toggleExpanded = (companyId: string) => setExpanded(expanded === companyId ? null : companyId);
  const allAuto = STAGES.some((id) => flow[id].handover === "auto") && STAGES.every((id) => flow[id].handover !== "manual");

  const steps: StepTab[] = [
    { id: "companies", label: "Companies", mark: flow.readinessNote ? "attention" : flow.companies ? "done" : null },
    { id: "identify", label: "Identify", mark: MARK[flow.identify.state] },
    { id: "documents", label: "Documents", mark: MARK[flow.documents.state] },
    ...(mode === "custom" ? [{ id: "schema", label: "Schema", mark: schema ? ("done" as const) : null }] : []),
    { id: "extract", label: "Extract", mark: MARK[extractStatus] },
  ];
  const topTabs = steps.map((t, i) => ({ ...t, label: `${i + 1}. ${t.label}` }));
  const extractTabs: StepTab[] = [
    { id: "setup", label: "Setup" },
    { id: "run", label: "Run", disabled: !runId },
    { id: "review", label: "Review", disabled: !runId, badge: tiles.pending, mark: extractStatus === "review" ? "waiting" : null },
  ];
  const tabRunTypes = { companies: ["identity", "discovery", profile.runType], schema: ["identity", "discovery", profile.runType], identify: ["identity"], documents: ["discovery"], extract: [profile.runType] }[tab];
  const tabRunId = tab === "identify" || tab === "documents" ? flow[tab].runId : tab === "extract" ? runId : null;
  const openRun = (id: string, s: Sub = "run") => {
    if (id === runId) openTab("extract", s);
    else for (const st of STAGES) if (flow[st].runId === id) openTab(st, s);
  };
  const innerTabs = (id: Inner, tabs: StepTab[], label: string) => (
    <StepTabs label={label} tabs={tabs} active={sub[id]} onSelect={(v) => setSub((s) => ({ ...s, [id]: v as Sub }))} />
  );

  return (
    <div className="page">
      <h1>Extraction</h1>
      <p className="help-text">Extract data points from company disclosures, each checked by a verifier and every citation re-verified against its source. Pick a profile: draft a custom schema, or run one of the built-in ones — Financials, TNFD or Transition Plan.</p>

      <div className="view-toggle" role="group" aria-label="Extraction profile">
        {(Object.entries(PROFILE_META) as [Mode, (typeof PROFILE_META)[Mode]][]).map(([id, p]) => (
          <button key={id} className={mode === id ? "active" : ""} aria-pressed={mode === id} onClick={() => switchMode(id)}>
            {p.label}
          </button>
        ))}
      </div>
      {profile.about && <p className="help-text">{profile.about}</p>}
      {mode === "transition_plan" && <TransitionPlanMethodology />}

      <label className="checkbox-label">
        <input type="checkbox" checked={allAuto} onChange={(e) => dispatch({ type: "allAuto", on: e.target.checked })} />
        Run all automatically
      </label>
      <StageFlowChart flow={flow} profile={mode} extract={extract} counts={counts} onOpen={openTab} onStart={onStart} onStop={onStop} onContinue={onContinue} dispatch={dispatch} />
      <StepTabs label="Extraction steps" tabs={topTabs} active={tab} onSelect={(id) => setTab(id as FlowStep)} />
      <FlowRuns
        key={tab}
        runTypes={tabRunTypes}
        runIds={flow.runIds}
        selected={tabRunId}
        onSelect={(id) => openRun(id)}
        onReview={(r) => openRun(r.run_id, "review")}
        onRerun={(r) => (r.run_type === "identity" ? onStart("identify") : r.run_type === "discovery" ? onStart("documents") : openTab("extract", "run"))}
        compact={tab === "companies" || tab === "schema"}
        storageKey={`flowRuns:${tab}`}
      />

      {error && <p className="error-text" role="alert">{error}</p>}

      <div role="tabpanel" aria-label="Companies" hidden={tab !== "companies"}>
        <CompaniesPanel flow={flow} dispatch={dispatch} pendingUniverse={pendingUniverse} tnfd={mode === "tnfd"} asOf={asOf} onAsOf={setAsOf} />
      </div>

      <div role="tabpanel" aria-label="Identify" hidden={tab !== "identify"}>
        {innerTabs("identify", stageTabs(flow.identify), "Identify")}
        <section className="card">
          <IdentityStage
            ref={identifyRef}
            input={stageInput(flow, "identify")}
            stage={flow.identify}
            dispatch={dispatch}
            view={sub.identify === "review" ? "review" : "run"}
            reviewer={reviewer}
            onOpenSource={setActiveSource}
          />
        </section>
        {activeSource && <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />}
      </div>

      <div role="tabpanel" aria-label="Documents" hidden={tab !== "documents"}>
        {innerTabs("documents", stageTabs(flow.documents), "Documents")}
        <section className="card">
          <DocumentsStage ref={documentsRef} input={stageInput(flow, "documents")} stage={flow.documents} dispatch={dispatch} view={sub.documents === "review" ? "review" : "run"} />
        </section>
      </div>

      {mode === "custom" && (
        <div role="tabpanel" aria-label="Schema" hidden={tab !== "schema"}>
          <section className="card">
            <h2>Describe what to extract</h2>
            <label className="field-label">
              Research request
              <textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
            </label>
            <button onClick={draft} disabled={busy}>
              Draft extraction schema
            </button>
            <p className="help-text">Or skip this and build a schema entirely by hand before starting a run.</p>
          </section>
          {schema && (
            <section className="card">
              <h2>Review &amp; edit fields</h2>
              <SchemaFieldsEditor fields={schema.fields} onChange={(fields) => setSchema({ ...schema, fields })} />
            </section>
          )}
        </div>
      )}

      <div role="tabpanel" aria-label="Extract" hidden={tab !== "extract"}>
        {innerTabs("extract", extractTabs, "Extract")}

        <div hidden={sub.extract !== "setup"}>
          <section className="card">
            <h2>Pipeline</h2>
            <p className="help-text">
              The steps every item goes through. Optional: click a step to change its settings for this run only; the app&apos;s
              defaults stay as they are.
            </p>
            <PipelineEditor profile={mode} value={stepSettings} onChange={setStepSettings} />
          </section>
          <section className="card">
            <h2>Score the results (optional)</h2>
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
          <section className="card">
            <h2>Start extraction</h2>
            <p className="help-text">
              {inputs.length
                ? `Runs on ${inputCount} companies with ${schemaInfo.label}.`
                : "No companies handed over yet: carry them through Identify and Documents, or skip those stages."}
            </p>
            {inputs.length > 0 && leftOut > 0 && (
              <p className="await-text">{leftOut} companies are still onboarding and will be left out</p>
            )}
            {flow.extractStale && <p className="await-text">Inputs changed since this run</p>}
            <button onClick={startRun} disabled={busy || !canStart}>
              Start extraction
            </button>
          </section>
        </div>

        {runId && (
          <div hidden={sub.extract !== "run"}>
            <section className="card">
              <h2>Run progress</h2>
              <RunProgress runId={runId} runType={profile.runType} />
              <PipelineEditor
                key={runId}
                profile={mode}
                runId={runId}
                onRestarted={(next) => {
                  dispatch({ type: "extractStarted", runId: next });
                  clearResults();
                }}
              />
              <div className="toolbar">
                <button onClick={refreshResults}>Refresh results</button>
                <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
                  Export CSV
                </a>
                <ReviewerField compact />
              </div>
            </section>
          </div>
        )}

        {runId && (
          <div hidden={sub.extract !== "review"}>
            {/* TNFD has no review decisions, so no tiles. */}
            {mode !== "tnfd" && <ReviewTiles counts={tiles} active={tileFilter} onSelect={setTileFilter} />}
            {mode === "financials" && financialsResults.length > 0 && <BatchSpendChart results={financialsResults} />}
            {mode === "transition_plan" && transitionResults.length > 0 && <TransitionPlanBatchOverview results={transitionResults} />}

            {results[mode].length > 0 && (
              <section className="card">
                <div className="split-review">
                  <div className="split-review-main">
                    <ResultsTable
                      mode={mode}
                      runId={runId}
                      results={results}
                      decisions={decisionMaps}
                      expanded={expanded}
                      onToggleExpanded={toggleExpanded}
                      reviewer={reviewer}
                      onReviewed={refreshResults}
                      onOpenSource={setActiveSource}
                      filter={tileFilter}
                    />
                  </div>
                  <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
                </div>
              </section>
            )}

            <RunScoringPanel key={runId} runId={runId} runType={profile.runType} fieldNames={mode === "custom" ? fieldNames : undefined} />
          </div>
        )}
      </div>
    </div>
  );
}
