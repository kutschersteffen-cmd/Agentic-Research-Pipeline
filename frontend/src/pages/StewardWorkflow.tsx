import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StewardshipFlow, StewardshipStage, StewardshipStream } from "../types";
import { SOURCE_LABEL } from "./steward/common";
import { FlowChart, FlowList } from "./steward/flow";
import {
  CheckpointStudio,
  ClientPicker,
  ClientPolicyStudio,
  DraftingStudio,
  MonitoringStudio,
  ReportingStudio,
  SelectionStudio,
  TrackingStudio,
  VotingStudio,
} from "./steward/studios";
import type { MetricSource } from "../types";

// One tab per stage of docs/STEWARDSHIP_OPERATING_MODEL.md, Part 2. Stages 1-6
// are house truth and always show the house program; 7-8 work on a client stream.
const STAGE_TABS = [
  { id: "monitoring", label: "1 Monitoring" },
  { id: "selection", label: "2 Selection" },
  { id: "drafting", label: "3 Drafting" },
  { id: "voting", label: "4 Voting" },
  { id: "checkpoint", label: "5 Checkpoint" },
  { id: "tracking", label: "6 Tracking" },
  { id: "client_policy", label: "7 Client policy" },
  { id: "reporting", label: "8 Reporting" },
] as const;
const CLIENT_STAGES = new Set(["client_policy", "reporting"]);

const openCount = (stage: StewardshipStage | undefined) =>
  stage ? stage.decisions.filter((d) => d.kind !== "policy_difference" || d.decision === null).length : 0;

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

export function StewardWorkflow() {
  const [tab, setTab] = useState<string>("overview");
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
    setTab(next);
    if (CLIENT_STAGES.has(next) && stream === "house" && firstClient) setStream(firstClient);
    window.scrollTo({ top: 0 });
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

      <nav className="sub-nav workflow-tabs" aria-label="Workflow stages">
        <button className={tab === "overview" ? "nav-tab active" : "nav-tab"} onClick={() => openTab("overview")}>
          Overview
        </button>
        {STAGE_TABS.map((t) => {
          const n = openCount(stageFor(t.id));
          return (
            <button key={t.id} className={tab === t.id ? "nav-tab active" : "nav-tab"} onClick={() => openTab(t.id)}>
              {t.label}
              {n > 0 && <span className="tab-badge">{n}</span>}
            </button>
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
      {tab !== "overview" && !stage && loading && <p className="status-text">Loading…</p>}

      {studioProps && tab === "monitoring" && <MonitoringStudio {...studioProps} />}
      {studioProps && tab === "selection" && <SelectionStudio {...studioProps} />}
      {studioProps && tab === "drafting" && <DraftingStudio {...studioProps} />}
      {studioProps && tab === "voting" && <VotingStudio {...studioProps} />}
      {studioProps && tab === "checkpoint" && <CheckpointStudio {...studioProps} />}
      {studioProps && tab === "tracking" && <TrackingStudio {...studioProps} />}
      {studioProps && tab === "client_policy" && stream !== "house" && <ClientPolicyStudio key={stream} {...studioProps} streamId={stream} />}
      {studioProps && tab === "reporting" && stream !== "house" && <ReportingStudio key={stream} {...studioProps} streamId={stream} />}
    </div>
  );
}
