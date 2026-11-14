import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { FileLink } from "../components/FileLink";
import { announce } from "../lib/announce";
import { usePoll } from "../lib/poll";
import { overflowing, pollMs, progressLine, resultLines, trimHistory, type RefineKind } from "../lib/refine";
import { useChartWidth } from "../lib/useChartWidth";
import type { RefineTurn, ReportManifest, RfpProject, RfpProjectSummary } from "../types";
import { STATUS_BADGE } from "./RfpAnswers";

interface Props {
  rfp: number | null;
  report: string | null;
}

/** One chat exchange: what the owner typed and the turn it started (null until the first poll). */
interface Entry {
  message: string;
  turnId: number;
  turn: RefineTurn | null;
}

/** Refine: edit an RFP's answers or a deck's slides by chatting, with the document live on the right. */
export function Refine({ rfp, report }: Props) {
  const [projects, setProjects] = useState<RfpProjectSummary[]>([]);
  const [decks, setDecks] = useState<ReportManifest[]>([]);
  useEffect(() => {
    api.listRfpProjects().then(setProjects, () => {});
    api.listReports().then((r) => setDecks(r.reports.filter((m) => m.has_deck)), () => {});
  }, []);
  const value = rfp !== null ? `rfp=${rfp}` : report !== null ? `report=${encodeURIComponent(report)}` : "";

  return (
    <div className="page">
      <h1>Refine</h1>
      <p className="help-text">Change an RFP's answers or a deck's slides by typing what you want; the document updates on the right as the agent works.</p>
      <label className="field-label">
        Document
        <select id="refine-doc" value={value} onChange={(e) => (window.location.hash = `/refine?${e.target.value}`)}>
          <option value="" disabled>Pick an RFP or a deck…</option>
          <optgroup label="RFPs">
            {projects.map((p) => <option key={p.id} value={`rfp=${p.id}`}>RFP: {p.investor}</option>)}
          </optgroup>
          <optgroup label="Decks">
            {decks.map((m) => <option key={m.report_id} value={`report=${encodeURIComponent(m.report_id)}`}>Deck: {m.title || m.report_id}</option>)}
          </optgroup>
        </select>
      </label>
      {rfp !== null && <Workspace key={`rfp/${rfp}`} kind="rfp" docId={String(rfp)} />}
      {report !== null && <Workspace key={`deck/${report}`} kind="deck" docId={report} />}
    </div>
  );
}

