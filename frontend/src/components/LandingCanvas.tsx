import { useEffect, useRef } from "react";
import { depthBucket, phaseAt } from "../lib/landingMotion";

// The landing animation (docs/superpowers/specs/2026-11-14-landing-brand-refresh-design.md), ported from
// the approved mockup: a huge chaotic network gathers into a rotating orange orb of rings, spokes and
// fragments; the pixel "ARP" emerges from its core, holds, and everything dissolves back.
const LETTERS: [number, string[]][] = [
  [0, [".X.X.", "X...X", "XXXXX", "X...X", "X...X"]],
  [6, ["XXXX.", "X...X", "XXXX.", "X..X.", "X...X"]],
  [12, ["XXXX.", "X...X", "XXXX.", "X....", "X...."]],
];
const HI: [number, number] = [2, 0];
const CELLS: [number, number][] = [...LETTERS.flatMap(([off, rows]) => rows.flatMap((row, y) => [...row].flatMap((c, x): [number, number][] => (c === "X" ? [[off + x, y]] : [])))), HI];
const ease = (u: number) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
const clamp = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

type Vec = [number, number, number];
type Ring = { n: Vec; u: Vec; v: Vec; c: number; rad: number; spin: number };
type Particle = {
  hx: number; hy: number; ph: number; sp: number; delay: number;
  kind: "ring" | "fixed"; ri: number; th: number; b: Vec; core: boolean;
  arp: boolean; tx: number; ty: number; hi: boolean;
  x: number; y: number; d: number; st: 0 | 1 | 2; // st: 0 network, 1 orb, 2 "ARP"
};
type Pulse = { a: number; b: number; t0: number; dur: number };

const cross = (a: Vec, b: Vec): Vec => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
function basis(n: Vec): [Vec, Vec] {
  const u0 = cross(n, Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]);
  const l = Math.hypot(...u0);
  const u = u0.map((x) => x / l) as Vec;
  return [u, cross(n, u)];
}

