import { useEffect, useRef, useState } from "react";
import { Cabinet, type Phase } from "./Cabinet";
import { bindKeys, loadBest, loop, pointerX, rnd, saveBest } from "./kit";

const W = 240, H = 180; // low-res frame, shown at 3x
const SEG = 200, ROAD = 2000, CAM_H = 1000, DEPTH = 0.84, DRAW = 110, MAX = SEG * 60, LAPS = 3;
const KEY = "arp-kartdash-best"; // best race time in milliseconds (lower is better)
const RIVALS = ["#3d9bff", "#ffd23d", "#c6ff3d", "#b86bff", "#ff8a1f", "#4cf0c9", "#ff6b6b"];

// Track layout as [curve strength, segments]; each curve eases in and out.
const SECTIONS: [number, number][] = [[0, 60], [3, 90], [0, 40], [-4, 100], [0, 60], [2, 80], [-2, 80], [0, 50], [5, 70], [0, 40], [-3, 100], [0, 60], [4, 80], [0, 50], [-5, 90], [0, 60], [2, 90]];
const CURVE: number[] = [];
for (const [c, n] of SECTIONS) for (let i = 0; i < n; i++) { const e = Math.min(1, i / (n * 0.25), (n - 1 - i) / (n * 0.25)); CURVE.push(c * e * e * (3 - 2 * e)); }
const N = CURVE.length, TRACK = N * SEG;

