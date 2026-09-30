import { useMemo, type CSSProperties } from "react";
import ReactFlow, { Controls, Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import type { StewardshipFlow, StewardshipStage } from "../../types";
import { SOURCE_LABEL, openCount } from "./common";

// Flowchart layout: the house row (stages 1-6) above the client row (7-8),
// as in docs/STEWARDSHIP_OPERATING_MODEL.md, Part 2. Drawn with React Flow
// (the same library the rule editor uses): pan, zoom and fit come with it.
const NODE_W = 200;
const NODE_H = 150;
const GAP = 44;
const HOUSE_Y = 60;
const CLIENT_Y = 330;
const X = (i: number) => i * (NODE_W + GAP);
const POSITIONS: Record<string, { x: number; y: number }> = {
  monitoring: { x: X(0), y: HOUSE_Y },
  selection: { x: X(1), y: HOUSE_Y },
  drafting: { x: X(2), y: HOUSE_Y },
  voting: { x: X(3), y: HOUSE_Y },
  checkpoint: { x: X(4), y: HOUSE_Y },
  tracking: { x: X(5), y: HOUSE_Y },
  client_policy: { x: X(4), y: CLIENT_Y },
  reporting: { x: X(5), y: CLIENT_Y },
};
const BANDS = [
  { id: "band-house", label: "House truth · stages 1–6 use house policies only", x: -20, y: HOUSE_Y - 44, w: X(6) - GAP + 40, h: NODE_H + 76 },
  { id: "band-client", label: "Client overlay · stages 7–8", x: X(4) - 20, y: CLIENT_Y - 44, w: 2 * NODE_W + GAP + 40, h: NODE_H + 76 },
];

// Which side of each node an edge leaves from and arrives at.
const EDGE_HANDLES: Record<string, { sourceHandle: string; targetHandle: string }> = {
  "tracking>monitoring": { sourceHandle: "top-out-a", targetHandle: "top-in-a" },
  "monitoring>client_policy": { sourceHandle: "bottom-out-a", targetHandle: "left-in" },
  "checkpoint>client_policy": { sourceHandle: "bottom-out-a", targetHandle: "top-in-a" },
  "client_policy>checkpoint": { sourceHandle: "top-out-b", targetHandle: "bottom-in-b" },
};

type StageNodeData = { stage: StewardshipStage; selected: boolean; onSelect: (id: string) => void };

function StageFlowNode({ data }: NodeProps<StageNodeData>) {
  return (
    <>
      <Handle id="left-in" type="target" position={Position.Left} />
      <Handle id="right-out" type="source" position={Position.Right} />
      <Handle id="top-in-a" type="target" position={Position.Top} style={{ left: "35%" }} />
      <Handle id="top-out-a" type="source" position={Position.Top} style={{ left: "35%" }} />
      <Handle id="top-out-b" type="source" position={Position.Top} style={{ left: "65%" }} />
      <Handle id="bottom-out-a" type="source" position={Position.Bottom} style={{ left: "35%" }} />
      <Handle id="bottom-in-b" type="target" position={Position.Bottom} style={{ left: "65%" }} />
      <StageNode stage={data.stage} selected={data.selected} onSelect={data.onSelect} style={{ width: NODE_W, height: NODE_H }} />
    </>
  );
}

function BandNode({ data }: NodeProps<{ label: string }>) {
  return <div className="flow-band-node">{data.label}</div>;
}

const NODE_TYPES = { stage: StageFlowNode, band: BandNode };

export function StageNode({ stage, selected, onSelect, style }: { stage: StewardshipStage; selected: boolean; onSelect: (id: string) => void; style?: CSSProperties }) {
  const open = openCount(stage);
  return (
    <button className={`flow-node flow-${stage.layer}${selected ? " selected" : ""}`} style={style} aria-pressed={selected} onClick={() => onSelect(stage.id)}>
      <span className="flow-node-head">
        <span className="flow-node-number">{stage.number}</span>
        <span className="flow-node-title">{stage.title}</span>
      </span>
      {stage.metrics.slice(0, 3).map((m) => (
        <span key={m.label} className={`flow-node-metric tone-${m.tone}`} title={`${m.label}: ${SOURCE_LABEL[m.source]}`}>
          <span className={`source-dot source-${m.source}`} />
          <span className="flow-node-metric-label">{m.label}</span>
          <strong>{m.value}</strong>
        </span>
      ))}
      {open > 0 && <span className="flow-node-badge">{open} to decide</span>}
    </button>
  );
}

/** Narrow screens: the same stages as a stacked list, in process order. */
export function FlowList({ flow, selected, onSelect }: { flow: StewardshipFlow; selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="flow-list">
      {(["house", "client"] as const).map((layer) => (
        <div key={layer}>
          <p className="flow-band-label">{layer === "house" ? "House truth · stages 1–6" : "Client overlay · stages 7–8"}</p>
          {flow.stages
            .filter((s) => s.layer === layer)
            .map((stage) => (
              <StageNode key={stage.id} stage={stage} selected={stage.id === selected} onSelect={onSelect} />
            ))}
        </div>
      ))}
      <p className="muted">Tracking loops back to monitoring; client exceptions go back to the human checkpoint.</p>
    </div>
  );
}

export function FlowChart({ flow, selected, onSelect }: { flow: StewardshipFlow; selected: string; onSelect: (id: string) => void }) {
  const nodes = useMemo<Node[]>(
    () => [
      ...BANDS.map((b) => ({
        id: b.id,
        type: "band",
        position: { x: b.x, y: b.y },
        data: { label: b.label },
        style: { width: b.w, height: b.h },
        selectable: false,
        draggable: false,
        zIndex: -1,
      })),
      ...flow.stages.map((stage) => ({
        id: stage.id,
        type: "stage",
        position: POSITIONS[stage.id],
        data: { stage, selected: stage.id === selected, onSelect },
        draggable: false,
      })),
    ],
    [flow, selected, onSelect],
  );
  const edges = useMemo<Edge[]>(
    () =>
      flow.edges.map((e) => ({
        id: `${e.from}>${e.to}`,
        source: e.from,
        target: e.to,
        ...(EDGE_HANDLES[`${e.from}>${e.to}`] ?? { sourceHandle: "right-out", targetHandle: "left-in" }),
        type: "smoothstep",
        label: e.label,
        labelBgPadding: [4, 2] as [number, number],
        className: "flow-rf-edge",
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        zIndex: 1,
      })),
    [flow],
  );
  return (
    <div className="flow-rf">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.06 }}
        minZoom={0.35}
        maxZoom={1.6}
        onNodeClick={(_, node) => node.type === "stage" && onSelect(node.id)}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
        zoomOnDoubleClick={false}
      >
        <Controls showInteractive={false} position="top-right" />
      </ReactFlow>
    </div>
  );
}