export function LandingCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current!;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    let W = 0, H = 0, N = 0, cell = 0, dotsPer = 4, dark = false;
    let ps: Particle[] = [], edges: [number, number][] = [], adj: number[][] = [], rings: Ring[] = [], groups: { ids: number[]; closed: boolean }[] = [], pulses: Pulse[] = [];
    let orb = { cx: 0, cy: 0, R: 0 };
    let col: Record<"g" | "m" | "r" | "f" | "o", string> = { g: "", m: "", r: "", f: "", o: "" };
    let seed = 11;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const unit = (): Vec => { const z = rnd() * 2 - 1, a = rnd() * 6.283, r = Math.sqrt(1 - z * z); return [r * Math.cos(a), z, r * Math.sin(a)]; };
    const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const readColours = () => {
      const s = getComputedStyle(cv), g = (n: string) => s.getPropertyValue(n).trim();
      col = { g: g("--orb"), m: g("--muted"), r: g("--run"), f: g("--text"), o: g("--brand-apex") };
      const theme = document.documentElement.dataset.theme;
      dark = theme ? theme === "dark" : darkQuery.matches;
    };
    const newPulse = (a: number, t0: number): Pulse => {
      const nb = adj[a];
      return { a, b: nb.length ? nb[Math.floor(rnd() * nb.length)] : a, t0, dur: 500 + rnd() * 700 };
    };

    const build = () => {
      W = cv.offsetWidth; H = cv.offsetHeight;
      if (!W || !H) return;
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      readColours();
      seed = 11;
      const narrow = W < 700;
      orb = narrow ? { cx: W / 2, cy: H / 2, R: Math.min(W * 0.42, H * 0.3) } : { cx: W * 0.7, cy: H / 2, R: Math.min(H * 0.34, W * 0.2) };
      N = Math.round(Math.max(500, Math.min(1400, (W * H) / 900)));
      dotsPer = [5, 4, 3].find((d) => CELLS.length * d * d <= N * 0.45) ?? 3;
      cell = Math.floor((orb.R * 1.75) / 17);
      // Network: nodes everywhere, wired to up to three nearest neighbours (grid buckets keep this linear).
      ps = Array.from({ length: N }, () => ({
        hx: rnd() * W, hy: rnd() * H, ph: rnd() * 6.28, sp: 0.3 + rnd() * 0.7, delay: rnd(),
        kind: "fixed", ri: 0, th: 0, b: [0, 0, 0], core: false, arp: false, tx: 0, ty: 0, hi: false, x: 0, y: 0, d: 0.5, st: 0,
      }));
      const D = Math.max(60, Math.sqrt((W * H) / N) * 1.7), grid = new Map<number, number[]>(), key = (x: number, y: number) => (x << 16) | y;
      ps.forEach((p, i) => { const k = key(Math.floor(p.hx / D), Math.floor(p.hy / D)); grid.set(k, [...(grid.get(k) ?? []), i]); });
      edges = []; adj = ps.map(() => []);
      ps.forEach((p, i) => {
        const gx = Math.floor(p.hx / D), gy = Math.floor(p.hy / D), near: [number, number][] = [];
        for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (const j of grid.get(key(gx + dx, gy + dy)) ?? []) {
          if (j === i) continue;
          const d = Math.hypot(ps[j].hx - p.hx, ps[j].hy - p.hy);
          if (d < D) near.push([d, j]);
        }
        near.sort((a, b) => a[0] - b[0]).slice(0, 3).forEach(([, j]) => { if (i < j) { edges.push([i, j]); adj[i].push(j); adj[j].push(i); } });
      });
      // Orb: 9 rings (3 latitude bands), 14 spokes, a core and shell fragments.
      rings = []; groups = [];
      const order = [...ps.keys()].sort(() => rnd() - 0.5);
      let next = 0;
      const take = (n: number) => order.slice(next, (next += n));
      for (let r = 0; r < 9; r++) {
        const lat = r < 3, n: Vec = lat ? [0, 1, 0] : unit(), [u, v] = basis(n);
        const c = lat ? (r - 1) * 0.42 : 0, rad = lat ? Math.sqrt(1 - c * c) : 0.62 + rnd() * 0.42;
        rings.push({ n, u, v, c, rad, spin: (lat ? 0.15 : 0.25 + rnd() * 0.45) * (rnd() < 0.5 ? -1 : 1) });
        const ids = take(Math.floor((N * 0.58) / 9));
        ids.forEach((i, k) => Object.assign(ps[i], { kind: "ring", ri: r, th: (k / ids.length) * 6.283 }));
        groups.push({ ids, closed: true });
      }
      for (let s = 0; s < 14; s++) {
        const d = unit(), ids = take(Math.floor((N * 0.14) / 14));
        ids.forEach((i, k) => { const f = 0.12 + (k / ids.length) * 0.98; ps[i].b = d.map((x) => x * f) as Vec; });
        groups.push({ ids, closed: false });
      }
      take(Math.floor(N * 0.05)).forEach((i) => { const d = unit(), f = rnd() * 0.13; Object.assign(ps[i], { b: d.map((x) => x * f), core: true }); });
      order.slice(next).forEach((i) => { const d = unit(), f = 0.78 + rnd() * 0.32; ps[i].b = d.map((x) => x * f) as Vec; });
      // "ARP": dot-matrix targets centred on the orb; a random share of the particles flies there.
      const step = cell / dotsPer, x0 = orb.cx - (cell * 17) / 2, y0 = orb.cy - (cell * 5) / 2, T: [number, number, boolean][] = [];
      for (const [c, r] of CELLS) for (let a = 0; a < dotsPer; a++) for (let b = 0; b < dotsPer; b++)
        T.push([x0 + c * cell + (b + 0.5) * step, y0 + r * cell + (a + 0.5) * step, c === HI[0] && r === HI[1]]);
      [...ps.keys()].sort(() => rnd() - 0.5).slice(0, T.length).forEach((i, k) => Object.assign(ps[i], { arp: true, tx: T[k][0], ty: T[k][1], hi: T[k][2] }));
      pulses = Array.from({ length: Math.round(N / 30) }, () => newPulse(Math.floor(rnd() * N), 0));
    };

    const home = (p: Particle, t: number): [number, number] => [
      p.hx + Math.sin((t / 2100) * p.sp + p.ph) * 34 + Math.sin(t / 370 + p.ph * 3) * 2,
      p.hy + Math.cos((t / 2700) * p.sp + p.ph * 1.3) * 26,
    ];
    const orbPos = (p: Particle, t: number, open: number): Vec => {
      let v = p.b;
      if (p.kind === "ring") {
        const r = rings[p.ri], th = p.th + (r.spin * t) / 1000, c = Math.cos(th) * r.rad, s = Math.sin(th) * r.rad;
        v = [0, 1, 2].map((k) => r.n[k] * r.c + c * r.u[k] + s * r.v[k]) as Vec;
      }
      const ay = t * 0.00022, ax = 0.32 + Math.sin(t * 0.0003) * 0.1, cy = Math.cos(ay), sy = Math.sin(ay), cx = Math.cos(ax), sx = Math.sin(ax);
      const x = v[0] * cy + v[2] * sy, z0 = -v[0] * sy + v[2] * cy, y = v[1] * cx - z0 * sx, z = v[1] * sx + z0 * cx;
      const R = orb.R * (1 + 0.025 * Math.sin(t / 900) + open * 0.18), s = 2.6 / (2.6 + z);
      return [orb.cx + x * R * s, orb.cy + y * R * s, (1 - z) / 2];
    };
    const sq = (x: number, y: number, s: number) => ctx.fillRect(x - s / 2, y - s / 2, s, s);

    const draw = (t: number) => {
      if (!W || !H) return;
      const { phase, t: pt } = phaseAt(t), e = ease(pt);
      const netVis = phase === "network" ? 1 : phase === "gather" ? clamp(1 - pt * 1.8) : phase === "dissolve" ? clamp((pt - 0.3) / 0.7) : 0;
      const orbVis = phase === "gather" ? e * e : phase === "orb" ? 1 : phase === "emerge" ? 1 - 0.55 * e : phase === "formed" ? 0.45 : phase === "dissolve" ? 0.45 * (1 - e) : 0;
      const open = phase === "emerge" ? e : phase === "formed" ? 1 : phase === "dissolve" ? 1 - e : 0;
      const add: GlobalCompositeOperation = dark ? "lighter" : "source-over";
      ctx.clearRect(0, 0, W, H);
      if (orbVis > 0) {
        const g = ctx.createRadialGradient(orb.cx, orb.cy, 0, orb.cx, orb.cy, orb.R * 1.25);
        g.addColorStop(0, col.g); g.addColorStop(1, "transparent");
        ctx.globalAlpha = (dark ? 0.3 : 0.12) * orbVis; ctx.fillStyle = g;
        ctx.fillRect(orb.cx - orb.R * 1.3, orb.cy - orb.R * 1.3, orb.R * 2.6, orb.R * 2.6);
      }
      for (const p of ps) {
        const net = home(p, t);
        let x = net[0], y = net[1], d = 0.5, st: Particle["st"] = 0;
        if (phase !== "network") {
          const o = orbPos(p, t, open);
          d = o[2];
          if (phase === "gather") { const k = ease(clamp((pt - p.delay * 0.35) / 0.65)); x = lerp(net[0], o[0], k); y = lerp(net[1], o[1], k); st = k > 0.5 ? 1 : 0; }
          else if (phase === "orb") { x = o[0]; y = o[1]; st = 1; }
          else if (phase === "emerge") {
            if (p.arp) { const k = ease(clamp((pt - p.delay * 0.4) / 0.6)); x = lerp(o[0], p.tx, k); y = lerp(o[1], p.ty, k); st = k > 0.6 ? 2 : 1; }
            else { x = o[0]; y = o[1]; st = 1; }
          } else if (phase === "formed") { if (p.arp) { x = p.tx; y = p.ty; st = 2; } else { x = o[0]; y = o[1]; st = 1; } }
          else { const k = ease(clamp((pt - p.delay * 0.3) / 0.7)); x = lerp(p.arp ? p.tx : o[0], net[0], k); y = lerp(p.arp ? p.ty : o[1], net[1], k); st = k < 0.4 ? (p.arp ? 2 : 1) : 0; }
        }
        p.x = x; p.y = y; p.d = d; p.st = st;
      }
      if (netVis > 0) {
        ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = (dark ? 0.22 : 0.16) * netVis; ctx.strokeStyle = col.m; ctx.lineWidth = 0.7;
        ctx.beginPath();
        for (const [a, b] of edges) { ctx.moveTo(ps[a].x, ps[a].y); ctx.lineTo(ps[b].x, ps[b].y); }
        ctx.stroke();
      }
      if (orbVis > 0) {
        // Ring arcs and spokes, bucketed by depth so the front reads brighter.
        ctx.globalCompositeOperation = add; ctx.strokeStyle = col.g; ctx.lineWidth = dark ? 0.9 : 0.8;
        const buckets: Particle[][] = [[], [], [], []];
        for (const g of groups) {
          const L = g.ids.length;
          for (let s = 0; s < (g.closed ? L : L - 1); s++) {
            const a = ps[g.ids[s]], b = ps[g.ids[(s + 1) % L]];
            if (a.st !== 1 || b.st !== 1 || Math.abs(a.x - b.x) + Math.abs(a.y - b.y) > orb.R * 0.5) continue;
            buckets[depthBucket(a.d + b.d)].push(a, b);
          }
        }
        buckets.forEach((seg, bi) => {
          ctx.globalAlpha = orbVis * (0.12 + bi * 0.2) * (dark ? 1 : 0.8);
          ctx.beginPath();
          for (let s = 0; s < seg.length; s += 2) { ctx.moveTo(seg[s].x, seg[s].y); ctx.lineTo(seg[s + 1].x, seg[s + 1].y); }
          ctx.stroke();
        });
      }
      // Particles are squares: the Pixel A's own marker.
      ctx.globalCompositeOperation = "source-over"; ctx.fillStyle = col.m;
      for (const p of ps) if (p.st === 0) { ctx.globalAlpha = 0.5 * (dark ? 0.9 : 1) * Math.max(netVis, 0.35); sq(p.x, p.y, 1.8); }
      ctx.globalCompositeOperation = add; ctx.fillStyle = col.g;
      for (const p of ps) if (p.st === 1) { ctx.globalAlpha = Math.max(0.15, orbVis) * (0.3 + 0.7 * p.d) * (p.core ? 1 : 0.85); sq(p.x, p.y, p.core ? 2.6 : 1.2 + 1.4 * p.d); }
      ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 1;
      const ds = Math.max(2, cell / dotsPer - 1.2);
      for (const p of ps) if (p.st === 2) { ctx.fillStyle = p.hi ? col.o : col.f; sq(p.x, p.y, ds); }
      if (netVis > 0) {
        // Signals running through the network.
        ctx.globalCompositeOperation = add; ctx.fillStyle = col.r; ctx.globalAlpha = netVis * 0.9;
        pulses.forEach((q, i) => {
          let u = (t - q.t0) / q.dur;
          if (u >= 1 || u < 0) { q = pulses[i] = newPulse(q.b, t); u = 0; }
          sq(lerp(ps[q.a].x, ps[q.b].x, u), lerp(ps[q.a].y, ps[q.b].y, u), 2.6);
        });
      }
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
    };

    build();
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const still = () => draw(18_500);
    // The sidebar theme switch sets data-theme on <html>; the system setting changes the media query.
    // Both re-read the colours, and the reduced-motion still frame is redrawn with them.
    const onTheme = () => {
      readColours();
      if (reduce) still();
    };
    const themeObserver = new MutationObserver(onTheme);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    darkQuery.addEventListener("change", onTheme);
    // Rebuild at most once per frame while the window is being resized.
    let resizeFrame = 0;
    const onResize = () => {
      if (resizeFrame) return;
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = 0;
        build();
        if (reduce) still();
      });
    };
    window.addEventListener("resize", onResize);
    let frame = 0;
    const io = new IntersectionObserver((e) => { visible = e[0].isIntersecting; });
    const onVisibility = () => { if (!document.hidden) readColours(); };
    const cleanup = () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(resizeFrame);
      io.disconnect();
      themeObserver.disconnect();
      darkQuery.removeEventListener("change", onTheme);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
    };
    if (reduce) {
      still();
      return cleanup;
    }
    let visible = true, start: number | null = null;
    io.observe(cv);
    const loop = (now: number) => {
      start ??= now;
      if (visible && !document.hidden) draw(now - start);
      frame = requestAnimationFrame(loop);
    };
    document.addEventListener("visibilitychange", onVisibility);
    frame = requestAnimationFrame(loop);
    return cleanup;
  }, []);
  return <canvas ref={ref} className="landing-canvas" aria-hidden="true" />;
}
