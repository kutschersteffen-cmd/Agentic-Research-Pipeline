import { useEffect, useRef, useState } from "react";
import { TouchPad } from "./TouchPad";

const W = 480;
const H = 640;
const SHIP_Y = H - 72;
const BEST_KEY = "arp-meteor-best";
const PHOSPHOR = "#c6ff3d";
const GROUND = "#05070a";
const TIERS = [13, 21, 34]; // asteroid radii: a shot large rock splits into two medium, medium into two small
const KILL_POINTS = { 13: 30, 21: 20, 34: 10 } as Record<number, number>;

type Phase = "title" | "play" | "over";
type Crater = { a: number; d: number; k: number };
type Rock = { frames: HTMLCanvasElement[]; x: number; y: number; vx: number; vy: number; r: number; rot: number; spin: number; shape: number[]; craters: Crater[]; near: boolean };
type Shard = { x: number; y: number; c: string; vx: number; vy: number; life: number };
type Ring = { x: number; y: number; age: number };
type Bolt = { x: number; y: number };

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

// 80s arcade rocks: chunky 3px pixels, four-tone orange shading lit from the top left, four 90-degree spin frames.
const PX = 3;
const TONES = ["#4a1c0c", "#a04418", "#e27a2c", "#ffc870"];

function bake(r: number, shape: number[], craters: Crater[]): HTMLCanvasElement[] {
  const n = Math.ceil((r * 2.5) / PX), c = n / 2;
  return [0, 1, 2, 3].map((k) => {
    const cv = document.createElement("canvas");
    cv.width = cv.height = n * PX;
    const g = cv.getContext("2d")!;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const dx = (x + 0.5 - c) * PX, dy = (y + 0.5 - c) * PX;
      const f = (((Math.atan2(dy, dx) - k * (Math.PI / 2)) / 6.2832) % 1 + 1) % 1 * shape.length;
      const i = Math.floor(f), edge = shape[i] + (shape[(i + 1) % shape.length] - shape[i]) * (f - i);
      if (Math.hypot(dx, dy) > r * edge) continue;
      let tone = (-dx * 0.6 - dy * 0.8) / r > 0.35 ? 3 : (-dx * 0.6 - dy * 0.8) / r > -0.1 ? 2 : (-dx * 0.6 - dy * 0.8) / r > -0.5 ? 1 : 0;
      for (const cr of craters) {
        const a = cr.a + k * (Math.PI / 2);
        if (Math.hypot(dx - Math.cos(a) * r * cr.d * 2, dy - Math.sin(a) * r * cr.d * 2) < r * cr.k) tone = Math.max(0, tone - 2);
      }
      g.fillStyle = TONES[tone];
      g.fillRect(x * PX, y * PX, PX, PX);
    }
    return cv;
  });
}

// The rocket: 11x15 pixel grid, drawn at 3px. R red, W white, B window, G/D greys, Y/O flame.
const ROCKET = [
  ".....R.....", "....RRR....", "....RRR....", "...RRRRR...", "...WWWWW...", "...WBBBW...", "...WBBBW...", "...WWWWW...",
  "...WGGGW...", "...WGGGW...", ".R.WWWWW.R.", "RR.WWWWW.RR", "RRRWGGGWRRR", "RR.DDDDD.RR", "....DDD....",
];
const FLAME = [["....YYY....", ".....O....."], ["....YYY....", "....YOY....", ".....O....."]];
const PAL: Record<string, string> = { R: "#e8382e", W: "#f2f2f2", B: "#4cc9f0", G: "#a3a9b3", D: "#575d68", Y: "#ffe45c", O: "#ff8a1f" };

function bakeRocket(white: boolean): HTMLCanvasElement {
  const cv = document.createElement("canvas");
  cv.width = 11 * PX; cv.height = ROCKET.length * PX;
  const g = cv.getContext("2d")!;
  ROCKET.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === ".") return;
    g.fillStyle = white ? "#ffffff" : PAL[ch];
    g.fillRect(x * PX, y * PX, PX, PX);
  }));
  return cv;
}

