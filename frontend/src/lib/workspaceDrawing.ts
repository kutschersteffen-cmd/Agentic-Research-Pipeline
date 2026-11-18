import type { WorkspaceId } from "./processes.ts";

/** One SVG path of a workspace drawing. Geometry only: colours come from CSS classes (face, top,
 * accent), so the drawings follow the theme. */
export type Shape = { d: string; part: "face" | "top"; accent: boolean };

export const DRAWING_IDS: WorkspaceId[] = ["stewardiq", "argus", "transitionIntel", "rdLab", "dataHub"];

// 30° isometric projection into a 200 × 156 viewBox, origin near the bottom centre.
const C = Math.cos(Math.PI / 6);
const OX = 100;
const OY = 112;
const pt = (x: number, y: number, z: number): [number, number] => [OX + (x - y) * C, OY + (x + y) * 0.5 - z];
const path = (pts: [number, number][]) => `M${pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L")}Z`;

/** A box: two side faces and a top, drawn back to front. `slot` marks the box that can carry the accent. */
function box(x: number, y: number, z: number, w: number, d: number, h: number, slot = false): Shape[] {
  const top = path([pt(x, y, z + h), pt(x + w, y, z + h), pt(x + w, y + d, z + h), pt(x, y + d, z + h)]);
  const left = path([pt(x, y + d, z), pt(x + w, y + d, z), pt(x + w, y + d, z + h), pt(x, y + d, z + h)]);
  const right = path([pt(x + w, y, z), pt(x + w, y + d, z), pt(x + w, y + d, z + h), pt(x + w, y, z + h)]);
  return [
    { d: left, part: "face", accent: false },
    { d: right, part: "face", accent: false },
    { d: top, part: "top", accent: slot },
  ];
}

/** A disc (a cylinder slice): the curved side, then the elliptical top. */
function disc(z: number, r: number, h: number): Shape[] {
  const [x, y] = pt(0, 0, z);
  const rx = r * 1.22;
  const ry = r * 0.7;
  const side = `M${(x - rx).toFixed(1)} ${(y - h).toFixed(1)}L${(x - rx).toFixed(1)} ${y.toFixed(1)}A${rx.toFixed(1)} ${ry.toFixed(1)} 0 0 0 ${(x + rx).toFixed(1)} ${y.toFixed(1)}L${(x + rx).toFixed(1)} ${(y - h).toFixed(1)}`;
  const top = `M${(x - rx).toFixed(1)} ${(y - h).toFixed(1)}A${rx.toFixed(1)} ${ry.toFixed(1)} 0 1 0 ${(x + rx).toFixed(1)} ${(y - h).toFixed(1)}A${rx.toFixed(1)} ${ry.toFixed(1)} 0 1 0 ${(x - rx).toFixed(1)} ${(y - h).toFixed(1)}Z`;
  return [
    { d: side, part: "face", accent: false },
    { d: top, part: "top", accent: false },
  ];
}

const DRAW: Record<WorkspaceId, () => Shape[]> = {
  // StewardIQ: a ledger of stacked slabs; the top slab is the decision that waits.
  stewardiq: () => [...Array.from({ length: 7 }, (_, i) => box(-46, -30, i * 9, 92, 60, 4)).flat(), ...box(-46, -30, 66, 92, 60, 4, true)],
  // Argus: a document slab with extracted data points rising off it; the centre one is being read.
  argus: () => {
    const hs = [18, 30, 12, 40, 22, 26, 14, 34, 20];
    const blocks = hs.map((h, k) => box(-44 + Math.floor(k / 3) * 32, -30 + (k % 3) * 24, 6, 16, 14, h, k === 4)).flat();
    return [...box(-58, -44, 0, 116, 88, 6), ...blocks];
  },
  // Transition Intel: a rising fin array, a pathway over time; the last fin is the latest step.
  transitionIntel: () => Array.from({ length: 8 }, (_, i) => box(-64 + i * 16, -14, 0, 6, 34, 14 + i * 9, i === 7)).flat(),
  // R&D Lab: grouped experiments of different heights; the first is the one under way.
  rdLab: () => [...box(-56, -18, 0, 36, 36, 34, true), ...box(-12, -40, 0, 30, 30, 66), ...box(20, 4, 0, 40, 40, 18), ...box(-8, 14, 0, 22, 22, 46)],
  // Data Hub: a store of stacked discs; the top disc is the latest load.
  dataHub: () => {
    const discs = Array.from({ length: 4 }, (_, i) => disc(i * 20, 44, 14)).flat();
    discs[discs.length - 1] = { ...discs[discs.length - 1], accent: true };
    return discs;
  },
};

/** The cockpit's drawing: a console of three upright panels on one base, read at a glance. No accent: the
 * cockpit shows state, it never waits on anyone. */
export const cockpitDrawing = (): Shape[] => [
  ...box(-62, -26, 0, 124, 52, 5),
  ...[-56, -16, 24].flatMap((x, i) => box(x, -14, 5, 32, 5, i === 1 ? 54 : 44)),
];

/** A workspace's drawing. With an accent, exactly one shape (the drawing's slot) carries it. */
export function drawing(id: WorkspaceId, accent: "wait" | "now" | null): Shape[] {
  return DRAW[id]().map((s) => ({ ...s, accent: accent !== null && s.accent }));
}
