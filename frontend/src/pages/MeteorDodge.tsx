import { useEffect, useRef, useState } from "react";

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
type Rock = { x: number; y: number; vx: number; vy: number; r: number; rot: number; spin: number; shape: number[]; craters: Crater[]; near: boolean };
type Shard = { x: number; y: number; a: number; len: number; vx: number; vy: number; spin: number; life: number };
type Ring = { x: number; y: number; age: number };
type Bolt = { x: number; y: number };

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

function newRock(x: number, y: number, r: number, vy: number, vx = rnd(-30, 30)): Rock {
  const n = 9 + Math.floor(Math.random() * 4);
  return {
    x, y, vx, vy, r, rot: 0, spin: rnd(-1.4, 1.4), near: false,
    shape: Array.from({ length: n }, () => rnd(0.72, 1.12)),
    craters: Array.from({ length: r > 15 ? 2 + Math.floor(Math.random() * 2) : 0 }, () => ({ a: rnd(0, 6.28), d: rnd(0.1, 0.5), k: rnd(0.14, 0.26) })),
  };
}

/** Vector-cabinet shooter: arrows / A D or drag to steer, hold Space (or press) to fire. */
export function MeteorDodge() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const launch = useRef<() => void>(() => {});
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
    const bloom = !still && (navigator.hardwareConcurrency ?? 4) > 2;

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

    const burst = (x: number, y: number, n: number, speed: number, life: number) => {
      for (let i = 0; i < n; i++) {
        const ang = rnd(0, 6.28), sp = rnd(speed * 0.4, speed);
        shards.push({ x, y, a: ang, len: rnd(5, 12), vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, spin: rnd(-10, 10), life: rnd(life * 0.5, life) });
      }
    };

    const crash = () => {
      state = "over"; shake = still ? 0 : 14;
      // The rocket's own outline breaks apart: nose, hull, both fins, nozzle.
      const parts: [number, number, number, number][] = [[0, -30, 8, -2], [0, -30, -8, -2], [8, -2, 8, 14], [-8, -2, -8, 14], [8, 4, 16, 18], [-8, 4, -16, 18], [-5, 14, 5, 14]];
      for (const [x1, y1, x2, y2] of parts) {
        const ang = rnd(0, 6.28);
        shards.push({ x: ship + (x1 + x2) / 2, y: SHIP_Y + (y1 + y2) / 2, a: Math.atan2(y2 - y1, x2 - x1), len: Math.hypot(x2 - x1, y2 - y1), vx: Math.cos(ang) * 90, vy: Math.sin(ang) * 90 - 30, spin: rnd(-6, 6), life: 1.6 });
      }
      burst(ship, SHIP_Y, 14, 300, 1.1);
      rings.push({ x: ship, y: SHIP_Y, age: 0 });
      const final = Math.floor(pts), prev = Number(localStorage.getItem(BEST_KEY) ?? 0);
      if (final > prev) { localStorage.setItem(BEST_KEY, String(final)); setBest(final); setNewBest(true); }
      setScore(final); setPhase("over");
    };

    const split = (rk: Rock) => {
      pts += KILL_POINTS[rk.r] ?? 10;
      burst(rk.x, rk.y, 8, 200, 0.7);
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
      ctx.beginPath();
      m.shape.forEach((k, i) => {
        const a = m.rot + (i / m.shape.length) * 6.283;
        const px = m.x + Math.cos(a) * m.r * k, py = m.y + Math.sin(a) * m.r * k;
        if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
      });
      ctx.closePath(); ctx.stroke();
      ctx.globalAlpha = 0.6;
      for (const c of m.craters) {
        ctx.beginPath(); ctx.arc(m.x + Math.cos(m.rot + c.a) * m.r * c.d * 2, m.y + Math.sin(m.rot + c.a) * m.r * c.d * 2, m.r * c.k, 0, 6.283); ctx.stroke();
      }
      if (m.r > 15) { // a ridge line across the face
        ctx.beginPath();
        ctx.moveTo(m.x + Math.cos(m.rot + 2.2) * m.r * 0.8, m.y + Math.sin(m.rot + 2.2) * m.r * 0.8);
        ctx.lineTo(m.x + Math.cos(m.rot + 3.6) * m.r * 0.35, m.y + Math.sin(m.rot + 3.6) * m.r * 0.35);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    };

    const drawRocket = (x: number, flicker: number) => {
      ctx.save(); ctx.translate(x, SHIP_Y);
      ctx.strokeStyle = flash > 0 ? "#ffffff" : PHOSPHOR; ctx.lineWidth = 2;
      ctx.beginPath(); // hull: ogive nose, straight body
      ctx.moveTo(0, -30); ctx.quadraticCurveTo(10, -17, 8, -2); ctx.lineTo(8, 14); ctx.lineTo(-8, 14); ctx.lineTo(-8, -2); ctx.quadraticCurveTo(-10, -17, 0, -30);
      ctx.stroke();
      ctx.beginPath(); ctx.arc(0, -10, 3.4, 0, 6.283); ctx.stroke(); // porthole
      ctx.beginPath(); ctx.moveTo(-8, 0); ctx.lineTo(8, 0); ctx.stroke(); // hull band
      ctx.beginPath(); // fins
      ctx.moveTo(8, 4); ctx.lineTo(17, 19); ctx.lineTo(8, 14); ctx.moveTo(-8, 4); ctx.lineTo(-17, 19); ctx.lineTo(-8, 14);
      ctx.stroke();
      ctx.beginPath(); ctx.moveTo(-5, 14); ctx.lineTo(-4, 19); ctx.lineTo(4, 19); ctx.lineTo(5, 14); ctx.stroke(); // nozzle
      ctx.strokeStyle = PHOSPHOR; ctx.lineWidth = 1.6; // flame: outer + inner
      ctx.beginPath(); ctx.moveTo(-4, 19); ctx.lineTo(0, 19 + 10 + flicker); ctx.lineTo(4, 19); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(-2, 19); ctx.lineTo(0, 19 + 4 + flicker * 0.5); ctx.lineTo(2, 19); ctx.stroke();
      ctx.restore();
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
      for (const s of shards) { s.x += s.vx * dt; s.y += s.vy * dt; s.a += s.spin * dt; s.life -= dt; }
      shards = shards.filter((s) => s.life > 0);
      for (const r of rings) r.age += dt;
      rings = rings.filter((r) => r.age < 0.5);
      shake = Math.max(0, shake - dt * 30); flash = Math.max(0, flash - dt * 4);

      ctx.save();
      ctx.fillStyle = GROUND; ctx.fillRect(0, 0, W, H);
      if (shake > 0) ctx.translate(rnd(-0.5, 0.5) * shake, rnd(-0.5, 0.5) * shake);
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      if (bloom) { ctx.shadowColor = PHOSPHOR; ctx.shadowBlur = 8; }

      const rush = state === "play" ? Math.min(1, t / 40) : 0;
      for (const l of layers) for (const s of l) {
        if (!still) s.y = (s.y + (14 + s.z * 26) * (1 + rush * 2) * dt) % H;
        ctx.globalAlpha = 0.25 + s.z * 0.25; ctx.fillStyle = PHOSPHOR;
        ctx.fillRect(s.x, s.y, 1 + s.z * 0.6, 1 + s.z * 0.6 + rush * s.z * 10);
      }
      ctx.globalAlpha = 1;

      ctx.lineWidth = 2; ctx.strokeStyle = PHOSPHOR;
      for (const m of rocks) drawRock(m);
      ctx.lineWidth = 2.5; ctx.strokeStyle = "#ffffff";
      for (const b of bolts) { ctx.beginPath(); ctx.moveTo(b.x, b.y); ctx.lineTo(b.x, b.y + 14); ctx.stroke(); }
      ctx.lineWidth = 2; ctx.strokeStyle = PHOSPHOR;
      for (const r of rings) { ctx.globalAlpha = 1 - r.age * 2; ctx.beginPath(); ctx.arc(r.x, r.y, 14 + r.age * 110, 0, 6.283); ctx.stroke(); }
      for (const s of shards) {
        ctx.globalAlpha = Math.min(1, s.life); ctx.beginPath();
        ctx.moveTo(s.x - Math.cos(s.a) * s.len / 2, s.y - Math.sin(s.a) * s.len / 2);
        ctx.lineTo(s.x + Math.cos(s.a) * s.len / 2, s.y + Math.sin(s.a) * s.len / 2); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      if (state !== "over") drawRocket(state === "title" ? W / 2 : ship, still ? 3 : rnd(0, 7));
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
    <div className="page">
      <h1>Meteor Dodge</h1>
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
          </div>
        )}
      </div>
    </div>
  );
}