function newRock(x: number, y: number, r: number, vy: number, vx = rnd(-30, 30)): Rock {
  const n = 9 + Math.floor(Math.random() * 4);
  const shape = Array.from({ length: n }, () => rnd(0.72, 1.12));
  const craters = Array.from({ length: r > 15 ? 2 + Math.floor(Math.random() * 2) : 0 }, () => ({ a: rnd(0, 6.28), d: rnd(0.1, 0.5), k: rnd(0.14, 0.26) }));
  return { frames: bake(r, shape, craters), x, y, vx, vy, r, rot: 0, spin: rnd(-1.4, 1.4), near: false, shape, craters };
}

/** Vector-cabinet shooter: arrows / A D or drag to steer, hold Space (or press) to fire. */
export function MeteorDodge() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const launch = useRef<() => void>(() => {});
  const press = useRef<(name: "left" | "right" | "fire", down: boolean) => void>(() => {});
  const [phase, setPhase] = useState<Phase>("title");
  const [score, setScore] = useState(0);
  const [best, setBest] = useState(() => Number(localStorage.getItem(BEST_KEY) ?? 0));
  const [newBest, setNewBest] = useState(false);

  useEffect(() => {
    const cv = canvas.current!;
    const ctx = cv.getContext("2d")!;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.scale(dpr, dpr);
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const hull = bakeRocket(false), hullWhite = bakeRocket(true);
    const layers = [0, 1, 2].map((z) => Array.from({ length: 22 + z * 10 }, () => ({ x: Math.random() * W, y: Math.random() * H, z })));
    let state: Phase = "title";
    let ship = W / 2, t = 0, spawn = 0, pts = 0, shown = 0, shake = 0, flash = 0, cool = 0, raf = 0, last = performance.now();
    let rocks: Rock[] = [], shards: Shard[] = [], rings: Ring[] = [], bolts: Bolt[] = [];
    let firing = false;
    const keys = new Set<string>();

    const show = () => { const s = Math.floor(pts); if (s !== shown) { shown = s; setScore(s); } };
    const start = () => {
      state = "play"; ship = W / 2; t = 0; spawn = 0.4; pts = 0; shown = 0; shake = 0; flash = 0; cool = 0;
      rocks = []; shards = []; rings = []; bolts = [];
      setPhase("play"); setScore(0); setNewBest(false);
    };
    launch.current = start;
    press.current = (name, down) => {
      if (name === "fire") { if (down && state !== "play") start(); else firing = down; return; }
      const k = name === "left" ? "arrowleft" : "arrowright";
      if (down) keys.add(k); else keys.delete(k);
    };

    const burst = (x: number, y: number, n: number, speed: number, life: number, colors: string[] = TONES) => {
      for (let i = 0; i < n; i++) {
        const ang = rnd(0, 6.28), sp = rnd(speed * 0.4, speed);
        shards.push({ x, y, c: colors[Math.floor(Math.random() * colors.length)], vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, life: rnd(life * 0.5, life) });
      }
    };

    const crash = () => {
      state = "over"; shake = still ? 0 : 14;
      // Every pixel of the rocket flies apart in its own colour.
      ROCKET.forEach((row, y) => [...row].forEach((ch, x) => {
        if (ch === ".") return;
        const ang = rnd(0, 6.28), sp = rnd(40, 220);
        shards.push({ x: ship + (x - 5) * PX, y: SHIP_Y - 30 + y * PX, c: PAL[ch], vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp - 30, life: rnd(0.8, 1.6) });
      }));
      burst(ship, SHIP_Y, 16, 300, 1.1, [PAL.Y, PAL.O, "#ffffff"]);
      rings.push({ x: ship, y: SHIP_Y, age: 0 });
      const final = Math.floor(pts), prev = Number(localStorage.getItem(BEST_KEY) ?? 0);
      if (final > prev) { localStorage.setItem(BEST_KEY, String(final)); setBest(final); setNewBest(true); }
      setScore(final); setPhase("over");
    };

    const split = (rk: Rock) => {
      pts += KILL_POINTS[rk.r] ?? 10;
      burst(rk.x, rk.y, 10, 200, 0.7);
      rings.push({ x: rk.x, y: rk.y, age: 0 });
      const i = TIERS.indexOf(rk.r);
      if (i > 0) for (const dir of [-1, 1]) rocks.push(newRock(rk.x, rk.y, TIERS[i - 1], rk.vy * 0.9, dir * rnd(50, 110)));
    };

    const onKey = (down: boolean) => (e: KeyboardEvent) => {
      if (/^(Arrow(Left|Right)|[adAD])$/.test(e.key)) { e.preventDefault(); if (down) keys.add(e.key.toLowerCase()); else keys.delete(e.key.toLowerCase()); }
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        if (state !== "play") { if (down) start(); } else if (e.key === " ") firing = down;
      }
    };
    const kd = onKey(true), ku = onKey(false);
    const aim = (e: PointerEvent) => { if (state === "play") ship = Math.max(18, Math.min(W - 18, ((e.clientX - cv.getBoundingClientRect().left) / cv.clientWidth) * W)); };
    const down = (e: PointerEvent) => { if (state !== "play") start(); else { aim(e); firing = true; } };
    const up = () => { firing = false; };
    addEventListener("keydown", kd); addEventListener("keyup", ku); addEventListener("pointerup", up);
    cv.addEventListener("pointermove", aim); cv.addEventListener("pointerdown", down);

    const drawRock = (m: Rock) => {
      const f = m.frames[((Math.floor(m.rot * 2) % 4) + 4) % 4];
      const prev = ctx.shadowBlur;
      ctx.shadowBlur = 0; ctx.imageSmoothingEnabled = false;
      ctx.drawImage(f, Math.round(m.x - f.width / 2), Math.round(m.y - f.height / 2));
      ctx.shadowBlur = prev;
    };

    const drawRocket = (x: number, frameNo: number) => {
      const left = Math.round(x - (11 * PX) / 2), top = SHIP_Y - 30;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(flash > 0 ? hullWhite : hull, left, top);
      FLAME[frameNo % 2].forEach((row, y) => [...row].forEach((ch, cx) => {
        if (ch === ".") return;
        ctx.fillStyle = PAL[ch];
        ctx.fillRect(left + cx * PX, top + (ROCKET.length + y) * PX, PX, PX);
      }));
    };

    function frame(now: number) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (state === "play") {
        t += dt; pts += dt * 5;
        const steer = (keys.has("arrowright") || keys.has("d") ? 1 : 0) - (keys.has("arrowleft") || keys.has("a") ? 1 : 0);
        ship = Math.max(18, Math.min(W - 18, ship + steer * 340 * dt));
        cool -= dt;
        if (firing && cool <= 0) { bolts.push({ x: ship, y: SHIP_Y - 32 }); cool = 0.2; }
        spawn -= dt;
        if (spawn <= 0) {
          const r = TIERS[Math.random() < 0.45 ? 2 : Math.floor(Math.random() * 2)];
          rocks.push(newRock(rnd(20, W - 20), -40, r, rnd(70, 130) + t * 3));
          spawn = Math.max(0.35, 1.1 - t * 0.012);
        }
        for (const b of bolts) b.y -= 640 * dt;
        bolts = bolts.filter((b) => b.y > -20);
        for (const m of [...rocks]) {
          m.x += m.vx * dt; m.y += m.vy * dt; m.rot += m.spin * dt;
          const i = bolts.findIndex((b) => Math.hypot(b.x - m.x, b.y - m.y) < m.r * 0.92);
          if (i >= 0) { bolts.splice(i, 1); rocks.splice(rocks.indexOf(m), 1); split(m); continue; }
          const d = Math.min(Math.hypot(m.x - ship, m.y - SHIP_Y), Math.hypot(m.x - ship, m.y - (SHIP_Y - 20)) + 2);
          if (d < m.r * 0.82 + 10) { crash(); break; }
          if (!m.near && m.y > SHIP_Y && d < m.r + 38) { m.near = true; pts += 5; flash = 1; rings.push({ x: m.x, y: m.y, age: 0 }); }
        }
        rocks = rocks.filter((m) => m.y < H + 60 && m.x > -60 && m.x < W + 60);
        show();
      }
      for (const s of shards) { s.x += s.vx * dt; s.y += s.vy * dt; s.life -= dt; }
      shards = shards.filter((s) => s.life > 0);
      for (const r of rings) r.age += dt;
      rings = rings.filter((r) => r.age < 0.5);
      shake = Math.max(0, shake - dt * 30); flash = Math.max(0, flash - dt * 4);

      ctx.save();
      ctx.fillStyle = GROUND; ctx.fillRect(0, 0, W, H);
      if (shake > 0) ctx.translate(rnd(-0.5, 0.5) * shake, rnd(-0.5, 0.5) * shake);
      ctx.lineCap = "round"; ctx.lineJoin = "round";

      const rush = state === "play" ? Math.min(1, t / 40) : 0;
      for (const l of layers) for (const s of l) {
        if (!still) s.y = (s.y + (14 + s.z * 26) * (1 + rush * 2) * dt) % H;
        ctx.globalAlpha = 0.25 + s.z * 0.25; ctx.fillStyle = PHOSPHOR;
        ctx.fillRect(s.x, s.y, 1 + s.z * 0.6, 1 + s.z * 0.6 + rush * s.z * 10);
      }
      ctx.globalAlpha = 1;

      ctx.lineWidth = 2; ctx.strokeStyle = PHOSPHOR;
      for (const m of rocks) drawRock(m);
      for (const b of bolts) {
        const bx = Math.round(b.x - 1.5), by = Math.round(b.y);
        ctx.fillStyle = PAL.Y; ctx.fillRect(bx, by, PX, PX);
        ctx.fillStyle = "#ffffff"; ctx.fillRect(bx, by + PX, PX, PX * 3);
      }
      ctx.lineWidth = 2; ctx.strokeStyle = PHOSPHOR;
      ctx.lineWidth = PX; ctx.lineJoin = "miter";
      for (const r of rings) { ctx.globalAlpha = 1 - r.age * 2; const h = Math.round((8 + r.age * 90) / PX) * PX; ctx.strokeRect(Math.round(r.x - h), Math.round(r.y - h), h * 2, h * 2); }
      ctx.lineJoin = "round";
      for (const sh of shards) {
        ctx.globalAlpha = Math.min(1, sh.life * 2); ctx.fillStyle = sh.c;
        ctx.fillRect(Math.round(sh.x / PX) * PX, Math.round(sh.y / PX) * PX, PX, PX);
      }
      ctx.globalAlpha = 1;
      if (state !== "over") drawRocket(state === "title" ? W / 2 : ship, still ? 0 : Math.floor(now / 90));
      ctx.restore();
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    const vis = () => { last = performance.now(); };
    document.addEventListener("visibilitychange", vis);
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("keydown", kd); removeEventListener("keyup", ku); removeEventListener("pointerup", up);
      cv.removeEventListener("pointermove", aim); cv.removeEventListener("pointerdown", down);
      document.removeEventListener("visibilitychange", vis);
    };
  }, []);

  return (
    <>
      <p className="muted">Steer with ← → or A D, or drag. Hold Space, or press and hold, to fire. Big rocks split in two.</p>
      <div className="cabinet">
        <div className="cabinet-hud" aria-hidden="true">
          <span className={newBest ? "cabinet-score cabinet-score-best" : "cabinet-score"}>{String(score).padStart(5, "0")}</span>
          <span>BEST {String(best).padStart(5, "0")}</span>
        </div>
        <canvas ref={canvas} aria-label="Meteor Dodge game area" />
        <div className="cabinet-vignette" aria-hidden="true" />
        {phase !== "play" && (
          <div className="cabinet-card" aria-live="polite">
            <strong>{phase === "title" ? "METEOR DODGE" : newBest ? "NEW BEST" : "ROCKET LOST"}</strong>
            {phase === "over" && <span>Score {score}</span>}
            <button type="button" className="cabinet-go" onClick={() => launch.current()}>
              {phase === "title" ? "PRESS SPACE TO LAUNCH" : "PRESS SPACE TO RETRY"}
            </button>
            {phase === "title" && <span className="cabinet-hint">← → steer · hold Space to fire · or drag</span>}
          </div>
        )}
      </div>
      <TouchPad maxWidth={480} pads={[
        { label: "◀", aria: "Steer left", hold: (d) => press.current("left", d) },
        { label: "FIRE", aria: "Fire", hold: (d) => press.current("fire", d) },
        { label: "▶", aria: "Steer right", hold: (d) => press.current("right", d) },
      ]} />
    </>
  );
}
