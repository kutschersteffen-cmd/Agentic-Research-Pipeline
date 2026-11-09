/** The landing animation's 22 s loop: network, light up, stream into the logo, hold, dissolve. */
export const LOOP_MS = 22_000;
export type Phase = "network" | "light" | "stream" | "formed" | "dissolve";
const PHASES: [Phase, number][] = [["network", 4000], ["light", 2000], ["stream", 8000], ["formed", 4000], ["dissolve", 4000]];

/** The phase at a moment since load, and how far through it (0..1). */
export function phaseAt(ms: number): { phase: Phase; t: number } {
  let rest = ((ms % LOOP_MS) + LOOP_MS) % LOOP_MS;
  for (const [phase, len] of PHASES) {
    if (rest < len) return { phase, t: rest / len };
    rest -= len;
  }
  return { phase: "network", t: 0 };
}
