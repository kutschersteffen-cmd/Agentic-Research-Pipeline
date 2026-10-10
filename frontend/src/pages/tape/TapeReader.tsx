import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, UIEvent } from "react";
import { api } from "../../api/client";
import { REVIEW_KIND_LABEL, fromReviewItem, type QueueItem } from "../../components/RunReviewList";
import { SignedInAs } from "../../components/SignedInAs";
import { useMe } from "../../lib/reviewer";
import { announce } from "../../lib/announce";
import type { ReviewDecision } from "../../types";
import { REASON_OPTIONS, accessFor, decisionBody, mergeDecided, nextAwaiting, recordedFrom, rowKey, sortQueue, toRow, type TapeAction } from "./tapeData";
import "./TapeReader.css";

const H = 24;
const DASH = "–";
const VERB: Record<TapeAction, string> = { approve: "Approve", reject: "Reject", escalate: "Escalate" };
const DONE: Record<TapeAction, string> = { approve: "Approved", reject: "Rejected", escalate: "Escalated" };

/** DOM id of a tape row, stable across re-sorts (ids cannot hold whitespace). */
const rowId = (key: string) => `tape-row-${key.replace(/\s/g, "_")}`;

interface Status { text: string; error: boolean }
interface Picker { key: string; action: "reject" | "escalate" }

