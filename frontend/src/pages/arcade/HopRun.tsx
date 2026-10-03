import { useEffect, useRef, useState } from "react";
import { Cabinet, type Phase } from "./Cabinet";
import { TouchPad } from "./TouchPad";
import { bindKeys, loadBest, loop, pad, pointerX, saveBest } from "./kit";

const W = 256, H = 144, T = 16, LW = 200, LH = 9; // low-res screen (shown at 3x), 16px tiles
const KEY = "arp-hoprun-best";

// ---- the level: ground with gaps, floating bricks, coins, walkers and a goal flag
const map: number[][] = Array.from({ length: LH }, () => Array<number>(LW).fill(0));
const GAPS: [number, number][] = [[22, 3], [38, 2], [55, 4], [72, 3], [90, 3], [108, 5], [128, 3], [150, 4], [170, 3]];
const inGap = (x: number) => GAPS.some(([g, w]) => x >= g && x < g + w);
for (let x = 0; x < LW; x++) if (!inGap(x)) { map[7][x] = 1; map[8][x] = 1; }
const BRICKS: [number, number, number][] = [[12, 5, 3], [28, 4, 3], [44, 4, 4], [60, 5, 3], [78, 3, 3], [96, 4, 4], [115, 3, 3], [134, 4, 4], [155, 3, 3], [176, 4, 3]];
for (const [x, y, w] of BRICKS) for (let i = 0; i < w; i++) map[y][x + i] = 2;
for (const x of [48, 100, 140]) { map[6][x] = 2; map[6][x + 1] = 2; map[5][x + 1] = 2; }
const COINS: { x: number; y: number }[] = [];
for (const [x, y, w] of BRICKS) for (let i = 0; i < w; i++) COINS.push({ x: (x + i) * T + 4, y: (y - 1) * T + 4 });
for (const [g, w] of GAPS) for (let i = 0; i < w; i++) COINS.push({ x: (g + i) * T + 4, y: 4 * T + (i === 1 ? 0 : 6) });
const WALKERS = [18, 34, 50, 66, 84, 102, 120, 140, 162, 182];
const GOAL_X = 195 * T;

const HERO = ["..RRRRRR..", ".RRRRRRRR.", ".RCCCCCCR.", ".RCCCCCCR.", "..RRRRRR..", "..WWWWWW..", ".WWWGGWWW.", ".WWWWWWWW.", ".WWWWWWWW.", "..WWWWWW.."];
const LEGS = [["..WW..WW..", "..WW..WW..", "..DD..DD..", ".DDD..DDD."], ["...WWWW...", "...WWWW...", "...DDDD...", "...DDDD..."], [".WW....WW.", ".DD....DD.", "..........", ".........."]];
const PAL: Record<string, string> = { R: "#e8382e", W: "#f2f2f2", C: "#4cc9f0", G: "#a3a9b3", D: "#575d68" };

