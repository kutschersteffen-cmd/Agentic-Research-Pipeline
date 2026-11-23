import type { WorkspaceId } from "./processes.ts";

/** One SVG path of a workspace drawing. Geometry only: colours come from CSS classes and the drawing's own
 * gradients. `accent` marks the top face of the status part (the one shape that carries `ws-accent-*`); `lit`
 * marks the status part's other faces, which take its colour without that class. `shadow` is a footprint on the
 * ground, `extra` the scan plane or outline shown while running (`opacity` fades it in), `detail` a dashed mark. */
export type Shape = { d: string; part: "face" | "top" | "shadow" | "extra" | "detail"; accent: boolean; lit?: boolean; dash?: boolean; opacity?: number };

export const DRAWING_IDS: WorkspaceId[] = ["stewardiq", "argus", "transitionIntel", "rdLab", "dataHub"];
export type Accent = "wait" | "now";

// 30° isometric projection into a 200 × 156 viewBox, origin near the bottom centre.
const C = Math.cos(Math.PI / 6);
const OX = 100;
const OY = 112;
const pt = (x: number, y: number, z: number): [number, number] => [OX + (x - y) * C, OY + (x + y) * 0.5 - z];
const path = (pts: [number, number][]) => `M${pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L")}Z`;
const quad = (x: number, y: number, z: number, w: number, d: number) => path([pt(x, y, z), pt(x + w, y, z), pt(x + w, y + d, z), pt(x, y + d, z)]);
export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** A box: two side faces and a top, drawn back to front. `slot` marks the status part. */
function box(x: number, y: number, z: number, w: number, d: number, h: number, slot = false): Shape[] {
  const left = path([pt(x, y + d, z), pt(x + w, y + d, z), pt(x + w, y + d, z + h), pt(x, y + d, z + h)]);
  const right = path([pt(x + w, y, z), pt(x + w, y + d, z), pt(x + w, y + d, z + h), pt(x + w, y, z + h)]);
  return [
    { d: left, part: "face", accent: false, lit: slot },
    { d: right, part: "face", accent: false, lit: slot },
    { d: quad(x, y, z + h, w, d), part: "top", accent: slot },
  ];
}

const shadow = (x: number, y: number, w: number, d: number): Shape => ({ d: quad(x, y, 0, w, d), part: "shadow", accent: false });

/** A disc (a cylinder slice): the curved side, the elliptical top and a dashed ring on it. */
function disc(z: number, r: number, h: number, slot = false): Shape[] {
  const [x, y] = pt(0, 0, z);
  const rx = r * 1.22;
  const ry = r * 0.7;
  const f = (n: number) => n.toFixed(1);
  const side = `M${f(x - rx)} ${f(y - h)}L${f(x - rx)} ${f(y)}A${f(rx)} ${f(ry)} 0 0 0 ${f(x + rx)} ${f(y)}L${f(x + rx)} ${f(y - h)}`;
  const ellipse = (a: number, b: number) => `M${f(x - a)} ${f(y - h)}A${f(a)} ${f(b)} 0 1 0 ${f(x + a)} ${f(y - h)}A${f(a)} ${f(b)} 0 1 0 ${f(x - a)} ${f(y - h)}Z`;
  return [
    { d: side, part: "face", accent: false, lit: slot },
    { d: ellipse(rx, ry), part: "top", accent: slot },
    { d: ellipse(rx * 0.72, ry * 0.72), part: "detail", accent: false },
  ];
}

// Each drawing is still. `out` is how far the status part has come out (0 in place, 1 out; a little over 1 while
// it overshoots on the way out); `acc` picks the part (Transition Intel's differs by status) and lights it.
const DRAW: Record<WorkspaceId, (acc: Accent | null, out: number) => Shape[]> = {
  // StewardIQ: a ledger of stacked slabs; the top slab, the decision, lifts 13 units off the stack.
  stewardiq: (acc, out) => [
    shadow(-46, -30, 92, 60),
    ...Array.from({ length: 7 }, (_, i) => box(-46, -30, i * 9, 92, 60, 4)).flat(),
    ...box(-46, -30, 63 + out * 13, 92, 60, 4, acc !== null),
  ],
  // Argus: a document slab with data points; the centre column rises 12 units, a scan plane rests over it while running.
  argus: (acc, out) => {
    const hs = [18, 30, 12, 40, 22, 26, 14, 34, 20];
    const blocks = hs.flatMap((h, k) => box(-44 + Math.floor(k / 3) * 32, -30 + (k % 3) * 24, 6, 16, 14, k === 4 ? h + out * 12 : h, k === 4 && acc !== null));
    const scan: Shape[] = acc === "now" ? [{ d: quad(-58, -44, 8 + out * 34, 116, 88), part: "extra", accent: false, opacity: clamp01(out) }] : [];
    return [...box(-58, -44, 0, 116, 88, 6), ...blocks, ...scan];
  },
  // Transition Intel: a rising fin array; the 4th fin rises while running, the 8th while waiting, 10 units.
  transitionIntel: (acc, out) => {
    const hot = acc === "now" ? 3 : acc === "wait" ? 7 : -1;
    return [shadow(-64, -14, 118, 34), ...Array.from({ length: 8 }, (_, i) => box(-64 + i * 16, -14, 0, 6, 34, 14 + i * 9 + (i === hot ? out * 10 : 0), i === hot)).flat()];
  },
  // R&D Lab: grouped experiments; the first grows 9 units, with a dashed outline of its next level while running.
  rdLab: (acc, out) => {
    const h = 34 + out * 9;
    const ghost: Shape[] = acc === "now" ? [{ d: quad(-56, -18, h + 13, 36, 36), part: "extra", accent: false, dash: true, opacity: clamp01(out) * 0.7 }] : [];
    return [
      shadow(-56, -40, 116, 84),
      ...box(-12, -40, 0, 30, 30, 66),
      ...box(20, 4, 0, 40, 40, 18),
      ...box(-56, -18, 0, 36, 36, h, acc !== null),
      ...ghost,
      ...box(-8, 14, 0, 22, 22, 46),
    ];
  },
  // Data Hub: a store of stacked discs; the top disc, the latest load, lifts 7 units.
  dataHub: (acc, out) => Array.from({ length: 4 }, (_, i) => disc(i * 20 + (i === 3 ? out * 7 : 0), 44, 14, i === 3 && acc !== null)).flat(),
};

/** The cockpit's drawing: a console of three upright panels on one base, read at a glance. No accent: the
 * cockpit shows state, it never waits on anyone. */
export const cockpitDrawing = (): Shape[] => [
  ...box(-62, -26, 0, 124, 52, 5),
  ...[-56, -16, 24].flatMap((x, i) => box(x, -14, 5, 32, 5, i === 1 ? 54 : 44)),
];

/** Whether two lit statuses light the same part: everywhere but Transition Intel, whose fin differs. */
export const samePart = (id: WorkspaceId, a: Accent, b: Accent) => id !== "transitionIntel" || a === b;

/** A workspace's drawing. With an accent, exactly one shape (the status part's top) carries it and the part is
 * out by `out` (default: fully out); without one, the part is in place. */
export function drawing(id: WorkspaceId, accent: Accent | null, out = accent ? 1 : 0): Shape[] {
  return DRAW[id](accent, out);
}
