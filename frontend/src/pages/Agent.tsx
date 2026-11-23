import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { AgentBoard } from "../components/AgentBoard";
import { AskCard } from "../components/AskCards";
import { ExplorationCard } from "../components/ExplorationCard";
import { MiniAppFrame } from "../components/MiniAppFrame";
import { RefinePicker, RefineStage, RefineStream, useRefine, useRefineThreads } from "../components/RefineThread";
import { StepTabs } from "../components/StepTabs";
import {
  answerActions, budgetLine, chipLabel, COMPOSER_COPY, composerModes, composerRequest, draftPlanFromAsk, exploreFromAsk, focusAfterFromAsk, INBOX_KIND, lineDiff,
  askingIn, nearEnd, needsYouLine, REFINE_COPY, REFINE_PLACEHOLDER, refineControls, refineDoc, scriptLines, streamResized, wasNearEnd, sendsComposer, stepState, threadRows, threadTitle, untilCancelled, usd, type Asking, type Mode, type Selection, type ThreadRow,
} from "../lib/agent";
import { ACTIVE, canReplan, resultHref, reviewHref, stepRows, type Plan } from "../lib/plans";
import { when } from "../lib/runs";
import type { AgentAsk, AskThread, Exploration, InboxRow } from "../types";

const POLL_MS = 3000;
const NARROW = "(max-width: 899.98px)";

type Drawer = "threads" | "stage" | null;
type StageTab = "board" | "script" | "diff" | "audit" | "miniapp";
const STAGE_TABS: { id: StageTab; label: string }[] = [
  { id: "board", label: "Board" }, { id: "script", label: "Script" }, { id: "diff", label: "Diff" }, { id: "audit", label: "Audit" },
  { id: "miniapp", label: "Mini-app" },
];

const Chip = ({ status }: { status: string }) => <span className={`status-pill status-${status}`}>{chipLabel(status)}</span>;

/** A side column opened as a drawer: a native modal <dialog>, so showModal() supplies the focus trap, the inert
 * background, Escape and the focus return to the header button, as in components/Modal.tsx. A backdrop click closes it. */
function DrawerDialog({ side, label, onClose, children }: { side: "left" | "right"; label: string; onClose: () => void; children: (close: () => void) => ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = () => ref.current?.close();
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog ref={ref} id="agent-drawer" className={`agent-drawer agent-drawer-${side}`} aria-label={label} onClose={onClose}
      onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="agent-drawer-body">{children(close)}</div>
    </dialog>
  );
}

/** The Agent screen: threads on the left, the selected plan's or ask thread's stream in the middle, its stage on the
 * right. Below 900 px the side columns are drawers opened from the header. */
