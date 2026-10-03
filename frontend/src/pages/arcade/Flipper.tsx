import { useEffect, useRef, useState } from "react";
import { Cabinet, type Phase } from "./Cabinet";
import { bindKeys, loadBest, loop, pad, pointerX, saveBest } from "./kit";

const W = 180, H = 320, R = 3; // low-res table, shown at 2x
const KEY = "arp-flipper-best";
const RAILS: [number, number, number, number][] = [
  [4, 250, 4, 50], [4, 50, 40, 8], [40, 8, 140, 8], [140, 8, 176, 50], [176, 50, 176, 300], [160, 70, 160, 300], [160, 300, 176, 300],
  [4, 250, 56, 284], [160, 250, 124, 284],
];
// slingshots: [kicking face, then the two solid sides]; the kick pushes along the face normal
const SLINGS = [
  { face: [24, 205, 50, 248], sides: [[24, 205, 24, 236], [24, 236, 50, 248]], nx: 0.857, ny: -0.518 },
  { face: [140, 205, 114, 248], sides: [[140, 205, 140, 236], [140, 236, 114, 248]], nx: -0.857, ny: -0.518 },
];
const WALLS = [...RAILS, ...SLINGS.flatMap((s) => s.sides as [number, number, number, number][])];
const BUMPERS = [{ x: 58, y: 96, r: 9 }, { x: 108, y: 96, r: 9 }, { x: 83, y: 134, r: 9 }];
const LANES = [50, 82, 114]; // top rollover lights
const FLIPPERS = [{ px: 56, py: 284, len: 34, side: 1, rest: 0.52, up: -0.5 }, { px: 124, py: 284, len: 34, side: -1, rest: 0.52, up: -0.5 }];
const C = { rail: "#4cc9f0", railDark: "#12385a", bump: "#ff3d9a", yellow: "#ffd23d", ball: "#ffffff" };
// 3x5 pixel letters for the table logo
const FONT: Record<string, string[]> = {
  F: ["111", "100", "110", "100", "100"], L: ["100", "100", "100", "100", "111"], I: ["111", "010", "010", "010", "111"],
  P: ["110", "101", "110", "100", "100"], E: ["111", "100", "110", "100", "111"], R: ["110", "101", "110", "101", "101"],
};

/** The static artwork (night sky, ringed planet, orbit rings, logo) drawn once into its own canvas. */
function paintTable(): HTMLCanvasElement {
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  const sky = ["#0a0420", "#0c0526", "#0e062c", "#110833", "#150a3a", "#190c42", "#1d0e48", "#22104f"];
  sky.forEach((c, i) => { g.fillStyle = c; g.fillRect(0, (i * H) / sky.length, W, H / sky.length + 1); });
  let seed = 11; const r = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 70; i++) { g.fillStyle = i % 7 === 0 ? "#ffd23d88" : "#8a7be0aa"; g.fillRect(Math.floor(r() * W), Math.floor(r() * 250), 1, 1); }
  const disc = (cx: number, cy: number, rad: number, c: string, clip?: (x: number, y: number) => boolean) => { g.fillStyle = c; for (let y = -rad; y <= rad; y++) for (let x = -rad; x <= rad; x++) if (x * x + y * y <= rad * rad && (!clip || clip(cx + x, cy + y))) g.fillRect(cx + x, cy + y, 1, 1); };
  const ring = (front: boolean) => { for (let a = 0; a < 6.283; a += 0.02) { const fr = Math.sin(a) > 0; if (fr !== front) continue; const x = Math.round(83 + Math.cos(a) * 44), y = Math.round(188 + Math.sin(a) * 9 - Math.cos(a) * 4); g.fillStyle = (Math.floor(a * 9) % 2) ? "#4cc9f0" : "#2a7fb0"; g.fillRect(x, y, 1, 2); } };
  ring(false);
  disc(83, 188, 25, "#3b1a78"); // planet body with bands and a lit edge
  for (let y = -22; y <= 22; y += 7) { g.fillStyle = "#5a2aa8"; for (let x = -25; x <= 25; x++) if (x * x + y * y <= 600) g.fillRect(83 + x, 188 + y, 1, 3); }
  for (let y = -25; y <= 25; y++) for (let x = -25; x <= 25; x++) if (x * x + y * y <= 625 && x * x + y * y > 520 && x + y < 4) { g.fillStyle = "#9b74ff"; g.fillRect(83 + x, 188 + y, 1, 1); }
  ring(true);
  for (let a = 0; a < 6.283; a += 0.07) { g.fillStyle = "#ff3d9a55"; g.fillRect(Math.round(83 + Math.cos(a) * 52), Math.round(115 + Math.sin(a) * 52), 1, 1); } // orbit around the bumpers
  const word = "FLIPPER";
  [...word].forEach((ch, i) => FONT[ch].forEach((row, y) => [...row].forEach((v, x) => { if (v === "1") { g.fillStyle = "#ffd23d"; g.fillRect(69 + i * 4 + x, 226 + y, 1, 1); } })));
  return cv;
}

