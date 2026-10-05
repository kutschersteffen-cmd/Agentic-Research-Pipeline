import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, UIEvent } from "react";
import "./TapeReader.css";

const N = 4000;
const H = 24;
const ENT = ["Meridian Labs", "Orrin Bio", "Calder Fund", "Halcyon Corp", "Vantage Ltd", "Kestrel AI", "Brightwater", "Northgate"];
const FLD = ["revenue_fy25", "headcount", "hq_city", "ceo_name", "founded", "funding_total", "ticker", "sector", "last_round", "cap_table.lead"];
const OLD = ["14.2M", "1,204", "Rotterdam", "M. Okafor", "2011", "$88M", "MRDN", "Biotech", "Series C", "Sequoia"];
const NEW = ["14.9M", "1,310", "Rotterdam NL", "M. Okafor-Reyes", "2012", "$91.5M", "MRDN.L", "Biotech/AI", "Series D", "Index"];

type Decision = "a" | "r";
interface Ev { t: string; ent: string; f: string; p: string; v: string; o: string; h: string }

// Seeded hash PRNG: same index and salt always give the same value in [0,1).
function rng(seed: number): number {
  const s = Math.imul(seed + 0x6d2b79f5 | 0, 1);
  let t = Math.imul(s ^ s >>> 15, s | 1);
  t ^= t + Math.imul(t ^ t >>> 7, t | 61);
  t = Math.imul(t ^ t >>> 15, 0x9e3779b1);
  t ^= t >>> 13;
  t = Math.imul(t, 0x85ebca6b);
  return ((t ^ t >>> 16) >>> 0) / 4294967296;
}
const hex = (i: number, k: number) => Math.floor(rng(i * 7 + k) * 0xffffff).toString(16).padStart(6, "0");

function makeEvent(i: number): Ev {
  const f = Math.floor(rng(i + 1) * FLD.length);
  const t = new Date(Date.UTC(2026, 9, 5, 18, 0, 0) - i * 37000);
  const p = rng(i + 2) < 0.5 ? OLD[f] : NEW[f];
  const v = rng(i + 3) < 0.8 ? NEW[f] : p;
  return {
    t: t.toISOString().slice(11, 19),
    ent: ENT[Math.floor(rng(i + 4) * ENT.length)],
    f: FLD[f], p, v,
    o: rng(i + 5) < 0.12 ? NEW[f] + " *" : "",
    h: hex(i, 9) + hex(i, 3).slice(0, 2),
  };
}

const LABEL = { a: "APPROVED", r: "REJECTED" } as const;

export function TapeReader() {
  const tapeRef = useRef<HTMLDivElement>(null);
  const scRef = useRef<HTMLDivElement>(null);
  const events = useMemo(() => Array.from({ length: N }, (_, i) => makeEvent(i)), []);
  const overrides = useMemo(() => events.filter((e) => e.o).length, [events]);
  const [sel, setSel] = useState(3);
  const [top, setTop] = useState(0);
  const [vh, setVh] = useState(560);
  // Seeded so the first paint shows state, as in the mock.
  const [dec, setDec] = useState<Map<number, Decision>>(
    () => new Map<number, Decision>([[0, "a"], [1, "a"], [2, "r"], [4, "a"]]),
  );

  useEffect(() => {
    tapeRef.current?.focus({ preventScroll: true });
    const sc = scRef.current;
    if (!sc) return;
    const ro = new ResizeObserver(() => setVh(sc.clientHeight));
    ro.observe(sc);
    return () => ro.disconnect();
  }, []);

  const go = (i: number) => {
    const n = Math.max(0, Math.min(N - 1, i));
    setSel(n);
    const sc = scRef.current;
    if (!sc) return;
    const y = n * H;
    if (y < sc.scrollTop) sc.scrollTop = y;
    else if (y + H > sc.scrollTop + sc.clientHeight) sc.scrollTop = y + H - sc.clientHeight;
  };
  const mark = (d: Decision) => {
    setDec((m) => new Map(m).set(sel, d));
    go(sel + 1);
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const k = e.key;
    if (k === "j" || k === "ArrowDown") { e.preventDefault(); go(sel + 1); }
    else if (k === "k" || k === "ArrowUp") { e.preventDefault(); go(sel - 1); }
    else if (k === "a") mark("a");
    else if (k === "r") mark("r");
  };

  const a = Math.max(0, Math.floor(top / H) - 4);
  const b = Math.min(N, Math.ceil((top + vh) / H) + 4);
  let ap = 0, rj = 0;
  dec.forEach((x) => (x === "a" ? ap++ : rj++));

  const rows = [];
  for (let i = a; i < b; i++) {
    const e = events[i], s = dec.get(i);
    const cls = "row" + (i === sel ? " sel" : "") + (s === "a" ? " ok" : s === "r" ? " no" : "");
    rows.push(
      <div key={i} className={cls} style={{ top: i * H }} onClick={() => setSel(i)} aria-selected={i === sel} role="row">
        <span className="d">{e.t}</span><span>{e.ent}</span><span>{e.f}</span>
        <span className="v">{e.p}</span><span className="v">{e.v}</span>
        <span className={e.o ? "ov" : "d"}>{e.o || "–"}</span>
        <span className="d">{e.h}</span>
        <span className="st">{s ? LABEL[s] : "PENDING"}</span>
      </div>,
    );
  }

  return (
    <div className="lab-tape">
      <p className="note">Sample data. Review queue of per-field audit events.</p>
      <div className="tape" ref={tapeRef} tabIndex={0} onKeyDown={onKey} aria-label="Tape reader. j and k move, a approves, r rejects.">
        <div className="bar">
          <div className="btns">
            <button type="button" onClick={() => mark("a")}>Approve</button>
            <button type="button" onClick={() => mark("r")}>Reject</button>
          </div>
          <span className="keys"><kbd>j</kbd> <kbd>k</kbd> move &nbsp;<kbd>a</kbd> approve &nbsp;<kbd>r</kbd> reject</span>
        </div>
        <div className="row hd" aria-hidden="true"><span>Time</span><span>Entity</span><span>Field</span><span>Proposed</span><span>Verified</span><span>Overridden</span><span>Source #</span><span className="st">Status</span></div>
        <div className="sc" ref={scRef} onScroll={(e: UIEvent<HTMLDivElement>) => setTop(e.currentTarget.scrollTop)}>
          <div className="in" style={{ height: N * H }} role="grid" aria-rowcount={N}>{rows}</div>
        </div>
        <div className="foot" aria-live="polite">
          <span>row <b>{sel + 1}</b>/{N}</span><span>pending <b>{N - ap - rj}</b></span>
          <span>approved <b>{ap}</b></span><span>rejected <b>{rj}</b></span>
          <span><i className="mk" />human overrides <b>{overrides}</b></span>
        </div>
      </div>
    </div>
  );
}