/** Pixel platformer: ←/→ run, Space or ↑ jump (hold for height). Stomp walkers, grab coins, reach the flag. */
export function HopRun() {
  const cv = useRef<HTMLCanvasElement>(null);
  const startRef = useRef(() => {});
  const press = useRef<(name: "run" | "jump", down: boolean) => void>(() => {});
  const [phase, setPhase] = useState<Phase>("title");
  const [score, setScore] = useState(0);
  const [headline, setHeadline] = useState("HOP & RUN");
  const [best, setBest] = useState(() => loadBest(KEY));
  const [fresh, setFresh] = useState(false);

  useEffect(() => {
    const ctx = cv.current!.getContext("2d")!;
    let state: Phase = "title", pts = 0, shown = 0, time = 0, coyote = 0, buffer = 0, anim = 0;
    const pl = { x: 2 * T, y: 6 * T - 14, vx: 0, vy: 0, face: 1, ground: false };
    let taken = new Set<number>(), walkers = WALKERS.map((x) => ({ x: x * T, y: 7 * T - 10, dir: -1, alive: true }));
    const key = { l: false, r: false, jump: false };

    const start = () => {
      state = "play"; pts = 0; shown = 0; time = 0; Object.assign(pl, { x: 2 * T, y: 6 * T - 14, vx: 0, vy: 0, face: 1, ground: false });
      taken = new Set(); walkers = WALKERS.map((x) => ({ x: x * T, y: 7 * T - 10, dir: -1, alive: true }));
      setScore(0); setFresh(false); setPhase("play");
    };
    startRef.current = start;
    press.current = (name, down) => {
      if (name === "run") { key.r = down; return; }
      key.jump = down;
      if (down) { if (state !== "play") start(); else buffer = 0.12; }
    };
    const finish = (won: boolean) => {
      state = "over"; setPhase("over");
      const f = Math.floor(pts + (won ? Math.max(0, 120 - time) * 5 : 0));
      setScore(f); setHeadline(won ? "COURSE CLEAR" : "TRY AGAIN");
      if (f > best) { saveBest(KEY, f); setBest(f); setFresh(true); }
    };
    const unbind = bindKeys((k, down) => {
      if (k === "arrowleft" || k === "a") key.l = down;
      if (k === "arrowright" || k === "d") key.r = down;
      if (k === "space" || k === "arrowup" || k === "w" || k === "z") {
        key.jump = down;
        if (down) { if (state !== "play") start(); else buffer = 0.12; }
      }
    });
    const el = cv.current!;
    const zones = new Map<number, number>();
    const apply = () => { const z = [...zones.values()]; key.l = z.includes(0); key.r = z.includes(2); key.jump = z.includes(1); if (key.jump) buffer = 0.12; };
    const pd = (e: PointerEvent) => { if (state !== "play") { start(); return; } const x = pointerX(e, el); zones.set(e.pointerId, x < 0.33 ? 0 : x > 0.66 ? 2 : 1); apply(); };
    const pu = (e: PointerEvent) => { zones.delete(e.pointerId); apply(); };
    el.addEventListener("pointerdown", pd); addEventListener("pointerup", pu);

    const solid = (x: number, y: number) => { const r = Math.floor(y / T), c = Math.floor(x / T); return r >= 0 && r < LH && c >= 0 && c < LW && map[r][c] > 0; };
    const hitsTile = (x: number, y: number, w: number, h: number) => solid(x, y) || solid(x + w - 1, y) || solid(x, y + h - 1) || solid(x + w - 1, y + h - 1);

    const stop = loop((dt, now) => {
      if (state === "play") {
        time += dt;
        const want = (key.r ? 1 : 0) - (key.l ? 1 : 0);
        pl.vx += (want * 95 - pl.vx) * Math.min(1, dt * (pl.ground ? 12 : 6));
        if (want) pl.face = want;
        pl.vy = Math.min(260, pl.vy + 900 * dt);
        coyote = pl.ground ? 0.1 : coyote - dt; buffer -= dt;
        if (buffer > 0 && coyote > 0) { pl.vy = -300; coyote = 0; buffer = 0; pl.ground = false; }
        if (!key.jump && pl.vy < -120) pl.vy = -120;
        pl.x += pl.vx * dt;
        if (hitsTile(pl.x, pl.y, 10, 14)) { pl.x = pl.vx > 0 ? Math.floor((pl.x + 10) / T) * T - 10 : (Math.floor(pl.x / T) + 1) * T; pl.vx = 0; }
        pl.x = Math.max(0, pl.x);
        pl.y += pl.vy * dt; pl.ground = false;
        if (hitsTile(pl.x, pl.y, 10, 14)) {
          if (pl.vy > 0) { pl.y = Math.floor((pl.y + 14) / T) * T - 14; pl.ground = true; } else pl.y = (Math.floor(pl.y / T) + 1) * T;
          pl.vy = 0;
        }
        anim += Math.abs(pl.vx) * dt * 0.12;
        COINS.forEach((c, i) => { if (!taken.has(i) && Math.abs(pl.x + 5 - (c.x + 4)) < 9 && Math.abs(pl.y + 7 - (c.y + 4)) < 11) { taken.add(i); pts += 10; } });
        for (const w of walkers) {
          if (!w.alive) continue;
          const nx = w.x + w.dir * 22 * dt, front = w.dir > 0 ? nx + 12 : nx;
          if (solid(front, w.y + 4) || !solid(front, w.y + 12)) w.dir = -w.dir; else w.x = nx;
          if (pl.x + 10 > w.x && pl.x < w.x + 12 && pl.y + 14 > w.y && pl.y < w.y + 10) {
            if (pl.vy > 40 && pl.y + 14 - pl.vy * dt <= w.y + 4) { w.alive = false; pl.vy = -190; pts += 100; } else { finish(false); break; }
          }
        }
        if (state === "play" && pl.y > H + 20) finish(false);
        if (state === "play" && pl.x + 10 > GOAL_X) finish(true);
        const s = Math.floor(pts); if (s !== shown) { shown = s; setScore(s); }
      }
      // ---- draw
      const camX = Math.round(Math.max(0, Math.min(LW * T - W, pl.x - 100)));
      ctx.fillStyle = "#4aa3e8"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#6ab8f0"; ctx.fillRect(0, 70, W, 74);
      ctx.fillStyle = "#ffffff";
      for (let i = 0; i < 9; i++) { const cx = ((i * 83 - camX * 0.25) % (W + 60) + W + 60) % (W + 60) - 30, cy = 14 + (i % 3) * 18; ctx.fillRect(cx, cy, 24, 6); ctx.fillRect(cx + 4, cy - 4, 14, 4); }
      for (const [par, col, amp] of [[0.4, "#2f8f55", 30], [0.65, "#247a45", 18]] as const) {
        ctx.fillStyle = col;
        for (let x = 0; x < W; x += 2) { const hh = 26 + amp * (0.5 + 0.5 * Math.sin((x + camX * par) * 0.03 + amp)); ctx.fillRect(x, H - 32 - hh, 2, hh + 32); }
      }
      for (let r = 0; r < LH; r++) for (let c = Math.floor(camX / T); c <= Math.floor((camX + W) / T); c++) {
        const t = map[r]?.[c]; if (!t) continue;
        const x = c * T - camX, y = r * T;
        if (t === 1) { ctx.fillStyle = "#8a5a2b"; ctx.fillRect(x, y, T, T); ctx.fillStyle = "#6e4520"; ctx.fillRect(x + 3, y + 7, 2, 2); ctx.fillRect(x + 10, y + 11, 2, 2); if (!map[r - 1]?.[c]) { ctx.fillStyle = "#3ec45a"; ctx.fillRect(x, y, T, 5); ctx.fillStyle = "#2a9a42"; ctx.fillRect(x, y + 4, T, 1); } }
        else { ctx.fillStyle = "#c4632b"; ctx.fillRect(x, y, T, T); ctx.fillStyle = "#7a3a14"; ctx.fillRect(x, y + 7, T, 1); ctx.fillRect(x, y + 15, T, 1); ctx.fillRect(x + 7, y, 1, 7); ctx.fillRect(x + 3, y + 8, 1, 7); ctx.fillStyle = "#e08a4a"; ctx.fillRect(x, y, T, 1); }
      }
      COINS.forEach((c, i) => { if (taken.has(i)) return; const w = Math.abs(Math.sin(now / 200 + i)) * 6 + 2; ctx.fillStyle = "#ffd23d"; ctx.fillRect(c.x - camX + 4 - w / 2, c.y, w, 8); ctx.fillStyle = "#b8860b"; ctx.fillRect(c.x - camX + 4 - w / 2, c.y + 7, w, 1); });
      for (const w of walkers) { if (!w.alive) continue; const x = Math.round(w.x - camX), y = Math.round(w.y), f = Math.floor(now / 160) % 2; ctx.fillStyle = "#8f3fb0"; ctx.fillRect(x, y + 2, 12, 7); ctx.fillRect(x + 2, y, 8, 2); ctx.fillStyle = "#fff"; ctx.fillRect(x + 2, y + 3, 3, 3); ctx.fillRect(x + 7, y + 3, 3, 3); ctx.fillStyle = "#000"; ctx.fillRect(x + 3, y + 4, 1, 2); ctx.fillRect(x + 8, y + 4, 1, 2); ctx.fillStyle = "#4a1c5c"; ctx.fillRect(x + (f ? 0 : 1), y + 9, 4, 1); ctx.fillRect(x + (f ? 8 : 7), y + 9, 4, 1); }
      ctx.fillStyle = "#f2f2f2"; ctx.fillRect(GOAL_X - camX, 3 * T, 2, 4 * T); ctx.fillStyle = "#e8382e"; ctx.fillRect(GOAL_X - camX + 2, 3 * T + 2, 12, 8); ctx.fillStyle = "#ffd23d"; ctx.fillRect(GOAL_X - camX - 1, 3 * T - 3, 4, 3);
      if (state !== "over") {
        const legs = LEGS[!pl.ground ? 2 : Math.abs(pl.vx) > 8 ? Math.floor(anim) % 2 : 0], rows = [...HERO, ...legs];
        rows.forEach((row, ry) => [...row].forEach((ch, cx) => { if (ch === ".") return; ctx.fillStyle = PAL[ch]; ctx.fillRect(Math.round(pl.x - camX) + (pl.face > 0 ? cx : 9 - cx), Math.round(pl.y) + ry, 1, 1); }));
      }
    });
    return () => { stop(); unbind(); el.removeEventListener("pointerdown", pd); removeEventListener("pointerup", pu); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the game owns its own loop; best is read at the end of a run
  }, []);

  return (
    <>
      <p className="muted">← → run, Space or ↑ jump (hold for height). Stomp the purple walkers, grab coins, reach the flag. On touch: left, middle and right thirds.</p>
      <Cabinet canvasRef={cv} w={W} h={H} scale={3} left={pad(score)} right={`BEST ${pad(best)}`} phase={phase} flash={fresh}
        headline={phase === "title" ? "HOP & RUN" : fresh ? "NEW BEST" : headline} sub={phase === "over" ? `Score ${score}` : undefined}
        cta={phase === "title" ? "PRESS SPACE TO START" : "PRESS SPACE TO RETRY"} hint={phase === "title" ? "← → run · Space jump · or touch thirds" : undefined} onStart={() => startRef.current()} />
      <TouchPad maxWidth={768} pads={[
        { label: "RUN", aria: "Run", hold: (d) => press.current("run", d) },
        { label: "JUMP", aria: "Jump", hold: (d) => press.current("jump", d) },
      ]} />
    </>
  );
}
