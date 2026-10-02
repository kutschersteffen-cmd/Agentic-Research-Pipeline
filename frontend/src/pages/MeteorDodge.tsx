import { useEffect, useRef, useState } from "react";

const W = 480;
const H = 640;
const SHIP_Y = H - 64;
const BEST_KEY = "arp-meteor-best";
const PHOSPHOR = "#c6ff3d";
const GROUND = "#05070a";

type Phase = "title" | "play" | "over";
type Meteor = { x: number; y: number; r: number; v: number; rot: number; spin: number; shape: number[]; near: boolean };
type Shard = { x: number; y: number; a: number; len: number; vx: number; vy: number; spin: number; life: number };
type Ring = { x: number; y: number; age: number };

const shapeOf = () => Array.from({ length: 6 + Math.floor(Math.random() * 4) }, () => 0.68 + Math.random() * 0.4);

/** Vector-cabinet dodge game: arrows / A D or drag to steer, space or tap to launch. */
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
    let ship = W / 2, t = 0, spawn = 0, pts = 0, shake = 0, flash = 0, raf = 0, last = performance.now();
    let meteors: Meteor[] = [], shards: Shard[] = [], rings: Ring[] = [];
    const keys = new Set<string>();

    const start = () => {
      state = "play"; ship = W / 2; t = 0; spawn = 0.4; pts = 0; shake = 0; flash = 0;
      meteors = []; shards = []; rings = [];
      setPhase("play"); setScore(0); setNewBest(false);
    };
    launch.current = start;

    const crash = () => {
      state = "over"; shake = still ? 0 : 14;
      const pieces: [number, number, number, number][] = [[0, -22, 13, 16], [13, 16, 0, 9], [0, 9, -13, 16], [-13, 16, 0, -22]];
      for (const [x1, y1, x2, y2] of pieces) {
        const a = Math.atan2(y2 - y1, x2 - x1), ang = Math.random() * 6.28;
        shards.push({ x: ship + (x1 + x2) / 2, y: SHIP_Y + (y1 + y2) / 2, a, len: Math.hypot(x2 - x1, y2 - y1), vx: Math.cos(ang) * 90, vy: Math.sin(ang) * 90, spin: (Math.random() - 0.5) * 8, life: 1.4 });
      }
      for (let i = 0; i < 12; i++) {
        const ang = Math.random() * 6.28, sp = 120 + Math.random() * 200;
        shards.push({ x: ship, y: SHIP_Y, a: ang, len: 6 + Math.random() * 10, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, spin: (Math.random() - 0.5) * 12, life: 0.7 + Math.random() * 0.6 });
      }
      const final = Math.floor(pts), prev = Number(localStorage.getItem(BEST_KEY) ?? 0);
      if (final > prev) { localStorage.setItem(BEST_KEY, String(final)); setBest(final); setNewBest(true); }
      setScore(final); setPhase("over");
    };

    const onKey = (down: boolean) => (e: KeyboardEvent) => {
      if (/^(Arrow(Left|Right)|[adAD])$/.test(e.key)) { e.preventDefault(); if (down) keys.add(e.key.toLowerCase()); else keys.delete(e.key.toLowerCase()); }
      if (down && (e.key === " " || e.key === "Enter") && state !== "play") { e.preventDefault(); start(); }
    };
    const kd = onKey(true), ku = onKey(false);
    const aim = (e: PointerEvent) => { if (state === "play") ship = Math.max(16, Math.min(W - 16, ((e.clientX - cv.getBoundingClientRect().left) / cv.clientWidth) * W)); };
    const tap = (e: PointerEvent) => { if (state !== "play") start(); else aim(e); };
    addEventListener("keydown", kd); addEventListener("keyup", ku);
    cv.addEventListener("pointermove", aim); cv.addEventListener("pointerdown", tap);

    const poly = (m: Meteor) => {
      ctx.beginPath();
      m.shape.forEach((k, i) => {
        const a = m.rot + (i / m.shape.length) * 6.283;
        const px = m.x + Math.cos(a) * m.r * k, py = m.y + Math.sin(a) * m.r * k;
        if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
      });
      ctx.closePath(); ctx.stroke();
    };

    function frame(now: number) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (state === "play") {
        t += dt; pts += dt * 10;
        const steer = (keys.has("arrowright") || keys.has("d") ? 1 : 0) - (keys.has("arrowleft") || keys.has("a") ? 1 : 0);
        ship = Math.max(16, Math.min(W - 16, ship + steer * 340 * dt));
        spawn -= dt;
        if (spawn <= 0) {
          meteors.push({ x: Math.random() * W, y: -40, r: [14, 22, 34][Math.floor(Math.random() * 3)], v: 140 + Math.random() * 120 + t * 6, rot: 0, spin: (Math.random() - 0.5) * 2, shape: shapeOf(), near: false });
          spawn = Math.max(0.18, 0.7 - t * 0.012);
        }
        for (const m of meteors) {
          m.y += m.v * dt; m.rot += m.spin * dt;
          const d = Math.hypot(m.x - ship, m.y - SHIP_Y);
          if (d < m.r * 0.82 + 10) { crash(); break; }
          if (!m.near && m.y > SHIP_Y && d < m.r + 36) { m.near = true; pts += 5; flash = 1; rings.push({ x: m.x, y: m.y, age: 0 }); }
        }
        meteors = meteors.filter((m) => m.y < H + 60);
        if (Math.floor(pts) !== Math.floor(pts - dt * 10)) setScore(Math.floor(pts));
      }
      for (const s of shards) { s.x += s.vx * dt; s.y += s.vy * dt; s.a += s.spin * dt; s.life -= dt; }
      shards = shards.filter((s) => s.life > 0);
      for (const r of rings) r.age += dt;
      rings = rings.filter((r) => r.age < 0.5);
      shake = Math.max(0, shake - dt * 30); flash = Math.max(0, flash - dt * 4);

      ctx.save();
      ctx.fillStyle = GROUND; ctx.fillRect(0, 0, W, H);
      if (shake > 0) ctx.translate((Math.random() - 0.5) * shake, (Math.random() - 0.5) * shake);
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
      for (const m of meteors) poly(m);
      for (const r of rings) { ctx.globalAlpha = 1 - r.age * 2; ctx.beginPath(); ctx.arc(r.x, r.y, 20 + r.age * 120, 0, 6.283); ctx.stroke(); }
      ctx.globalAlpha = 1;
      for (const s of shards) {
        ctx.globalAlpha = Math.min(1, s.life); ctx.beginPath();
        ctx.moveTo(s.x - Math.cos(s.a) * s.len / 2, s.y - Math.sin(s.a) * s.len / 2);
        ctx.lineTo(s.x + Math.cos(s.a) * s.len / 2, s.y + Math.sin(s.a) * s.len / 2); ctx.stroke();
      }
      ctx.globalAlpha = 1;

      if (state === "play" || state === "title") {
        const x = state === "title" ? W / 2 : ship;
        ctx.strokeStyle = flash > 0 ? "#ffffff" : PHOSPHOR; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.moveTo(x, SHIP_Y - 22); ctx.lineTo(x + 13, SHIP_Y + 16); ctx.lineTo(x, SHIP_Y + 9); ctx.lineTo(x - 13, SHIP_Y + 16); ctx.closePath(); ctx.stroke();
        ctx.lineWidth = 2; ctx.strokeStyle = PHOSPHOR;
        const f = still ? 10 : 8 + Math.random() * 12;
        ctx.beginPath(); ctx.moveTo(x - 5, SHIP_Y + 13); ctx.lineTo(x, SHIP_Y + 13 + f); ctx.lineTo(x + 5, SHIP_Y + 13); ctx.stroke();
      }
      ctx.restore();
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    const vis = () => { last = performance.now(); };
    document.addEventListener("visibilitychange", vis);
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("keydown", kd); removeEventListener("keyup", ku);
      cv.removeEventListener("pointermove", aim); cv.removeEventListener("pointerdown", tap);
      document.removeEventListener("visibilitychange", vis);
    };
  }, []);

  return (
    <div className="page">
      <h1>Meteor Dodge</h1>
      <p className="muted">Steer with ← → or A D, or drag. Space or a tap launches.</p>
      <div className="cabinet">
        <div className="cabinet-hud" aria-hidden="true">
          <span className={newBest ? "cabinet-score cabinet-score-best" : "cabinet-score"}>{String(score).padStart(5, "0")}</span>
          <span>BEST {String(best).padStart(5, "0")}</span>
        </div>
        <canvas ref={canvas} aria-label="Meteor Dodge game area" />
        <div className="cabinet-vignette" aria-hidden="true" />
        {phase !== "play" && (
          <div className="cabinet-card" aria-live="polite">
            <strong>{phase === "title" ? "METEOR DODGE" : newBest ? "NEW BEST" : "SHIP LOST"}</strong>
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
