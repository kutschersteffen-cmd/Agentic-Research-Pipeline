import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { api } from "../api/client";
import { RunProgress } from "./RunProgress";
import { ReviewTiles } from "./ReviewTiles";
import { DocumentUpload } from "./DocumentUpload";
import { UniversePicker } from "./UniversePicker";
import {
  autoContinueDue,
  companiesToCheck,
  docRows,
  type DocRow,
  type FlowAction,
  type StageHandle,
  type Handover,
  type ReviewTileCounts,
  type Stage,
  type StageOutput,
} from "../lib/stagedFlow";
import type { CompanyRef, DiscoveryCompanyResult, JobStatus, RunManifest } from "../types";

const FINAL: JobStatus[] = ["completed", "partially_completed", "failed", "cancelled"];
const FINISHED = ["review", "ready", "done", "stale", "failed"];
const HANDOVERS: [Handover, string][] = [["manual", "Manual"], ["auto", "Automatic"], ["skip", "Skip"]];

const marker = (r: DocRow) => (r.flagged ? "None" : r.uploaded ? "Uploaded" : "Discovered");

export function DocumentsStage({
  input,
  stage,
  dispatch,
  view,
  ref,
}: {
  input: StageOutput | null;
  stage: Stage;
  dispatch: (a: FlowAction) => void;
  view: "run" | "review";
  ref?: Ref<StageHandle>;
}) {
  const [picked, setPicked] = useState<StageOutput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<DiscoveryCompanyResult[]>([]);
  const [onFile, setOnFile] = useState<Record<string, number>>({});
  const [uploaded, setUploaded] = useState<Set<string>>(new Set());
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [tile, setTile] = useState<keyof ReviewTileCounts | null>(null);
  const finishedRef = useRef<string | null>(null);
  const loadedRef = useRef<string | null>(null);
  const handedRef = useRef<string | null>(null);
  const uploadedRef = useRef(uploaded);
  uploadedRef.current = uploaded;

  const source = input ?? picked;
  const { runId } = stage;
  const rows = docRows(results, onFile, uploaded);
  const isTicked = (r: DocRow) => decisions[r.companyId] ?? !r.flagged;

  async function checkFiles(ids: string[]) {
    const entries = await Promise.all(
      ids.map(async (id) => {
        const res = (await api.listDocuments(id)) as { documents: unknown[] };
        return [id, res.documents.length] as const;
      }),
    );
    setOnFile((o) => ({ ...o, ...Object.fromEntries(entries) }));
    return Object.fromEntries(entries);
  }

  /** Loads discovery results, then checks stored files for companies that found none. Returns the flagged count. */
  async function load(id: string): Promise<number> {
    const res = (await api.getDiscoveryResults(id)) as { results: DiscoveryCompanyResult[] };
    setResults(res.results);
    const files = await checkFiles(companiesToCheck(res.results, uploadedRef.current));
    setLoadedFor(id);
    return docRows(res.results, files, uploadedRef.current).filter((r) => r.flagged).length;
  }

  async function start() {
    if (!source) return;
    setBusy(true);
    setError(null);
    setResults([]);
    setOnFile({});
    setUploaded(new Set());
    setDecisions({});
    setLoadedFor(null);
    try {
      const res = await api.startDiscoveryRun({ universe_path: source.path });
      dispatch({ type: "runStarted", stage: "documents", runId: res.run_id });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // RunProgress has no status callback, so watch the run here until it ends.
  useEffect(() => {
    if (!runId || stage.state !== "running") return;
    let live = true;
    let timer: number | undefined;
    async function poll() {
      try {
        const m = (await api.getRun(runId!)) as RunManifest;
        if (!live) return;
        if (FINAL.includes(m.status)) {
          if (finishedRef.current !== runId) {
            finishedRef.current = runId;
            loadedRef.current = runId;
            let flagged = 0;
            try {
              flagged = await load(runId!);
            } catch (err) {
              setError(`Couldn't load results: ${(err as Error).message}`);
            }
            dispatch({ type: "runFinished", stage: "documents", status: m.status, flagged, failed: m.failed_count });
          }
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
  }, [runId, stage.state]);

  // A remount (or switching back to a finished run) still shows the results.
  useEffect(() => {
    if (!runId || !FINISHED.includes(stage.state) || loadedRef.current === runId) return;
    loadedRef.current = runId;
    load(runId).catch((err) => setError(`Couldn't load results: ${(err as Error).message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, stage.state]);

  async function onUploaded(id: string) {
    setUploaded((u) => new Set(u).add(id));
    try {
      await checkFiles([id]);
    } catch (err) {
      setError(`Couldn't re-check documents: ${(err as Error).message}`);
    }
  }

  async function carryOn() {
    setBusy(true);
    setError(null);
    try {
      const keep = new Set(rows.filter(isTicked).map((r) => r.companyId));
      const companies: CompanyRef[] = input?.companies
        ? input.companies.filter((c) => keep.has(c.company_id))
        : rows.filter(isTicked).map((r) => ({ company_id: r.companyId, name: r.name }));
      if (companies.length === 0) {
        dispatch({ type: "handedOver", stage: "documents", output: { path: "", count: 0, companies } });
        return;
      }
      const res = await api.universeFromCompanies(companies, "documents_ready");
      dispatch({ type: "handedOver", stage: "documents", output: { path: res.path, count: res.company_count, companies } });
    } catch (err) {
      setError(`Failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  // No deps: the handle always calls this render's start / carryOn.
  useImperativeHandle(ref, () => ({ start, carryOn }));

  const due = autoContinueDue(stage) && runId != null && loadedFor === runId;
  useEffect(() => {
    if (!due || !runId || handedRef.current === runId) return;
    handedRef.current = runId;
    carryOn();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [due, runId]);

  const skipped = stage.handover === "skip";
  const canContinue = !skipped && (stage.state === "ready" || stage.state === "review" || autoContinueDue(stage));

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
    const flaggedRows = rows.filter((r) => r.flagged);
    const counts: ReviewTileCounts = {
      pending: flaggedRows.filter((r) => decisions[r.companyId] === undefined).length,
      approved: rows.filter(isTicked).length,
      edited: 0,
      rejected: rows.filter((r) => !isTicked(r)).length,
      flagged: flaggedRows.length,
    };
    const shown = rows.filter((r) => {
      if (tile === "pending") return r.flagged && decisions[r.companyId] === undefined;
      if (tile === "approved") return isTicked(r);
      if (tile === "rejected") return !isTicked(r);
      if (tile === "flagged") return r.flagged;
      return tile !== "edited";
    });
    return (
      <div>
        {rows.length > 0 ? (
          <>
            <ReviewTiles counts={counts} active={tile} onSelect={setTile} />
            <ul className="plain-list">
              {shown.map((r) => (
                <li key={r.companyId}>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={isTicked(r)}
                      onChange={(e) => setDecisions((d) => ({ ...d, [r.companyId]: e.target.checked }))}
                    />
                    {r.name} <span className={r.flagged ? "await-text" : "muted"}>{marker(r)}</span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">Nothing to review yet. Run document discovery first.</p>
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
          <button key={h} className={stage.handover === h ? "active" : ""} onClick={() => dispatch({ type: "setHandover", stage: "documents", handover: h })}>
            {label}
          </button>
        ))}
      </div>
      {skipped ? (
        <p className="status-text">Skipped — the list passes straight to Extract.</p>
      ) : (
        <button onClick={start} disabled={busy || !source || stage.state === "running"}>
          Search for documents across {source?.count ? `${source.count} companies` : "your companies (upload them first)"}
        </button>
      )}
      {runId && !skipped && (
        <>
          <RunProgress runId={runId} runType="discovery" />
          {results.length > 0 && <DocumentUpload companies={results.map((r) => ({ company_id: r.company_id, name: r.name }))} onUploaded={onUploaded} />}
          {rows.length > 0 && (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Documents</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.companyId}>
                      <td>{r.name}</td>
                      <td>{r.onFile}</td>
                      <td>{r.flagged ? <span className="await-text">{marker(r)}</span> : marker(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {footer}
    </div>
  );
}
