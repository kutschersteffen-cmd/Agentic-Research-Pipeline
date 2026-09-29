import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StewardshipFlow, StewardshipStream } from "../types";
import { SOURCE_LABEL, openCount } from "./steward/common";
import { useReviewer } from "../lib/reviewer";
import { FlowChart, FlowList } from "./steward/flow";
import { DraftingStudio } from "./steward/drafting";
import { ProgramStudio } from "./steward/program";
import { TrackingStudio } from "./steward/tracking";
import {
  CheckpointStudio,
  ClientPicker,
  ClientPolicyStudio,
  MonitoringStudio,
  ReportingStudio,
  SelectionStudio,
  VotingStudio,
} from "./steward/studios";
import type { MetricSource } from "../types";

// One tab per stage of docs/STEWARDSHIP_OPERATING_MODEL.md, Part 2. Stages 1-6
// are house truth and always show the house program; 7-8 work on a client stream.
export const STAGE_TABS = [
  { id: "monitoring", n: 1, label: "Monitoring" },
  { id: "selection", n: 2, label: "Selection" },
  { id: "drafting", n: 3, label: "Drafting" },
  { id: "voting", n: 4, label: "Voting" },
  { id: "checkpoint", n: 5, label: "Checkpoint" },
  { id: "tracking", n: 6, label: "Tracking" },
  { id: "client_policy", n: 7, label: "Client policy" },
  { id: "reporting", n: 8, label: "Reporting" },
  { id: "program", n: null, label: "Client program" },
] as const;
// "program" is not a stage: it calibrates a client program across stages 2-5 (Part 5).
const CLIENT_STAGES = new Set(["client_policy", "reporting", "program"]);

/** Which companies the house program covers (see backend stewardship/universe.py).
 * Portfolio holdings make stewardship share company ids with Risk Monitoring,
 * Proxy Voting and Decision Studio, so their handoffs match. */
