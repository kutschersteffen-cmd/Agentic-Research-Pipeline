// The Orb's timing and quality rules (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md).
// Pure: no DOM, no three.js, so the rules are unit-tested and the main bundle stays small.

export type OrbPhase = "assembling" | "locked" | "idle" | "folding" | "realigning" | "unfolding" | "speaking";
export type OrbColour = "gold" | "ice" | "ember" | "mint";
export type OrbLevel = "high" | "medium" | "low" | "still";
export type OrbQuality = Exclude<OrbLevel, "still">;

export const COLOURS: readonly OrbColour[] = ["gold", "ice", "ember", "mint"];
// The Orb Colour Rule (DESIGN.md): these live only in the Orb's canvas and its phase label.
export const COLOUR_HEX: Record<OrbColour, string> = { gold: "#ff8f1f", ice: "#249eff", ember: "#ff451a", mint: "#1aeb9e" };
export const PHASE_LABEL: Record<OrbPhase, string> = {
  assembling: "Assembling",
  locked: "Locked",
  idle: "Idle",
  folding: "Folding",
  realigning: "Re-aligning",
  unfolding: "Unfolding",
  speaking: "Speaking",
};
export const nextColour = (c: OrbColour): OrbColour => COLOURS[(COLOURS.indexOf(c) + 1) % COLOURS.length];

/** Seconds. A frame gap longer than MAX_STEP counts as MAX_STEP. */
export const MAX_STEP = 0.25;
export const INTRO = { assembled: 2.6, end: 3.5 };
export const TRANSFORM = { fold: 0.75, realign: 1.6, unfold: 2.35, end: 3.3 };
const AUTO_MIN = 8;
const AUTO_SPREAD = 3;

export function introPhase(t: number): OrbPhase {
  return t < INTRO.assembled ? "assembling" : t < INTRO.end ? "locked" : "idle";
}
export function transformPhase(t: number): OrbPhase {
  if (t < TRANSFORM.fold) return "folding";
  if (t < TRANSFORM.realign) return "realigning";
  if (t < TRANSFORM.unfold) return "unfolding";
  return t < TRANSFORM.end ? "locked" : "idle";
}

export interface ClockEvents {
  /** A transformation started on this tick (by itself). */
  started: boolean;
  /** A transformation ended on this tick and the colour moved on. */
  committed: boolean;
}

/** The Orb's phase and colour over elapsed time: intro, idle, transformations, speaking. */
export class OrbClock {
  phase: OrbPhase;
  colour: OrbColour = "gold";
  private intro: number | null;
  private transform: number | null = null;
  private idleFor = 0;
  private autoAfter: number;
  private speaking = false;
  private readonly random: () => number;

  constructor(intro: boolean, random: () => number = Math.random) {
    this.random = random;
    this.intro = intro ? 0 : null;
    this.phase = intro ? "assembling" : "idle";
    this.autoAfter = this.drawAuto();
  }

  private drawAuto() {
    return AUTO_MIN + AUTO_SPREAD * this.random();
  }

  private toIdle() {
    this.idleFor = 0;
    this.autoAfter = this.drawAuto();
    this.phase = this.speaking ? "speaking" : "idle";
  }

  /** True while no intro or transformation runs (the phase is idle or speaking). */
  get resting() {
    return this.intro === null && this.transform === null;
  }

  setSpeaking(on: boolean) {
    if (on === this.speaking) return;
    this.speaking = on;
    if (!this.resting) return;
    if (on) this.phase = "speaking";
    else this.toIdle();
  }

  /** A click or tap: starts a transformation only while idle. */
  click(): boolean {
    if (this.phase !== "idle") return false;
    this.startTransform();
    return true;
  }

  private startTransform() {
    this.transform = 0;
    this.phase = "folding";
  }

  /** Advance by `dt` seconds (clamped to MAX_STEP). */
  tick(dt: number): ClockEvents {
    const step = Math.min(Math.max(dt, 0), MAX_STEP);
    const ev: ClockEvents = { started: false, committed: false };
    if (this.intro !== null) {
      this.intro += step;
      this.phase = introPhase(this.intro);
      if (this.phase === "idle") {
        this.intro = null;
        this.toIdle();
      }
    } else if (this.transform !== null) {
      this.transform += step;
      this.phase = transformPhase(this.transform);
      if (this.phase === "idle") {
        this.transform = null;
        this.colour = nextColour(this.colour);
        ev.committed = true;
        this.toIdle();
      }
    } else if (this.phase === "idle") {
      this.idleFor += step;
      if (this.idleFor >= this.autoAfter) {
        this.startTransform();
        ev.started = true;
      }
    }
    return ev;
  }
}

/** Mean frame time over 60 frames: above 33.3 ms step down one level; at low, above 50 ms go still. Never up. */
export class QualityRule {
  level: OrbLevel;
  private frames = 0;
  private sum = 0;

  constructor(level: OrbLevel) {
    this.level = level;
  }

  /** `gapMs`: time since the previous requestAnimationFrame timestamp. A first frame after a pause is not counted. */
  add(gapMs: number, afterPause = false): OrbLevel {
    if (this.level === "still" || afterPause) return this.level;
    this.sum += Math.min(Math.max(gapMs, 0), 1000);
    if (++this.frames < 60) return this.level;
    const mean = this.sum / this.frames;
    this.frames = 0;
    this.sum = 0;
    if (this.level === "low") {
      if (mean > 50) this.level = "still";
    } else if (mean > 33.3) {
      this.level = this.level === "high" ? "medium" : "low";
    }
    return this.level;
  }
}

const LEVELS: readonly OrbLevel[] = ["high", "medium", "low", "still"];
const asLevel = (v: string | null | undefined): OrbLevel | null => (LEVELS as readonly string[]).includes(v ?? "") ? (v as OrbLevel) : null;
/** `localStorage["arp.orb"]`: a valid level pins it and turns the quality rule off. */
export const pinnedLevel = asLevel;
/** Where an Orb starts: the pin, else the level this browser session reached, else high. */
export const startLevel = (pin: string | null, session: string | null): OrbLevel => asLevel(pin) ?? asLevel(session) ?? "high";

/** Canvas pixel ratio for a quality level; high is capped so the canvas has at most 3.4 million pixels. */
export function pixelRatio(q: OrbQuality, dpr: number, w: number, h: number): number {
  if (q === "low") return 0.75;
  if (q === "medium") return 1;
  return Math.min(dpr || 1, 2, Math.sqrt(3.4e6 / Math.max(1, w * h)));
}
