import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { CMDS, RUNS } from "./consoleData";
import type { Run, Status } from "./consoleData";
import "./PhosphorConsole.css";

type Decision = "approved" | "rejected";
type Act = "approve" | "reject" | "undo";

const RATING_CLASS = { H: "ok", M: "md", L: "lo" } as const;

/** Subsequence match; returns highlighted segments or null. */
function fuzzy(q: string, s: string): ReactNode[] | null {
  let i = 0;
  const out: ReactNode[] = [];
  [...s].forEach((c, n) => {
    if (i < q.length && c.toLowerCase() === q[i].toLowerCase()) {
      out.push(<mark key={n}>{c}</mark>);
      i++;
    } else out.push(c);
  });
  return i === q.length ? out : null;
}

export function PhosphorConsole() {
  const root = useRef<HTMLDivElement>(null);
  const dlg = useRef<HTMLDivElement>(null);
  const [r, setR] = useState(0);
  const [e, setE] = useState(0);
  const [f, setF] = useState(0);
  const [dec, setDec] = useState<Record<string, Decision>>({});
  const [cmd, setCmd] = useState("arp runs list");
  const [msg, setMsg] = useState("ready");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [ps, setPs] = useState(0);

  useEffect(() => root.current?.focus(), []);

  const stOf = (x: Run): Status | Decision => dec[x.id] ?? x.status;
  const run = RUNS[r];
  const s = stOf(run);
  const waiting = RUNS.filter((x) => stOf(x) === "await").length;

  const matches = useMemo(() => {
    const q = query.replace(/\s+/g, "").replace(/^arp/, "");
    return CMDS.flatMap((c) => {
      const h = fuzzy(q, c.replace(/^arp /, ""));
      return h ? [{ c, h }] : [];
    });
  }, [query]);
  const sel = Math.min(ps, Math.max(0, matches.length - 1));

  const say = (c: string, m = "") => { setCmd(c); setMsg(m); };
  const firstAwait = (d: Record<string, Decision>) => RUNS.findIndex((x) => !d[x.id] && x.status === "await");
  const pick = (i: number) => { setR(i); setE(0); say(`arp runs show ${RUNS[i].id}`); };
  const evCmd = (i: number, ri = r) => say(`arp transition-barrier sources --code ${RUNS[ri].evidence[i].code}`);

  function act(k: Act) {
    if (k === "undo") {
      if (!dec[run.id]) return;
      setDec(Object.fromEntries(Object.entries(dec).filter(([id]) => id !== run.id)));
      return say(`arp decision audit ${run.id}`, "undone");
    }
    if (s !== "await") return;
    const next = { ...dec, [run.id]: k === "approve" ? ("approved" as const) : ("rejected" as const) };
    setDec(next);
    // no CLI "reject": the decision is recorded in the audit trail only
    say(k === "approve" ? run.approveCmd : `arp decision audit ${run.id}`, k === "approve" ? "approved" : "rejected");
    const n = firstAwait(next);
    if (n > -1) { setR(n); setE(0); }
  }

  function setOpenPal(o: boolean) {
    setOpen(o);
    if (o) { setQuery(""); setPs(0); }
    else root.current?.focus();
  }

  function runPal(i: number) {
    const m = matches[i];
    if (!m) return;
    setOpenPal(false);
    say(m.c, "ran in palette");
    if (/(runs show|decision ratify|voting review|decision list|voting ballots)/.test(m.c)) {
      const n = firstAwait(dec);
      if (n > -1) { setR(n); setE(0); }
    }
  }

  function onKey(ev: KeyboardEvent<HTMLDivElement>) {
    if (open || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const t = ev.target as HTMLElement;
    if (t.closest("input, textarea, select, [contenteditable]")) return;
    const k = ev.key;
    if (k === ":") { ev.preventDefault(); setOpenPal(true); }
    else if (k === "Tab" && t === root.current) { ev.preventDefault(); setF((f + (ev.shiftKey ? 2 : 1)) % 3); }
    else if (k === "j" || k === "k") {
      const d = k === "j" ? 1 : -1;
      if (f === 1) { const n = Math.max(0, Math.min(run.evidence.length - 1, e + d)); setE(n); evCmd(n); }
      else pick(Math.max(0, Math.min(RUNS.length - 1, r + d)));
    }
    else if (k === "a") act("approve");
    else if (k === "x") act("reject");
    else if (k === "u") act("undo");
  }

  function onPalKey(ev: KeyboardEvent<HTMLDivElement>) {
    ev.stopPropagation();
    const k = ev.key;
    if (k === "Escape") { ev.preventDefault(); setOpenPal(false); }
    else if (k === "Enter" && ev.target instanceof HTMLInputElement) { ev.preventDefault(); runPal(sel); }
    else if (k === "ArrowDown" || (ev.ctrlKey && k === "n")) { ev.preventDefault(); setPs(Math.min(matches.length - 1, sel + 1)); }
    else if (k === "ArrowUp" || (ev.ctrlKey && k === "p")) { ev.preventDefault(); setPs(Math.max(0, sel - 1)); }
    else if (k === "Tab") {
      const els = dlg.current?.querySelectorAll<HTMLElement>("input, button");
      if (!els?.length) return;
      const first = els[0], last = els[els.length - 1];
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
  }

  const minConf = Math.min(...run.evidence.map((x) => x.conf));
  const heading = s === "await" ? "Awaiting your decision" : s === "run" ? "In progress" : s === "rejected" ? "Rejected" : "Settled";

  return (
    <div className="lab-console" ref={root} tabIndex={0} onKeyDown={onKey} role="group"
      aria-label="Phosphor console. Keys: j and k move, Tab switches pane, a approve, x reject, u undo, colon opens commands.">
      <p className="c-note">Sample data</p>
      <div className="c-head">
        <b>ARP://CONSOLE</b><span className="hd">session ratify-2026-10-05</span><span className="c-sp" />
        <span aria-live="polite" style={waiting ? { color: "var(--c-lime)" } : undefined}>{waiting ? `${waiting} await a person` : "queue clear"}</span>
        <button type="button" className="c-cmdbtn" onClick={() => setOpenPal(true)} aria-haspopup="dialog">Commands <kbd>:</kbd></button>
      </div>
      <div className="c-main">
        <section className={`c-pane${f === 0 ? " on" : ""}`} aria-label="Runs">
          <h2><span>RUNS</span><span>j/k</span></h2>
          <div className="c-body">
            {RUNS.map((x, i) => {
              const st = stOf(x), a = st === "await";
              return (
                <button type="button" key={x.id} className={`c-row${a ? " wait" : ""}${i === r ? " sel" : ""}`} aria-current={i === r} onClick={() => { setF(0); pick(i); }}>
                  <span className="dot">{a ? "●" : st === "run" ? "◐" : st === "rejected" ? "✕" : "○"}</span>
                  <span>{x.id} {x.name}</span>
                  <span className={`st ${st === "approved" ? "ok" : st === "rejected" ? "lo" : ""}`}>{a ? "awaits you" : st}</span>
                  <small>{x.scope}</small>
                </button>
              );
            })}
          </div>
        </section>
        <section className={`c-pane${f === 1 ? " on" : ""}`} aria-label="Evidence">
          <h2><span>EVIDENCE</span><span>j/k</span></h2>
          <div className="c-body">
            {run.evidence.map((x, i) => {
              const k = Math.round(x.conf * 5);
              return (
                <button type="button" key={x.code} className={`c-ev${i === e ? " sel" : ""}`} aria-current={i === e} onClick={() => { setF(1); setE(i); evCmd(i); }}>
                  <span className="m">{x.code} · <span className={RATING_CLASS[x.rating]}>{x.rating}</span> · <span className="cf" aria-hidden="true">{"█".repeat(k)}{"░".repeat(5 - k)}</span> {x.conf}</span>
                  <q>{x.text}</q>
                  <span className="m">src: {x.src}</span>
                </button>
              );
            })}
          </div>
        </section>
        <section className={`c-pane${f === 2 ? " on" : ""}`} aria-label="Verdict">
          <h2><span>VERDICT</span><span>a / x / u</span></h2>
          <div className="c-body">
            <div className="v">
              <span className="m">{run.id} · {run.scope}</span>
              <h3>{heading}</h3>
              <p>{run.verdict}</p>
              <dl>
                <dt>evidence</dt><dd>{run.evidence.length} cells</dd>
                <dt>min confidence</dt><dd>{minConf}</dd>
                <dt>signer</dt><dd>{s === "await" ? "unsigned" : s === "approved" ? "you, just now" : "s.kutscher"}</dd>
              </dl>
              <div className="c-act">
                <button type="button" className="a" disabled={s !== "await"} onClick={() => { setF(2); act("approve"); }}>[a] approve</button>
                <button type="button" disabled={s !== "await"} onClick={() => { setF(2); act("reject"); }}>[x] reject</button>
                {dec[run.id] && <button type="button" onClick={() => { setF(2); act("undo"); }}>[u] undo</button>}
              </div>
              <p className="stamp">{s === "await" ? "Nothing ships unsigned." : "Recorded to audit log."}</p>
            </div>
          </div>
        </section>
      </div>
      <div className="c-foot">
        <span className="cmd">{cmd}</span><span>{msg}</span>
        <span className="h">tab pane · a approve · x reject · : commands</span>
      </div>
      {open && (
        <div className="c-pal" onMouseDown={(ev) => { if (ev.target === ev.currentTarget) setOpenPal(false); }}>
          <div ref={dlg} role="dialog" aria-modal="true" aria-label="Command palette" onKeyDown={onPalKey}>
            <input autoFocus value={query} placeholder="arp ..." autoComplete="off" aria-label="Filter commands" role="combobox"
              aria-expanded="true" aria-controls="lab-console-list" aria-activedescendant={matches.length ? `lab-console-o${sel}` : undefined}
              onChange={(ev) => { setQuery(ev.target.value); setPs(0); }} />
            <ul id="lab-console-list" role="listbox" aria-label="Commands">
              {matches.map((m, i) => (
                <li key={m.c} id={`lab-console-o${i}`} role="option" aria-selected={i === sel} onClick={() => runPal(i)}>arp {m.h}</li>
              ))}
              {!matches.length && <li role="option" aria-selected="false">no match</li>}
            </ul>
            <p className="ro"><span>enter: run in pane · esc: close · mirrors the arp CLI</span><button type="button" onClick={() => setOpenPal(false)}>Close</button></p>
          </div>
        </div>
      )}
    </div>
  );
}