function Workspace({ kind, docId }: { kind: RefineKind; docId: string }) {
  const [chat, setChat] = useState<Entry[]>([]);
  const [project, setProject] = useState<RfpProject | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ReportManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const latest = chat.at(-1);
  const running = !!latest && (latest.turn === null || latest.turn.status === "running");
  // The newest turn's items carry `changed` until the next turn starts (or it is undone).
  const changed = latest?.turn && latest.turn.status !== "undone" ? latest.turn.changed : [];

  async function loadDoc() {
    if (kind === "rfp") setProject(await api.getRfpProject(Number(docId)));
    else {
      const [h, m] = await Promise.all([api.getDeckHtml(docId), api.getReport(docId)]);
      setHtml(h);
      setManifest(m);
    }
  }

  usePoll(async () => {
    try {
      // The turn first, then the document, so a finished reply never shows before its edits.
      if (running && latest) {
        const turn = await api.getRefineTurn(latest.turnId);
        setChat((c) => c.map((e) => (e.turnId === turn.id ? { ...e, turn } : e)));
        if (turn.status !== "running") announce(turn.reply || turn.error || "The change finished.");
      }
      await loadDoc();
    } catch (e) {
      setError((e as Error).message);
    }
  }, pollMs(running));

  async function send(ev: React.FormEvent) {
    ev.preventDefault();
    const text = message.trim();
    if (!text) return;
    setError(null);
    setBusy(true);
    try {
      const history = trimHistory(chat.filter((e) => e.turn && e.turn.status !== "running").map((e) => ({ message: e.message, reply: e.turn!.reply })));
      const { turn_id } = await api.postRefineTurn(kind, docId, text, history);
      setChat((c) => [...c, { message: text, turnId: turn_id, turn: null }]);
      setMessage("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    setError(null);
    setBusy(true);
    try {
      const turn = await api.undoRefine(kind, docId);
      setChat((c) => c.map((e) => (e.turnId === turn.id ? { ...e, turn } : e)));
      announce("Last turn undone.");
      await loadDoc();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function exportDeck() {
    setError(null);
    setBusy(true);
    try {
      setManifest(await api.renderReport(docId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const progress = latest?.turn ? progressLine(latest.turn) : null;
  return (
    <>
      <div className="toolbar">
        <button className="secondary" disabled={busy || running} onClick={() => void undo()}>Undo last turn</button>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="refine-grid">
        <section className="card refine-chat" aria-label="Chat">
          <h2>Chat</h2>
          {chat.length === 0 && <p className="muted">Say what to change, e.g. “make all ESG answers shorter”.</p>}
          {chat.map((e) => (
            <div key={e.turnId} className="refine-entry">
              <p><strong>You:</strong> {e.message}</p>
              {e.turn && e.turn.status !== "running" && (
                <>
                  <p><strong>Agent:</strong> {e.turn.status === "failed" ? `The change failed: ${e.turn.error}` : e.turn.reply}{e.turn.status === "undone" && <span className="chip">undone</span>}</p>
                  {resultLines(e.turn, kind).map((line) => <p key={line} className="muted">{line}</p>)}
                </>
              )}
            </div>
          ))}
          <form onSubmit={(ev) => void send(ev)}>
            <label className="field-label">
              Instruction
              <textarea id="refine-message" rows={3} value={message} placeholder="Type an instruction…" onChange={(e) => setMessage(e.target.value)} />
            </label>
            <button disabled={busy || running || !message.trim()}>Send</button>
          </form>
        </section>
        <section className="card refine-view" aria-label="Live view">
          <div className="toolbar">
            <h2>Live view</h2>
            {running && <p className="muted" role="status">Working… {progress}</p>}
          </div>
          {kind === "rfp" ? <RfpView project={project} changed={changed} /> : (
            <>
              {manifest?.deck_edited_since_render && (
                <div className="toolbar">
                  <p className="muted">Preview changed since last export</p>
                  <button disabled={busy || running} onClick={() => void exportDeck()}>{busy ? "Exporting…" : "Export .pptx"}</button>
                </div>
              )}
              {manifest && !manifest.deck_edited_since_render && manifest.output_files.includes("output.pptx") && (
                <FileLink className="button-link" url={api.reportDownloadUrl(docId, "output.pptx")} name="output.pptx">Download .pptx</FileLink>
              )}
              <DeckView html={html} changed={changed} />
            </>
          )}
        </section>
      </div>
    </>
  );
}

function RfpView({ project, changed }: { project: RfpProject | null; changed: number[] }) {
  if (!project) return <p className="muted">Loading…</p>;
  if (project.questions.length === 0) return <p className="muted">No questions found yet.</p>;
  return (
    <>
      {project.questions.map((q) => (
        <article key={q.id} className="refine-item" aria-label={`Q${q.id}`}>
          <h3>Q{q.id} {q.question}</h3>
          <div className="chip-row">
            <span className={STATUS_BADGE[q.status] ?? "badge"}>{q.status}</span>
            {q.flags.map((f) => <span key={f} className="chip chip-warn">{f}</span>)}
            {changed.includes(q.id) && <span className="chip chip-changed">changed</span>}
          </div>
          <p>{q.answer || <span className="muted">No answer yet.</span>}</p>
          {q.sources.length > 0 && (
            <ul>
              {q.sources.map((s, i) => (
                <li key={i}><strong>{s.entry_question}</strong> “{s.quote}” <span className="muted">— {s.file ? `${s.file}, ${s.location}` : s.source}</span></li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </>
  );
}

function DeckView({ html, changed }: { html: string | null; changed: number[] }) {
  const [selected, setSelected] = useState(1);
  const count = useMemo(() => (html ? new DOMParser().parseFromString(html, "text/html").querySelectorAll("section[data-slide]").length : 0), [html]);
  const [wrapRef, width] = useChartWidth(1200, 240);
  if (html === null) return <p className="muted">Loading…</p>;
  const slide = Math.min(selected, count);
  return (
    <>
      <div className="refine-thumbs" role="list" aria-label="Slides">
        {Array.from({ length: count }, (_, i) => i + 1).map((n) => (
          <button key={n} role="listitem" className={n === slide ? "refine-thumb active" : "refine-thumb"} aria-current={n === slide ? "true" : undefined} onClick={() => setSelected(n)}>
            <SlideFrame html={html} slide={n} width={144} title={`Slide ${n} thumbnail`} />
            <span className="refine-thumb-label">
              Slide {n} {changed.includes(n) && <span className="chip chip-changed">changed</span>}
            </span>
          </button>
        ))}
      </div>
      <div ref={wrapRef} className="refine-slide">
        {count > 0 && <SlideFrame html={html} slide={slide} width={width} title={`Slide ${slide}`} />}
      </div>
    </>
  );
}

// shortcut: the house canvas is 1920x1080 (reporting/style/tokens.json); read it from the HTML if decks get other sizes.
const CANVAS = { w: 1920, h: 1080 };
const MARK_CSS =
  ".arp-overflow{outline:6px solid #c8323f!important;outline-offset:-6px}" +
  ".arp-overflow-label{position:absolute;top:0;right:0;z-index:9;background:#c8323f;color:#fff;font:600 32px/1.3 system-ui,sans-serif;padding:4px 12px}";

/** One slide of the deck HTML, scaled to `width`, in a sandboxed iframe (no scripts; same origin so the
 * page can mark slots whose text does not fit). */
function SlideFrame({ html, slide, width, title }: { html: string; slide: number; width: number; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  // data-slide is the 0-based index; `slide` is the 1-based position.
  const srcDoc = html.replace("</head>", `<style>section.slide:not([data-slide="${slide - 1}"]){display:none}${MARK_CSS}</style></head>`);
  const scale = width / CANVAS.w;
  function mark() {
    const doc = ref.current?.contentDocument;
    if (!doc) return;
    void doc.fonts.ready.then(() => {
      const over = [...doc.querySelectorAll<HTMLElement>("[data-slot]")].filter(overflowing);
      for (const el of over) {
        el.classList.add("arp-overflow");
        const label = doc.createElement("span");
        label.className = "arp-overflow-label";
        label.textContent = "Text doesn't fit";
        el.append(label);
      }
    });
  }
  return (
    <div className="refine-frame" style={{ width, height: CANVAS.h * scale }}>
      <iframe ref={ref} title={title} sandbox="allow-same-origin" srcDoc={srcDoc} onLoad={mark} tabIndex={-1}
        style={{ width: CANVAS.w, height: CANVAS.h, transform: `scale(${scale})` }} />
    </div>
  );
}
