import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfidenceBadge, VerdictBadge } from "../components/ConfidenceBadge";
import { CitationList } from "../components/CitationList";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { Citation, ReviewableRunKind, RunManifest } from "../types";
import { Button, Field, PageHeader, StateBlock } from "../ui";

const REVIEW_KIND_LABEL: Record<ReviewableRunKind, string> = {
  theme: "Thematic universe",
  extraction: "Data-point extraction",
  financials: "Company financials",
  identity: "Identity resolution",
};

const QUEUE_FNS: Record<ReviewableRunKind, (runId: string) => Promise<unknown>> = {
  theme: api.getThemeReviewQueue,
  extraction: api.getExtractionReviewQueue,
  financials: api.getFinancialsReviewQueue,
  identity: api.getIdentityReviewQueue,
};

const SUBMIT_FNS: Record<ReviewableRunKind, (runId: string, body: unknown) => Promise<unknown>> = {
  theme: api.submitThemeReview,
  extraction: api.submitExtractionReview,
  financials: api.submitFinancialsReview,
  identity: api.submitIdentityReview,
};

interface Props {
  pendingReview?: { kind: ReviewableRunKind; runId: string } | null;
}

function isCitationArray(v: unknown): v is Citation[] {
  return Array.isArray(v) && v.every((c) => c && typeof c === "object" && "quote" in c && "doc_type" in c);
}

/** Renders whatever a pending review item happens to carry: the fields
 * every run kind's flagged payload tends to share (item identity, a
 * confidence/verdict, citations) get the same badges/CitationList used
 * everywhere else in the app; anything kind-specific that doesn't map to a
 * known field stays available, just tucked behind "Full record" instead of
 * dominating the card the way a top-level JSON.stringify dump used to. */
function ReviewItemFields({ item, onOpenSource }: { item: Record<string, unknown>; onOpenSource: (s: ActiveSource) => void }) {
  const known = new Set(["item_key", "queued_at", "company_id", "name", "ticker", "confidence", "verdict", "citations", "adjudicator_rationale", "rationale"]);
  const rest = Object.fromEntries(Object.entries(item).filter(([k]) => !known.has(k)));
  const hasRest = Object.keys(rest).length > 0;

  return (
    <div>
      <div className="run-progress-header">
        <strong>
          {(item.name as string | undefined) ?? (item.company_id as string | undefined) ?? (item.item_key as string)}
          {item.ticker ? <span className="muted"> ({item.ticker as string})</span> : null}
        </strong>
        <span>
          {typeof item.verdict === "string" && <VerdictBadge verdict={item.verdict} />}{" "}
          {typeof item.confidence === "number" && <ConfidenceBadge value={item.confidence} />}
        </span>
      </div>
      {Boolean(item.company_id && item.name) && <p className="muted">{item.item_key as string}</p>}
      {Boolean(item.adjudicator_rationale || item.rationale) && <p>{(item.adjudicator_rationale ?? item.rationale) as string}</p>}
      {isCitationArray(item.citations) && (
        <>
          <p className="muted">Citations:</p>
          <CitationList citations={item.citations} onOpenSource={onOpenSource} />
        </>
      )}
      {hasRest && (
        <details className="inline-block">
          <summary className="muted clickable-row">
            Full record
          </summary>
          <pre className="review-json">{JSON.stringify(rest, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

export function ReviewQueue({ pendingReview }: Props = {}) {
  const [kind, setKind] = useState<ReviewableRunKind>(pendingReview?.kind ?? "theme");
  const [runId, setRunId] = useState(pendingReview?.runId ?? "");
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [pending, setPending] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  async function load(loadKind: ReviewableRunKind = kind, loadRunId: string = runId) {
    if (!loadRunId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await QUEUE_FNS[loadKind](loadRunId);
      setPending((res as { pending: Record<string, unknown>[] }).pending);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    setRuns([]);
    api
      .listRuns(kind)
      .then((res) => setRuns((res as { runs: RunManifest[] }).runs))
      .catch(() => setRuns([]));
  }, [kind]);

  // A run clicked from Run History's "Review" link arrives here -- load its
  // queue immediately instead of making the user re-pick the type and
  // re-type/paste the run ID they just came from.
  useEffect(() => {
    if (!pendingReview) return;
    setKind(pendingReview.kind);
    setRunId(pendingReview.runId);
    load(pendingReview.kind, pendingReview.runId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingReview]);

  async function decide(itemKey: string, decision: "approve" | "reject") {
    await SUBMIT_FNS[kind](runId, { item_key: itemKey, decision, reviewer: "ui-user" });
    setPending((prev) => prev.filter((p) => p.item_key !== itemKey));
  }

  const runsWithFlags = runs.filter((r) => r.review_count > 0);

  return (
    <div className="page">
      <PageHeader
        title="Review Queue"
        description={
          <>
            Every low-confidence verdict, ungrounded citation, or "uncertain" call lands here instead of the trusted
            output. Nothing flagged is included in exports until a human approves it.
          </>
        }
      />

      <section className="card">
        <Field label="Run type">
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as ReviewableRunKind);
              setRunId("");
              setPending([]);
            }}
          >
            {(Object.keys(REVIEW_KIND_LABEL) as ReviewableRunKind[]).map((k) => (
              <option key={k} value={k}>
                {REVIEW_KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Run">
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            <option value="">-- select a run --</option>
            {runsWithFlags.length > 0 && (
              <optgroup label="Has flagged items">
                {runsWithFlags.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} -- {r.review_count} flagged ({r.status})
                  </option>
                ))}
              </optgroup>
            )}
            <optgroup label="All runs">
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} -- {r.review_count} flagged ({r.status})
                </option>
              ))}
            </optgroup>
          </select>
        </Field>
        {runs.length === 0 && <StateBlock kind="empty" message={<>No {REVIEW_KIND_LABEL[kind].toLowerCase()} runs found.</>} />}

        <Button onClick={() => load()} disabled={busy || !runId}>
          Load pending items
        </Button>
        {error && <StateBlock kind="error" message={error} />}
      </section>

      {pending.length > 0 && (
        <div className="split-review">
          <div className="split-review-main">
            <section className="card">
              <h3>{pending.length} pending</h3>
              {pending.map((item) => (
                <div className="review-item" key={item.item_key as string}>
                  <ReviewItemFields item={item} onOpenSource={setActiveSource} />
                  <div className="toolbar">
                    <Button onClick={() => decide(item.item_key as string, "approve")}>Approve</Button>
                    <Button variant="danger" onClick={() => decide(item.item_key as string, "reject")}>
                      Reject
                    </Button>
                  </div>
                </div>
              ))}
            </section>
          </div>
          <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
        </div>
      )}
      {pending.length === 0 && runId && !busy && <p className="muted">Nothing pending for this run.</p>}
    </div>
  );
}