function HouseUniverse({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<Awaited<ReturnType<typeof api.getHouseUniverse>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewer] = useReviewer();
  useEffect(() => {
    api.getHouseUniverse().then(setInfo, (e: Error) => setError(e.message));
  }, []);
  async function choose(source: "sample" | "portfolio") {
    setError(null);
    try {
      await api.setHouseUniverse({ source, set_by: reviewer });
      setInfo(await api.getHouseUniverse());
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!info) return error ? <p className="error-text">{error}</p> : null;
  return (
    <div className="toolbar">
      <span className="muted">Companies covered:</span>
      {(["sample", "portfolio"] as const).map((s) => (
        <button
          key={s}
          className={info.source === s ? "nav-tab active" : "nav-tab"}
          aria-pressed={info.source === s}
          disabled={!reviewer.trim() && info.source !== s}
          onClick={() => info.source !== s && choose(s)}
        >
          {s === "sample" ? "Synthetic sample" : "Portfolio holdings"}
        </button>
      ))}
      <span className="muted">
        {info.issuers} companies{info.set_by ? ` · set by ${info.set_by}` : ""}
        {!reviewer.trim() && " · enter your name in the sidebar to change it"}
      </span>
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}

function AddStream({ onCreated }: { onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [vehicle, setVehicle] = useState("SMA");
  const [policy, setPolicy] = useState<unknown | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function readFile(file: File | undefined) {
    setError(null);
    if (!file) return;
    try {
      setPolicy(JSON.parse(await file.text()));
      setFileName(file.name);
    } catch {
      setError("That file is not valid JSON.");
    }
  }
  async function create() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.createStewardshipStream({ name, vehicle_type: vehicle, client_policy: policy ?? undefined });
      onCreated(res.stream_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h3>Add a client stream</h3>
      <p className="help-text">
        A client stream runs the house process with the client's own policy on top. Start from the client's envisioned voting
        policy as a questionnaire (JSON, positions on the issue catalogue), or from the built-in example to try it out.
      </p>
      <div className="inline-fields">
        <input aria-label="Client name" placeholder="Client name" value={name} onChange={(e) => setName(e.target.value)} />
        <select aria-label="Vehicle type" value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
          <option value="SMA">SMA (segregated)</option>
          <option value="CCF">CCF (pooled)</option>
          <option value="ETF">ETF (pooled)</option>
        </select>
        <label className="link-button file-button">
          {fileName ?? "Upload client policy (optional)"}
          <input type="file" accept="application/json,.json" onChange={(e) => readFile(e.target.files?.[0])} hidden />
        </label>
        <button onClick={create} disabled={!name.trim() || busy}>
          {busy ? "Creating…" : "Create stream"}
        </button>
      </div>
      {!policy && <p className="muted">No file chosen: the stream starts from the example envisioned policy.</p>}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}

/** The stage lives in the URL (`#/stewardship/<stage>`), so Back moves between
 * stages and a process step can open a stage studio directly. */
export function StewardWorkflow({ initialTab }: { initialTab?: string }) {
  const tab: string = STAGE_TABS.some((t) => t.id === initialTab) ? initialTab! : "overview";
  const [streams, setStreams] = useState<StewardshipStream[]>([]);
  const [stream, setStream] = useState("house");
  const [houseFlow, setHouseFlow] = useState<StewardshipFlow | null>(null);
  const [clientFlow, setClientFlow] = useState<StewardshipFlow | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadStreams = useCallback(async () => {
    try {
      setStreams((await api.listStewardshipStreams()).streams);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setHouseFlow(await api.getStewardshipFlow("house"));
      setClientFlow(stream === "house" ? null : await api.getStewardshipFlow(stream));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [stream]);

  useEffect(() => {
    loadStreams();
  }, [loadStreams]);
  useEffect(() => {
    reload();
  }, [reload]);

  // Client stages default to the first client stream when the house is selected.
  const firstClient = streams.find((s) => s.kind === "client")?.stream_id;
  function openTab(next: string) {
    setAdding(false);
    if (CLIENT_STAGES.has(next) && stream === "house" && firstClient) setStream(firstClient);
    window.location.hash = next === "overview" ? "/stewardship" : `/stewardship/${next}`;
  }

  const overviewFlow = stream === "house" ? houseFlow : clientFlow;
  const stageFor = (id: string) => (CLIENT_STAGES.has(id) ? (stream === "house" ? houseFlow : clientFlow) : houseFlow)?.stages.find((s) => s.id === id);
  const stage = tab === "overview" ? undefined : stageFor(tab);
  const mandate = overviewFlow?.stream.mandate;
  const studioProps = stage ? { stage, onChanged: reload, onOpen: openTab } : null;

  return (
    <div className="page">
      <h2>Steward Workflow</h2>
      <p className="help-text">
        The stewardship process end to end. The overview shows every stage with its key numbers and the decisions waiting; each stage
        has its own studio to review its data, design and calibrate its rules, and take its decisions.
      </p>

      <nav className="sub-nav workflow-tabs stepper" aria-label="Workflow stages">
        <button className={tab === "overview" ? "nav-tab active" : "nav-tab"} aria-current={tab === "overview" ? "step" : undefined} onClick={() => openTab("overview")}>
          Overview
        </button>
        {STAGE_TABS.map((t) => {
          const n = openCount(stageFor(t.id));
          return (
            <span key={t.id} className="stepper-item">
              {t.id === "monitoring" && <span className="stepper-group">House</span>}
              {t.id === "client_policy" && (
                <>
                  <span className="stepper-break" />
                  <span className="stepper-group">Client</span>
                </>
              )}
              <button
                className={tab === t.id ? "nav-tab active" : "nav-tab"}
                aria-current={tab === t.id ? "step" : undefined}
                aria-label={n > 0 ? `${t.label}, ${n} open decisions` : undefined}
                onClick={() => openTab(t.id)}
              >
                {t.n && <span className="stepper-num">{t.n}</span>}
                {t.label}
                {n > 0 && <span className="tab-badge">{n}</span>}
              </button>
            </span>
          );
        })}
      </nav>

      {error && <p className="error-text">{error}</p>}

      {tab === "overview" && (
        <>
          <nav className="sub-nav" aria-label="Process streams">
            {streams.map((s) => (
              <button
                key={s.stream_id}
                className={s.stream_id === stream && !adding ? "nav-tab active" : "nav-tab"}
                onClick={() => {
                  setAdding(false);
                  setStream(s.stream_id);
                }}
              >
                {s.name}
              </button>
            ))}
            <button className={adding ? "nav-tab active" : "nav-tab"} onClick={() => setAdding(true)}>
              + Client stream
            </button>
          </nav>
          {adding && (
            <AddStream
              onCreated={async (id) => {
                await loadStreams();
                setAdding(false);
                setStream(id);
              }}
            />
          )}
          {!adding && overviewFlow && (
            <section className="card">
              <div className="section-heading">
                <h3>{overviewFlow.stream.name}</h3>
                {mandate && (
                  <span className="chip">
                    {[mandate.vehicle_type, mandate.benchmark, mandate.voting_mode && mandate.voting_mode.replace(/_/g, " ")].filter(Boolean).join(" · ")}
                  </span>
                )}
                {loading && <span className="muted">Refreshing…</span>}
              </div>
              <div className="chip-row source-legend">
                {(Object.keys(SOURCE_LABEL) as MetricSource[]).map((s) => (
                  <span key={s} className="chip">
                    <span className={`source-dot source-${s}`} /> {SOURCE_LABEL[s]}
                  </span>
                ))}
              </div>
              {stream === "house" && <HouseUniverse onChanged={reload} />}
              <p className="muted">{overviewFlow.data_note} Click a stage to open its studio.</p>
              <FlowChart flow={overviewFlow} selected="" onSelect={openTab} />
              <FlowList flow={overviewFlow} selected="" onSelect={openTab} />
            </section>
          )}
        </>
      )}

      {tab !== "overview" && CLIENT_STAGES.has(tab) && <ClientPicker streams={streams} active={stream} onChange={setStream} onOpen={openTab} />}
      {tab !== "overview" && CLIENT_STAGES.has(tab) && stream === "house" && (
        <p className="muted card">Choose a client stream above (or create one on the overview) to work on its policy and reporting.</p>
      )}
      {tab !== "overview" && tab !== "program" && !stage && loading && <p className="status-text">Loading…</p>}

      {studioProps && tab === "monitoring" && <MonitoringStudio {...studioProps} />}
      {studioProps && tab === "selection" && <SelectionStudio {...studioProps} />}
      {studioProps && tab === "drafting" && <DraftingStudio {...studioProps} />}
      {studioProps && tab === "voting" && <VotingStudio {...studioProps} />}
      {studioProps && tab === "checkpoint" && <CheckpointStudio {...studioProps} />}
      {studioProps && tab === "tracking" && <TrackingStudio {...studioProps} />}
      {studioProps && tab === "client_policy" && stream !== "house" && <ClientPolicyStudio key={stream} {...studioProps} streamId={stream} />}
      {studioProps && tab === "reporting" && stream !== "house" && <ReportingStudio key={stream} {...studioProps} streamId={stream} />}
      {tab === "program" && stream !== "house" && <ProgramStudio key={stream} streamId={stream} />}
    </div>
  );
}
