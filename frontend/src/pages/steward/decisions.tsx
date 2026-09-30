import { useState } from "react";
import { api } from "../../api/client";
import { ConfirmDecision } from "../../components/ConfirmDecision";
import type { ClientExceptionItem, EscalationDecisionItem, PolicyDifferenceItem, TierChangeItem } from "../../types";
import { fmt, words } from "./common";

export function TierDecisions({ items, actor, onDone }: { items: TierChangeItem[]; actor: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  async function confirm(issuerIds?: string[], by = actor) {
    setConfirmingAll(false);
    setBusy(issuerIds ? issuerIds[0] : "all");
    setError(null);
    try {
      await api.confirmTiers({ decided_by: by, issuer_ids: issuerIds });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const needName = actor ? undefined : "Enter your name above first";
  return (
    <>
      <div className="section-heading">
        <h3>Coverage tiers to confirm</h3>
        <button onClick={() => setConfirmingAll(true)} disabled={busy !== null}>
          {busy === "all" ? "Confirming…" : `Confirm all ${items.length}…`}
        </button>
      </div>
      {confirmingAll && (
        <ConfirmDecision
          title={`Confirm all ${items.length} tiers?`}
          confirmLabel={`Confirm ${items.length} tiers`}
          onConfirm={(by) => confirm(undefined, by)}
          onCancel={() => setConfirmingAll(false)}
        >
          <p>
            Each company below moves to its proposed tier and coverage follows from it. Every confirmation is kept; to undo one,
            confirm a different tier later.
          </p>
        </ConfirmDecision>
      )}
      <p className="muted">
        Proposed by the house coverage rules (a decision table you can edit in the rule editor). A tier only counts once it is
        confirmed; every confirmation is kept, never overwritten.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Tier</th>
              <th>Why (rule that fired)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.issuer_id}>
                <td>{item.company}</td>
                <td>
                  {item.current} → <strong>{item.proposed}</strong>
                </td>
                <td>
                  {item.reason} <span className="muted">({item.rule})</span>
                </td>
                <td>
                  <button className="secondary" onClick={() => confirm([item.issuer_id])} disabled={!actor || busy !== null} title={needName}>
                    {busy === item.issuer_id ? "Confirming…" : "Confirm"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function EscalationDecisions({ items, actor, onDone }: { items: EscalationDecisionItem[]; actor: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function escalate(item: EscalationDecisionItem) {
    if (!item.next) return;
    setBusy(item.issue_id);
    setError(null);
    try {
      await api.escalateEngagementIssue(item.company_id, item.issue_id, { stage: item.next, decided_by: actor, reason: item.reason });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Theme</th>
              <th>Why (rule)</th>
              <th>Escalation step</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.issue_id}>
                <td>{item.company}</td>
                <td>{words(item.theme)}</td>
                <td>{item.reason}</td>
                <td>
                  {item.next ? (
                    <>
                      {words(item.current)} → <strong>{words(item.next)}</strong>
                    </>
                  ) : (
                    words(item.current)
                  )}
                  {item.promote_tier && (
                    <span className="muted"> · capped by its tier at {words(item.max_step)}: consider promoting the tier</span>
                  )}
                </td>
                <td>
                  <button
                    className="secondary"
                    onClick={() => escalate(item)}
                    disabled={!actor || !item.next || busy !== null}
                    title={actor ? undefined : "Enter your name above first"}
                  >
                    {busy === item.issue_id ? "Escalating…" : "Escalate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">Not escalating is also a decision: log the next outreach on the Engagement page to restart the clock.</p>
    </>
  );
}

/** A client's escalation rules want a higher step than the house's: the house engages
 * each company once, so it adopts the client's step or keeps its own. */
export function ClientExceptionDecisions({ items, actor, onDone }: { items: ClientExceptionItem[]; actor: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function decide(item: ClientExceptionItem, decision: "adopt" | "decline") {
    setBusy(`${item.stream_id}-${item.issue_id}`);
    setError(null);
    try {
      await api.decideClientException(item.stream_id, {
        issue_id: item.issue_id,
        client_step: item.client_step,
        decision,
        decided_by: actor,
      });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Client</th>
              <th>Company</th>
              <th>Theme</th>
              <th>Why (client rule)</th>
              <th>Step</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.stream_id}-${item.issue_id}`}>
                <td>{item.client}</td>
                <td>{item.company}</td>
                <td>{words(item.theme)}</td>
                <td>{item.reason}</td>
                <td>
                  now {words(item.current)} · house {words(item.house)} · client <strong>{words(item.client_step)}</strong>
                </td>
                <td>
                  <div className="row-actions">
                    <button
                      onClick={() => decide(item, "adopt")}
                      disabled={!actor || busy !== null}
                      title={actor ? undefined : "Enter your name above first"}
                    >
                      Adopt
                    </button>
                    <button className="secondary" onClick={() => decide(item, "decline")} disabled={!actor || busy !== null}>
                      Keep the house step
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">Adopting moves the engagement to the client&apos;s step. Either way the decision is logged for the client&apos;s report.</p>
    </>
  );
}

const DECISIONS_FOR: Record<string, string[]> = {
  unclear: ["clarify", "decline"],
  unmapped: ["clarify", "decline"],
};
const DEFAULT_DECISIONS = ["adopt", "decline", "defer"];
const RECOMMENDED: Record<string, string> = {
  adopt: "adopt",
  adopt_when_scale_defined: "defer",
  adopt_with_modification: "defer",
  review_with_house: "decline",
  decline_or_change_vehicle: "decline",
  clarify: "clarify",
  clarify_or_add_issue: "clarify",
};

export function PolicyDifference({ item, streamId, actor, onDone }: { item: PolicyDifferenceItem; streamId: string; actor: string; onDone: () => void }) {
  const options = DECISIONS_FOR[item.difference] ?? DEFAULT_DECISIONS;
  const [choice, setChoice] = useState(options.includes(RECOMMENDED[item.recommendation]) ? RECOMMENDED[item.recommendation] : options[0]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function record() {
    setBusy(true);
    setError(null);
    try {
      await api.recordPolicyDecision(streamId, { issue_id: item.issue_id, decision: choice, decided_by: actor, note: note || undefined });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={`decision-card${item.decision ? " decided" : ""}`}>
      <div className="decision-card-head">
        <strong>{item.title}</strong>
        <span className="chip">{words(item.difference)}</span>
        {item.votes_changed !== null && (
          <span className="chip" title="Expected votes this difference changes on the synthetic meeting sample">
            {item.votes_changed} {item.votes_changed === 1 ? "vote" : "votes"} changed (sample)
          </span>
        )}
      </div>
      {item.changes.length > 0 && (
        <ul className="decision-changes">
          {item.changes.map((c) => (
            <li key={c.field}>
              <code>{c.field}</code>: {fmt(c.house)} → <strong>{fmt(c.client)}</strong>
            </li>
          ))}
        </ul>
      )}
      {item.source && <p className="decision-quote">“{item.source}”</p>}
      {item.question && <p className="help-text">Question for the client: {item.question}</p>}
      {item.flags.map((f) => (
        <p key={f} className="decision-flag">
          {f}
        </p>
      ))}
      <p className="muted">
        Recommendation: <strong>{words(item.recommendation)}</strong>
        {item.recommendation === "adopt_with_modification" &&
          " — this page cannot record the modification yet: defer it here, and record the modification through the API."}
      </p>
      {item.decision ? (
        <p className="decision-made">
          Decided: <strong>{words(item.decision.decision)}</strong> by {item.decision.decided_by}
          {item.decision.note ? ` — ${item.decision.note}` : ""}
        </p>
      ) : (
        <div className="inline-fields decision-controls">
          <select aria-label={`Decision on ${item.title}`} value={choice} onChange={(e) => setChoice(e.target.value)}>
            {options.map((o) => (
              <option key={o} value={o}>
                {words(o)}
              </option>
            ))}
          </select>
          <input aria-label={`Note on ${item.title}`} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button onClick={record} disabled={!actor || busy} title={actor ? undefined : "Enter your name above first"}>
            {busy ? "Recording…" : "Record decision"}
          </button>
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}
