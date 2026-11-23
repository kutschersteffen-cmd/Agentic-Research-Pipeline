import { useId, useLayoutEffect, useRef, useState } from "react";
import { clamp01, drawing, samePart, type Accent, type Shape } from "../lib/workspaceDrawing";
import type { WorkspaceId } from "../lib/processes";

type Status = Accent | "none";
/** Milliseconds of the status part's move and of the figure area's flash. */
const MOVE_MS = 850;
const FLASH_MS = 950;
// Out with a slight overshoot; back in eased.
const back = (x: number) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

type Pose = { acc: Accent | null; out: number; moving: boolean; flash: boolean };
const rest = (s: Status): Pose => ({ acc: s === "none" ? null : s, out: s === "none" ? 0 : 1, moving: false, flash: false });

/** A workspace's drawing. It is still; only its status part is lit (amber when the workspace waits on a person,
 * the running colour when it runs) and out of place while lit. `known` is false until the runs have loaded: the
 * status is then `none`, and the first known status is drawn in place. Every later change moves the part once, in
 * 850 ms, and flashes the figure area (DESIGN.md, The Icon Accent Rule). */
export function WorkspaceDrawing({ id, accent, known = true }: { id: WorkspaceId; accent: Accent | null; known?: boolean }) {
  const status: Status = known && accent ? accent : "none";
  const [pose, setPose] = useState<Pose>(() => rest(status));
  // Where the part is now, so a move starts from there, also when the status changes during a move.
  const at = useRef(pose);
  at.current = pose;
  const seen = useRef<{ known: boolean; status: Status }>({ known, status });

  useLayoutEffect(() => {
    const prev = seen.current;
    seen.current = { known, status };
    if (prev.status === status) return;
    // Before the first known status, and under reduced motion, the part is drawn at its new place at once.
    if (!prev.known || reduced()) {
      setPose(rest(status));
      return;
    }
    const going = status !== "none";
    const now0 = at.current;
    // Going out: the part keeps its place when the lit part stays the same one (running -> waiting), else the
    // newly lit part starts in place. Going in: the lit part returns from wherever it is.
    const acc = going ? (status as Accent) : (now0.acc ?? (prev.status as Accent));
    const from = going ? (now0.acc === null || samePart(id, now0.acc, acc) ? now0.out : 0) : now0.acc ? now0.out : 1;
    const to = going ? 1 : 0;
    const t0 = performance.now();
    let raf = 0;
    const frame = (now: number) => {
      const k = clamp01((now - t0) / MOVE_MS);
      if (k >= 1) {
        setPose((p) => ({ ...rest(status), flash: p.flash }));
        return;
      }
      setPose({ acc, out: from + (to - from) * (going ? back(k) : ease(k)), moving: true, flash: true });
      raf = requestAnimationFrame(frame);
    };
    setPose({ acc, out: from, moving: true, flash: true });
    raf = requestAnimationFrame(frame);
    const off = window.setTimeout(() => setPose((p) => ({ ...p, flash: false })), FLASH_MS);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(off);
    };
  }, [id, known, status]);

  return <Drawing shapes={drawing(id, pose.acc, pose.out)} accent={pose.acc} status={status} moving={pose.moving} flash={pose.flash} />;
}

/** Any drawing (a workspace's or the cockpit's), in the same isometric style. Faces take the drawing's dark
 * gradients; the status part takes the gradient of its colour. */
export function Drawing({ shapes, accent = null, status, moving = false, flash = false }: { shapes: Shape[]; accent?: Accent | null; status?: Status; moving?: boolean; flash?: boolean }) {
  const g = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const fill = (s: Shape) => {
    if (s.part === "shadow" || s.part === "extra" || s.part === "detail") return undefined;
    if (accent && (s.accent || s.lit)) return `url(#${g}-${accent})`;
    return `url(#${g}-${s.part})`;
  };
  const cls = (s: Shape) => {
    const base = `ws-${s.part}`;
    if (!accent) return base;
    if (s.accent) return `${base} ws-accent-${accent}`;
    if (s.lit) return `${base} ws-lit-${accent}`;
    if (s.part === "extra") return `${base}${s.dash ? " ws-dash" : ""}`;
    return base;
  };
  return (
    <svg
      className="ws-drawing"
      viewBox="-6 -30 212 190"
      aria-hidden="true"
      focusable="false"
      data-status={status}
      data-moving={moving ? "true" : undefined}
      data-flash={flash ? "true" : undefined}
    >
      <defs>
        {(["face", "top", "wait", "now"] as const).map((k) => (
          <linearGradient key={k} id={`${g}-${k}`} x1="0" y1="0" x2={k === "face" ? "0" : "1"} y2="1">
            <stop offset="0" className={`ws-g-${k}-0`} />
            <stop offset="1" className={`ws-g-${k}-1`} />
          </linearGradient>
        ))}
      </defs>
      {shapes.map((s, i) => (
        <path key={i} d={s.d} className={cls(s)} fill={fill(s)} style={s.opacity === undefined ? undefined : { opacity: s.opacity }} />
      ))}
    </svg>
  );
}