export function TapeReader() {
  const me = useMe();
  const tapeRef = useRef<HTMLDivElement>(null);
  const scRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<HTMLSelectElement>(null);
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshed, setRefreshed] = useState<Date | null>(null);
  const [decided, setDecided] = useState<Record<string, ReviewDecision>>({});
  const [sessionCount, setSessionCount] = useState(0);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [status, setStatus] = useState<Status | null>(null);
  const [picker, setPicker] = useState<Picker | null>(null);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [sel, setSel] = useState(0);
  const [top, setTop] = useState(0);
  const [vh, setVh] = useState(560);

  const load = useCallback(async () => {
    setError(null);
    setItems(null);
    setDecided({});
    setPicker(null);
    setStatus(null);
    try {
      setItems(sortQueue((await api.listReviewItems()).items.map(fromReviewItem)));
      setRefreshed(new Date());
    } catch (err) {
      setError(`Flagged items could not be loaded: ${(err as Error).message}.`);
      setItems([]);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const rows = useMemo(() => (items ?? []).map((q) => toRow(q, me, decided[rowKey(q)])), [items, me, decided]);
  const total = rows.length;
  const cur = rows[Math.min(sel, total - 1)];
  const ready = total > 0;

  // The tape mounts once rows exist: focus it, and keep the window sized to its scroller.
  useEffect(() => {
    if (!ready) return;
    tapeRef.current?.focus({ preventScroll: true });
    const sc = scRef.current;
    if (!sc) return;
    setVh(sc.clientHeight);
    const ro = new ResizeObserver(() => setVh(sc.clientHeight));
    ro.observe(sc);
    return () => ro.disconnect();
  }, [ready]);

  useEffect(() => { if (picker) reasonRef.current?.focus(); }, [picker]);

  const go = (i: number) => {
    const n = Math.max(0, Math.min(total - 1, i));
    setSel(n);
    const sc = scRef.current;
    if (!sc) return;
    const y = n * H;
    if (y < sc.scrollTop) sc.scrollTop = y;
    else if (y + H > sc.scrollTop + sc.clientHeight) sc.scrollTop = y + H - sc.clientHeight;
  };

  const closePicker = () => { setPicker(null); setReason(""); setComment(""); tapeRef.current?.focus({ preventScroll: true }); };

  /** Reload the run's open items and merge them in; null when that fails. */
  const freshRun = async (q: QueueItem): Promise<QueueItem[] | null> => {
    try { return (await api.listReviewItems(q.runId)).items.map(fromReviewItem); } catch { return null; }
  };

  async function submit(index: number, action: TapeAction, pick?: { reason: string; comment: string }) {
    const row = rows[index];
    if (!row || !me) return;
    const q = row.q;
    if (busy.has(row.key)) return;
    setBusy((b) => new Set(b).add(row.key));
    setStatus({ text: `${VERB[action]} sent for ${row.entity ?? row.key}…`, error: false });
    try {
      const ctx = await api.getItemContext(q.runId, q.review.item_key);
      const body = decisionBody(action, q, ctx, pick);
      if (!body) throw new Error("Choose a reason first.");
      await api.decideItem(q.runId, q.review.item_key, body);
      const recorded = recordedFrom(body, me, q.review.item_key, q.review.state, new Date());
      const fresh = await freshRun(q);
      const merged = mergeDecided(items ?? [], q, recorded, fresh);
      const nextRows = merged.items.map((x) => toRow(x, me, rowKey(x) === row.key ? merged.decided ?? undefined : decided[rowKey(x)]));
      setItems(merged.items);
      if (merged.decided) setDecided((d) => ({ ...d, [row.key]: merged.decided as ReviewDecision }));
      setSessionCount((n) => n + 1);
      const done = `${body.decision === "correct" ? "Agreed" : DONE[action]}; recorded against ${me.name}.`;
      setStatus({ text: done, error: false });
      announce(done);
      go(nextAwaiting(nextRows, index));
    } catch (err) {
      const message = (err as Error).message;
      if (message.startsWith("409")) {
        try { await api.getItemContext(q.runId, q.review.item_key); } catch { /* the next press reloads it */ }
        const fresh = await freshRun(q);
        if (fresh) setItems((prev) => prev && mergeDecided(prev, q, {} as ReviewDecision, fresh).items);
        setStatus({ text: "This item changed since you opened it. Its latest version is loaded; check it and decide again.", error: true });
      } else {
        setStatus({ text: message, error: true });
      }
    } finally {
      setBusy((b) => { const n = new Set(b); n.delete(row.key); return n; });
    }
  }

  /** a approves, r and e open the reason picker; every path first asks accessFor. */
  const act = (action: TapeAction) => {
    if (!cur) return;
    const index = rows.indexOf(cur);
    if (busy.has(cur.key)) return;
    const acc = accessFor(cur.q, me, cur.key in decided);
    if (!acc.ok) { setStatus({ text: acc.reason, error: false }); return; }
    if (!acc.actions.includes(action)) { setStatus({ text: `${VERB[action]} is not available for this item.`, error: false }); return; }
    if (action === "approve") void submit(index, "approve");
    else { setReason(""); setComment(""); setPicker({ key: cur.key, action }); }
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const k = e.key;
    if (k === "j" || k === "ArrowDown") { e.preventDefault(); go(sel + 1); }
    else if (k === "k" || k === "ArrowUp") { e.preventDefault(); go(sel - 1); }
    else if (k === "a") act("approve");
    else if (k === "r") act("reject");
    else if (k === "e") act("escalate");
  };

  const onPickerKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { e.preventDefault(); closePicker(); }
    else if (e.key === "Enter" && (e.target as HTMLElement).tagName !== "BUTTON") { e.preventDefault(); sendPicker(); }
  };
  const sendPicker = () => {
    if (!picker || !reason) return;
    const index = rows.findIndex((r) => r.key === picker.key);
    const { action } = picker;
    const pick = { reason, comment };
    closePicker();
    if (index >= 0) void submit(index, action, pick);
  };

  const pickedRow = picker ? rows.find((r) => r.key === picker.key) : undefined;
  const a = Math.max(0, Math.floor(top / H) - 4);
  const b = Math.min(total, Math.ceil((top + vh) / H) + 4);
  const pending = rows.filter((r) => r.state !== "final" && r.state !== "second_done").length;
  const awaiting = rows.filter((r) => r.awaiting).length;
  const signedIn = me && me.role !== "viewer";

  const rendered = [];
  for (let i = a; i < b; i++) {
    const r = rows[i];
    const cls = "row" + (i === sel ? " sel" : "") + (r.decision ? " done" : "") + (busy.has(r.key) ? " busy" : "");
    const kind = REVIEW_KIND_LABEL[r.q.kind];
    const stateText = busy.has(r.key) ? "SENDING…" : r.decision ?? r.state.replace("_", " ");
    rendered.push(
      <div key={r.key} id={rowId(r.key)} className={cls} style={{ top: i * H }} onClick={() => setSel(i)} aria-selected={i === sel} aria-rowindex={i + 1} role="row">
        <span role="gridcell" className="d">{r.queued ?? DASH}</span>
        <span role="gridcell" title={`${kind} · ${r.q.runId}`}>{r.q.runId} · <span className="d">{kind}</span></span>
        <span role="gridcell">{r.entity ?? DASH}</span>
        <span role="gridcell">{r.field ?? DASH}</span>
        <span role="gridcell" className="v">{r.proposed ?? DASH}</span>
        <span role="gridcell" className="d">{r.confidence === null ? DASH : r.confidence.toFixed(2)}</span>
        <span role="gridcell" className="d" title={r.reasons.join(", ")}>{r.reasons.length ? r.reasons.map((x) => x.replaceAll("_", " ")).join(", ") : DASH}</span>
        <span role="gridcell" className="st" title={stateText}>
          {r.awaiting && <i className="mk" role="img" aria-label="Awaiting your decision" />}
          {stateText}
          {r.escalated && <abbr title="Escalated"> ESC</abbr>}
          {r.highRisk && <abbr title="High risk"> HR</abbr>}
          {(r.readOnly || r.citation) && <a className="go" href={r.href} aria-label={r.readOnly ? "Decide in Review Queue" : "Correct in Review Queue"}> ↗</a>}
        </span>
      </div>,
    );
  }

  const toolbar = (
    <div className="head">
      <button type="button" className="rf" onClick={() => void load()} disabled={items === null}>Refresh</button>
      <span className="note">Live review queue{refreshed ? ` · refreshed ${refreshed.toLocaleTimeString()}` : ""}</span>
      {!signedIn && <SignedInAs compact />}
    </div>
  );

  if (items === null) return <div className="lab-tape">{toolbar}<p className="msg" role="status">Loading flagged items…</p></div>;
  if (!ready) {
    return (
      <div className="lab-tape">
        {toolbar}
        {error
          ? <p className="msg err" role="alert">Error: {error} <button type="button" onClick={() => void load()}>Retry</button></p>
          : <p className="msg">Nothing is waiting for review.</p>}
      </div>
    );
  }

  return (
    <div className="lab-tape">
      {toolbar}
      <p className="note">Corrections need a citation, so they are made in the Review Queue (↗). The tape approves, rejects and escalates.</p>
      <div className="tape" ref={tapeRef} tabIndex={0} onKeyDown={onKey} role="group" aria-activedescendant={cur && sel >= a && sel < b ? rowId(cur.key) : undefined} aria-label="Tape reader. j and k move, a approves, r rejects, e escalates.">
        <div className="bar">
          <div className="btns">
            {(["approve", "reject", "escalate"] as const).map((x) => (
              <button key={x} type="button" onClick={() => act(x)} disabled={!!cur && busy.has(cur.key)}>{VERB[x]}</button>
            ))}
          </div>
          <span className="keys"><kbd>j</kbd> <kbd>k</kbd> move &nbsp;<kbd>a</kbd> approve &nbsp;<kbd>r</kbd> reject &nbsp;<kbd>e</kbd> escalate</span>
        </div>
        <div className="row hd" aria-hidden="true"><span>Queued</span><span>Run</span><span>Entity</span><span>Field</span><span>Proposed</span><span>Conf.</span><span>Flagged</span><span className="st">State</span></div>
        <div className="sc" ref={scRef} onScroll={(e: UIEvent<HTMLDivElement>) => setTop(e.currentTarget.scrollTop)}>
          <div className="in" style={{ height: total * H }} role="grid" aria-label="Flagged items" aria-rowcount={total}>{rendered}</div>
        </div>
        <div className="foot">
          <span>row <b>{Math.min(sel, total - 1) + 1}</b>/{total}</span>
          <span>pending <b>{pending}</b></span>
          <span>decided this session <b>{sessionCount}</b></span>
          <span><i className="mk" />awaiting you <b>{awaiting}</b></span>
          <span>{signedIn ? <>signed in <b>{me.name}</b> · {me.role}</> : "Not signed in"}</span>
        </div>
      </div>
      {cur && (cur.readOnly || cur.citation) && (
        <p className="note">
          {cur.readOnly ? "This item cannot be decided on the tape. " : "Correcting this item needs a citation. "}
          <a href={cur.href}>{cur.readOnly ? "Decide in Review Queue" : "Correct in Review Queue"}</a>
        </p>
      )}
      {picker && (
        <div className="picker" role="group" aria-label={`${VERB[picker.action]} reason`} onKeyDown={onPickerKey}>
          <b>{VERB[picker.action]} {pickedRow?.entity ?? ""}{pickedRow?.field ? ` · ${pickedRow.field}` : ""}</b>
          <label>Reason
            <select ref={reasonRef} value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">Choose a reason</option>
              {REASON_OPTIONS.map((r) => <option key={r} value={r}>{r.replaceAll("_", " ")}</option>)}
            </select>
          </label>
          <label>Comment (optional)
            <input value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <button type="button" onClick={sendPicker} disabled={!reason}>{VERB[picker.action]}</button>
          <button type="button" onClick={closePicker}>Cancel</button>
          <small>Enter submits, Esc cancels.</small>
        </div>
      )}
      <p className={status?.error ? "msg err" : "msg"} role={status?.error ? "alert" : "status"}>{status?.error ? "Error: " : ""}{status?.text ?? ""}</p>
    </div>
  );
}
