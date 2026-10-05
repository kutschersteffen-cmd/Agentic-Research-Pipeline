import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import "./RunHeat.css";
import { CHECKPOINTS, END, HOLD, N, STAGES, buildRun, companyName, eta, progress, stats, throughput } from "./runHeatData.ts";
import type { Run, Stats } from "./runHeatData.ts";

const GUT = 44, TOP = 26, SPEED = 110; // SPEED: real ms per simulated minute
const NS = STAGES.length;
const READ_IDLE = "Hover or tap a row to read company, stage, retries.";

interface Palette { bg: string; grid: string; ink: string; muted: string; hi: string; from: number[]; to: number[] }

// Resolve any CSS colour to [r,g,b] via the canvas itself.
function rgb(ctx: CanvasRenderingContext2D, css: string): number[] {
  ctx.fillStyle = "#000";
  ctx.fillStyle = css;
  const h = ctx.fillStyle as string;
  return h.startsWith("#") ? [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) : [0, 0, 0];
}
const mix = (a: number[], b: number[], p: number) => `rgb(${a.map((v, n) => Math.round(v * (1 - p) + b[n] * p)).join(",")})`;

function readPalette(el: HTMLElement, ctx: CanvasRenderingContext2D): Palette {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  const bg = rgb(ctx, v("--panel")), ink = rgb(ctx, v("--text"));
  return {
    bg: mix(bg, bg, 0), grid: v("--panel-border"), ink: v("--text"), muted: v("--muted"), hi: v("--hi"),
    from: rgb(ctx, v("--panel-border")),
    to: ink.map((c, n) => c * 0.85 + bg[n] * 0.15),
  };
}

function stageAt(run: Run, i: number, t: number): number {
  let k = 0;
  while (k < NS - 1 && run.blockedAt[i] !== k && t >= run.start[i * NS + k] + run.dur[i * NS + k]) k++;
  return k;
}