export function Agent({ selected, onSelect, canAsk, focusToken, pendingAsk, onPendingAskTaken }: {
  selected: Selection;
  onSelect: (s: Selection) => void;
  canAsk: boolean;
  /** Changes on every Ctrl/⌘J: the composer takes focus in `Ask` mode. */
  focusToken: number;
  /** A question typed in the search-or-ask box, sent once as a new ask thread. */
  pendingAsk: { id: number; question: string } | null;
  onPendingAskTaken: () => void;
}) {
  const planId = selected?.kind === "plan" ? selected.id : null;
  const askId = selected?.kind === "ask" ? selected.id : null;
  const explorationId = selected?.kind === "exploration" ? selected.id : null;
  const [plans, setPlans] = useState<Plan[]>([]);
  const [explorations, setExplorations] = useState<Exploration[]>([]);
  const [exploration, setExploration] = useState<Exploration | null>(null);
  const [askThreads, setAskThreads] = useState<AskThread[]>([]);
  const [inbox, setInbox] = useState<InboxRow[]>([]);
  const [waiting, setWaiting] = useState<number | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [asks, setAsks] = useState<AgentAsk[]>([]);
  const [asking, setAsking] = useState<Asking>(null); // the ask in flight and the thread it was sent in
  const [mode, setMode] = useState<Mode>(() => composerModes(canAsk).initial);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [tab, setTab] = useState<StageTab>("board");
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true); // the reader was near the stream's end at the last scroll
  const follow = useRef(true); // the stream follows new content down; the Refine picker is a list, not a chat
  const [jump, setJump] = useState(false);
  const refocus = useRef(false);
  const miniappFocus = useRef<"tab" | "button" | null>(null); // where focus goes once Show as mini-app has answered
  // The drawer Show as mini-app opened: focus was on <body> then (the button was disabled), so the dialog would give
  // it back there on close. It goes back to the button instead.
  const drawerReturn = useRef(false);
  useEffect(() => {
    if (drawer !== null || !drawerReturn.current) return;
    drawerReturn.current = false;
    if (document.activeElement === document.body) document.getElementById("agent-show-miniapp")?.focus();
  }, [drawer]);
  const current = useRef(selected); // the selection now, for a request that answers after it changed
  current.current = selected;
  const modes = composerModes(canAsk);
  // A Refine thread (spec refine-chat-design): its own stream, composer copy and stage; `#/agent/refine` is the picker.
  const refineSel = selected?.kind === "refine" ? selected.id : null;
  const refine = useRefine(refineSel ? refineDoc(refineSel) : null);
  const refineThreads = useRefineThreads();
  const refineCtl = refineControls(canAsk);
  const copy = refine.doc ? REFINE_COPY : COMPOSER_COPY[mode];
  const sending = refine.doc ? refine.busy : busy;
  const closed = sending || (refine.doc !== null && refine.turns === null); // a Refine thread's history must load first

  const loadInbox = useCallback(() => {
    api.getAgentInbox().then(setInbox).catch((e: Error) => setError(`The inbox could not be loaded: ${e.message}.`));
    api.getWaiting().then((w) => setWaiting(w.total)).catch(() => setWaiting(null)); // no count rather than a wrong one
  }, []);
  const loadList = useCallback(() => {
    api.listPlans().then(setPlans).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
    api.listAskThreads().then(setAskThreads).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
    api.listExplorations().then(setExplorations).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
    loadInbox();
  }, [loadInbox]);
  const loadPlan = useCallback(() => {
    if (!planId) return setPlan(null);
    api.getPlan(planId).then(setPlan).catch((e: Error) => setError(`The plan could not be loaded: ${e.message}.`));
  }, [planId]);
  const loadExploration = useCallback(() => {
    if (!explorationId) return setExploration(null);
    api.getExploration(explorationId).then(setExploration).catch((e: Error) => setError(`The exploration could not be loaded: ${e.message}.`));
  }, [explorationId]);
  // A thread's asks; a response that lands after another thread was picked is dropped.
  const loadAsks = useCallback(() => {
    if (!askId) return;
    return untilCancelled(api.getAskThread(askId), setAsks, (e) => setError(`The ask thread could not be loaded: ${e.message}.`));
  }, [askId]);

  useEffect(loadList, [loadList]);
  useEffect(loadPlan, [loadPlan]);
  useEffect(loadExploration, [loadExploration]);
  useEffect(loadAsks, [loadAsks]);
  // A viewer's composer opens in Plan; once the signed-in user is known to be able to ask, it opens in Ask.
  useEffect(() => setMode(composerModes(canAsk).initial), [canAsk]);
  useEffect(() => {
    if (sending || !refocus.current) return;
    refocus.current = false;
    input.current?.focus();
  }, [sending]);
  // After Show as mini-app: the Mini-app tab where the stage shows (the drawer below 900 px), or the button on failure.
  useEffect(() => {
    if (busy || !miniappFocus.current) return;
    const where = miniappFocus.current;
    miniappFocus.current = null;
    const scope = drawer === "stage" ? document.getElementById("agent-drawer") : document.querySelector(".agent-stage");
    (where === "tab" ? scope?.querySelector<HTMLElement>('[data-tab="miniapp"]') : document.getElementById("agent-show-miniapp"))?.focus();
  }, [busy, tab, drawer]);
  // Opening a thread shows its newest turn and its Board; the Refine picker opens at its heading.
  useLayoutEffect(() => {
    setTab("board");
    const picker = refineSel === "";
    atEnd.current = !picker;
    follow.current = !picker;
    setJump(false);
    const el = scroller.current;
    if (el) el.scrollTop = picker ? 0 : el.scrollHeight;
  }, [planId, askId, explorationId, refineSel]);
  // When the stream grows, or its box shrinks under a taller composer, follow it down only if the reader was at the end.
  useEffect(() => {
    const el = scroller.current;
    if (!el || !content.current) return;
    let prev = { height: el.scrollHeight, box: el.clientHeight };
    const ro = new ResizeObserver(() => {
      if (!follow.current) {
        prev = { height: el.scrollHeight, box: el.clientHeight };
        return;
      }
      const before = { scrollHeight: prev.height, clientHeight: prev.box };
      const next = streamResized({ wasNearEnd: wasNearEnd(atEnd.current, el.scrollTop, before), contentGrew: el.scrollHeight > prev.height, boxShrank: el.clientHeight < prev.box, nowNearEnd: nearEnd(el) });
      prev = { height: el.scrollHeight, box: el.clientHeight };
      if (next.scrollToEnd) el.scrollTop = el.scrollHeight;
      if (next.jump !== null) setJump(next.jump);
    });
    ro.observe(content.current);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // The text box grows with its text; CSS caps it at about 8 lines, then it scrolls inside itself.
  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
  }, [text]);
  function onStreamScroll() {
    const el = scroller.current;
    if (!el) return;
    atEnd.current = nearEnd(el);
    if (atEnd.current) setJump(false);
  }
  // Your own send always takes the stream to the latest turn, wherever you had scrolled: the `Working…` turn it adds
  // grows the stream, which then follows it down. (Scrolling here, before that turn lands, would fire a scroll event
  // that reads the grown stream as scrolled up.)
  function followOwnSend() {
    atEnd.current = true;
    setJump(false);
  }
  function jumpToLatest() {
    const el = scroller.current;
    if (!el) return;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    input.current?.focus(); // the button goes once the end is reached; focus waits in the composer, not on <body>
  }
  useEffect(() => {
    if (!focusToken) return;
    if (canAsk) setMode("Ask");
    input.current?.focus();
  }, [focusToken, canAsk]);
  // The thread list shows each plan's chip: reload it when the open plan's status changes.
  const planStatus = plan?.status;
  const shownStatus = useRef(planStatus);
  useEffect(() => {
    if (shownStatus.current && planStatus && planStatus !== shownStatus.current) loadList(); // a change, not the first load
    shownStatus.current = planStatus;
  }, [planStatus, loadList]);
  // While the plan runs or waits for a review, re-read it and the inbox every 3 s (D6).
  const active = plan !== null && ACTIVE.has(plan.status);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => { loadPlan(); loadInbox(); }, POLL_MS);
    return () => clearInterval(t);
  }, [active, loadPlan, loadInbox]);
  // Widening past 900 px shows the columns again, so an open drawer goes.
  useEffect(() => {
    const mq = window.matchMedia(NARROW);
    const onChange = () => {
      setNarrow(mq.matches);
      if (!mq.matches) setDrawer(null);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  async function act(fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await fn();
      loadPlan();
      loadExploration();
      loadList();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** An ask: a follow-up in the selected ask thread, else a new thread, which is selected once it answers. */
  async function ask(question: string, newThread: boolean) {
    followOwnSend();
    const req = composerRequest("Ask", question, newThread ? null : selected);
    if (!req.body.thread_id && selected) onSelect(null); // no thread is selected while a new one's first ask runs
    setAsking({ question, threadId: req.body.thread_id ?? null });
    setBusy(true);
    setError(null);
    try {
      const a = await api.agentPost<AgentAsk>(req.path, req.body);
      if (!req.body.thread_id) {
        setAsks([a]);
        onSelect({ kind: "ask", id: a.thread_id });
      } else if (current.current?.kind === "ask" && current.current.id === a.thread_id) {
        setAsks((xs) => [...xs, a]);
      }
      loadList();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAsking(null);
      setBusy(false);
      refocus.current = true; // the text box is disabled until this render lands
    }
  }

  async function send() {
    const t = text.trim();
    if (closed || !t) return;
    if (refine.doc) {
      followOwnSend();
      const sentFrom = refineSel;
      const ok = await refine.send(t);
      if (current.current?.kind !== "refine" || current.current.id !== sentFrom) return; // another thread is open now
      if (ok) setText("");
      refocus.current = true; // the text box stays disabled while the turn runs
      return;
    }
    if (mode === "Ask") {
      setText("");
      return ask(t, false);
    }
    const req = composerRequest(mode, t, selected); // a new plan opens at its end; a failed one leaves the stream be
    await act(async () => {
      const created = await api.agentPost<Plan | Exploration>(req.path, req.body);
      setText("");
      onSelect({ kind: mode === "Explore" ? "exploration" : "plan", id: created.id });
    });
  }

  const sentPending = useRef<number | null>(null);
  useEffect(() => {
    if (!pendingAsk || sentPending.current === pendingAsk.id) return;
    sentPending.current = pendingAsk.id;
    onPendingAskTaken();
    setMode("Ask");
    void ask(pendingAsk.question, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- send each pending question once, by its id
  }, [pendingAsk]);

  function drafted(askIdOf: string, p: Plan) {
    setAsks((xs) => xs.map((x) => (x.id === askIdOf ? { ...x, plans: [...x.plans, { plan_id: p.id, brief: p.brief, status: p.status }] } : x)));
    loadList();
  }

  function explored(askIdOf: string, e: Exploration) {
    const link = { exploration_id: e.id, question: e.question, status: e.status, label: e.label };
    setAsks((xs) => xs.map((x) => (x.id === askIdOf ? { ...x, explorations: [...x.explorations, link] } : x)));
    loadList();
  }

  const rows = threadRows(plans, askThreads, explorations, refineThreads.threads);
  const isSelected = (r: ThreadRow) => r.kind === selected?.kind && r.id === selected.id;
  // `id` keeps the column's and the drawer's ids apart; `close` is set inside a drawer.
  const threads = (id: string, close?: () => void) => (
    <>
      <div className="agent-side-head">
        <h2 id={`${id}-h`}>Threads</h2>
        {close && <button type="button" className="link-button" onClick={close}>Close</button>}
      </div>
      {refineThreads.error && <p className="error-text">{refineThreads.error}</p>}
      {refineCtl.picker && (
        <button type="button" className="secondary agent-refine-new" aria-current={refineSel === "" ? "true" : undefined}
          onClick={() => { close?.(); onSelect({ kind: "refine", id: "" }); }}>
          Refine a document
        </button>
      )}
      {rows.length === 0 ? (
        <p className="muted">No threads yet. Ask a question or write a brief to start one.</p>
      ) : (
        <ul className="agent-thread-list">
          {rows.map((r) => (
            <li key={`${r.kind}:${r.id}`} className={isSelected(r) ? "selected" : undefined}>
              <button type="button" className="link-button" aria-current={isSelected(r) ? "true" : undefined}
                onClick={() => { close?.(); onSelect({ kind: r.kind, id: r.id }); }}>
                {r.title}
              </button>
              <Chip status={r.status} />
            </li>
          ))}
        </ul>
      )}
      <h2 id={`${id}-inbox-h`} className="agent-inbox-h">Inbox</h2>
      {inbox.length === 0 ? (
        <p className="muted">Nothing here is waiting on you.</p>
      ) : (
        <ul className="agent-inbox" aria-labelledby={`${id}-inbox-h`}>
          {inbox.map((r) => (
            <li key={`${r.kind}:${r.plan_id ?? r.exploration_id}:${r.seq ?? ""}`}>
              <a href={r.href} onClick={close}>{r.title}</a>
              <span className="muted">{INBOX_KIND[r.kind]}</span>
            </li>
          ))}
        </ul>
      )}
      {waiting !== null && <p className="agent-inbox-foot"><a href="#/review" onClick={close}>{needsYouLine(waiting)}</a></p>}
    </>
  );
  const closeButton = (close?: () => void) => close && <button type="button" className="link-button" onClick={close}>Close</button>;
  const stage = (id: string, close?: () => void) => refineSel !== null ? (
    <RefineStage refine={refine} canEdit={refineCtl.undo} idPrefix={id} head={closeButton(close)} />
  ) : (
    <>
      <div className="agent-side-head">
        <StepTabs label="Stage" tabs={STAGE_TABS} active={tab} onSelect={(t) => setTab(t as StageTab)} />
        {close && <button type="button" className="link-button" onClick={close}>Close</button>}
      </div>
      <div id={`${id}-panel`} role="tabpanel" aria-label={STAGE_TABS.find((t) => t.id === tab)!.label}>
        {tab === "miniapp" ? (
          exploration && explorationId && exploration.miniapp_html != null ? (
            <MiniAppFrame key={exploration.id} title={`Mini-app: ${exploration.question}`} html={exploration.miniapp_html} asks={exploration.miniapp_asks ?? []}
              onAsk={(q) => { if (canAsk) setMode("Ask"); setText(q); }} />
          ) : (
            <p className="muted">{exploration && explorationId ? "Show as mini-app, on a done exploration, builds a small page for its result here." : "A done exploration can be shown here as a mini-app."}</p>
          )
        ) : tab === "board" ? (
          plan ? (
            <AgentBoard key={plan.id} planId={plan.id} planStatus={plan.status} idPrefix={id} />
          ) : (
            <p className="muted">{explorationId ? "An exploration has no board yet." : "The selected plan’s board shows here."}</p>
          )
        ) : !plan ? (
          <p className="muted">{explorationId ? "An exploration has no script, changes or audit trail: its code and tool calls are in the stream." : "The selected plan’s script, changes and audit trail show here."}</p>
        ) : tab === "script" ? (
          <pre className="mono agent-script" aria-label="Plan script, read-only">
            {scriptLines(plan.script).map((l) => (
              <span key={l.n} className="agent-script-line"><span className="agent-ln" aria-hidden="true">{l.n}</span><span>{l.text}{"\n"}</span></span>
            ))}
          </pre>
        ) : tab === "diff" ? (
          <DiffTab plan={plan} />
        ) : (
          <AuditTab plan={plan} />
        )}
      </div>
    </>
  );

  const drawerButton = (which: "threads" | "stage", label: string) => (
    <button type="button" className="secondary" aria-haspopup="dialog" aria-expanded={drawer === which}
      aria-controls={drawer === which ? "agent-drawer" : undefined} onClick={() => setDrawer(which)}>
      {label}
    </button>
  );

  return (
    <div className="page agent-page">
      <div className="agent-head">
        <h1>Agent</h1>
        <div className="agent-drawer-buttons">
          {drawerButton("threads", "Threads")}
          {drawerButton("stage", "Stage")}
        </div>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}

      <div className={refineSel !== null ? "agent-shell agent-shell-refine" : "agent-shell"}>
        <aside className="agent-side agent-threads" aria-labelledby="agent-threads-h">{threads("agent-threads")}</aside>

        <section className="agent-stream" aria-label="Stream">
          <div className="agent-scroll" ref={scroller} onScroll={onStreamScroll} tabIndex={0} role="region" aria-label="Conversation">
          <div ref={content}>
          {refineSel !== null ? (
            refine.doc ? <RefineStream refine={refine} emptyLine={refineCtl.emptyLine} /> : <RefinePicker />
          ) : exploration && explorationId ? (
            <ExplorationCard key={exploration.id} exploration={exploration} busy={busy} onAccept={() => act(() => api.acceptExploration(exploration.id))}
              onMiniapp={async () => {
                const made = await act(() => api.createMiniapp(exploration.id));
                miniappFocus.current = made ? "tab" : "button"; // the button was disabled while it ran: focus fell to <body>
                if (!made) return;
                setTab("miniapp");
                if (!window.matchMedia(NARROW).matches) return;
                setDrawer("stage");
                drawerReturn.current = true;
              }} />
          ) : plan && planId ? (
            <Stream key={plan.id} plan={plan} busy={busy} act={act} />
          ) : askId || askingIn(asking, null) ? (
            <AskStream asks={asks.filter((a) => a.thread_id === askId)} asking={askingIn(asking, askId)} canAsk={canAsk} onDrafted={drafted} onExplored={explored} />
          ) : (
            <p className="muted agent-empty">Pick a thread, ask a question, or describe the research you want below. For research, a planner writes a short script that chains ARP’s runs; nothing runs until you approve it.</p>
          )}
          </div>
          </div>
          {jump && (
            <div className="agent-jump">
              <button type="button" className="secondary" onClick={jumpToLatest}>Jump to latest</button>
            </div>
          )}
          {(refineSel === null || (refine.doc && refineCtl.composer)) && (
          <form className="agent-composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
            {!refine.doc && (
            <div className="agent-modes" role="group" aria-label="Mode">
              {modes.modes.map((m) => (
                <button key={m} type="button" className="secondary" aria-pressed={mode === m} onClick={() => setMode(m)}>{m}</button>
              ))}
            </div>
            )}
            <label className="visually-hidden" htmlFor="agent-brief">{copy.label}</label>
            <textarea id="agent-brief" ref={input} rows={2} value={text} disabled={closed} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (sendsComposer({ key: e.key, shiftKey: e.shiftKey, isComposing: e.nativeEvent.isComposing })) {
                  e.preventDefault();
                  send();
                }
              }}
              aria-describedby="agent-brief-help" maxLength={mode === "Ask" && !refine.doc ? 1000 : undefined} placeholder={refine.doc ? REFINE_PLACEHOLDER[refine.doc.kind] : copy.placeholder} />
            <div className="agent-composer-foot">
              <p id="agent-brief-help" className="muted">{copy.help}</p>
              <button type="submit" disabled={closed || !text.trim()}>{sending ? copy.sending : copy.submit}</button>
            </div>
            {refine.doc && refine.error && <p className="error-text" role="alert">{refine.error}</p>}
          </form>
          )}
        </section>

        {/* Below 900 px the stage lives in its drawer only, so the Board polls and draws once. */}
        <aside className={refineSel !== null ? "agent-side agent-stage refine-stage" : "agent-side agent-stage"} aria-label="Stage">{!narrow && stage("agent-stage")}</aside>
      </div>
      {drawer && (
        <DrawerDialog key={drawer} side={drawer === "threads" ? "left" : "right"} label={drawer === "threads" ? "Threads" : "Stage"} onClose={() => setDrawer(null)}>
          {(close) => (drawer === "threads" ? threads("agent-drawer-threads", close) : stage("agent-drawer-stage", close))}
        </DrawerDialog>
      )}
    </div>
  );
}

/** The selected plan, top to bottom: brief, script, planned steps, approval, one card per stored call, failure. */
function Stream({ plan, busy, act }: { plan: Plan; busy: boolean; act: (fn: () => Promise<unknown>) => Promise<boolean> }) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <>
      <article className="card agent-card" aria-labelledby="agent-brief-h">
        <h2 id="agent-brief-h">{plan.brief}</h2>
        <p className="agent-meta">
          <Chip status={plan.status} /> <span className="muted">version {plan.version}</span>
          {plan.approved_by && <span className="muted"> · approved by {plan.approved_by}</span>}
        </p>
        {plan.source_ask && (
          <p className="agent-meta"><a href={`#/agent/ask/${encodeURIComponent(plan.source_ask.thread_id)}`}>From ask: {plan.source_ask.question}</a></p>
        )}
        {(plan.status === "approved" || ACTIVE.has(plan.status)) && (
          <div className="toolbar">
            {plan.status === "approved" && <button disabled={busy} onClick={() => act(() => api.runPlan(plan.id))}>Run</button>}
            {ACTIVE.has(plan.status) && <button className="danger" disabled={busy} onClick={() => act(() => api.cancelPlan(plan.id))}>Cancel</button>}
          </div>
        )}
      </article>

      <article className="card agent-card" aria-labelledby="agent-script-h">
        <h3 id="agent-script-h">Script</h3>
        <pre className="mono plan-script agent-wrap" aria-label="Plan script">{plan.script}</pre>
      </article>

      <article className="card agent-card" aria-labelledby="agent-steps-h">
        <h3 id="agent-steps-h">Planned steps</h3>
        <ol className="agent-steps">
          {plan.dry_run.map((s) => (
            <li key={s.seq}>
              <span className="mono">{s.kind}</span>{" "}
              <code className="agent-params">{JSON.stringify(s.params)}</code>
              {s.depends_on && <span className="muted"> (depends on step {s.depends_on})</span>}
            </li>
          ))}
        </ol>
      </article>

      {plan.status === "draft" && (
        <article className="card agent-card agent-approval" aria-labelledby="agent-approval-h">
          <h3 id="agent-approval-h">Approve this plan?</h3>
          {draft === null ? (
            <>
              <p className="muted">Nothing runs until you approve it. Once approved, Run starts it.</p>
              <div className="toolbar">
                <button disabled={busy} onClick={() => act(() => api.approvePlan(plan.id))}>Approve</button>
                <button className="secondary" disabled={busy} onClick={() => setDraft(plan.script)}>Edit</button>
              </div>
            </>
          ) : (
            <form onSubmit={async (e) => {
              e.preventDefault();
              if (await act(() => api.editPlan(plan.id, draft))) setDraft(null);
            }}>
              <label className="field-label" htmlFor="agent-edit">Script</label>
              <textarea id="agent-edit" className="mono" rows={Math.min(16, draft.split("\n").length + 1)} value={draft} onChange={(e) => setDraft(e.target.value)} />
              <div className="toolbar">
                <button type="submit" disabled={busy}>Save script</button>
                <button type="button" className="secondary" disabled={busy} onClick={() => setDraft(null)}>Discard changes</button>
              </div>
            </form>
          )}
        </article>
      )}

      {(plan.calls ?? []).length > 0 && (
        <ol className="agent-calls" aria-label="Steps run">
          {(plan.calls ?? []).map((c) => {
            const href = c.status === "done" ? resultHref(c) : null;
            const review = c.status === "awaiting_review" ? reviewHref(c) : null;
            return (
              <li key={c.seq} className="card agent-card agent-call">
                <span className="muted">Step {c.seq}</span> <span className="mono">{c.kind}</span> <Chip status={c.status} />
                {href && <> <a href={href}>{c.run_id ?? "Open"}</a></>}
                {review && <> <a href={review}>Review</a></>}
              </li>
            );
          })}
        </ol>
      )}

      {plan.status === "failed" && (
        <article className="card agent-card agent-failure" aria-labelledby="agent-failure-h">
          <h3 id="agent-failure-h">The plan failed</h3>
          {plan.error && <p className="error-text">{plan.error}</p>}
          <div className="toolbar">
            <button disabled={busy} onClick={() => act(() => api.runPlan(plan.id))}>Resume</button>
            {canReplan(plan) && <button className="secondary" disabled={busy} onClick={() => act(() => api.replanPlan(plan.id))}>Re-plan</button>}
          </div>
        </article>
      )}
    </>
  );
}

