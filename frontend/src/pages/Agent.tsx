import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { StepTabs } from "../components/StepTabs";
import { budgetLine, chipLabel, INBOX_KIND, lineDiff, reviewQueueLine, scriptLines, sendsComposer, stepState, threadTitle, usd } from "../lib/agent";
import { ACTIVE, canReplan, resultHref, reviewHref, stepRows, type Plan } from "../lib/plans";
import { when } from "../lib/runs";
import type { InboxRow } from "../types";

const POLL_MS = 3000;
const NARROW = "(max-width: 899.98px)";

type Drawer = "threads" | "stage" | null;
type StageTab = "script" | "diff" | "audit";
const STAGE_TABS: { id: StageTab; label: string }[] = [{ id: "script", label: "Script" }, { id: "diff", label: "Diff" }, { id: "audit", label: "Audit" }];

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
  const [inbox, setInbox] = useState<InboxRow[]>([]);
  const [waiting, setWaiting] = useState<number | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [tab, setTab] = useState<StageTab>("script");

  const loadInbox = useCallback(() => {
    api.getAgentInbox().then(setInbox).catch((e: Error) => setError(`The inbox could not be loaded: ${e.message}.`));
    api.getWaiting().then((w) => setWaiting(w.total)).catch(() => setWaiting(null)); // no count rather than a wrong one
  }, []);
  const loadList = useCallback(() => {
    api.listPlans().then(setPlans).catch((e: Error) => setError(`Threads could not be loaded: ${e.message}.`));
    loadInbox();
  }, [loadInbox]);
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
      {waiting !== null && <p className="agent-inbox-foot"><a href="#/review" onClick={close}>{reviewQueueLine(waiting)}</a></p>}
    </>
  );
  const stage = (id: string, close?: () => void) => (
    <>
      <div className="agent-side-head">
        <StepTabs label="Stage" tabs={STAGE_TABS} active={tab} onSelect={(t) => setTab(t as StageTab)} />
        {close && <button type="button" className="link-button" onClick={close}>Close</button>}
      </div>
      <div id={`${id}-panel`} role="tabpanel" aria-label={STAGE_TABS.find((t) => t.id === tab)!.label}>
        {!plan ? (
          <p className="muted">The selected plan’s script, changes and audit trail show here.</p>
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
