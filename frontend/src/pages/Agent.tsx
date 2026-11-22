import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { chipLabel, scriptLines, sendsComposer, threadTitle } from "../lib/agent";
import { ACTIVE, canReplan, resultHref, reviewHref, type Plan } from "../lib/plans";

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

/** The Agent screen: threads on the left, the selected plan's stream in the middle, its stage on the right.
 * Below 900 px the side columns are drawers opened from the header. */
export function Agent({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string) => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);

  const loadList = useCallback(() => {
    api.listPlans().then(setPlans).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
  }, []);
  const loadPlan = useCallback(() => {
    if (!selectedId) return setPlan(null);
    api.getPlan(selectedId).then(setPlan).catch((e: Error) => setError(`The plan could not be loaded: ${e.message}.`));
  }, [selectedId]);

  useEffect(loadList, [loadList]);
  useEffect(loadPlan, [loadPlan]);
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

  async function send() {
    if (busy || !brief.trim()) return;
    await act(async () => {
      const p = await api.draftPlan(brief);
      setBrief("");
      onSelect(p.id);
    });
  }

  // `id` keeps the column's and the drawer's ids apart; `close` is set inside a drawer.
  const threads = (id: string, close?: () => void) => (
    <>
      <div className="agent-side-head">
        <h2 id={`${id}-h`}>Threads</h2>
        {close && <button type="button" className="link-button" onClick={close}>Close</button>}
      </div>
      {plans.length === 0 ? (
        <p className="muted">No threads yet. Write a brief to start one.</p>
      ) : (
        <ul className="agent-thread-list">
          {plans.map((p) => (
            <li key={p.id} className={p.id === selectedId ? "selected" : undefined}>
              <button type="button" className="link-button" aria-current={p.id === selectedId ? "true" : undefined}
                onClick={() => { close?.(); onSelect(p.id); }}>
                {threadTitle(p.brief)}
              </button>
              <Chip status={p.status} />
            </li>
          ))}
        </ul>
      )}
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
          {plan ? (
            <Stream key={plan.id} plan={plan} busy={busy} act={act} />
          ) : (
            <p className="muted agent-empty">Pick a thread, or describe the research you want below. A planner writes a short script that chains ARP’s runs; nothing runs until you approve it.</p>
          )}
          <form className="agent-composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <label className="visually-hidden" htmlFor="agent-brief">Research brief</label>
            <textarea id="agent-brief" rows={2} value={brief} onChange={(e) => setBrief(e.target.value)}
              onKeyDown={(e) => {
                if (sendsComposer({ key: e.key, shiftKey: e.shiftKey, isComposing: e.nativeEvent.isComposing })) {
                  e.preventDefault();
                  send();
                }
              }}
              aria-describedby="agent-brief-help"
              placeholder={'Grid-storage companies in the saved universe "eu listed": extract green capex, score, report'} />
            <div className="agent-composer-foot">
              <p id="agent-brief-help" className="muted">Enter drafts a plan; Shift+Enter adds a line. Name a saved universe in the brief.</p>
              <button type="submit" disabled={busy || !brief.trim()}>{busy ? "Drafting…" : "Draft plan"}</button>
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
