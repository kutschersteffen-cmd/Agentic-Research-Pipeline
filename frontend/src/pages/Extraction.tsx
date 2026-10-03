import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "../api/client";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { ExtractionProfile, StepSettings, UniverseHandoff } from "../types";
import { useMe } from "../lib/reviewer";
import { ScoringTemplatePicker } from "../components/RunScoring";
import { PipelineEditor } from "../components/PipelineEditor";
import { StepTabs, type StepTab } from "../components/StepTabs";
import { StageFlowChart } from "../components/StageFlowChart";
import { isReleased } from "../lib/fieldValue";
import { FlowRuns } from "../components/FlowRuns";
import { IdentityStage } from "../components/IdentityStage";
import { DocumentsStage } from "../components/DocumentsStage";
import {
  initialJobs,
  jobLabel,
  jobReady,
  jobRunType,
  jobsToStart,
  startJobs,
  startsText,
  toggleProfile,
  worstStatus,
  type Job,
  type JobSettings,
} from "../lib/jobs";
import {
  STAGES,
  extractInputs,
  pendingOnboard,
  flowReducer,
  initialFlow,
  latestExtractRun,
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
import { DEFAULT_CRITERIA, SchemaPanel } from "./extraction/SchemaPanel";
import { Overview } from "./extraction/Overview";
import { ScoringSummary } from "./extraction/ScoringSummary";

type Sub = "setup" | "run" | "review";
type Inner = "identify" | "documents" | "extract";
type Tab = FlowStep | "overview";

const MARK: Partial<Record<StageState, StepTab["mark"]>> = { done: "done", ready: "waiting", review: "waiting", failed: "attention", stale: "attention" };
const NO_SETTINGS: JobSettings = { stepSettings: {}, templateId: null };
const noop = () => {};

const stageTabs = (st: Stage): StepTab[] => [
  { id: "run", label: "Run" },
  { id: "review", label: "Review", badge: st.state === "review" ? st.flagged : null, mark: st.state === "review" ? "waiting" : null },
];

interface Props {
  pendingUniverse?: UniverseHandoff | null;
  /** The profile the screen opens on, e.g. the Transition Plan menu item. */
  initialProfile?: ExtractionProfile;
}

export function Extraction({ pendingUniverse, initialProfile = "custom" }: Props = {}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flow, dispatch] = useReducer(flowReducer, initialFlow, (init) =>
    pendingUniverse ? flowReducer(init, { type: "companies", output: { path: pendingUniverse.path, count: pendingUniverse.count } }) : init,
  );
  const [tab, setTab] = useState<Tab>("overview");
  const [sub, setSub] = useState<Record<Inner, Sub>>({ identify: "run", documents: "run", extract: "setup" });
  const reviewer = useMe()?.name ?? "";
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const identifyRef = useRef<StageHandle>(null);
  const documentsRef = useRef<StageHandle>(null);

  const [jobs, setJobs] = useState<Job[]>(() => initialJobs(initialProfile, "custom:1", DEFAULT_CRITERIA));
  const customCounter = useRef(1);
  const nextCustomId = useCallback(() => `custom:${++customCounter.current}`, []);
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [settings, setSettings] = useState<Record<string, JobSettings>>({});
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Record<string, JobStatus>>({});
  const [pending, setPending] = useState<Record<string, number>>({});
  const [frameworks, setFrameworks] = useState<Record<string, string | null>>({});
  const [startErrors, setStartErrors] = useState<Record<string, string>>({});
  // Each extraction run's profile, for the Overview's per-company steps of an older run.
  const [runProfiles, setRunProfiles] = useState<Record<string, ExtractionProfile>>({});
  const [overviewRun, setOverviewRun] = useState<string | null>(null);

  // TNFD jobs only
  const [asOf, setAsOf] = useState(`FY${new Date().getFullYear() - 1}`);

  const hasCustom = jobs.some((j) => j.profile === "custom");
  const runJobs = jobs.filter((j) => j.id in flow.extractRuns);
  const activeJob = jobs.find((j) => j.id === activeJobId) ?? jobs[0];
  const reviewJob = runJobs.find((j) => j.id === activeJobId) ?? runJobs[0] ?? null;
  const hasRuns = runJobs.length > 0;

  /** Every change to the job list goes through here; a changed set of jobs drops the removed jobs' runs and settings. */
  function changeJobs(next: Job[]) {
    const ids = next.map((j) => j.id);
    setJobs(next);
    if (!next.some((j) => j.profile === "custom")) setTab((t) => (t === "schema" ? "overview" : t));
    if (ids.join() !== jobs.map((j) => j.id).join()) {
      dispatch({ type: "jobsChanged", jobIds: ids });
      const keep = <T,>(m: Record<string, T>) => Object.fromEntries(Object.entries(m).filter(([k]) => ids.includes(k)));
      setSettings(keep);
      setStartErrors(keep);
      setStatuses(keep);
      setPending(keep);
      setFrameworks(keep);
    }
  }
  function toggle(profile: ExtractionProfile) {
    const r = toggleProfile(jobs, profile, nextCustomId);
    setPickerError(r.error);
    if (!r.error) changeJobs(r.jobs);
  }
  const patchSettings = (id: string, p: Partial<JobSettings>) => setSettings((s) => ({ ...s, [id]: { ...(s[id] ?? NO_SETTINGS), ...p } }));
  /** A started or restarted job keeps the stale flag; Start-all clears it once every job started. */
  const restarted = (job: Job, runId: string) => {
    dispatch({ type: "extractRestarted", job: job.id, runId });
    setRunProfiles((m) => ({ ...m, [runId]: job.profile }));
  };

  const inputs = extractInputs(flow);
  const leftOut = pendingOnboard(flow);
  const inputCount = inputs.length === 1 ? inputs[0].count : mergeCompanies(inputs).length;
  const toStart = jobsToStart(jobs, flow.extractRuns, flow.extractStale, flow.freshJobs);
  const canStart = inputs.length > 0 && toStart.length > 0;

  const isTrial = (job: Job) => job.profile === "custom" && !!job.schema && !isReleased(job.schema);

  async function startOne(job: Job): Promise<string> {
    if (job.profile === "tnfd" && !asOf.trim()) throw new Error("Set the TNFD reporting period on Companies first.");
    const s = settings[job.id] ?? NO_SETTINGS;
    // Identify and Documents ran as checkpoints, so the run must not repeat them; a skipped stage keeps the user's setting.
    const step: StepSettings = {
      ...s.stepSettings,
      ...(flow.identify.state !== "skipped" ? { pre_identity_enabled: false } : {}),
      ...(flow.documents.state !== "skipped" ? { pre_content_search_enabled: false, pre_document_mgmt_enabled: false } : {}),
    };
    const res = await api.startExtraction({
      profile: job.profile,
      datapoint_schema: job.profile === "custom" ? job.schema : undefined,
      trial: isTrial(job),
      as_of: job.profile === "tnfd" ? asOf : undefined,
      ...(inputs.length === 1 ? { universe_path: inputs[0].path } : { companies: mergeCompanies(inputs) }),
      decision_framework_id: s.templateId ?? undefined,
      step_settings: Object.keys(step).length ? step : undefined,
    });
    restarted(job, res.run_id);
    return res.run_id;
  }

  const startingRef = useRef(false);
  async function startAll() {
    if (startingRef.current) return; // a second Start while the first is still starting jobs
    if (!inputs.length) {
      setError("Nothing to extract yet: carry the companies through Identify and Documents, or skip those stages.");
      return;
    }
    if (!toStart.length) {
      setError("Every ready job already has a run: restart one in Extract › Run, or finish a Custom schema.");
      return;
    }
    startingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const { started, errors } = await startJobs(toStart, startOne);
      setStartErrors(errors);
      if (!Object.keys(errors).length) dispatch({ type: "staleCleared" });
      if (Object.keys(started).length) setSub((s) => ({ ...s, extract: "run" }));
    } finally {
      startingRef.current = false;
      setBusy(false);
    }
  }
  const startRef = useRef(startAll);
  startRef.current = startAll;
  const flowRef = useRef(flow);
  flowRef.current = flow;

  const { extractRuns, extractStale, freshJobs } = flow;
  const startable = toStart.length;
  const extract = useMemo(() => {
    const lines = jobs.map((j) => {
      // A ready job without a run waits to start ("ready"); one that cannot start yet stays "idle".
      const r: JobStatus = j.id in extractRuns ? statuses[j.id] ?? { status: "running", counts: null } : { status: jobReady(j) ? "ready" : "idle", counts: null };
      const status: StageState =
        !(j.id in extractRuns) || r.status === "running" ? r.status
        : extractStale && !freshJobs.includes(j.id) ? "stale"
        : r.status === "done" && (pending[j.id] ?? 0) > 0 ? "review"
        : r.status;
      const scoring = !(j.id in extractRuns) || status === "running" ? null : frameworks[j.id] ?? null;
      return { id: j.id, label: jobLabel(j), status, counts: r.counts, ready: jobReady(j), scoring };
    });
    return { jobs: lines, status: worstStatus(lines.map((l) => l.status)), startable: busy || !inputCount ? 0 : startable };
  }, [jobs, extractRuns, extractStale, freshJobs, statuses, pending, frameworks, busy, inputCount, startable]);
  const extractStatus = extract.status;

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
      setSub((prev) => ({ ...prev, [step]: step === "extract" && s !== "setup" && !hasRuns ? "setup" : s }));
    },
    [hasRuns],
  );
  const openJob = useCallback(
    (id: string) => {
      setActiveJobId(id);
      openTab("extract", "review");
    },
    [openTab],
  );
  const onStart = useCallback((step: StageId | "extract") => {
    if (step === "extract") startRef.current();
    // Skip means the stage does not run.
    else if (flowRef.current[step].state !== "skipped") (step === "identify" ? identifyRef : documentsRef).current?.start();
  }, []);
  const onFramework = useCallback((id: string, name: string | null) => setFrameworks((m) => (m[id] === name ? m : { ...m, [id]: name })), []);

  // Automatic handover advances the tab once, when the stage turns done; a later manual tab change stays.
  const { identify, documents } = flow;
  const prevState = useRef({ identify: identify.state, documents: documents.state });
  useEffect(() => {
    const now = { identify, documents };
    for (const id of STAGES) {
      if (now[id].state === "done" && prevState.current[id] !== "done" && now[id].handover === "auto") {
        setTab(id === "identify" ? "documents" : hasCustom ? "schema" : "extract");
      }
    }
    prevState.current = { identify: identify.state, documents: documents.state };
  }, [identify, documents, hasCustom]);
  const onStop = useCallback((id: string) => {
    api.cancelRun(id).catch((err) => setError(`Run could not be stopped: ${(err as Error).message}`));
  }, []);
  const onContinue = useCallback((stage: StageId) => (stage === "identify" ? identifyRef : documentsRef).current?.carryOn(), []);

  const allAuto = STAGES.some((id) => flow[id].handover === "auto") && STAGES.every((id) => flow[id].handover !== "manual");
  const totalPending = runJobs.reduce((n, j) => n + (pending[j.id] ?? 0), 0);

  const steps: StepTab[] = [
    { id: "companies", label: "Companies", mark: flow.readinessNote ? "attention" : flow.companies ? "done" : null },
    { id: "identify", label: "Identify", mark: MARK[flow.identify.state] },
    { id: "documents", label: "Documents", mark: MARK[flow.documents.state] },
    ...(hasCustom ? [{ id: "schema", label: "Schema", mark: jobs.every(jobReady) ? ("done" as const) : null }] : []),
    { id: "extract", label: "Extract", mark: MARK[extractStatus] },
  ];
  const topTabs: StepTab[] = [{ id: "overview", label: "Overview" }, ...steps.map((t, i) => ({ ...t, label: `${i + 1}. ${t.label}` }))];
  const extractTabs: StepTab[] = [
    { id: "setup", label: "Setup" },
    { id: "run", label: "Run", disabled: !hasRuns },
    { id: "review", label: "Review", disabled: !hasRuns, badge: totalPending, mark: runJobs.some((j) => extract.jobs.find((l) => l.id === j.id)?.status === "review") ? "waiting" : null },
  ];
  const jobTypes = [...new Set(jobs.map(jobRunType))];
  const allTypes = ["identity", "discovery", ...jobTypes];
  const tabRunTypes = { overview: allTypes, companies: allTypes, schema: allTypes, identify: ["identity"], documents: ["discovery"], extract: jobTypes }[tab];
  const overviewSelected = (overviewRun && Object.values(flow.extractRuns).includes(overviewRun) ? overviewRun : null) ?? latestExtractRun(flow);
  const tabRunId =
    tab === "identify" || tab === "documents" ? flow[tab].runId
    : tab === "extract" ? (reviewJob ? extractRuns[reviewJob.id] : null)
    : tab === "overview" ? overviewSelected
    : null;
  const jobOfRun = (id: string) => jobs.find((j) => extractRuns[j.id] === id);
  const openRun = (id: string, s: Sub = "run") => {
    const job = jobOfRun(id);
    if (job) {
      setActiveJobId(job.id);
      openTab("extract", s);
    } else for (const st of STAGES) if (flow[st].runId === id) openTab(st, s);
  };
  const innerTabs = (id: Inner, tabs: StepTab[], label: string) => (
    <StepTabs label={label} tabs={tabs} active={sub[id]} onSelect={(v) => setSub((s) => ({ ...s, [id]: v as Sub }))} />
  );
  const jobSwitch = (list: Job[], current: string | undefined, label: string) => (
    <div className="view-toggle job-switch" role="group" aria-label={label}>
      {list.map((j) => (
        <button key={j.id} className={j.id === current ? "active" : ""} aria-pressed={j.id === current} onClick={() => setActiveJobId(j.id)}>
          {jobLabel(j)}
          {startErrors[j.id] ? " — failed to start" : ""}
        </button>
      ))}
    </div>
  );

  const runsPanel = (
    <FlowRuns
      key={tab}
      runTypes={tabRunTypes}
      runIds={flow.runIds}
      selected={tabRunId}
      onSelect={(id) => (tab === "overview" && id in runProfiles ? setOverviewRun(id) : openRun(id))}
      onReview={(r) => openRun(r.run_id, "review")}
      onRerun={(r) => (r.run_type === "identity" ? onStart("identify") : r.run_type === "discovery" ? onStart("documents") : openRun(r.run_id, "run"))}
      compact={tab === "companies" || tab === "schema"}
      storageKey={`flowRuns:${tab}`}
    />
  );
  const s = settings[activeJob.id] ?? NO_SETTINGS;

  return (
    <div className="page">
      <h1>Extraction</h1>
      <p className="help-text">Extract data points from company disclosures, each checked by a verifier and every citation re-verified against its source. Pick one or more profiles: your own Custom schemas, or the built-in Financials, TNFD and Transition Plan. Each runs as its own extraction on the same companies.</p>

      <StepTabs label="Extraction steps" tabs={topTabs} active={tab} onSelect={(id) => setTab(id as Tab)} />
      {tab !== "overview" && (
        <>
          <button type="button" className="link-button" onClick={() => setTab("overview")}>
            ← Overview
          </button>
          {runsPanel}
        </>
      )}

      {error && <p className="error-text" role="alert">{error}</p>}

      <div role="tabpanel" aria-label="Overview" hidden={tab !== "overview"}>
        <Overview
          jobs={jobs}
          onToggle={toggle}
          pickerError={pickerError}
          allAuto={allAuto}
          onAllAuto={(on) => dispatch({ type: "allAuto", on })}
          chart={
            <StageFlowChart
              flow={flow}
              profile={hasCustom ? "custom" : jobs[0].profile}
              extract={extract}
              height={420}
              counts={counts}
              onOpen={openTab}
              onOpenJob={openJob}
              onStart={onStart}
              onStop={onStop}
              onContinue={onContinue}
              dispatch={dispatch}
            />
          }
          scoring={<ScoringSummary rows={runJobs.map((j) => ({ job: j, runId: extractRuns[j.id], status: extract.jobs.find((l) => l.id === j.id)!.status }))} onOpen={openJob} onFramework={onFramework} />}
          runs={tab === "overview" ? runsPanel : <></>}
          selectedRunId={overviewSelected}
          selectedProfile={overviewSelected ? runProfiles[overviewSelected] ?? null : null}
          onRestarted={(next) => {
            const job = overviewSelected ? jobOfRun(overviewSelected) : undefined;
            if (job) restarted(job, next);
            setOverviewRun(next);
          }}
        />
      </div>

      <div role="tabpanel" aria-label="Companies" hidden={tab !== "companies"}>
        <CompaniesPanel flow={flow} dispatch={dispatch} pendingUniverse={pendingUniverse} tnfd={jobs.some((j) => j.profile === "tnfd")} asOf={asOf} onAsOf={setAsOf} />
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

      {hasCustom && (
        <div role="tabpanel" aria-label="Schema" hidden={tab !== "schema"}>
          <SchemaPanel jobs={jobs} onChange={changeJobs} nextCustomId={nextCustomId} defaultRequest={DEFAULT_CRITERIA} />
        </div>
      )}

      <div role="tabpanel" aria-label="Extract" hidden={tab !== "extract"}>
        {innerTabs("extract", extractTabs, "Extract")}

        <div hidden={sub.extract !== "setup"}>
          {jobSwitch(jobs, activeJob.id, "Job to set up")}
          {jobs.map((j) => startErrors[j.id] && (
            <p key={j.id} className="error-text" role="alert">
              {jobLabel(j)} did not start: {startErrors[j.id]}
            </p>
          ))}
          <section className="card">
            <h2>Pipeline: {jobLabel(activeJob)}</h2>
            <p className="help-text">
              The steps every item goes through. Optional: click a step to change its settings for this job&apos;s run only; the
              app&apos;s defaults stay as they are.
            </p>
            <PipelineEditor key={activeJob.id} profile={activeJob.profile} value={s.stepSettings} onChange={(v) => patchSettings(activeJob.id, { stepSettings: v })} />
          </section>
          <section className="card">
            <h2>Score the results (optional)</h2>
            <p className="help-text">
              Attach a Decision Studio framework: once every company is extracted, the run applies its rules as the last step
              and stores the scores and tiers with the run. You can also attach one after the run.
            </p>
            <ScoringTemplatePicker
              key={activeJob.id}
              runType={jobRunType(activeJob)}
              fieldNames={activeJob.profile === "custom" ? activeJob.schema?.fields.map((f) => f.name) ?? [] : undefined}
              value={s.templateId}
              onChange={(v) => patchSettings(activeJob.id, { templateId: v })}
            />
          </section>
          <section className="card">
            <h2>Start extraction</h2>
            <p className="help-text">
              {inputs.length
                ? startsText(toStart.length, inputCount)
                : "No companies handed over yet: carry them through Identify and Documents, or skip those stages."}
            </p>
            {inputs.length > 0 && leftOut > 0 && <p className="await-text">{leftOut} companies are still onboarding and will be left out</p>}
            {toStart.some(isTrial) && <p className="await-text">Trial run: the custom schema is not released, so results are not final.</p>}
            {flow.extractStale && <p className="await-text">Inputs changed since this run</p>}
            <button onClick={startAll} disabled={busy || !canStart}>
              Start extraction
            </button>
          </section>
        </div>

        <div hidden={sub.extract !== "run"}>
          {runJobs.map((j) => (
            <JobRun
              key={`${j.id}:${extractRuns[j.id]}`}
              job={j}
              runId={extractRuns[j.id]}
              onRestarted={(next) => restarted(j, next)}
              onStatus={(st) => setStatuses((m) => ({ ...m, [j.id]: st }))}
            />
          ))}
        </div>

        <div hidden={sub.extract !== "review"}>
          {hasRuns && jobSwitch(runJobs, reviewJob?.id, "Job to review")}
          {runJobs.map((j) => (
            <div key={`${j.id}:${extractRuns[j.id]}`} hidden={j.id !== reviewJob?.id}>
              <JobReview job={j} runId={extractRuns[j.id]} reviewer={reviewer} onSourceOpen={noop} onPending={(n) => setPending((m) => ({ ...m, [j.id]: n }))} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
