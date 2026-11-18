import { drawing, type Shape } from "../lib/workspaceDrawing";
import type { WorkspaceId } from "../lib/processes";

/** The start page's wireframe drawing of a workspace. One shape lights up: amber when the
 * workspace waits on a person, the running colour when it runs (DESIGN.md, The Icon Accent Rule). */
export function WorkspaceDrawing({ id, accent }: { id: WorkspaceId; accent: "wait" | "now" | null }) {
  return <Drawing shapes={drawing(id, accent)} accent={accent} />;
}

/** Any start-page drawing (a workspace's or the cockpit's), in the same wireframe style. */
export function Drawing({ shapes, accent = null }: { shapes: Shape[]; accent?: "wait" | "now" | null }) {
  return (
    <svg className="ws-drawing" viewBox="0 0 200 156" aria-hidden="true" focusable="false">
      {shapes.map((s, i) => (
        <path key={i} d={s.d} className={`ws-${s.part}${s.accent && accent ? ` ws-accent-${accent}` : ""}`} />
      ))}
    </svg>
  );
}
