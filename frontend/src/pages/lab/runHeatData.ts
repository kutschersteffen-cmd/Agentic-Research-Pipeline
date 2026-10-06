// Sample data: a seeded simulation of a 4,000-company run through 6 stages.
export const N = 4000;
export const STAGES = ["resolve", "discover", "extract", "verify", "ground", "review"] as const;
export const END = 130; // simulated minutes until the run is over
export const HOLD = 0.55; // progress at which a blocked company stops, waiting on a person
export const CHECKPOINTS: ReadonlyArray<readonly [number, number]> = [[1, 0.5], [3, 0.35], [4, 0.8]];

const NS = STAGES.length;
const MEAN_DUR = [3, 8, 14, 10, 9, 6];
const BLOCK_P = [0, 0, 0.002, 0.003, 0.004, 0.022];
const RETRY_P = [0.05, 0.12, 0.28, 0.1, 0.15, 0.08];
const PRE = ["Ar", "Bel", "Cor", "Dun", "Eld", "Fen", "Gal", "Hart", "Isk", "Jov", "Kel", "Lum", "Mar", "Nor", "Orr", "Pel", "Quin", "Rav", "Sol", "Tev", "Umb", "Vex", "Wyn"];
const SUF = ["tek", "works", "ra", "lyn", "dyne", "corp", "labs", "io", "ity", "ton", "gen", "mark"];

export interface Run {
  start: Float32Array; // N*NS, start time of company i in stage k
  dur: Float32Array;
  retries: Uint8Array;
  blockedAt: Int8Array; // stage where company i stops for a person, or -1
}

export interface Stats {
  done: number;
  retries: number;
  blocked: number;
}

export const companyName = (i: number): string => {
  const a = (i * 2654435761) >>> 0;
  return PRE[a % PRE.length] + SUF[(a >>> 8) % SUF.length];
};

export function buildRun(seed = 20261005): Run {
  let s = seed >>> 0;
  const rnd = () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296;
  const start = new Float32Array(N * NS);
  const dur = new Float32Array(N * NS);
  const retries = new Uint8Array(N * NS);
  const blockedAt = new Int8Array(N).fill(-1);
  for (let i = 0; i < N; i++) {
    let t = Math.pow(i / N, 0.9) * 44 + rnd() * 4;
    for (let k = 0; k < NS; k++) {
      let r = 0;
      while (r < 3 && rnd() < RETRY_P[k]) r++;
      retries[i * NS + k] = r;
      const d = MEAN_DUR[k] * (0.6 + rnd()) * (1 + 0.45 * r);
      start[i * NS + k] = t;
      dur[i * NS + k] = d;
      t += d + rnd();
      if (blockedAt[i] < 0 && rnd() < BLOCK_P[k]) {
        blockedAt[i] = k;
        break;
      }
    }
  }
  return { start, dur, retries, blockedAt };
}

/** Progress 0..1 of company i in stage k at time t (a blocked stage caps at HOLD). */
export function progress(run: Run, i: number, k: number, t: number): number {
  const q = (t - run.start[i * NS + k]) / run.dur[i * NS + k];
  const c = q < 0 ? 0 : q > 1 ? 1 : q;
  return run.blockedAt[i] === k ? Math.min(c, HOLD) : c;
}

export function stats(run: Run, t: number): Stats {
  let done = 0, retries = 0, blocked = 0;
  for (let i = 0; i < N; i++) {
    const b = run.blockedAt[i];
    if (b < 0 && t >= run.start[i * NS + 5] + run.dur[i * NS + 5]) done++;
    if (b >= 0 && t >= run.start[i * NS + b] + run.dur[i * NS + b] * HOLD) blocked++;
    for (let k = 0; k < NS; k++) {
      if (t > run.start[i * NS + k]) retries += Math.floor(run.retries[i * NS + k] * Math.min(1, (t - run.start[i * NS + k]) / run.dur[i * NS + k]));
    }
  }
  return { done, retries, blocked };
}

/** Companies finished per simulated minute, over the trailing window. */
export function throughput(run: Run, t: number, doneNow: number, window = 4): number {
  if (t >= END) return 0;
  const t0 = Math.max(0, t - window);
  return t > t0 ? (doneNow - stats(run, t0).done) / (t - t0) : 0;
}

/** Minutes -> h:mm (e.g. 2918 -> "48:38"). */
export function formatEta(minutes: number): string {
  const m = Math.max(0, Math.floor(minutes));
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}

export function eta(t: number, remaining: number, blocked: number, tp: number): string {
  if (t >= END) return blocked ? "holds" : "0:00";
  return tp > 0 ? formatEta(remaining / tp) : "--";
}
