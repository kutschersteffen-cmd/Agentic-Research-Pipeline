import { useEffect, useMemo, useState } from "react";
import ReactFlow, { Controls, Handle, MarkerType, Position, getNodesBounds, useReactFlow, useStore, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import { COARSE_POINTER, layoutPipeline } from "../lib/pipelineLayout";
import { extractInputs, type FlowAction, type FlowState, type FlowStep, type Handover, type StageId, type StageState } from "../lib/stagedFlow";
import type { ExtractionProfile, PipelineShape } from "../types";

const CARD_W = 214;
const COL_W = CARD_W + 56;

export interface JobLine { id: string; label: string; status: StageState; counts: string | null; ready: boolean; scoring: string | null }
/** `startable`: how many runs Start would launch now (0 disables Start / Run again). */
export interface ExtractNodeInfo { jobs: JobLine[]; status: StageState; startable: number }

type NodeId = "companies" | StageId | "schema" | "extract" | "scoring" | "results";
type Sub = "setup" | "run" | "review";

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
  lines: { id: string; text: string; word: string; warn: boolean }[];
  onOpenJob: (id: string) => void;
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
          {data.counts && <span className="pipeline-card-footer">{data.counts}</span>}
          {data.note && <span className="pipeline-card-footer">{data.note}</span>}
        </button>
        {data.lines.length > 0 && (
          <div className="stage-card-jobs">
            {data.lines.map((l) => (
              <button type="button" key={l.id} className={`nodrag stage-job-line${l.warn ? " warn" : ""}`} onClick={() => data.onOpenJob(l.id)}>
                <span className="stage-job-label">{l.text}</span>
                <span className="stage-job-word">{l.word}</span>
              </button>
            ))}
          </div>
        )}
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
const FIT = { padding: 0.05 };
// Never fit smaller than this: 13px labels stay >= 11px. A wider chart overflows and pans instead.
const MIN_ZOOM = 0.85;

/** Reports the measured nodes' width / height once React Flow has sized them, and refits when that changes. */
function FitAspect({ onAspect }: { onAspect: (a: number) => void }) {
  const key = useStore((st) => {
    const ns = Array.from(st.nodeInternals.values());
    if (!ns.length || ns.some((n) => !n.width)) return "";
    const r = getNodesBounds(ns);
    return `${Math.round(r.width)}x${Math.round(r.height)}`;
  });
  const box = useStore((st) => `${st.width}x${st.height}`);
  const { fitView, getViewport, setViewport } = useReactFlow();
  useEffect(() => {
    if (!key) return;
    const [w, h] = key.split("x").map(Number);
    onAspect(w / h);
  }, [key, onAspect]);
  // Refit once the box has taken its new size.
  useEffect(() => {
    if (!key) return;
    const t = requestAnimationFrame(() => {
      fitView(FIT);
      // Too wide to fit (a phone): start at the left edge, Companies first, and let the user pan.
      const v = getViewport();
      if (v.zoom <= MIN_ZOOM) setViewport({ ...v, x: 8 });
    });
    return () => cancelAnimationFrame(t);
  }, [key, box, fitView, getViewport, setViewport]);
  return null;
}

interface Props {
  flow: FlowState;
  profile: ExtractionProfile;
  extract: ExtractNodeInfo;
  height?: number;
  counts: Partial<Record<StageId | "companies", string>>;
  onOpen: (step: FlowStep, sub?: Sub) => void;
  onOpenJob: (jobId: string) => void;
  onStart: (step: StageId | "extract") => void;
  onStop: (runId: string) => void;
  onContinue: (stage: StageId) => void;
  dispatch: (a: FlowAction) => void;
}

/** Every stage on one line: state, counts, handover mode, schema and the run controls. Read-only canvas. */
export function StageFlowChart({ flow, profile, extract, height = 260, counts, onOpen, onOpenJob, onStart, onStop, onContinue, dispatch }: Props) {
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
      if (id === "schema") return extract.jobs.every((j) => j.ready) ? "done" : "idle";
      if (id === "extract") return extract.status;
      return id === "results" && extract.status === "done" ? "done" : "idle";
    };

    const stageData = (id: StageId): CardData => {
      const st = flow[id];
      return {
        label: id === "identify" ? "Identify" : "Documents",
        state: st.state,
        lines: [], onOpenJob,
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
      label, state, lines: [], onOpenJob, counts: countsLine, note: null, handover: null,
      startLabel: null, startDisabled: false, onStart: () => {}, onStop: null, onContinue: null, onCycle: () => {}, onOpen: open,
    });

    const jobLines = (pick: (j: JobLine) => string | null) =>
      extract.jobs.filter((j) => j.status !== "idle" && pick(j)).map((j) => ({ id: j.id, text: j.label, word: pick(j)!, warn: false }));

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
          const runIds = extract.jobs.filter((j) => j.status === "running").flatMap((j) => flow.extractRuns[j.id] ?? []);
          const running = runIds.length > 0;
          return {
            ...plain("Extract & verify", extract.status, reuses ? `reuses stored documents for ${reuses.count} companies` : null, () => onOpen("extract", extract.status === "review" ? "review" : "setup")),
            lines: extract.jobs.map((j) => ({ id: j.id, text: j.label, word: [j.status === "ready" ? "Ready to start" : STATE_WORD[j.status], j.counts].filter(Boolean).join(" · "), warn: !j.ready })),
            startLabel: running ? null : START_STATES.has(extract.status) || extract.startable > 0 ? "Start" : "Run again",
            startDisabled: extract.startable === 0,
            onStart: () => onStart("extract"),
            onStop: running ? () => runIds.forEach(onStop) : null,
          };
        }
        case "scoring":
          return { ...plain("Scoring", stageState(id), null, () => onOpen("extract", "setup")), lines: jobLines((j) => j.scoring) };
        default:
          return { ...plain("Results", stageState(id), null, () => onOpen("extract", "review")), lines: jobLines((j) => j.counts) };
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
  }, [flow, profile, extract, counts, onOpen, onOpenJob, onStart, onStop, onContinue, dispatch]);

  // The box takes the content's aspect ratio, capped at `height`, so a wide, short chart leaves no empty band.
  const [aspect, setAspect] = useState<number | null>(null);
  // Touch: the canvas does not pan, so it is drawn at full width and the page scrolls it sideways.
  const minWidth = COARSE_POINTER ? Math.ceil(((nodes.length - 1) * COL_W + CARD_W) * (1 + FIT.padding) * MIN_ZOOM) + 2 : undefined;
  return (
    <div className="chart-scroll">
    <div className="flow-rf stage-rf" style={aspect ? { width: "100%", minWidth, height: "auto", aspectRatio: aspect, maxHeight: height, minHeight: 180 } : { minWidth, height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={FIT}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={!COARSE_POINTER}
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        minZoom={MIN_ZOOM}
        maxZoom={1.2}
      >
        <Controls showInteractive={false} fitViewOptions={FIT} />
        <FitAspect onAspect={setAspect} />
      </ReactFlow>
    </div>
    </div>
  );
}
