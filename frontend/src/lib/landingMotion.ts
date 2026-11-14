/** The landing animation's 24 s loop: network, gather into the orb, orb, ARP emerges, hold, dissolve. */
export const LOOP_MS = 24_000;
export type Phase = "network" | "gather" | "orb" | "emerge" | "formed" | "dissolve";
const PHASES: [Phase, number][] = [["network", 5000], ["gather", 4000], ["orb", 4000], ["emerge", 3500], ["formed", 4000], ["dissolve", 3500]];

/** The phase at a moment since load, and how far through it (0..1). */
export function phaseAt(ms: number): { phase: Phase; t: number } {
  let rest = ((ms % LOOP_MS) + LOOP_MS) % LOOP_MS;
  for (const [phase, len] of PHASES) {
    if (rest < len) return { phase, t: rest / len };
    rest -= len;
  }
  return { phase: "network", t: 0 };
}
