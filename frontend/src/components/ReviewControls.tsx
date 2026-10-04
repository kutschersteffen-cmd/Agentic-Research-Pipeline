import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EvidenceSpan, ItemContext, ItemDecisionBody, ReviewDecision, ReviewItem, SimilarDecision } from "../types";
import { SIGN_IN_REQUIRED, useMe } from "../lib/reviewer";
import { DECISION_REASONS, agreeBody, decideBlock, decisionChoices, needsCitation, type Me } from "../lib/reviewKeys";
import { CitationList } from "./CitationList";
import { CheckResults } from "./ReviewTiles";
import type { ActiveSource } from "./SourcePanel";
import { DecisionBar } from "./DecisionBar";
import { ProposedTag } from "./ProposedTag";
import { announce } from "../lib/announce";
import { CommentField } from "./CommentField";

export function decisionBadgeClass(decision: string): string {
  if (decision === "approve") return "badge badge-high";
  if (decision === "edit" || decision === "correct") return "badge badge-mid";
  return "badge badge-low";
}

export function decisionLabel(d: ReviewDecision): string {
  if (d.decision === "approve") return "approved";
  if (d.decision === "reject") return "rejected";
  if (d.decision === "escalate") return "escalated";
  if (d.decision === "correct") {
    const c = (d.corrected_value ?? d.edited_value)?.value;
    return `corrected${c !== undefined && c !== null ? ` → ${c}` : ""}`;
  }
  const v = d.edited_value?.value;
  return `overridden${v !== undefined && v !== null ? ` → ${v}` : ""}`;
}

