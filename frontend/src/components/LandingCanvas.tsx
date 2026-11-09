import { useEffect, useRef } from "react";
import { phaseAt } from "../lib/landingMotion";

// The landing animation, ported from the Night Desk mockup: a network of dots; a share lights up,
// streams through an unseen funnel and forms the ARP logo, holds, then dissolves.
const MARK = [[1, 0], [3, 0], [0, 1], [4, 1], [0, 2], [1, 2], [2, 2], [3, 2], [4, 2], [0, 3], [4, 3], [0, 4], [4, 4]];
const HI = [2, 0];
const ease = (u: number) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
const clamp = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

type Dot = { hx: number; hy: number; ph: number; sp: number; lit: boolean; tx: number; ty: number; hi: boolean; lane: number; delay: number };

export function LandingCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current!;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    let W = 0, H = 0, dots: Dot[] = [], col: Record<string, string> = {};
    let seed = 11;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const funnel = { mouth: 0, p0: 0, p1: 0, cy: 0, wide: 0, pipe: 0 };

    const readColours = () => {
      const s = getComputedStyle(cv);
      col = { m: s.getPropertyValue("--muted").trim(), r: s.getPropertyValue("--run").trim(), f: s.getPropertyValue("--text").trim(), o: s.getPropertyValue("--hi").trim() };
    };
    const build = () => {
      W = cv.offsetWidth; H = cv.offsetHeight;
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      readColours();
      const narrow = W < 700;
      Object.assign(funnel, { mouth: W * 0.2, p0: W * 0.3, p1: narrow ? W * 0.45 : W * 0.5, cy: H * 0.5, wide: H * 0.36, pipe: H * 0.07 });
      const oc = document.createElement("canvas"); oc.width = W; oc.height = H;
      const o = oc.getContext("2d")!;
      const area = narrow ? W * 0.8 : W * 0.4;
      let cell = Math.round(H * 0.11), fs = Math.round(H * 0.62);
      o.font = `700 ${fs}px Geist, system-ui, sans-serif`;
      let tw = o.measureText("ARP").width;
      const fit = Math.min(1, area / (cell * 6.2 + tw));
      cell = Math.round(cell * fit); fs = Math.round(fs * fit);
      o.font = `700 ${fs}px Geist, system-ui, sans-serif`; tw = o.measureText("ARP").width;
      const mw = cell * 5, gap = cell * 1.2, total = mw + gap + tw;
      const x0 = narrow ? (W - total) / 2 : W * 0.585 + (W * 0.39 - total) / 2, y0 = (H - cell * 5) / 2;
      o.fillStyle = "#000";
      MARK.concat([HI]).forEach(([c, r]) => o.fillRect(x0 + c * cell, y0 + r * cell, cell - 2, cell - 2));
      o.textBaseline = "middle"; o.fillText("ARP", x0 + mw + gap, H / 2 + fs * 0.04);
      const d = o.getImageData(0, 0, W, H).data, step = Math.max(4, Math.round(Math.min(H / 72, cell / 4))), T: [number, number, boolean][] = [];
      for (let y = 0; y < H; y += step) for (let x = 0; x < W; x += step)
        if (d[(y * W + x) * 4 + 3] > 128) T.push([x, y, x >= x0 + HI[0] * cell && x < x0 + (HI[0] + 1) * cell && y >= y0 && y < y0 + cell]);
      const N = Math.min(3200, Math.max(T.length * 3, Math.round((W * H) / 170)));
      dots = Array.from({ length: N }, () => ({ hx: rnd() * W, hy: rnd() * H, ph: rnd() * 6.28, sp: 0.3 + rnd() * 0.7, lit: false, tx: 0, ty: 0, hi: false, lane: 0, delay: 0 }));
      const idx = [...dots.keys()].sort(() => rnd() - 0.5).slice(0, T.length);
      idx.forEach((i, k) => Object.assign(dots[i], { lit: true, tx: T[k][0], ty: T[k][1], hi: T[k][2], lane: (rnd() - 0.5) * 2, delay: rnd() }));
    };
    const home = (p: Dot, t: number): [number, number] => [p.hx + Math.sin((t / 2600) * p.sp + p.ph) * 24, p.hy + Math.cos((t / 3100) * p.sp + p.ph * 1.3) * 16];
    // Where a lit dot is: at home, in the stream (0..1 through funnel and lane), landed, or returning.
    const litPos = (p: Dot, t: number, phase: string, pt: number): [number, number, number] => {
      const h = home(p, t);
      if (phase === "network" || phase === "light") return [h[0], h[1], 0];
      if (phase === "formed") return [p.tx, p.ty, 1];
      if (phase === "dissolve") { const k = ease(pt); return [lerp(p.tx, h[0], k), lerp(p.ty, h[1], k), 1 - k]; }
      const u = clamp((pt - p.delay * 0.25) / 0.75);
      const laneY = funnel.cy + p.lane * funnel.pipe * 0.8;
      if (u < 0.3) { const k = ease(u / 0.3); return [lerp(h[0], funnel.mouth, k), lerp(h[1], funnel.cy + p.lane * funnel.wide, k), 0]; }
      if (u < 0.4) { const k = (u - 0.3) / 0.1; return [lerp(funnel.mouth, funnel.p0, k), lerp(funnel.cy + p.lane * funnel.wide, laneY, ease(k)), 0]; }
      if (u < 0.75) return [lerp(funnel.p0, funnel.p1, (u - 0.4) / 0.35), laneY, 0];
      const k = ease((u - 0.75) / 0.25);
      return [lerp(funnel.p1, p.tx, k), lerp(laneY, p.ty, k), k];
    };
    const draw = (t: number) => {
      const { phase, t: pt } = phaseAt(t);
      ctx.clearRect(0, 0, W, H);
      const glow = phase === "light" ? pt : phase === "network" ? 0 : 1;
      const dim = phase === "stream" || phase === "formed" ? 0.4 : phase === "light" ? 1 - 0.6 * pt : phase === "dissolve" ? 0.4 + 0.6 * pt : 1;
      for (const p of dots) {
        let x: number, y: number, k = 0;
        if (p.lit) [x, y, k] = litPos(p, t, phase, pt);
        else [x, y] = home(p, t);
        let fill = col.m, a = 0.45 * dim, r = 1.2;
        if (p.lit) {
          if (k > 0.55) { fill = p.hi ? col.o : col.f; a = 0.6 + 0.4 * k; r = 1.4 + k * 0.9; }
          else if (glow > 0) { fill = col.r; a = 0.45 + 0.5 * glow; r = 1.2 + 0.8 * glow; }
        }
        ctx.globalAlpha = a; ctx.fillStyle = fill;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    build();
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { draw(16000); return; }
    let visible = true, frame = 0, start: number | null = null;
    const io = new IntersectionObserver((e) => { visible = e[0].isIntersecting; });
    io.observe(cv);
    const loop = (now: number) => {
      start ??= now;
      if (visible && !document.hidden) draw(now - start);
      frame = requestAnimationFrame(loop);
    };
    const onVisibility = () => { if (!document.hidden) readColours(); };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("resize", build);
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", build);
    };
  }, []);
  return <canvas ref={ref} className="landing-canvas" aria-hidden="true" />;
}
