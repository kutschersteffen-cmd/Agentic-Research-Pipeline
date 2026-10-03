// Shared bits for the arcade games: random, number padding, saved best score, key bindings and the frame loop.
export const rnd = (a: number, b: number) => a + Math.random() * (b - a);
export const pad = (n: number, len = 5) => String(Math.max(0, Math.floor(n))).padStart(len, "0");
export const loadBest = (key: string) => { try { return Number(localStorage.getItem(key) ?? 0); } catch { return 0; } };
export const saveBest = (key: string, v: number) => { try { localStorage.setItem(key, String(v)); } catch { /* private window: best stays in memory */ } };

/** Calls `h(key, down)` for key events; keys are lower-case, space is "space". Arrows and space never scroll the page. */
export function bindKeys(h: (key: string, down: boolean) => void) {
  const on = (down: boolean) => (e: KeyboardEvent) => {
    const k = e.key === " " ? "space" : e.key.toLowerCase();
    if (k === "space" || k.startsWith("arrow")) e.preventDefault();
    h(k, down);
  };
  const kd = on(true), ku = on(false);
  addEventListener("keydown", kd); addEventListener("keyup", ku);
  return () => { removeEventListener("keydown", kd); removeEventListener("keyup", ku); };
}

/** Runs `frame(dt, now)` every animation frame (dt capped at 50ms); returns the stop function. */
export function loop(frame: (dt: number, now: number) => void) {
  let id = 0, last = performance.now();
  const tick = (now: number) => { frame(Math.min(0.05, (now - last) / 1000), now); last = now; id = requestAnimationFrame(tick); };
  const vis = () => { last = performance.now(); };
  document.addEventListener("visibilitychange", vis);
  id = requestAnimationFrame(tick);
  return () => { cancelAnimationFrame(id); document.removeEventListener("visibilitychange", vis); };
}

/** Pointer x as 0..1 across the canvas. */
export const pointerX = (e: PointerEvent, cv: HTMLCanvasElement) => (e.clientX - cv.getBoundingClientRect().left) / cv.clientWidth;