export function RunHeat() {
  const rootRef = useRef<HTMLDivElement>(null);
  const cvRef = useRef<HTMLCanvasElement>(null);
  const run = useMemo(() => buildRun(), []);
  const reduced = useRef(typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const T = useRef(reduced.current ? END : 0);
  const hov = useRef(-1);
  const playingRef = useRef(!reduced.current);
  const redraw = useRef<() => void>(() => {});
  const [playing, setPlaying] = useState(!reduced.current);
  const [finished, setFinished] = useState(reduced.current);
  const [hud, setHud] = useState({ tp: 0, st: { done: 0, retries: 0, blocked: 0 } as Stats, t: T.current });
  const [read, setRead] = useState(READ_IDLE);
  const [summary, setSummary] = useState("");
  const latest = useRef(hud);
  latest.current = hud;

  const readRow = useCallback(() => {
    const i = hov.current, t = T.current;
    if (i < 0) return setRead(READ_IDLE);
    const k = stageAt(run, i, t), p = progress(run, i, k, t), b = run.blockedAt[i] === k && p >= HOLD;
    const pct = Math.round((p * 100) / (b ? HOLD : 1));
    setRead(`#${String(i + 1).padStart(4, "0")} ${companyName(i)} · ${STAGES[k]} ${pct}% · retries ${run.retries[i * NS + k]}${b ? " · ● waiting on a person" : t < run.start[i * NS] ? " · queued" : ""}`);
  }, [run]);

  useEffect(() => {
    const root = rootRef.current, cv = cvRef.current;
    const ctx = cv?.getContext("2d");
    if (!root || !cv || !ctx) return;
    let W = 0, H = 0, K = 1, pal = readPalette(root, ctx), raf = 0, prev = 0;
    const lane = (k: number): [number, number] => { const w = (W - GUT - 8) / NS; return [GUT + k * w, w]; };

    const draw = (t: number) => {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = pal.bg; ctx.fillRect(0, 0, W, H);
      const rows = Math.max(1, H - TOP - 4), blk: number[] = [];
      const pulse = reduced.current ? 1 : 0.65 + 0.35 * Math.sin(performance.now() / 260);
      for (let r = 0; r < rows; r++) {
        const a = Math.floor(r * K), b = Math.min(N, Math.floor((r + 1) * K)), y = TOP + r;
        for (let k = 0; k < NS; k++) {
          let sum = 0, bl = false, re = 0;
          for (let i = a; i < b; i++) {
            const p = progress(run, i, k, t); sum += p;
            if (run.blockedAt[i] === k && p >= HOLD) bl = true;
            re = Math.max(re, t > run.start[i * NS + k] ? run.retries[i * NS + k] : 0);
          }
          const p = sum / Math.max(1, b - a), [lx, w] = lane(k), fw = w * p;
          if (bl) { blk.push(lx, y, fw || w * HOLD); continue; }
          if (p > 0) { ctx.fillStyle = mix(pal.from, pal.to, p > 0.995 ? 1 : p); ctx.fillRect(lx, y, fw, 1); }
          if (re && p > 0 && p < 1) {
            ctx.fillStyle = pal.ink; ctx.fillRect(Math.min(lx + w - 2, lx + fw + re * 3), y, 2, 1);
            ctx.fillStyle = pal.bg; ctx.fillRect(lx + fw + 1, y, re * 3 - 1, 1);
          } else if (re && p >= 1 && (r * 7 + k) % 3 === 0) {
            ctx.fillStyle = pal.muted; ctx.fillRect(lx + w * 0.72 + re * 2, y, 2, 1);
          }
        }
      }
      ctx.save(); ctx.shadowColor = pal.hi; ctx.shadowBlur = 10; ctx.fillStyle = pal.hi; ctx.globalAlpha = pulse;
      for (let j = 0; j < blk.length; j += 3) ctx.fillRect(blk[j], blk[j + 1], blk[j + 2], 1);
      ctx.restore();
      ctx.fillStyle = pal.hi;
      for (let j = 0; j < blk.length; j += 3) ctx.fillRect(blk[j], blk[j + 1], Math.min(blk[j + 2], 3), 1);
      ctx.strokeStyle = pal.grid; ctx.fillStyle = pal.muted; ctx.font = `500 ${W < 500 ? 8.5 : 11}px "Geist Mono", "JetBrains Mono", monospace`; ctx.lineWidth = 1;
      for (let k = 0; k <= NS; k++) {
        const [lx, w] = lane(Math.min(k, NS - 1)), x = (k === NS ? lx + w : lx) + 0.5;
        if (k < NS) ctx.fillText(STAGES[k].toUpperCase(), lx + 4, 16);
        ctx.beginPath(); ctx.moveTo(x, TOP - 4); ctx.lineTo(x, H); ctx.stroke();
      }
      for (let y = 0; y <= N; y += 1000) ctx.fillText(y ? `${y / 1000}k` : "0", 4, Math.min(TOP + y / K + 10, H - 3));
      ctx.strokeStyle = pal.ink; ctx.setLineDash([2, 3]);
      for (const [k, f] of CHECKPOINTS) {
        const [lx, w] = lane(k), cx = Math.round(lx + w * f) + 0.5;
        ctx.beginPath(); ctx.moveTo(cx, TOP - 4); ctx.lineTo(cx, H); ctx.stroke();
      }
      ctx.setLineDash([]);
      if (hov.current >= 0) {
        ctx.save(); ctx.globalAlpha = 0.4; ctx.fillStyle = pal.ink;
        ctx.fillRect(GUT, TOP + hov.current / K - 0.5, W - GUT, 2); ctx.restore();
      }
    };

    const tick = (t: number) => {
      draw(t);
      const st = stats(run, t);
      setHud({ st, tp: throughput(run, t, st.done), t });
    };
    redraw.current = () => draw(T.current);

    const size = () => {
      const b = cv.parentElement!.getBoundingClientRect(), d = devicePixelRatio || 1;
      W = b.width; H = b.height; cv.width = Math.round(W * d); cv.height = Math.round(H * d);
      ctx.setTransform(d, 0, 0, d, 0, 0); K = N / Math.max(1, H - TOP - 4);
      draw(T.current);
    };

    const frame = (n: number) => {
      raf = 0;
      if (!playingRef.current) return;
      T.current = Math.min(END, T.current + (n - (prev || n)) / SPEED);
      prev = n; tick(T.current); readRow();
      if (T.current >= END) { playingRef.current = false; setPlaying(false); setFinished(true); return; }
      raf = requestAnimationFrame(frame);
    };
    const kick = () => { prev = 0; if (!raf && playingRef.current) raf = requestAnimationFrame(frame); };
    kickRef.current = kick;

    const ro = new ResizeObserver(size); ro.observe(cv.parentElement!);
    const recolour = () => { pal = readPalette(root, ctx); draw(T.current); };
    const mo = new MutationObserver(recolour);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    const mq = matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", recolour);
    size(); tick(T.current); kick();

    return () => { cancelAnimationFrame(raf); ro.disconnect(); mo.disconnect(); mq.removeEventListener("change", recolour); redraw.current = () => {}; kickRef.current = () => {}; };
  }, [run, readRow]);
  const kickRef = useRef<() => void>(() => {});

  // Screen-reader summary: polite, refreshed at most every 2 s.
  useEffect(() => {
    const say = () => {
      const { st, t } = latest.current;
      const s = t >= END ? `Run finished: ${st.done} done, ${st.blocked} blocked on a person.` : `${st.done} of ${N} companies done, ${st.blocked} blocked on a person.`;
      setSummary((p) => (p === s ? p : s));
    };
    say();
    const id = setInterval(say, 2000);
    return () => clearInterval(id);
  }, []);

  const toggle = () => {
    if (finished) { T.current = 0; setFinished(false); }
    playingRef.current = !playingRef.current || finished;
    setPlaying(playingRef.current);
    kickRef.current();
  };

  const point = (e: PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect(), y = e.clientY - r.top - TOP, rows = r.height - TOP - 4;
    hov.current = y < 0 || y > rows ? -1 : Math.min(N - 1, Math.floor((y * N) / rows));
    readRow(); if (!playingRef.current) redraw.current();
  };
  const leave = () => { hov.current = -1; readRow(); if (!playingRef.current) redraw.current(); };

  const { st, tp, t } = hud;
  const etaText = eta(t, N - st.done - st.blocked, st.blocked, tp);
  const parts = read.split(" · ● ");

  return (
    <div className="lab-heat" ref={rootRef}>
      <p className="rh-note">Sample data</p>
      <div className="rh-head">
        <p className="rh-sub">Run 0417 · backpressure heat<br />4,000 companies · 1 row ≈ 1 company · 6 stages</p>
        <dl className="rh-m" aria-hidden="true">
          <div><dd>{t >= END ? 0 : Math.round(tp)}</dd><dt>cos / min</dt></div>
          <div><dd>{etaText}</dd><dt>ETA</dt></div>
          <div><dd>{st.done.toLocaleString()}</dd><dt>done</dt></div>
          <div><dd>{st.retries.toLocaleString()}</dd><dt>retries</dt></div>
          <div className="rh-h"><dd>{st.blocked}</dd><dt>need a human</dt></div>
        </dl>
      </div>
      <div className="rh-bar">
        <button type="button" className="rh-btn" onClick={toggle}>{finished ? "Replay" : playing ? "Pause" : "Play"}</button>
        <span className="rh-sr" role="status" aria-live="polite">{summary}</span>
      </div>
      <div className="rh-cv">
        <canvas ref={cvRef} role="img" aria-label="Heat map of 4,000 companies across six stages. See the text summary for counts."
          onPointerDown={point} onPointerMove={point} onPointerLeave={leave} onPointerCancel={leave} />
      </div>
      <div className="rh-foot">
        <div className="rh-read">{parts[0]}{parts[1] !== undefined && <> · <i>● {parts[1]}</i></>}</div>
        <ul className="rh-key">
          <li><s style={{ background: "var(--panel-border)" }} />running</li>
          <li><s style={{ background: "var(--text)" }} />done</li>
          <li><s style={{ background: "var(--hi)" }} />blocked on a person</li>
          <li>┆ resume checkpoint</li>
          <li>kink = retry</li>
        </ul>
      </div>
    </div>
  );
}