export function ReviewControls({
  runId,
  itemKey,
  current,
  onDone,
  submitFn,
  historyFn = null,
  item,
  onOpenSource,
}: {
  runId: string;
  itemKey: string;
  current?: ReviewDecision;
  reviewer?: string;
  /** Called with the decision just recorded. */
  onDone: (recorded: ReviewDecision) => void;
  /** The legacy kind's own decision endpoint; required unless `item` is passed. */
  submitFn?: (runId: string, body: unknown) => Promise<unknown>;
  /** null: this run kind keeps no per-item history endpoint, so no History button. */
  historyFn?: ((runId: string, itemKey: string) => Promise<unknown>) | null;
  /** Review workbench item: decide it through the item decision endpoint, with its context bundle. */
  item?: Pick<ReviewItem, "kind" | "state" | "escalated" | "decision"> & { run_type?: string };
  onOpenSource?: (s: ActiveSource) => void;
}) {
  const me = useMe();
  const signedIn = me?.name ?? "";
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [overrideValue, setOverrideValue] = useState("");
  const [showOverrideInput, setShowOverrideInput] = useState(false);
  const [history, setHistory] = useState<ReviewDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (item) return <ItemDecision runId={runId} itemKey={itemKey} item={item} me={me} onDone={onDone} onOpenSource={onOpenSource} />;

  async function submit(decision: "approve" | "edit" | "reject") {
    if (!submitFn) return;
    if (!signedIn) {
      setError(SIGN_IN_REQUIRED);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const recorded = {
        item_key: itemKey,
        decision,
        edited_value: decision === "edit" ? { value: overrideValue } : null,
        comment: comment || null,
      };
      await submitFn(runId, recorded);
      setComment("");
      setOverrideValue("");
      setShowOverrideInput(false);
      setHistory(null);
      announce(`${decision === "approve" ? "Approved" : decision === "edit" ? "Overridden" : "Rejected"}; recorded against ${signedIn}.`);
      onDone({ ...recorded, reviewer: signedIn, role: me?.role, mine: true, decided_at: new Date().toISOString() });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadHistory() {
    if (!historyFn) return;
    if (history !== null) {
      setHistory(null); // toggle closed
      return;
    }
    try {
      const res = (await historyFn(runId, itemKey)) as { history: ReviewDecision[] };
      setHistory(res.history);
    } catch (err) {
      setError(`Could not load history: ${(err as Error).message}`);
    }
  }

  return (
    <div className="review-controls">
      {current ? (
        <span className={decisionBadgeClass(current.decision)}>
          {decisionLabel(current)}
          {current.reviewer ? ` by ${current.reviewer}` : ""}
        </span>
      ) : (
        <ProposedTag />
      )}
      <DecisionBar
        onApprove={() => submit("approve")}
        onOverride={() => setShowOverrideInput((s) => !s)}
        overrideOpen={showOverrideInput}
        onReject={() => submit("reject")}
        disabled={busy}
      >
        {historyFn && (
          <button className="link-button" onClick={loadHistory} aria-expanded={history !== null}>
            History
          </button>
        )}
      </DecisionBar>
      {showOverrideInput && (
        <div className="inline-fields">
          <input
            aria-label="Corrected value"
            placeholder="Corrected value"
            value={overrideValue}
            onChange={(e) => setOverrideValue(e.target.value)}
          />
          <button onClick={() => submit("edit")} disabled={busy || !overrideValue}>
            Submit override
          </button>
        </div>
      )}
      <CommentField value={comment} onChange={setComment} />
      {error && <p className="error-text" role="alert">{error}</p>}
      {history !== null && (
        <ul className="review-history">
          {history.length === 0 && <li className="muted">No decisions yet.</li>}
          {history.map((h, i) => (
            <li key={i}>
              <span className={decisionBadgeClass(h.decision)}>{decisionLabel(h)}</span>{" "}
              {h.reviewer && <span className="muted">by {h.reviewer}</span>}{" "}
              <span className="muted">{new Date(h.decided_at).toLocaleString()}</span>
              {h.comment && <div className="muted">"{h.comment}"</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type Decision = ItemDecisionBody["decision"];
const DECISION_BUTTON: Record<Decision, string> = { approve: "Accept", correct: "Correct…", reject: "Reject", escalate: "Escalate" };
const DECIDED: Record<Decision, string> = { approve: "Accepted", correct: "Corrected", reject: "Rejected", escalate: "Escalated" };
const shown = (v: unknown): string => (v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
const dated = (iso: string) => new Date(iso).toLocaleString();

function ItemStatus({ item, first }: { item: Pick<ReviewItem, "state" | "escalated" | "decision">; first?: ReviewDecision }) {
  if (item.state === "first_done")
    return (
      <span className="muted">
        Awaiting a second review{first ? ` · first review: ${decisionLabel(first)}${first.role ? ` by ${first.role}` : ""}${first.mine ? " (you)" : ""}` : ""}
      </span>
    );
  if (item.state === "disagreed") return <span className="muted">Reviewers disagree — approver decides</span>;
  if (item.escalated) return <span className="badge badge-low">Escalated</span>;
  if ((item.state === "second_done" || item.state === "final") && item.decision) {
    const d = item.decision;
    return (
      <span className={decisionBadgeClass(d.decision)}>
        {decisionLabel(d)}
        {d.role ? ` by ${d.role}` : ""}
        {d.mine ? " (you)" : ""}
      </span>
    );
  }
  return <ProposedTag />;
}

/** Decision mode: the item's decision-ready context and the decisions its kind allows. */
function ItemDecision({
  runId,
  itemKey,
  item,
  me,
  onDone,
  onOpenSource,
}: {
  runId: string;
  itemKey: string;
  item: Pick<ReviewItem, "kind" | "state" | "escalated" | "decision"> & { run_type?: string };
  me: Me | null;
  onDone: (recorded: ReviewDecision) => void;
  onOpenSource?: (s: ActiveSource) => void;
}) {
  const [ctx, setCtx] = useState<ItemContext | null>(null);
  const [open, setOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [reason, setReason] = useState("");
  const [corrected, setCorrected] = useState<Record<string, string>>({});
  const [quote, setQuote] = useState<{ doc_id: string; doc_type: string; quote: string } | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [similar, setSimilar] = useState<SimilarDecision[]>([]);
  const block = decideBlock(item, me);
  const kind = item.kind;
  const awaitingSecond = item.state === "first_done" && !block;

  useEffect(() => {
    // A second reviewer sees the first decision (unless blind) and can agree with a correction.
    if (!awaitingSecond) return;
    let live = true;
    api.getItemContext(runId, itemKey).then((c) => live && setCtx(c), () => undefined);
    return () => {
      live = false;
    };
  }, [awaitingSecond, runId, itemKey]);

  async function loadContext(): Promise<ItemContext | null> {
    setError(null);
    setStale(null);
    if (item.run_type === "extraction" && kind === "value") {
      api.getSimilarDecisions(runId, itemKey).then((r) => setSimilar(r.items), () => setSimilar([]));
    }
    try {
      const c = await api.getItemContext(runId, itemKey);
      setCtx(c);
      return c;
    } catch (err) {
      setError(`Could not load the item: ${(err as Error).message}`);
      return null;
    }
  }

  /** Opening Correct starts from the verifier's or adjudicator's value, never over a typed one. */
  function prefill(c: ItemContext | null) {
    const v = c?.suggested_correction?.value;
    if (v !== undefined && v !== null) setCorrected((cur) => (cur.value ? cur : { ...cur, value: String(v) }));
  }

  function choose(d: Decision) {
    setDecision(d);
    setReason(d === "approve" ? "confirmed" : "");
    if (d === "correct") {
      if (ctx) prefill(ctx);
      else void loadContext().then(prefill);
    } else if (!ctx) void loadContext();
  }

  function openSpan(s: EvidenceSpan) {
    onOpenSource?.({
      title: `${s.title ?? s.source_filename ?? s.doc_type}${s.page ? ` — p. ${s.page}` : ""}`,
      src: s.company_id && s.source_filename ? `${api.documentRawUrl(s.company_id, s.doc_type, s.source_filename)}${s.page ? `#page=${s.page}` : ""}` : "",
      quote: s.quote,
      text:
        s.page_text !== null && s.page_start !== null
          ? {
              run_id: runId,
              item_key: itemKey,
              doc_id: s.doc_id,
              doc_type: s.doc_type,
              page: s.page,
              pages: ctx?.documents.find((d) => d.doc_id === s.doc_id)?.pages ?? undefined,
              page_start: s.page_start,
              page_text: s.page_text,
              char_start: s.char_start,
              char_end: s.char_end,
            }
          : undefined,
      onSelectQuote: setQuote,
    });
  }

  async function openDocument(docId: string) {
    if (!docId) return;
    setError(null);
    try {
      const s = await api.getItemSource(runId, itemKey, docId, 1);
      onOpenSource?.({
        title: s.title ?? s.source_filename ?? s.doc_id,
        src: s.company_id && s.source_filename ? api.documentRawUrl(s.company_id, s.doc_type, s.source_filename) : "",
        text: { run_id: runId, item_key: itemKey, doc_id: s.doc_id, doc_type: s.doc_type, page: s.page, pages: s.pages, page_start: s.page_start, page_text: s.page_text },
        onSelectQuote: setQuote,
      });
    } catch (err) {
      setError(`Could not open the document: ${(err as Error).message}`);
    }
  }

  const correctedValue: Record<string, string> | null =
    decision === "correct" ? Object.fromEntries(Object.entries(corrected).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v !== "")) : null;
  const correctionReady =
    decision !== "correct" ||
    (kind === "identity"
      ? !!(correctedValue?.resolved_website || correctedValue?.resolved_cik) && comment.trim() !== ""
      : kind === "sector_code"
        ? !!correctedValue?.isic_code && comment.trim() !== ""
        : kind === "security"
          ? !!correctedValue?.value && comment.trim() !== ""
        : !!correctedValue?.value && (!needsCitation(kind) || quote !== null));
  const canSubmit = !!ctx && !!decision && !!reason && correctionReady && !block && !busy;
  const agree = ctx && !block ? agreeBody(kind, item.state, ctx) : null;
  const first = item.state === "first_done" && ctx && !ctx.blind ? ctx.decisions[ctx.decisions.length - 1] : undefined;

  /** `agreed`: the first correction resubmitted as is (the Agree action). */
  async function submit(agreed?: NonNullable<typeof agree>) {
    if (!ctx || !(agreed || decision) || !me) return;
    setBusy(true);
    setError(null);
    setStale(null);
    try {
      const body: ItemDecisionBody = agreed
        ? { ...agreed, comment: comment || agreed.comment, context_etag: ctx.etag }
        : {
            decision: decision!,
            reason_code: reason,
            corrected_value: correctedValue,
            correction_citation: decision === "correct" && needsCitation(kind) ? quote : null,
            comment: comment || null,
            context_etag: ctx.etag,
          };
      const res = await api.decideItem(runId, itemKey, body);
      announce(`${agreed ? "Agreed" : DECIDED[body.decision]}; ${res.state}.`);
      onDone({
        item_key: itemKey,
        decision: body.decision,
        reason_code: body.reason_code,
        corrected_value: body.corrected_value,
        edited_value: body.corrected_value,
        role: me.role,
        mine: true,
        decided_at: new Date().toISOString(),
        step: item.state === "first_done" ? "second" : item.state === "disagreed" ? "resolution" : "first",
      });
      setDecision(null);
      setReason("");
      setCorrected({});
      setQuote(null);
      setComment("");
      setCtx(null); // its etag is stale now
      setOpen(false);
      setShowHistory(false);
    } catch (err) {
      const message = (err as Error).message;
      if (message.startsWith("409")) setStale(message);
      else setError(message);
    } finally {
      setBusy(false);
    }
  }

  const fd = ctx?.field_definition ?? null;
  const input = (key: string, label: string) => (
    <input aria-label={label} placeholder={label} value={corrected[key] ?? ""} onChange={(e) => setCorrected((c) => ({ ...c, [key]: e.target.value }))} />
  );

  return (
    <div className="review-controls">
      <ItemStatus item={item} first={first} />
      <div className="toolbar decision-bar">
        {agree && (
          <button onClick={() => void submit(agree)} disabled={busy}>
            Agree
          </button>
        )}
        {decisionChoices(kind, item.run_type)
          .filter((d) => !(d === "escalate" && item.state === "disagreed"))
          .map((d) => (
          <button
            key={d}
            className={d === "approve" ? undefined : d === "reject" ? "danger-outline" : "secondary"}
            data-decision={d}
            onClick={() => choose(d)}
            disabled={!!block || busy}
            aria-pressed={decision === d}
          >
            {agree && d === "approve" ? "Accept original value" : DECISION_BUTTON[d]}
          </button>
        ))}
        <button
          className="link-button"
          aria-expanded={open}
          onClick={() => {
            if (!open && !ctx) void loadContext();
            setOpen((o) => !o);
          }}
        >
          Review
        </button>
        <button
          className="link-button"
          aria-expanded={showHistory}
          onClick={() => {
            if (!showHistory && !ctx) void loadContext();
            setShowHistory((h) => !h);
          }}
        >
          History
        </button>
      </div>
      {block && <p className="muted">{block}</p>}
      {open && ctx && (
        <div className="decision-view">
          {fd && (
            <p>
              <strong>{shown(fd.name)}</strong>
              {fd.unit != null && <span className="muted"> ({shown(fd.unit)})</span>}
              {fd.description != null && <span className="muted"> — {shown(fd.description)}</span>}
            </p>
          )}
          {fd?.extraction_instructions != null && (
            <details>
              <summary>Instructions</summary>
              <p className="muted">{shown(fd.extraction_instructions)}</p>
            </details>
          )}
          {ctx.value && (
            <p>
              Value: <strong>{shown(ctx.value.value)}</strong>
              {ctx.confidence && (
                <span className="muted">
                  {" "}
                  · confidence {ctx.confidence.final.toFixed(2)}
                  {ctx.confidence.extractor != null && ` · extractor ${ctx.confidence.extractor.toFixed(2)}`}
                  {ctx.confidence.verifier != null && ` · verifier ${ctx.confidence.verifier.toFixed(2)}`}
                  {ctx.confidence.grounded ? " · grounded" : " · not grounded"}
                  {ctx.confidence.match_methods.length > 0 && ` (${ctx.confidence.match_methods.join(", ")})`}
                  {ctx.confidence.auto_accept_min != null && ` · auto-accept at ${ctx.confidence.auto_accept_min.toFixed(2)}`}
                </span>
              )}
            </p>
          )}
          <CheckResults checks={ctx.failed_checks} />
          {ctx.route_reasons.length > 0 && <p className="muted">Routed for review: {ctx.route_reasons.join(", ")}</p>}
          {ctx.conflict && ctx.conflict.alternatives.length > 0 && (
            <div>
              <p className="muted">Other sources disagree:</p>
              <ul>
                {ctx.conflict.alternatives.map((a, i) => (
                  <li key={i}>
                    {shown(a.value)} <span className="muted">({a.source})</span>
                    {onOpenSource && <CitationList citations={a.citations} onOpenSource={onOpenSource} />}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {ctx.prior_period && (
            <p className="muted">
              Prior period ({ctx.prior_period.period_end}): {shown(ctx.prior_period.value)}
            </p>
          )}
          {ctx.published && <p className="muted">Published: {shown(ctx.published.value)}</p>}
          {similar.length > 0 && (
            <div>
              <p className="muted">Earlier decisions on this field, same document type:</p>
              <ul>
                {similar.map((h) => (
                  <li key={`${h.run_id}/${h.item_key}`}>
                    {h.period}: {shown(h.value)} <span className={decisionBadgeClass(h.decision.decision)}>{decisionLabel(h.decision)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {ctx.evidence.length > 0 && (
            <ul className="citation-list">
              {ctx.evidence.map((s, i) => (
                <li key={i}>
                  [{s.doc_type}] "{s.quote}"{s.page ? <span className="muted"> p. {s.page}</span> : null}
                  {onOpenSource && (s.page_text !== null || (s.company_id && s.source_filename)) && (
                    <>
                      {" "}
                      <button type="button" className="link-button" onClick={() => openSpan(s)}>
                        Show in source
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {onOpenSource && ctx.documents.length > 0 && (
            <label className="field-label">
              Open a document
              <select value="" onChange={(e) => void openDocument(e.target.value)}>
                <option value="">Choose…</option>
                {ctx.documents.map((d) => (
                  <option key={d.doc_id} value={d.doc_id}>
                    {d.title ?? d.doc_id} [{d.doc_type}]{d.pages != null ? ` · ${d.pages} p.` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          {ctx.blind && <p className="muted">Earlier decision hidden (blind second review)</p>}
        </div>
      )}
      {decision && !block && (
        <div className="inline-fields">
          <select aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} disabled={decision === "approve"}>
            {decision === "approve" ? (
              <option value="confirmed">confirmed</option>
            ) : (
              <>
                <option value="">Reason…</option>
                {DECISION_REASONS.filter((r) => r !== "confirmed").map((r) => (
                  <option key={r} value={r}>
                    {r.replace(/_/g, " ")}
                  </option>
                ))}
              </>
            )}
          </select>
          {decision === "correct" &&
            (kind === "sector_code" ? (
              input("isic_code", "ISIC code")
            ) : kind === "identity" ? (
              <>
                {input("resolved_website", "Website")}
                {input("resolved_cik", "CIK")}
              </>
            ) : kind === "security" ? (
              input("value", "LEI")
            ) : (
              input("value", "Corrected value")
            ))}
          <button onClick={() => void submit()} disabled={!canSubmit}>
            Submit
          </button>
        </div>
      )}
      {decision === "correct" && needsCitation(kind) && (
        <p className="muted" aria-live="polite">{quote ? `Source: "${quote.quote}"` : "Open a source and select the text that shows the corrected value."}</p>
      )}
      {decision === "correct" && (kind === "identity" || kind === "sector_code" || kind === "security") && (
        <p className="muted">A correction needs a comment naming its source.</p>
      )}
      <CommentField value={comment} onChange={setComment} />
      {stale && (
        <p className="error-text" role="alert">
          {stale}{" "}
          <button className="secondary" onClick={() => void loadContext()}>
            Reload
          </button>
        </p>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
      {showHistory && ctx && (
        <ul className="review-history">
          {ctx.decisions.length === 0 && <li className="muted">No decisions yet.</li>}
          {ctx.decisions.map((h, i) => (
            <li key={i}>
              <span className={decisionBadgeClass(h.decision)}>{decisionLabel(h)}</span>{" "}
              {h.role && <span className="muted">by {h.role}</span>} <span className="muted">{dated(h.decided_at)}</span>
              {h.comment && <div className="muted">"{h.comment}"</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
