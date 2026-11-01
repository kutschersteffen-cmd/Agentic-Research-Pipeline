import { createContext, useContext, useMemo, type ComponentProps, type ReactNode } from "react";
import { Background, BackgroundVariant, Handle, useNodeId, type Edge } from "reactflow";

/** Shared pieces of every flow canvas: the dot-grid ground and connection dots that show only where an edge attaches. */
const Linked = createContext<Set<string>>(new Set());

const handleKey = (node: string, handle: string | null | undefined, type: "source" | "target") => `${node}:${handle ?? type}`;

export function LinkedHandles({ edges, children }: { edges: Edge[]; children: ReactNode }) {
  const linked = useMemo(
    () => new Set(edges.flatMap((e) => [handleKey(e.source, e.sourceHandle, "source"), handleKey(e.target, e.targetHandle, "target")])),
    [edges],
  );
  return <Linked.Provider value={linked}>{children}</Linked.Provider>;
}

export function FlowHandle(props: ComponentProps<typeof Handle>) {
  const node = useNodeId() ?? "";
  const linked = useContext(Linked).has(handleKey(node, props.id, props.type));
  return <Handle {...props} className={linked ? "linked" : undefined} />;
}

export const DotGrid = () => <Background variant={BackgroundVariant.Dots} gap={18} size={1.4} />;