/** Pixel pinball: Left/Right arrows (or tap either half) flip, Space (or tap) launches. */
export function Flipper() {
  const cv = useRef<HTMLCanvasElement>(null);
  const startRef = useRef(() => {});
  const [phase, setPhase] = useState<Phase>("title");
  const [score, setScore] = useState(0);
  const [balls, setBalls] = useState(3);
  const [best, setBest] = useState(() => loadBest(KEY));
  const [fresh, setFresh] = useState(false);

  useEffect(() => {
    const ctx = cv.current!.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let state: Phase = "title", pts = 0, shown = 0, left = 3, ready = true, flashT = 0;
    const ball = { x: 168, y: 292, vx: 0, vy: 0 };
    const ang = [FLIPPERS[0].rest, FLIPPERS[1].rest], omega = [0, 0], held = [false, false], hit = [0, 0, 0], slingHit = [0, 0], lit = [false, false, false], trail: { x: number; y: number }[] = [];
    const art = paintTable();

    const serve = () => { Object.assign(ball, { x: 168, y: 292, vx: 0, vy: 0 }); ready = true; };
    const launch = () => { if (state === "play" && ready) { ball.vy = -420 - (still ? 0 : Math.random() * 20); ready = false; } };
    const start = () => { state = "play"; lit.fill(false); pts = 0; shown = 0; left = 3; setScore(0); setBalls(3); setFresh(false); setPhase("play"); serve(); };
    startRef.current = start;

    const press = (i: 0 | 1, down: boolean) => { held[i] = down; };
    const unbind = bindKeys((k, down) => {
      if (k === "arrowleft" || k === "a" || k === "z") press(0, down);
      if (k === "arrowright" || k === "d" || k === "/" || k === "m") press(1, down);
      if (down && (k === "space" || k === "enter")) { if (state !== "play") start(); else launch(); }
    });
    const el = cv.current!;
    const pd = (e: PointerEvent) => { if (state !== "play") { start(); return; } if (ready) launch(); press(pointerX(e, el) < 0.5 ? 0 : 1, true); };
    const pu = () => { press(0, false); press(1, false); };
    el.addEventListener("pointerdown", pd); addEventListener("pointerup", pu);

    function hitSeg(x0: number, y0: number, x1: number, y1: number, rad: number, e: number, vsAt?: (t: number) => [number, number]) {
      const dx = x1 - x0, dy = y1 - y0;
      const t = Math.max(0, Math.min(1, ((ball.x - x0) * dx + (ball.y - y0) * dy) / (dx * dx + dy * dy)));
      const cx = x0 + t * dx, cy = y0 + t * dy;
      let nx = ball.x - cx, ny = ball.y - cy;
      const d = Math.hypot(nx, ny);
      if (d >= R + rad || d === 0) return null;
      nx /= d; ny /= d;
      ball.x = cx + nx * (R + rad); ball.y = cy + ny * (R + rad);
      const [vsx, vsy] = vsAt ? vsAt(t) : [0, 0];
      let rx = ball.vx - vsx, ry = ball.vy - vsy;
      const vn = rx * nx + ry * ny;
      if (vn < 0) { rx -= (1 + e) * vn * nx; ry -= (1 + e) * vn * ny; ball.vx = rx + vsx; ball.vy = ry + vsy; }
      return t;
    }

    const step = (dt: number) => {
      ball.vy += 260 * dt; ball.x += ball.vx * dt; ball.y += ball.vy * dt;
      for (const [a, b, c, d] of WALLS) hitSeg(a, b, c, d, 1, 0.45);
      SLINGS.forEach((sl, i) => {
        if (hitSeg(sl.face[0], sl.face[1], sl.face[2], sl.face[3], 1.5, 0.3) !== null) { ball.vx += sl.nx * 150; ball.vy += sl.ny * 150; pts += 50; slingHit[i] = 0.12; }
      });
      LANES.forEach((lx, i) => { if (!lit[i] && ball.y < 30 && Math.abs(ball.x - lx) < 9) { lit[i] = true; pts += 25; } });
      if (lit.every(Boolean)) { pts += 500; lit.fill(false); flashT = 0.25; }
      BUMPERS.forEach((b, i) => {
        const dx = ball.x - b.x, dy = ball.y - b.y, d = Math.hypot(dx, dy);
        if (d < R + b.r && d > 0) {
          const nx = dx / d, ny = dy / d;
          ball.x = b.x + nx * (R + b.r); ball.y = b.y + ny * (R + b.r);
          const vn = ball.vx * nx + ball.vy * ny;
          if (vn < 0) { ball.vx -= 2 * vn * nx; ball.vy -= 2 * vn * ny; }
          const sp = Math.hypot(ball.vx, ball.vy) || 1, boost = Math.max(sp, 150) / sp;
          ball.vx *= boost; ball.vy *= boost; pts += 100; hit[i] = 0.15;
        }
      });
      FLIPPERS.forEach((f, i) => {
        const a = ang[i], dirx = f.side * Math.cos(a), diry = Math.sin(a);
        const tx = f.px + dirx * f.len, ty = f.py + diry * f.len;
        // the contact point moves with the flipper: rho * omega, perpendicular to its length
        hitSeg(f.px, f.py, tx, ty, 2.5, 0.35, (t) => [-f.side * Math.sin(a) * omega[i] * t * f.len, Math.cos(a) * omega[i] * t * f.len]);
      });
      const sp = Math.hypot(ball.vx, ball.vy);
      if (sp > 480) { ball.vx *= 480 / sp; ball.vy *= 480 / sp; }
    };

    const stop = loop((dt) => {
      FLIPPERS.forEach((f, i) => {
        const target = held[i] ? f.up : f.rest, old = ang[i];
        ang[i] += Math.max(-1, Math.min(1, (target - old) / (dt * 14))) * dt * 14;
        omega[i] = (ang[i] - old) / dt;
      });
      for (let i = 0; i < hit.length; i++) hit[i] = Math.max(0, hit[i] - dt);
      for (let i = 0; i < slingHit.length; i++) slingHit[i] = Math.max(0, slingHit[i] - dt);
      flashT = Math.max(0, flashT - dt);
      if (state === "play") {
        for (let k = 0; k < 4; k++) {
          if (ready) { ball.y = 292; ball.vy = 0; } else step(dt / 4);
        }
        if (ball.y > H + 8) {
          left -= 1; setBalls(left);
          if (left <= 0) {
            state = "over"; setPhase("over");
            const f = Math.floor(pts);
            if (f > best) { saveBest(KEY, f); setBest(f); setFresh(true); }
          } else serve();
        }
        const s = Math.floor(pts); if (s !== shown) { shown = s; setScore(s); }
      }
      // draw: pre-painted night sky and planet first, then everything that moves or lights up
      ctx.drawImage(art, 0, 0);
      const now = performance.now();
      const line = (x0: number, y0: number, x1: number, y1: number, c: string, th: number) => {
        ctx.fillStyle = c;
        const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0));
        for (let k = 0; k <= n; k++) { const t = k / n; ctx.fillRect(Math.round(x0 + (x1 - x0) * t - th / 2), Math.round(y0 + (y1 - y0) * t - th / 2), th, th); }
      };
      const disc = (cx: number, cy: number, r: number, c: string) => { ctx.fillStyle = c; for (let dy = -r; dy <= r; dy++) { const w = Math.floor(Math.sqrt(r * r - dy * dy)); ctx.fillRect(Math.round(cx) - w, Math.round(cy) + dy, 2 * w + 1, 1); } };
      // rails: dark channel, neon core, bright edge, with a chasing light strip
      RAILS.forEach(([a, b, c, d], ri) => {
        line(a, b, c, d, C.railDark, 5); line(a, b, c, d, C.rail, 2);
        const n = Math.floor(Math.hypot(c - a, d - b) / 9);
        for (let k = 1; k < n; k++) { const t = k / n, on = (Math.floor(now / 140) + k + ri) % 4 === 0; ctx.fillStyle = on ? C.yellow : "#1c5f86"; ctx.fillRect(Math.round(a + (c - a) * t), Math.round(b + (d - b) * t) - 3, 1, 1); }
      });
      SLINGS.forEach((sl, i) => {
        const [fx0, fy0, fx1, fy1] = sl.face;
        line(fx0, fy0, fx1, fy1, slingHit[i] > 0 ? "#ffffff" : C.yellow, 3);
        for (const [a, b, c, d] of sl.sides) line(a, b, c, d, C.rail, 2);
      });
      LANES.forEach((lx, i) => { ctx.fillStyle = lit[i] ? C.yellow : "#3a2a6a"; ctx.fillRect(lx - 3, 20, 7, 3); if (lit[i]) { ctx.fillStyle = "#ffd23d55"; ctx.fillRect(lx - 4, 19, 9, 5); } });
      const pulse = Math.floor(now / 200) % 2;
      BUMPERS.forEach((b, i) => {
        const on = hit[i] > 0;
        disc(b.x, b.y, b.r + 2, on ? "#ffffff55" : "#ff3d9a22");
        disc(b.x, b.y, b.r, on ? "#ffffff" : C.bump); disc(b.x, b.y, b.r - 3, on ? C.yellow : "#7a1a4d"); disc(b.x, b.y, b.r - 6 + (on ? 0 : pulse), on ? "#ffffff" : "#ff3d9a");
      });
      FLIPPERS.forEach((f, i) => {
        const a = ang[i], tx = f.px + f.side * Math.cos(a) * f.len, ty = f.py + Math.sin(a) * f.len;
        line(f.px, f.py, tx, ty, "#12385a", 7); line(f.px, f.py, tx, ty, C.rail, 5); line(f.px, f.py, tx, ty, "#d6f4ff", 2); disc(f.px, f.py, 3, C.yellow);
      });
      if (ready && state === "play" && !still) { ctx.fillStyle = C.yellow; const o = Math.floor(now / 250) % 2 * 2; ctx.fillRect(166, 262 + o, 5, 1); ctx.fillRect(167, 261 + o, 3, 1); ctx.fillRect(168, 260 + o, 1, 1); }
      if (state !== "title") {
        trail.push({ x: ball.x, y: ball.y }); if (trail.length > 7) trail.shift();
        trail.forEach((t, i) => { if (i < trail.length - 1) disc(t.x, t.y, i < 3 ? 1 : 2, i < 3 ? "#4cc9f044" : "#4cc9f088"); });
        disc(ball.x, ball.y, R, "#cfd8e8"); disc(ball.x - 0.5, ball.y - 0.5, 2, C.ball); ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(ball.x) - 1, Math.round(ball.y) - 2, 1, 1);
      }
      if (flashT > 0) { ctx.fillStyle = "#ffd23d33"; ctx.fillRect(0, 0, W, H); }
    });
    return () => { stop(); unbind(); el.removeEventListener("pointerdown", pd); removeEventListener("pointerup", pu); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the game owns its own loop; best is read once at game over
  }, []);

  return (
    <>
      <p className="muted">← → (or A D, or tap the left / right half) flip. Space or a tap launches. Three balls.</p>
      <Cabinet canvasRef={cv} w={W} h={H} scale={2} left={pad(score)} right={`BALLS ${balls}  BEST ${pad(best)}`} phase={phase} flash={fresh}
        headline={phase === "title" ? "FLIPPER" : fresh ? "NEW BEST" : "GAME OVER"} sub={phase === "over" ? `Score ${score}` : undefined}
        cta={phase === "title" ? "PRESS SPACE TO PLAY" : "PRESS SPACE TO RETRY"} onStart={() => startRef.current()} />
    </>
  );
}