type FromAsk = { onDrafted: (askId: string, plan: Plan) => void; onExplored: (askId: string, e: Exploration) => void };

/** An ask thread, oldest ask first: each question, then its answer card or error, the buttons for an answer, and a
 * link card per plan or exploration started from it. `asking` is the question in flight, shown with `Working…`. */
function AskStream({ asks, asking, canAsk, onDrafted, onExplored }: FromAsk & {
  asks: AgentAsk[]; asking: string | null; canAsk: boolean;
}) {
  return (
    <ol className="agent-calls" aria-label="Asks">
      {asks.map((a) => <AskTurn key={a.id} ask={a} canAsk={canAsk} onDrafted={onDrafted} onExplored={onExplored} />)}
      {asking !== null && (
        <li className="ask-turn">
          <p className="ask-question">{asking}</p>
          <p className="ask-card muted" role="status">Working…</p>
        </li>
      )}
    </ol>
  );
}

function AskTurn({ ask, canAsk, onDrafted, onExplored }: FromAsk & { ask: AgentAsk; canAsk: boolean }) {
  const [drafting, setDrafting] = useState(false);
  const [exploring, setExploring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A pressed button is disabled while its request runs, so focus drops to <body>: once the request ends, focus moves
  // to the new link card, or back to the button on failure (WCAG 2.4.3). Kept until that element has rendered.
  const [focusNext, setFocusNext] = useState<ReturnType<typeof focusAfterFromAsk> | null>(null);
  const turn = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (!focusNext || !turn.current) return;
    const target = "href" in focusNext
      ? [...turn.current.querySelectorAll<HTMLAnchorElement>(".agent-link-card a")].find((a) => a.getAttribute("href") === focusNext.href)
      : [...turn.current.querySelectorAll<HTMLButtonElement>(".agent-ask-actions button")].find((b) => b.textContent === focusNext.button && !b.disabled);
    if (!target) return;
    target.focus();
    setFocusNext(null);
  }, [focusNext, ask.plans, ask.explorations, drafting, exploring]);
  async function draft() {
    setDrafting(true);
    setError(null);
    const out = await draftPlanFromAsk(ask, (path, body) => api.agentPost<Plan>(path, body));
    setDrafting(false);
    if (out.ok) onDrafted(ask.id, out.plan);
    else setError(out.error);
    setFocusNext(focusAfterFromAsk("plan", out));
  }
  async function explore() {
    setExploring(true);
    setError(null);
    const out = await exploreFromAsk(ask, (path, body) => api.agentPost<Exploration>(path, body));
    setExploring(false);
    if (out.ok) onExplored(ask.id, out.exploration);
    else setError(out.error);
    setFocusNext(focusAfterFromAsk("exploration", out));
  }
  return (
    <li className="ask-turn" ref={turn}>
      <p className="ask-question">{ask.question}</p>
      {ask.error ? <p className="ask-card error-text">{ask.error}</p> : ask.response && <AskCard response={ask.response} />}
      {!ask.error && answerActions(canAsk).length > 0 && (
        <div className="agent-ask-actions">
          <button type="button" className="secondary" disabled={drafting} onClick={draft}>Draft a plan</button>
          <button type="button" className="secondary" disabled={exploring} onClick={explore}>Explore</button>
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
      {ask.plans.map((p) => (
        <p key={p.plan_id} className="agent-link-card">
          <a href={`#/agent/${encodeURIComponent(p.plan_id)}`}>Plan: {threadTitle(p.brief)}</a> <Chip status={p.status} />
        </p>
      ))}
      {ask.explorations.map((x) => (
        <p key={x.exploration_id} className="agent-link-card">
          <a href={`#/agent/exploration/${encodeURIComponent(x.exploration_id)}`}>Exploration: {threadTitle(x.question)}</a>{" "}
          <span className="agent-badge">{x.label}</span>
        </p>
      ))}
    </li>
  );
}

/** The Diff tab: each planned step against the stored calls, then, after a re-plan, the previous script against this one. */
function DiffTab({ plan }: { plan: Plan }) {
  const prev = plan.previous_scripts.at(-1);
  const diff = prev ? lineDiff(prev.script, plan.script) : null;
  return (
    <>
      <h3 className="agent-stage-h">Steps</h3>
      <ol className="agent-diff-steps">
        {stepRows(plan).map(({ step, call }) => {
          const state = stepState(plan.status, call !== null);
          return (
            <li key={step.seq}>
              <span className="muted">Step {step.seq}</span> <span className="mono">{step.kind}</span>{" "}
              <span className={`agent-step-state agent-step-${state}`}>{state}</span>
              {call && <> <Chip status={call.status} /></>}
            </li>
          );
        })}
      </ol>
      {prev && diff ? (
        <>
          <h3 className="agent-stage-h mono" aria-label={`${diff.removed} lines removed, ${diff.added} added`}>-{diff.removed} +{diff.added}</h3>
          <p className="muted agent-diff-caption">Script version {prev.version} against version {plan.version}</p>
          <pre className="mono agent-diff" aria-label={`Script diff, version ${prev.version} to ${plan.version}`}>
            {diff.lines.map((l, k) => (
              <span key={k} className={l.op === "-" ? "agent-diff-del" : l.op === "+" ? "agent-diff-add" : undefined}><span>{l.op}</span><span>{l.text}{"\n"}</span></span>
            ))}
          </pre>
        </>
      ) : (
        <p className="muted">No re-plan yet, so there is no earlier script to compare.</p>
      )}
    </>
  );
}

/** The Audit tab: who approved the plan and when, what it spent, and one row per stored call. */
function AuditTab({ plan }: { plan: Plan }) {
  const calls = plan.calls ?? [];
  return (
    <>
      <p className="agent-audit-line">
        {plan.approved_by ? (
          <>Approved by <strong>{plan.approved_by}</strong>{plan.approved_at && <> on <time dateTime={plan.approved_at}>{when(plan.approved_at)}</time></>}</>
        ) : (
          "Not approved yet."
        )}
      </p>
      {plan.spent_usd !== undefined && <p className="agent-audit-line">{budgetLine(plan.spent_usd, plan.budget_usd)}</p>}
      {calls.length === 0 ? (
        <p className="muted">No step has started yet.</p>
      ) : (
        <ol className="agent-audit" aria-label="Calls">
          {calls.map((c) => (
            <li key={c.seq} className="agent-audit-row">
              <div className="agent-audit-head">
                <span className="muted">Step {c.seq}</span> <span className="mono">{c.kind}</span> <Chip status={c.status} />
              </div>
              <dl className="agent-audit-fields">
                <dt>Run</dt><dd className="mono">{c.run_id ?? "–"}</dd>
                <dt>Started</dt><dd>{c.started_at ? <time dateTime={c.started_at}>{when(c.started_at)}</time> : "–"}</dd>
                <dt>Model</dt><dd className="mono">{c.model ?? "–"}</dd>
                <dt>Cost</dt><dd>{usd(c.estimated_cost_usd)}</dd>
                <dt>Params</dt><dd><code className="agent-params">{JSON.stringify(c.params)}</code></dd>
              </dl>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
