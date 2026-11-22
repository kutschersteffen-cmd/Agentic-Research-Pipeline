import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { AskCard } from "../components/AskCards";
import {
  answerActions, chipLabel, COMPOSER_COPY, composerModes, composerRequest, draftPlanFromAsk, INBOX_KIND, needsYouLine,
  scriptLines, sendsComposer, threadRows, threadTitle, type Mode, type Selection, type ThreadRow,
} from "../lib/agent";
import { ACTIVE, canReplan, resultHref, reviewHref, type Plan } from "../lib/plans";
import type { AgentAsk, AskThread, InboxRow } from "../types";

const POLL_MS = 3000;
const NARROW = "(max-width: 899.98px)";

type Drawer = "threads" | "stage" | null;

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
  const [plans, setPlans] = useState<Plan[]>([]);
  const [askThreads, setAskThreads] = useState<AskThread[]>([]);
  const [inbox, setInbox] = useState<InboxRow[]>([]);
  const [waiting, setWaiting] = useState<number | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [asks, setAsks] = useState<AgentAsk[]>([]);
  const [asking, setAsking] = useState<string | null>(null); // the question of the ask in flight
  const [mode, setMode] = useState<Mode>(() => composerModes(canAsk).initial);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const refocus = useRef(false);
  const current = useRef(selected); // the selection now, for a request that answers after it changed
  current.current = selected;
  const modes = composerModes(canAsk);
  const copy = COMPOSER_COPY[mode];

  const loadList = useCallback(() => {
    api.listPlans().then(setPlans).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
    api.listAskThreads().then(setAskThreads).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
    api.getAgentInbox().then(setInbox).catch((e: Error) => setError(`The inbox could not be loaded: ${e.message}.`));
    api.getWaiting().then((w) => setWaiting(w.total)).catch(() => setWaiting(null)); // no count rather than a wrong one
  }, []);
  const loadPlan = useCallback(() => {
    if (!planId) return setPlan(null);
    api.getPlan(planId).then(setPlan).catch((e: Error) => setError(`The plan could not be loaded: ${e.message}.`));
  }, [planId]);
  const loadAsks = useCallback(() => {
    if (!askId) return;
    api.getAskThread(askId).then(setAsks).catch((e: Error) => setError(`The ask thread could not be loaded: ${e.message}.`));
  }, [askId]);

  useEffect(loadList, [loadList]);
  useEffect(loadPlan, [loadPlan]);
  useEffect(loadAsks, [loadAsks]);
  // A viewer's composer opens in Plan; once the signed-in user is known to be able to ask, it opens in Ask.
  useEffect(() => setMode(composerModes(canAsk).initial), [canAsk]);
  useEffect(() => {
    if (busy || !refocus.current) return;
    refocus.current = false;
    input.current?.focus();
  }, [busy]);
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
  useEffect(() => {
    if (!plan || !ACTIVE.has(plan.status)) return;
    const t = setInterval(loadPlan, POLL_MS);
    return () => clearInterval(t);
  }, [plan, loadPlan]);
  // Widening past 900 px shows the columns again, so an open drawer goes.
  useEffect(() => {
    const mq = window.matchMedia(NARROW);
    const onChange = () => { if (!mq.matches) setDrawer(null); };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  async function act(fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await fn();
      loadPlan();
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
    const req = composerRequest("Ask", question, newThread ? null : selected);
    if (!req.body.thread_id && selected) onSelect(null); // no thread is selected while a new one's first ask runs
    setAsking(question);
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
    if (busy || !t) return;
    if (mode === "Ask") {
      setText("");
      return ask(t, false);
    }
    const req = composerRequest("Plan", t, selected);
    await act(async () => {
      const p = await api.agentPost<Plan>(req.path, req.body);
      setText("");
      onSelect({ kind: "plan", id: p.id });
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

  const rows = threadRows(plans, askThreads);
  const isSelected = (r: ThreadRow) => r.kind === selected?.kind && r.id === selected.id;
  // `id` keeps the column's and the drawer's ids apart; `close` is set inside a drawer.
  const threads = (id: string, close?: () => void) => (
    <>
      <div className="agent-side-head">
        <h2 id={`${id}-h`}>Threads</h2>
        {close && <button type="button" className="link-button" onClick={close}>Close</button>}
      </div>
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
  const stage = (id: string, close?: () => void) => (
    <>
      <div className="agent-side-head">
        <div className="sub-nav" role="tablist" aria-label="Stage">
          <button type="button" id={`${id}-tab-script`} className="nav-tab active" role="tab" aria-selected="true" aria-controls={`${id}-panel-script`}>Script</button>
        </div>
        {close && <button type="button" className="link-button" onClick={close}>Close</button>}
      </div>
      <div id={`${id}-panel-script`} role="tabpanel" aria-labelledby={`${id}-tab-script`}>
        {plan ? (
          <pre className="mono agent-script" aria-label="Plan script, read-only">
            {scriptLines(plan.script).map((l) => (
              <span key={l.n} className="agent-script-line"><span className="agent-ln" aria-hidden="true">{l.n}</span><span>{l.text}{"\n"}</span></span>
            ))}
          </pre>
        ) : (
          <p className="muted">The selected plan’s script shows here.</p>
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

      <div className="agent-shell">
        <aside className="agent-side agent-threads" aria-labelledby="agent-threads-h">{threads("agent-threads")}</aside>

        <section className="agent-stream" aria-label="Stream">
          {plan && planId ? (
            <Stream key={plan.id} plan={plan} busy={busy} act={act} />
          ) : askId || asking ? (
            <AskStream asks={asks.filter((a) => a.thread_id === askId)} asking={asking} canAsk={canAsk} onDrafted={drafted} />
          ) : (
            <p className="muted agent-empty">Pick a thread, ask a question, or describe the research you want below. For research, a planner writes a short script that chains ARP’s runs; nothing runs until you approve it.</p>
          )}
          <form className="agent-composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <div className="agent-modes" role="group" aria-label="Mode">
              {modes.modes.map((m) => (
                <button key={m} type="button" className="secondary" aria-pressed={mode === m} onClick={() => setMode(m)}>{m}</button>
              ))}
            </div>
            <label className="visually-hidden" htmlFor="agent-brief">{copy.label}</label>
            <textarea id="agent-brief" ref={input} rows={2} value={text} disabled={busy} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (sendsComposer({ key: e.key, shiftKey: e.shiftKey, isComposing: e.nativeEvent.isComposing })) {
                  e.preventDefault();
                  send();
                }
              }}
              aria-describedby="agent-brief-help" maxLength={mode === "Ask" ? 1000 : undefined} placeholder={copy.placeholder} />
            <div className="agent-composer-foot">
              <p id="agent-brief-help" className="muted">{copy.help}</p>
              <button type="submit" disabled={busy || !text.trim()}>{busy ? copy.sending : copy.submit}</button>
            </div>
          </form>
        </section>

        <aside className="agent-side agent-stage" aria-label="Stage">{stage("agent-stage")}</aside>
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

/** An ask thread, oldest ask first: each question, then its answer card or error, the buttons for an answer, and a
 * link card per plan drafted from it. `asking` is the question in flight, shown with `Working…`. */
function AskStream({ asks, asking, canAsk, onDrafted }: {
  asks: AgentAsk[]; asking: string | null; canAsk: boolean; onDrafted: (askId: string, plan: Plan) => void;
}) {
  return (
    <ol className="agent-calls" aria-label="Asks">
      {asks.map((a) => <AskTurn key={a.id} ask={a} canAsk={canAsk} onDrafted={onDrafted} />)}
      {asking !== null && (
        <li className="ask-turn">
          <p className="ask-question">{asking}</p>
          <p className="ask-card muted" role="status">Working…</p>
        </li>
      )}
    </ol>
  );
}

function AskTurn({ ask, canAsk, onDrafted }: { ask: AgentAsk; canAsk: boolean; onDrafted: (askId: string, plan: Plan) => void }) {
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function draft() {
    setDrafting(true);
    setError(null);
    const out = await draftPlanFromAsk(ask, (path, body) => api.agentPost<Plan>(path, body));
    setDrafting(false);
    if (out.ok) onDrafted(ask.id, out.plan);
    else setError(out.error);
  }
  return (
    <li className="ask-turn">
      <p className="ask-question">{ask.question}</p>
      {ask.error ? <p className="ask-card error-text">{ask.error}</p> : ask.response && <AskCard response={ask.response} />}
      {!ask.error && answerActions(canAsk).length > 0 && (
        <div className="agent-ask-actions">
          <button type="button" className="secondary" disabled={drafting} onClick={draft}>Draft a plan</button>
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
      {ask.plans.map((p) => (
        <p key={p.plan_id} className="agent-link-card">
          <a href={`#/agent/${encodeURIComponent(p.plan_id)}`}>Plan: {threadTitle(p.brief)}</a> <Chip status={p.status} />
        </p>
      ))}
    </li>
  );
}
