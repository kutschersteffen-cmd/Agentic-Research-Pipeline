import { useEffect, useRef, useState } from "react";

const W = 480;
const H = 640;
const BEST_KEY = "arp-meteor-best";

type Meteor = { x: number; y: number; r: number; v: number };

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

/** Arrow keys / A-D or drag to steer, dodge the meteors. Space or tap to restart. */
export function MeteorDodge() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [score, setScore] = useState(0);
  const [best, setBest] = useState(() => Number(localStorage.getItem(BEST_KEY) ?? 0));
  const [over, setOver] = useState(false);
  const [round, setRound] = useState(0);

  useEffect(() => {
    const cv = canvas.current!;
    const ctx = cv.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ship = { x: W / 2, dir: 0 };
    const meteors: Meteor[] = [];
    const keys = new Set<string>();
    let t = 0, spawn = 0, pts = 0, dead = false, raf = 0, last = performance.now();

    const key = (down: boolean) => (e: KeyboardEvent) => {
      if (e.key === " " && down && dead) setRound((n) => n + 1);
      if (/^(Arrow|[adAD])/.test(e.key)) { e.preventDefault(); if (down) keys.add(e.key.toLowerCase()); else keys.delete(e.key.toLowerCase()); }
    };
    const kd = key(true), ku = key(false);
    const point = (e: PointerEvent) => { if (dead) return; ship.x = ((e.clientX - cv.getBoundingClientRect().left) / cv.clientWidth) * W; };
    addEventListener("keydown", kd); addEventListener("keyup", ku);
    cv.addEventListener("pointermove", point); cv.addEventListener("pointerdown", point);
    cv.addEventListener("pointerdown", () => dead && setRound((n) => n + 1));

    const stars = Array.from({ length: 60 }, () => ({ x: Math.random() * W, y: Math.random() * H, s: 0.3 + Math.random() }));

    function frame(now: number) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (!dead) {
        t += dt; pts += dt * 10;
        const steer = (keys.has("arrowright") || keys.has("d") ? 1 : 0) - (keys.has("arrowleft") || keys.has("a") ? 1 : 0);
        ship.x = Math.max(16, Math.min(W - 16, ship.x + steer * 340 * dt));
        spawn -= dt;
        if (spawn <= 0) {
          meteors.push({ x: Math.random() * W, y: -30, r: 12 + Math.random() * 22, v: 140 + Math.random() * 120 + t * 6 });
          spawn = Math.max(0.18, 0.7 - t * 0.012);
        }
        for (const m of meteors) m.y += m.v * dt;
        while (meteors.length && meteors[0].y > H + 40) meteors.shift();
        if (meteors.some((m) => Math.hypot(m.x - ship.x, m.y - (H - 60)) < m.r + 12)) {
          dead = true; setOver(true);
          const final = Math.floor(pts);
          if (final > Number(localStorage.getItem(BEST_KEY) ?? 0)) { localStorage.setItem(BEST_KEY, String(final)); setBest(final); }
        }
        setScore(Math.floor(pts));
      }

      const ink = css("--accent"), bg = css("--panel"), sig = css("--signal") || ink;
      ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = css("--muted");
      for (const s of stars) { if (!still) s.y = (s.y + s.s * 40 * dt) % H; ctx.fillRect(s.x, s.y, s.s, s.s); }
      ctx.strokeStyle = ink; ctx.lineWidth = 2;
      for (const m of meteors) { ctx.beginPath(); ctx.arc(m.x, m.y, m.r, 0, 7); ctx.stroke(); ctx.beginPath(); ctx.arc(m.x - m.r * 0.3, m.y - m.r * 0.2, m.r * 0.25, 0, 7); ctx.stroke(); }
      if (!dead) {
        const y = H - 60;
        ctx.fillStyle = ink; ctx.beginPath(); ctx.moveTo(ship.x, y - 22); ctx.lineTo(ship.x + 13, y + 16); ctx.lineTo(ship.x, y + 9); ctx.lineTo(ship.x - 13, y + 16); ctx.closePath(); ctx.fill();
        ctx.fillStyle = sig; ctx.beginPath(); ctx.moveTo(ship.x - 5, y + 12); ctx.lineTo(ship.x, y + 20 + Math.random() * 10); ctx.lineTo(ship.x + 5, y + 12); ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    setScore(0); setOver(false);
    return () => { cancelAnimationFrame(raf); removeEventListener("keydown", kd); removeEventListener("keyup", ku); };
  }, [round]);

  return (
    <div className="page">
      <h1>Meteor Dodge</h1>
      <p className="muted">← → or A D to steer, or drag. Survive as long as you can.</p>
      <p><strong>Score {score}</strong> · Best {best}{over && " · Crashed. Press space or tap to retry."}</p>
      <canvas ref={canvas} width={W} height={H} aria-label="Meteor Dodge game" style={{ width: "100%", maxWidth: W, border: "1px solid var(--panel-border)", touchAction: "none", display: "block" }} />
    </div>
  );
}
