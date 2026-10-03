import { useEffect, useRef, useState } from "react";
import { Cabinet, type Phase } from "./Cabinet";
import { bindKeys, loadBest, loop, pad, pointerX, saveBest } from "./kit";

const W = 180, H = 320, R = 3; // low-res table, shown at 2x
const KEY = "arp-flipper-best";
const WALLS: [number, number, number, number][] = [
  [4, 250, 4, 50], [4, 50, 40, 8], [40, 8, 140, 8], [140, 8, 176, 50], [176, 50, 176, 300], [160, 70, 160, 300], [160, 300, 176, 300],
  [4, 250, 56, 284], [160, 250, 124, 284],
];
const BUMPERS = [{ x: 58, y: 96, r: 9 }, { x: 108, y: 96, r: 9 }, { x: 83, y: 134, r: 9 }];
const FLIPPERS = [{ px: 56, py: 284, len: 34, side: 1, rest: 0.52, up: -0.5 }, { px: 124, py: 284, len: 34, side: -1, rest: 0.52, up: -0.5 }];
const C = { bg: "#05070a", wall: "#c6ff3d", bump: "#ff3d9a", bumpHi: "#ffd23d", flip: "#4cc9f0", ball: "#ffffff", dim: "#1d2410" };

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
    const ang = [FLIPPERS[0].rest, FLIPPERS[1].rest], omega = [0, 0], held = [false, false], hit = [0, 0, 0];

    const serve = () => { Object.assign(ball, { x: 168, y: 292, vx: 0, vy: 0 }); ready = true; };
    const launch = () => { if (state === "play" && ready) { ball.vy = -420 - (still ? 0 : Math.random() * 20); ready = false; } };
    const start = () => { state = "play"; pts = 0; shown = 0; left = 3; setScore(0); setBalls(3); setFresh(false); setPhase("play"); serve(); };
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
      // draw
      ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = C.dim;
      for (let y = 20; y < 250; y += 12) for (let x = 12; x < 156; x += 12) ctx.fillRect(x, y, 1, 1);
      const line = (x0: number, y0: number, x1: number, y1: number, c: string, th: number) => {
        ctx.fillStyle = c;
        const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0));
        for (let k = 0; k <= n; k++) { const t = k / n; ctx.fillRect(Math.round(x0 + (x1 - x0) * t - th / 2), Math.round(y0 + (y1 - y0) * t - th / 2), th, th); }
      };
      for (const [a, b, c, d] of WALLS) line(a, b, c, d, C.wall, 2);
      const disc = (cx: number, cy: number, r: number, c: string) => { ctx.fillStyle = c; for (let dy = -r; dy <= r; dy++) { const w = Math.floor(Math.sqrt(r * r - dy * dy)); ctx.fillRect(Math.round(cx) - w, Math.round(cy) + dy, 2 * w + 1, 1); } };
      BUMPERS.forEach((b, i) => { disc(b.x, b.y, b.r, hit[i] > 0 ? "#ffffff" : C.bump); disc(b.x, b.y, b.r - 3, hit[i] > 0 ? C.bumpHi : "#7a1a4d"); });
      FLIPPERS.forEach((f, i) => { const a = ang[i]; line(f.px, f.py, f.px + f.side * Math.cos(a) * f.len, f.py + Math.sin(a) * f.len, C.flip, 5); disc(f.px, f.py, 3, C.flip); });
      if (ready && state === "play" && !still) { ctx.fillStyle = C.wall; const o = Math.floor(performance.now() / 250) % 2 * 2; ctx.fillRect(166, 262 + o, 5, 1); ctx.fillRect(167, 261 + o, 3, 1); ctx.fillRect(168, 260 + o, 1, 1); }
      if (state !== "title") disc(ball.x, ball.y, R, C.ball);
      if (flashT > 0) { ctx.fillStyle = "#ffffff22"; ctx.fillRect(0, 0, W, H); }
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
