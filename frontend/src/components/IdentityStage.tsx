import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { api } from "../api/client";
import { RunProgress } from "./RunProgress";
import { ReviewTiles } from "./ReviewTiles";
import { RunReviewList } from "./RunReviewList";
import type { ActiveSource } from "./SourcePanel";
import { UniversePicker } from "./UniversePicker";
import { autoContinueDue, reviewCounts, type FlowAction, type StageHandle, type Handover, type Stage, type StageOutput, type ReviewTileCounts } from "../lib/stagedFlow";
import type { CompanyRef, IdentityResolutionResult, JobStatus, ReviewDecision, RunManifest } from "../types";

const FINAL: JobStatus[] = ["completed", "partially_completed", "failed", "cancelled"];
const HANDOVERS: [Handover, string][] = [["manual", "Manual"], ["auto", "Automatic"], ["skip", "Skip"]];

export function IdentityStage({
  input,
  stage,
  dispatch,
  view,
  reviewer,
  onOpenSource,
  ref,
}: {
  input: StageOutput | null;
  stage: Stage;
  dispatch: (a: FlowAction) => void;
  view: "run" | "review";
  ref?: Ref<StageHandle>;
  reviewer: string;
  onOpenSource: (s: ActiveSource) => void;
}) {
  const [picked, setPicked] = useState<StageOutput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<IdentityResolutionResult[]>([]);
  const [counts, setCounts] = useState<{ pending: number; decisions: ReviewDecision[] }>({ pending: 0, decisions: [] });
  const [tile, setTile] = useState<keyof ReviewTileCounts | null>(null);
  const finishedRef = useRef<string | null>(null);
  const handedRef = useRef<string | null>(null);

  const source = input ?? picked;
  const { runId } = stage;

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getIdentityResults(runId)) as { results: IdentityResolutionResult[] };
    setResults(res.results);
  }

  async function start() {
    if (!source) return;
    setBusy(true);
    setError(null);
    setResults([]);
    try {
      const res = await api.startIdentityRun({ universe_path: source.path });
      dispatch({ type: "runStarted", stage: "identify", runId: res.run_id });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // RunProgress has no status callback, so watch the run here until it ends (a stale stage's run may still be going).
  const watching = stage.state === "running" || (stage.state === "stale" && finishedRef.current !== runId);
  useEffect(() => {
    if (!runId || !watching) return;
    let live = true;
    let timer: number | undefined;
    async function poll() {
      try {
        const m = (await api.getRun(runId!)) as RunManifest;
        if (!live) return;
        if (FINAL.includes(m.status)) {
          if (finishedRef.current !== runId) {
            finishedRef.current = runId;
            dispatch({ type: "runFinished", stage: "identify", status: m.status, flagged: m.review_count, failed: m.failed_count });
          }
          refreshResults().catch(() => {});
          return;
        }
      } catch {
        // keep polling; RunProgress shows the load error
      }
      if (live) timer = window.setTimeout(poll, 2500);
    }
    poll();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, watching]);

  async function carryOn() {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      const companies = (await api.getEnrichedUniverse(runId)).companies as unknown as CompanyRef[];
      if (companies.length === 0) {
        dispatch({ type: "handedOver", stage: "identify", output: { path: "", count: 0, companies } });
        return;
      }
      const res = await api.universeFromCompanies(companies, "identity_resolved");
      dispatch({ type: "handedOver", stage: "identify", output: { path: res.path, count: res.company_count, companies } });
    } catch (err) {
      setError(`Failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  // No deps: the handle always calls this render's start / carryOn.
  useImperativeHandle(ref, () => ({ start, carryOn }));

  const due = autoContinueDue(stage);
  useEffect(() => {
    if (!due || !runId || handedRef.current === runId) return;
    handedRef.current = runId;
    carryOn();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [due, runId]);

  const skipped = stage.handover === "skip";
  const canContinue = !skipped && (stage.state === "ready" || stage.state === "review" || due);

  const footer = (
    <>
      {error && <p className="error-text" role="alert">{error}</p>}
      {stage.note && <p className="status-text">{stage.note}</p>}
      {canContinue && (
        <div className="toolbar">
          <button onClick={carryOn} disabled={busy}>Continue &rarr;</button>
        </div>
      )}
    </>
  );

  if (view === "review") {
    return (
      <div>
        {runId ? (
          <>
            <ReviewTiles counts={reviewCounts(counts.pending, counts.decisions, stage.flagged)} active={tile} onSelect={setTile} />
            <RunReviewList
              kind="identity"
              runId={runId}
              reviewer={reviewer}
              onOpenSource={onOpenSource}
              filter={tile}
              onCounts={(pending, decisions) => setCounts({ pending, decisions })}
            />
          </>
        ) : (
          <p className="muted">Nothing to review yet. Run identity resolution first.</p>
        )}
        {footer}
      </div>
    );
  }

  return (
    <div>
      {!input && <UniversePicker onResolved={(path, count) => setPicked({ path, count })} />}
      <div className="view-toggle" role="group" aria-label="Handover">
        {HANDOVERS.map(([h, label]) => (
          <button key={h} className={stage.handover === h ? "active" : ""} onClick={() => dispatch({ type: "setHandover", stage: "identify", handover: h })}>
            {label}
          </button>
        ))}
      </div>
      {skipped ? (
        <p className="status-text">Skipped — the list passes straight to Documents.</p>
      ) : (
        <button onClick={start} disabled={busy || !source?.path || !source.count || stage.state === "running"}>
          Resolve identity for {source?.count ? `${source.count} companies` : "your companies (upload them first)"}
        </button>
      )}
      {runId && !skipped && (
        <>
          <RunProgress runId={runId} runType="identity" />
          <button onClick={refreshResults}>Refresh results</button>
          {results.length > 0 && (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Verdict</th>
                    <th>Confidence</th>
                    <th>Resolved website</th>
                    <th>Resolved CIK</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.company_id}>
                      <td>{r.input_name}</td>
                      <td>{r.verdict}</td>
                      <td>{r.confidence.toFixed(2)}</td>
                      <td>{r.resolved_website ?? "-"}</td>
                      <td>{r.resolved_cik ?? "-"}</td>
                      <td>
                        {r.flagged_for_review ? (
                          <span className="await-text" title={r.rationale}>
                            Needs review
                          </span>
                        ) : (
                          "ok"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">
            Anything flagged for review must be approved (or edited with a corrected website/CIK) in the Review view before it's included in the list carried forward.
          </p>
        </>
      )}
      {stage.state === "stale" && stage.output && (
        <div className="toolbar">
          <span className="await-text">Inputs changed since this stage ran.</span>
          <button className="secondary" onClick={() => dispatch({ type: "useAnyway", stage: "identify" })}>Use anyway</button>
        </div>
      )}
      {footer}
    </div>
  );
}
