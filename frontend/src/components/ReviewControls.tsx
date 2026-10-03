import { useState } from "react";
import { api } from "../api/client";
import type { ReviewDecision } from "../types";
import { SIGN_IN_REQUIRED, useMe } from "../lib/reviewer";
import { canCosign } from "../lib/reviewKeys";
import { DecisionBar } from "./DecisionBar";
import { ProposedTag } from "./ProposedTag";
import { announce } from "../lib/announce";
import { CommentField } from "./CommentField";

export function decisionBadgeClass(decision: string): string {
  if (decision === "approve") return "badge badge-high";
  if (decision === "edit") return "badge badge-mid";
  return "badge badge-low";
}

export function decisionLabel(d: ReviewDecision): string {
  if (d.decision === "approve") return "approved";
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
  cosignFn,
}: {
  runId: string;
  itemKey: string;
  current?: ReviewDecision;
  reviewer: string;
  /** Called with the decision just recorded. */
  onDone: (recorded: ReviewDecision) => void;
  /** Defaults to the scalar Data-Point Extraction Engine's endpoints; pass
   * the segments/spend equivalents when reusing this component elsewhere. */
  submitFn?: (runId: string, body: unknown) => Promise<unknown>;
  /** null: this run kind keeps no per-item history endpoint, so no History button. */
  historyFn?: ((runId: string, itemKey: string) => Promise<unknown>) | null;
  /** Only runs whose overrides need a second approver (extraction) pass this. */
  cosignFn?: (runId: string, itemKey: string) => Promise<unknown>;
}) {
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [overrideValue, setOverrideValue] = useState("");
  const [showOverrideInput, setShowOverrideInput] = useState(false);
  const [history, setHistory] = useState<ReviewDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(decision: "approve" | "edit" | "reject") {
    if (!reviewer.trim()) {
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
      announce(`${decision === "approve" ? "Approved" : decision === "edit" ? "Overridden" : "Rejected"}; recorded against ${reviewer.trim()}.`);
      onDone({ ...recorded, reviewer: reviewer.trim(), user_id: me?.user_id, role: me?.role, cosigned: false, decided_at: new Date().toISOString() });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function cosign() {
    if (!cosignFn || !current) return;
    setBusy(true);
    setError(null);
    try {
      await cosignFn(runId, itemKey);
      announce("Co-signed.");
      onDone({ ...current, cosigned: true });
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
      {cosignFn && current?.decision === "edit" && !current.cosigned && (
        <span className="muted">
          Awaiting second sign-off{" "}
          {canCosign(current, me) && (
            <button className="secondary" onClick={cosign} disabled={busy}>
              Co-sign
            </button>
          )}
        </span>
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
