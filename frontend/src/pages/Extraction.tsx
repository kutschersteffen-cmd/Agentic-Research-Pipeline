import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "../api/client";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { DataPointSchema, ExtractionProfile, StepSettings, UniverseHandoff } from "../types";
import { useReviewer } from "../lib/reviewer";
import { ScoringTemplatePicker } from "../components/RunScoring";
import { TransitionPlanMethodology } from "../components/TransitionPlanResults";
import { PipelineEditor } from "../components/PipelineEditor";
import { SchemaFieldsEditor } from "../components/SchemaFieldsEditor";
import { StepTabs, type StepTab } from "../components/StepTabs";
import { StageFlowChart } from "../components/StageFlowChart";
import { FlowRuns } from "../components/FlowRuns";
import { IdentityStage } from "../components/IdentityStage";
import { DocumentsStage } from "../components/DocumentsStage";
import { PROFILE_META, jobLabel, jobReady, type Job } from "../lib/jobs";
import {
  STAGES,
  extractInputs,
  pendingOnboard,
  flowReducer,
  initialFlow,
  mergeCompanies,
  stageInput,
  type FlowStep,
  type Stage,
  type StageHandle,
  type StageId,
  type StageState,
} from "../lib/stagedFlow";
import { JobReview } from "./extraction/JobReview";
import { JobRun, type JobStatus } from "./extraction/JobRun";
import { CompaniesPanel } from "./extraction/CompaniesPanel";

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
  const [error, setError] = useState<string | null>(null);
  const [flow, dispatch] = useReducer(flowReducer, initialFlow, (init) =>
    pendingUniverse ? flowReducer(init, { type: "companies", output: { path: pendingUniverse.path, count: pendingUniverse.count } }) : init,
  );
  const [tab, setTab] = useState<FlowStep>("companies");
  const [sub, setSub] = useState<Record<Inner, Sub>>({ identify: "run", documents: "run", extract: "setup" });
  const [reviewer] = useReviewer();
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const identifyRef = useRef<StageHandle>(null);
  const documentsRef = useRef<StageHandle>(null);
  const runId = flow.extractRuns[mode] ?? null;

  // Custom-schema mode only
  const [criteria, setCriteria] = useState(DEFAULT_CRITERIA);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [stepSettings, setStepSettings] = useState<StepSettings>({});

  // TNFD profile only
  const [asOf, setAsOf] = useState(`FY${new Date().getFullYear() - 1}`);

  const profile = PROFILE_META[mode];

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    dispatch({ type: "jobsChanged", jobIds: [next] });
    setTab("companies");
    setSub((s) => ({ ...s, extract: "setup" }));
    setError(null);
    setTemplateId(null);
    setStepSettings({});
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

  const inputs = extractInputs(flow);
  const leftOut = pendingOnboard(flow);
  const inputCount = inputs.length === 1 ? inputs[0].count : mergeCompanies(inputs).length;
  const currentJob: Job = useMemo(
    () => (mode === "custom" ? { id: "custom:1", profile: "custom", schema, request: "" } : { id: mode, profile: mode }),
    [mode, schema],
  );
  const schemaReady = jobReady(currentJob);
  const canStart = inputs.length > 0 && schemaReady && (mode !== "tnfd" || !!asOf.trim());

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
      dispatch({ type: "extractStarted", job: mode, runId: res.run_id });
      setTab("extract");
      setSub((s) => ({ ...s, extract: "run" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const [runStatus, setRunStatus] = useState<JobStatus>({ status: "running", counts: null });
  const [pending, setPending] = useState(0);
  const extractStatus: StageState =
    !runId ? "idle"
    : flow.extractStale && runStatus.status !== "running" ? "stale"
    : runStatus.status === "done" && pending > 0 ? "review"
    : runStatus.status;
  const extractCounts = runId ? runStatus.counts : null;
  const startRef = useRef(startRun);
  startRef.current = startRun;
  const flowRef = useRef(flow);
  flowRef.current = flow;

  const extract = useMemo(
    () => ({ jobs: [{ id: currentJob.id, label: jobLabel(currentJob), status: extractStatus, counts: extractCounts, ready: schemaReady, scoring: null }], status: extractStatus }),
    [currentJob, schemaReady, extractStatus, extractCounts],
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
  const openJob = useCallback(() => openTab("extract", "review"), [openTab]); // one job today; the job id matters once several run
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
    { id: "review", label: "Review", disabled: !runId, badge: pending, mark: extractStatus === "review" ? "waiting" : null },
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
      <StageFlowChart flow={flow} profile={mode} extract={extract} counts={counts} onOpen={openTab} onOpenJob={openJob} onStart={onStart} onStop={onStop} onContinue={onContinue} dispatch={dispatch} />
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
                ? `Runs on ${inputCount} companies with ${jobLabel(currentJob)}.`
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
            <JobRun
              job={currentJob}
              runId={runId}
              onRestarted={(next) => dispatch({ type: "extractStarted", job: mode, runId: next })}
              onStatus={setRunStatus}
            />
          </div>
        )}

        {runId && (
          <div hidden={sub.extract !== "review"}>
            <JobReview job={currentJob} runId={runId} reviewer={reviewer} onSourceOpen={() => {}} onPending={setPending} />
          </div>
        )}
      </div>
    </div>
  );
}
