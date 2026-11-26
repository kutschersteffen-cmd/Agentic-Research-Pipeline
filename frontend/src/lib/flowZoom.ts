// The zoom of a process flow (spec process-flow-viewer): a percent from 50 to 200, 100 by default. The zoom is kept
// unrounded; steps, the reading and the stored value use it rounded to a whole number.

export const MIN_ZOOM = 50;
export const MAX_ZOOM = 200;
export const STEP_WIDTH = 180; // a step card at 100%, px
export const STEP_GAP = 18; // between two cards at 100%, px
export const ZOOM_KEY = "arp.flowZoom";

export const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** The next multiple of 10 above (dir 1) or below (dir -1) the rounded zoom. */
export function stepZoom(z: number, dir: 1 | -1): number {
  const r = Math.round(z);
  return clampZoom(dir > 0 ? Math.floor(r / 10) * 10 + 10 : Math.ceil(r / 10) * 10 - 10);
}

/** Ctrl or cmd + wheel: the zoom changes by -deltaY / 10. */
export const wheelZoom = (z: number, deltaY: number) => clampZoom(z - deltaY / 10);

/** The largest whole zoom from 50 to 100 at which `steps` cards fit `innerWidth` px; 50 when none does. */
export function fitZoom(innerWidth: number, steps: number): number {
  const need = steps * STEP_WIDTH + (steps - 1) * STEP_GAP;
  return Math.min(100, Math.max(MIN_ZOOM, Math.floor((innerWidth * 100) / need)));
}

/** The stored zoom; anything that is not a number from 50 to 200 counts as 100. */
export function readStoredZoom(raw: string | null): number {
  const z = raw === null || raw.trim() === "" ? NaN : Number(raw);
  return Number.isFinite(z) && z >= MIN_ZOOM && z <= MAX_ZOOM ? z : 100;
}
