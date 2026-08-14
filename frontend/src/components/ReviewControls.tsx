import { useState } from "react";
import { api } from "../api/client";
import type { ReviewDecision } from "../types";

function decisionBadgeClass(decision: string): string {
  if (decision === "approve") return "badge badge-high";
  if (decision === "edit") return "badge badge-mid";
  return "badge badge-low";
}

function decisionLabel(d: ReviewDecision): string {
  if (d.decision === "approve") return "reviewed";
  if (d.decision === "reject") return "rejected";
  const v = d.edited_value?.value;
  return `overridden${v !== undefined && v !== null ? ` → ${v}` : ""}`;
}

export function ReviewControls({
  runId,
  itemKey,
  current,
  reviewer,
  onDone,
  submitFn = api.submitExtractionReview,
  historyFn = api.getExtractionReviewHistory,
}: {
  runId: string;
  itemKey: string;
  current?: ReviewDecision;
  reviewer: string;
  onDone: () => void;
  /** Defaults to the scalar Data-Point Extraction Engine's endpoints; pass
   * the segments/spend equivalents when reusing this component elsewhere. */
  submitFn?: (runId: string, body: unknown) => Promise<unknown>;
  historyFn?: (runId: string, itemKey: string) => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [overrideValue, setOverrideValue] = useState("");
  const [showOverrideInput, setShowOverrideInput] = useState(false);
  const [history, setHistory] = useState<ReviewDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(decision: "approve" | "edit" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await submitFn(runId, {
        item_key: itemKey,
        decision,
        reviewer: reviewer || null,
        edited_value: decision === "edit" ? { value: overrideValue } : null,
        comment: comment || null,
      });
      setComment("");
      setOverrideValue("");
      setShowOverrideInput(false);
      setHistory(null);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadHistory() {
    if (history !== null) {
      setHistory(null); // toggle closed
      return;
    }
    const res = (await historyFn(runId, itemKey)) as { history: ReviewDecision[] };
    setHistory(res.history);
  }

  return (
    <div className="review-controls">
      {current && (
        <span className={decisionBadgeClass(current.decision)}>
          {decisionLabel(current)}
          {current.reviewer ? ` by ${current.reviewer}` : ""}
        </span>
      )}
      <div className="toolbar">
        <button onClick={() => submit("approve")} disabled={busy}>
          Mark reviewed
        </button>
        <button onClick={() => setShowOverrideInput((s) => !s)} disabled={busy}>
          Override
        </button>
        <button onClick={() => submit("reject")} disabled={busy}>
          Reject
        </button>
        <button onClick={loadHistory}>History{current ? "" : " (0)"}</button>
      </div>
      {showOverrideInput && (
        <div className="inline-fields">
          <input
            placeholder="corrected value"
            value={overrideValue}
            onChange={(e) => setOverrideValue(e.target.value)}
          />
          <button onClick={() => submit("edit")} disabled={busy || !overrideValue}>
            Submit override
          </button>
        </div>
      )}
      <textarea
        rows={1}
        placeholder="Comment (optional)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {error && <p className="error-text">{error}</p>}
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
