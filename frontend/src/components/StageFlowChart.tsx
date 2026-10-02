import { useMemo } from "react";
import ReactFlow, { Controls, Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import { layoutPipeline } from "../lib/pipelineLayout";
import { when } from "../lib/runs";
import { extractInputs, latestExtractRun, type FlowAction, type FlowState, type FlowStep, type Handover, type StageId, type StageState } from "../lib/stagedFlow";
import type { DataPointSchema, ExtractionProfile, PipelineShape } from "../types";

const CARD_W = 214;
const COL_W = CARD_W + 56;

export interface ExtractNodeInfo { schemaLabel: string; ready: boolean; status: StageState; counts: string | null }

type NodeId = "companies" | StageId | "schema" | "extract" | "scoring" | "results";
type Sub = "setup" | "run" | "review";

/** The schema line on the Extract card, and whether Extract can start with it. */
// oxlint-disable-next-line react/only-export-components -- pure helper the parent calls beside the component
export function schemaLabel(profile: ExtractionProfile, schema: DataPointSchema | null): { label: string; ready: boolean } {
  switch (profile) {
    case "financials": return { label: "Financials: segments, CapEx, R&D", ready: true };
    case "tnfd": return { label: "TNFD: 14 recommendations + core metrics", ready: true };
    case "transition_plan": return { label: "Transition Plan: 64 indicators", ready: true };
    default:
      return schema
        ? { label: `${schema.name} · ${schema.fields.length} fields · ${when(schema.created_at)}`, ready: true }
        : { label: "No schema yet", ready: false };
  }
}

const STATE_WORD: Record<StageState, string> = {
  idle: "Not started",
  running: "Running",
  ready: "Waiting on you",
  review: "Needs review",
  done: "Done",
  skipped: "Skipped",
  stale: "Stale",
  failed: "Failed",
};
const STATE_CLASS: Record<StageState, string> = {
  idle: "status-idle",
  running: "status-running",
  ready: "status-done",
  review: "status-review",
  done: "status-done",
  skipped: "status-skipped",
  stale: "status-stale",
  failed: "status-failed",
};
const START_STATES = new Set<StageState>(["idle", "ready", "stale"]);
const NEXT_HANDOVER: Record<Handover, Handover> = { manual: "auto", auto: "skip", skip: "manual" };
const HANDOVER_WORD: Record<Handover, string> = { manual: "Manual", auto: "Automatic", skip: "Skip" };

interface CardData {
  label: string;
  state: StageState;
  line: { text: string; warn: boolean } | null;
  counts: string | null;
  note: string | null;
  handover: Handover | null;
  startLabel: string | null;
  startDisabled: boolean;
  onStart: () => void;
  onStop: (() => void) | null;
  onContinue: (() => void) | null;
  onCycle: () => void;
  onOpen: () => void;
}

function StageCard({ data }: NodeProps<CardData>) {
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <Handle id="bottom-in" type="target" position={Position.Bottom} />
      <div className={`pipeline-card stage-card ${STATE_CLASS[data.state]}`} style={{ width: CARD_W }}>
        <button type="button" className="nodrag stage-card-main" onClick={data.onOpen}>
          <span className="pipeline-card-head">
            <span className="pipeline-card-title">{data.label}</span>
            {data.state === "running" && <span className="pipeline-card-spinner" aria-hidden />}
          </span>
          <span className="stage-card-state">{STATE_WORD[data.state]}</span>
          {data.line && <span className={`stage-card-line${data.line.warn ? " warn" : ""}`}>{data.line.text}</span>}
          {data.counts && <span className="pipeline-card-footer">{data.counts}</span>}
          {data.note && <span className="pipeline-card-footer">{data.note}</span>}
        </button>
        {(data.handover || data.startLabel || data.onStop || data.onContinue) && (
          <div className="stage-card-actions">
            {data.handover && (
              <button
                type="button"
                className="nodrag stage-mode-chip"
                aria-label={`Handover mode: ${HANDOVER_WORD[data.handover]}. Click to change.`}
                onClick={data.onCycle}
              >
                {HANDOVER_WORD[data.handover]}
              </button>
            )}
            {data.startLabel && (
              <button type="button" className="nodrag" onClick={data.onStart} disabled={data.startDisabled}>
                {data.startLabel}
              </button>
            )}
            {data.onStop && (
              <button type="button" className="nodrag" onClick={data.onStop}>
                Stop
              </button>
            )}
            {data.onContinue && (
              <button type="button" className="nodrag" onClick={data.onContinue}>
                Continue →
              </button>
            )}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
      <Handle id="bottom-out" type="source" position={Position.Bottom} />
    </>
  );
}

const NODE_TYPES = { stage: StageCard };

interface Props {
  flow: FlowState;
  profile: ExtractionProfile;
  extract: ExtractNodeInfo;
  counts: Partial<Record<StageId | "companies", string>>;
  onOpen: (step: FlowStep, sub?: Sub) => void;
  onStart: (step: StageId | "extract") => void;
  onStop: (runId: string) => void;
  onContinue: (stage: StageId) => void;
  dispatch: (a: FlowAction) => void;
}

/** Every stage on one line: state, counts, handover mode, schema and the run controls. Read-only canvas. */
export function StageFlowChart({ flow, profile, extract, counts, onOpen, onStart, onStop, onContinue, dispatch }: Props) {
  const { nodes, edges } = useMemo(() => {
    const ids: NodeId[] = ["companies", "identify", "documents", ...(profile === "custom" ? (["schema"] as const) : []), "extract", "scoring", "results"];
    const links = ids.slice(1).map((target, i) => ({ source: ids[i], target }));
    const shape = {
      nodes: ids.map((id) => ({ id })),
      edges: links.map((l) => ({ ...l, conditional: false })),
    } as unknown as PipelineShape; // layoutPipeline reads only node ids and edges
    const positions = layoutPipeline(shape, COL_W, 0);

    const reuses = extractInputs(flow).find((o) => o === flow.ready);
    const stageState = (id: NodeId): StageState => {
      if (id === "identify" || id === "documents") return flow[id].state;
      if (id === "companies") return flow.companies ? "done" : "idle";
      if (id === "schema") return extract.ready ? "done" : "idle";
      if (id === "extract") return extract.status;
      return id === "results" && extract.status === "done" ? "done" : "idle";
    };

    const stageData = (id: StageId): CardData => {
      const st = flow[id];
      return {
        label: id === "identify" ? "Identify" : "Documents",
        state: st.state,
        line: null,
        counts: counts[id] ?? null,
        note: st.note,
        handover: st.handover,
        startLabel: st.state === "running" || st.state === "skipped" ? null : START_STATES.has(st.state) ? "Start" : "Run again",
        startDisabled: false,
        onStart: () => onStart(id),
        onStop: st.state === "running" && st.runId ? () => onStop(st.runId!) : null,
        onContinue: st.state === "ready" && st.handover === "manual" ? () => onContinue(id) : null,
        onCycle: () => dispatch({ type: "setHandover", stage: id, handover: NEXT_HANDOVER[st.handover] }),
        onOpen: () => onOpen(id, st.state === "review" ? "review" : "run"),
      };
    };

    const plain = (label: string, state: StageState, countsLine: string | null, open: () => void): CardData => ({
      label, state, line: null, counts: countsLine, note: null, handover: null,
      startLabel: null, startDisabled: false, onStart: () => {}, onStop: null, onContinue: null, onCycle: () => {}, onOpen: open,
    });

    const data = (id: NodeId): CardData => {
      switch (id) {
        case "identify":
        case "documents":
          return stageData(id);
        case "companies":
          return plain("Companies", stageState(id), counts.companies ?? null, () => onOpen("companies"));
        case "schema":
          return plain("Schema", stageState(id), null, () => onOpen("schema"));
        case "extract": {
          const running = extract.status === "running";
          return {
            ...plain("Extract & verify", extract.status, [extract.counts, reuses ? `reuses stored documents for ${reuses.count} companies` : null].filter(Boolean).join(" · ") || null, () => onOpen("extract", extract.status === "review" ? "review" : "setup")),
            line: { text: extract.schemaLabel, warn: !extract.ready },
            startLabel: running ? null : START_STATES.has(extract.status) ? "Start" : "Run again",
            startDisabled: !extract.ready,
            onStart: () => onStart("extract"),
            onStop: running && latestExtractRun(flow) ? () => onStop(latestExtractRun(flow)!) : null,
          };
        }
        case "scoring":
          return plain("Scoring", stageState(id), null, () => onOpen("extract", "setup"));
        default:
          return plain("Results", stageState(id), null, () => onOpen("extract", "review"));
      }
    };

    const nodes: Node<CardData>[] = ids.map((id) => ({
      id,
      type: "stage",
      position: positions[id] ?? { x: 0, y: 0 },
      draggable: false,
      // React Flow drops pointer events on nodes that are neither selectable nor draggable.
      style: { pointerEvents: "all" },
      data: data(id),
    }));

    const accent = "var(--hi)";
    const edges: Edge[] = links.map(({ source, target }) => {
      const src = source as NodeId;
      const dashed = stageState(src) === "skipped" || stageState(target as NodeId) === "skipped";
      const hot = (src === "identify" || src === "documents") && flow[src].state === "ready" && flow[src].handover === "manual";
      return {
        id: `${source}>${target}`,
        source,
        target,
        className: "flow-rf-edge",
        style: { ...(dashed ? { strokeDasharray: "5 4" } : {}), ...(hot ? { stroke: accent, strokeWidth: 2 } : {}) },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, ...(hot ? { color: accent } : {}) },
      };
    });
    if (reuses) {
      edges.push({
        id: "companies>extract",
        source: "companies",
        sourceHandle: "bottom-out",
        target: "extract",
        targetHandle: "bottom-in",
        type: "smoothstep",
        label: `${reuses.count} ready`,
        className: "flow-rf-edge",
        style: { strokeDasharray: "5 4" },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      });
    }
    return { nodes, edges };
  }, [flow, profile, extract, counts, onOpen, onStart, onStop, onContinue, dispatch]);

  return (
    <div className="flow-rf stage-rf">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={1.2}
      >
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