const fmt = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${Math.floor((ms % 1000) / 100)}`;
const ord = (n: number) => ["1ST", "2ND", "3RD"][n - 1] ?? `${n}TH`;

/** Pixel kart race: ←/→ steer, hold Space to boost, S to brake. Three laps against seven rivals. */
export function KartDash() {
  const cv = useRef<HTMLCanvasElement>(null);
  const startRef = useRef(() => {});
  const [phase, setPhase] = useState<Phase>("title");
  const [hud, setHud] = useState({ lap: 1, place: 8, time: 0 });
  const [result, setResult] = useState("");
  const [best, setBest] = useState(() => loadBest(KEY));
  const [fresh, setFresh] = useState(false);

  useEffect(() => {
    const ctx = cv.current!.getContext("2d")!;
    let state: Phase = "title", total = 0, speed = 0, px = 0, time = 0, bump = 0, sky = 0;
    const key = { l: false, r: false, boost: false, brake: false };
    let rivals = RIVALS.map((c, i) => ({ c, total: 700 + i * 1100, x: [-0.6, 0.55, -0.2, 0.25, -0.7, 0.7, 0][i], v: MAX * rnd(0.6, 0.86) }));
    const start = () => {
      state = "play"; total = 0; speed = 0; px = 0; time = 0; sky = 0;
      rivals = RIVALS.map((c, i) => ({ c, total: 700 + i * 1100, x: [-0.6, 0.55, -0.2, 0.25, -0.7, 0.7, 0][i], v: MAX * rnd(0.6, 0.86) }));
      setPhase("play"); setFresh(false); setHud({ lap: 1, place: 8, time: 0 });
    };
    startRef.current = start;
    const unbind = bindKeys((k, down) => {
      if (k === "arrowleft" || k === "a") key.l = down;
      if (k === "arrowright" || k === "d") key.r = down;
      if (k === "space" || k === "arrowup" || k === "w") { key.boost = down; if (down && k === "space" && state !== "play") start(); }
      if (k === "arrowdown" || k === "s") key.brake = down;
      if (down && k === "enter" && state !== "play") start();
    });
    const el = cv.current!;
    const pd = (e: PointerEvent) => { if (state !== "play") { start(); return; } const x = pointerX(e, el); key.l = x < 0.5; key.r = x >= 0.5; };
    const pu = () => { key.l = key.r = false; };
    el.addEventListener("pointerdown", pd); el.addEventListener("pointermove", (e) => { if (e.buttons) pd(e); }); addEventListener("pointerup", pu);

    const rect = (x: number, y: number, w: number, h: number, c: string) => { ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h))); };
    const kart = (cx: number, by: number, w: number, c: string) => { // rear view, anchored bottom-centre
      const u = w / 20, x = cx - w / 2, y = by - 11 * u;
      rect(x, y + 5 * u, 4 * u, 6 * u, "#15171c"); rect(x + 16 * u, y + 5 * u, 4 * u, 6 * u, "#15171c");
      rect(x + 3 * u, y + 3 * u, 14 * u, 6 * u, c); rect(x + 2 * u, y, 16 * u, 2 * u, "#f2f2f2");
      rect(x + 7 * u, y - 4 * u, 6 * u, 5 * u, "#ffd23d"); rect(x + 8 * u, y - 2 * u, 4 * u, 2 * u, "#15171c");
      rect(x + 5 * u, y + 9 * u, 3 * u, 2 * u, "#ff8a1f"); rect(x + 12 * u, y + 9 * u, 3 * u, 2 * u, "#ff8a1f");
    };

    const stop = loop((dt, now) => {
      const base = Math.floor((total % TRACK) / SEG), pct = ((total % TRACK) % SEG) / SEG;
      if (state === "play") {
        time += dt * 1000;
        const sp = speed / MAX, d = dt * 2 * sp;
        if (key.l) px -= d; if (key.r) px += d;
        px -= d * sp * CURVE[base] * 0.3; sky += CURVE[base] * sp * dt * 14;
        const top = MAX * (key.boost ? 1.12 : 1);
        speed = key.brake ? Math.max(0, speed - MAX * 0.6 * dt) : Math.min(top, speed + MAX * (key.boost ? 0.5 : 0.28) * dt);
        if (Math.abs(px) > 1 && speed > MAX / 4) speed -= MAX * 0.5 * dt;
        px = Math.max(-2, Math.min(2, px));
        for (const r of rivals) {
          r.total += r.v * dt;
          const rel = (((r.total - total) % TRACK) + TRACK * 1.5) % TRACK - TRACK / 2;
          if (Math.abs(rel) < 230 && Math.abs(r.x - px) < 0.3) { if (rel > -60) speed = Math.min(speed, r.v * 0.8); px += (px >= r.x ? 1 : -1) * dt * 0.8; bump = 0.15; }
        }
        total += speed * dt; bump = Math.max(0, bump - dt);
        const lap = Math.min(LAPS, Math.floor(total / TRACK) + 1);
        const place = 1 + rivals.filter((r) => r.total > total).length;
        setHud((h) => (h.lap !== lap || h.place !== place || Math.floor(h.time / 100) !== Math.floor(time / 100) ? { lap, place, time } : h));
        if (total >= TRACK * LAPS) {
          state = "over"; setPhase("over"); setResult(`${ord(place)} · ${fmt(time)}`);
          if (!best || time < best) { saveBest(KEY, Math.floor(time)); setBest(Math.floor(time)); setFresh(place === 1); }
        }
      }
      // sky: sunset bands, a striped sun and hills that slide with the bends
      const bands = ["#1a0b3a", "#3a1257", "#6a1b6e", "#a62a74", "#e2476b", "#ff7a4d", "#ffb347", "#ffd98a"];
      bands.forEach((c, i) => rect(0, (i * H) / 2 / bands.length, W, Math.ceil(H / 2 / bands.length) + 1, c));
      ctx.fillStyle = "#ffe27a"; for (let dy = -22; dy <= 0; dy++) { if (dy > -10 && dy % 4 === 0) continue; const w = Math.floor(Math.sqrt(22 * 22 - dy * dy)); ctx.fillRect(W / 2 - w - sky * 0.3, H / 2 + dy, 2 * w, 1); }
      ctx.fillStyle = "#2a0f3f";
      for (let x = 0; x < W; x++) { const hh = 14 + Math.sin((x + sky) * 0.045) * 6 + Math.sin((x + sky) * 0.13) * 3; ctx.fillRect(x, H / 2 - hh, 1, hh + 1); }
      // road
      let maxY = H, x = 0, dx = -(CURVE[base] * pct);
      const proj: { x: number; y: number; w: number; s: number }[] = [];
      for (let n = 0; n < DRAW; n++) {
        const i = (base + n) % N, zNear = n * SEG - pct * SEG + 1, zFar = zNear + SEG;
        const camX = px * ROAD;
        const sN = DEPTH / zNear, sF = DEPTH / zFar;
        const x1 = W / 2 + sN * (-camX + x) * (W / 2), y1 = H / 2 + sN * CAM_H * (H / 2), w1 = sN * ROAD * (W / 2);
        const x2 = W / 2 + sF * (-camX + x + dx) * (W / 2), y2 = H / 2 + sF * CAM_H * (H / 2), w2 = sF * ROAD * (W / 2);
        x += dx; dx += CURVE[i];
        proj[n] = { x: x1, y: y1, w: w1, s: sN };
        if (zNear <= DEPTH || y2 >= maxY) continue;
        const alt = Math.floor((total + n * SEG) / (SEG * 3)) % 2 === 0;
        const rows = Math.max(1, Math.round(Math.min(y1, maxY) - y2));
        for (let r = 0; r < rows; r++) {
          const t = rows === 1 ? 1 : r / (rows - 1), yy = Math.round(y2 + (Math.min(y1, maxY) - y2) * t);
          const cx = x2 + (x1 - x2) * t, cw = w2 + (w1 - w2) * t;
          ctx.fillStyle = alt ? "#1d5a28" : "#164a20"; ctx.fillRect(0, yy, W, 1);
          ctx.fillStyle = alt ? "#e8382e" : "#f2f2f2"; ctx.fillRect(Math.round(cx - cw * 1.12), yy, Math.round(cw * 2.24), 1);
          ctx.fillStyle = alt ? "#4a4f5c" : "#434853"; ctx.fillRect(Math.round(cx - cw), yy, Math.round(cw * 2), 1);
          if (alt) { ctx.fillStyle = "#f2f2f2"; ctx.fillRect(Math.round(cx - cw * 0.03), yy, Math.max(1, Math.round(cw * 0.06)), 1); }
        }
        maxY = y2;
      }
      // rivals, far to near
      for (let n = DRAW - 1; n >= 0; n--) {
        const p = proj[n]; if (!p || p.y > H + 20) continue;
        for (const r of rivals) {
          const rel = (((r.total - total) % TRACK) + TRACK) % TRACK;
          if (Math.floor(rel / SEG) !== n) continue;
          kart(p.x + p.w * r.x, p.y, Math.max(2, p.w * 0.2), r.c);
        }
      }
      kart(W / 2 + (key.l ? -3 : key.r ? 3 : 0) + (bump > 0 ? Math.round(rnd(-1, 1)) : 0), H - 8, 30, "#e8382e");
      if (state === "play" && speed > 1000) for (let k = 0; k < 6; k++) rect(rnd(0, W), rnd(H / 2, H), 1, Math.round(speed / MAX * 8), "#ffffff22");
      void now;
    });
    return () => { stop(); unbind(); el.removeEventListener("pointerdown", pd); removeEventListener("pointerup", pu); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the game owns its own loop; best is read at the finish
  }, []);

  return (
    <>
      <p className="muted">← → steer (or touch the left / right half). Hold Space to boost, S to brake. Three laps, seven rivals.</p>
      <Cabinet canvasRef={cv} w={W} h={H} scale={3} left={`LAP ${hud.lap}/${LAPS}  ${hud.place === 8 ? "" : ord(hud.place)}`} right={`${fmt(hud.time)}  BEST ${best ? fmt(best) : "-:--.-"}`}
        phase={phase} flash={fresh} headline={phase === "title" ? "KART DASH" : fresh ? "WINNER" : "FINISH"} sub={phase === "over" ? result : undefined}
        cta={phase === "title" ? "PRESS SPACE TO RACE" : "PRESS SPACE TO RACE AGAIN"} hint={phase === "title" ? "← → steer · Space boost · or touch left / right" : undefined} onStart={() => startRef.current()} />
    </>
  );
}
