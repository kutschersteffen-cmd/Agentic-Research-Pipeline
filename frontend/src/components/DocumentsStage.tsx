import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { api } from "../api/client";
import { RunProgress } from "./RunProgress";
import { ReviewTiles } from "./ReviewTiles";
import { DocumentUpload } from "./DocumentUpload";
import { UniversePicker } from "./UniversePicker";
import {
  autoContinueDue,
  docList,
  docRows,
  type CompanyDocs,
  type DocListRow,
  flagReason,
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
const PAGE = 1000;

/** Every discovery result of a run, paged by the endpoint's `total`. */
async function allResults(runId: string): Promise<DiscoveryCompanyResult[]> {
  const all: DiscoveryCompanyResult[] = [];
  for (;;) {
    const res = (await api.getDiscoveryResults(runId, all.length, PAGE)) as { total: number; results: DiscoveryCompanyResult[] };
    all.push(...res.results);
    if (res.results.length === 0 || all.length >= res.total) return all;
  }
}

/** Full company records plus on-disk file counts for a list, in one readiness call. */
async function readiness(body: { companies: CompanyRef[] } | { universe_path: string }) {
  const res = await api.documentReadiness(body);
  const records = new Map<string, CompanyRef>([...res.ready.map(({ readiness: _r, ...c }) => c), ...res.onboard].map((c) => [c.company_id, c]));
  const companies = Object.keys(res.readiness).flatMap((id) => records.get(id) ?? []);
  // Registered counts EDGAR filings, which are stored without a file in the company folder.
  const onDisk = Object.fromEntries(Object.entries(res.readiness).map(([id, r]) => [id, Math.max(r.on_disk, r.registered)]));
  return { companies, onDisk };
}

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
  const [companies, setCompanies] = useState<CompanyRef[]>([]);
  const [results, setResults] = useState<DiscoveryCompanyResult[]>([]);
  const [onDisk, setOnDisk] = useState<Record<string, number>>({});
  const [uploaded, setUploaded] = useState<Set<string>>(new Set());
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [tile, setTile] = useState<keyof ReviewTileCounts | null>(null);
  const [docs, setDocs] = useState<Record<string, DocListRow[]>>({});
  const finishedRef = useRef<string | null>(null);
  const loadedRef = useRef<string | null>(null);
  const handedRef = useRef<string | null>(null);
  const uploadedRef = useRef(uploaded);
  uploadedRef.current = uploaded;

  const source = input ?? picked;
  const { runId } = stage;
  const rows = docRows(companies, results, onDisk, uploaded);
  const isTicked = (r: DocRow) => decisions[r.companyId] ?? !r.flagged;

  /** Loads the input list with its on-disk counts and every discovery result. Returns the flagged count. */
  async function load(id: string): Promise<number> {
    const [list, res] = await Promise.all([
      source ? readiness(input?.companies ? { companies: input.companies } : { universe_path: source.path }) : null,
      allResults(id),
    ]);
    // No source (e.g. its upstream stage was rerun): fall back to the companies the run reported.
    const cos = list?.companies ?? res.map((r) => ({ company_id: r.company_id, name: r.name }));
    setCompanies(cos);
    setResults(res);
    setOnDisk(list?.onDisk ?? {});
    setLoadedFor(id);
    // ponytail: one request per company; batch the endpoint if lists grow past a few hundred
    const foundBy = new Map(res.map((r) => [r.company_id, r.documents_found]));
    Promise.all(cos.map(async (c) => [c.company_id, docList((await api.listDocuments(c.company_id)) as CompanyDocs, foundBy.get(c.company_id))] as const))
      .then((pairs) => setDocs(Object.fromEntries(pairs)))
      .catch((err) => setError(`Couldn't list the documents: ${(err as Error).message}`));
    return docRows(cos, res, list?.onDisk ?? {}, uploadedRef.current).filter((r) => r.flagged).length;
  }

  async function start() {
    if (!source) return;
    setBusy(true);
    setError(null);
    setCompanies([]);
    setResults([]);
    setOnDisk({});
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
            loadedRef.current = runId;
            try {
              const flagged = await load(runId!);
              dispatch({ type: "runFinished", stage: "documents", status: m.status, flagged, failed: m.failed_count });
            } catch (err) {
              setError(`Couldn't load results: ${(err as Error).message}`);
              dispatch({ type: "runFinished", stage: "documents", status: m.status, flagged: 0, failed: 0, note: "Couldn't check documents" });
            }
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
  }, [runId, watching]);

  // A remount (or switching back to a finished run) still shows the results.
  useEffect(() => {
    if (!runId || !FINISHED.includes(stage.state) || loadedRef.current === runId) return;
    loadedRef.current = runId;
    load(runId).catch((err) => setError(`Couldn't load results: ${(err as Error).message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, stage.state]);

  async function onUploaded(id: string) {
    setUploaded((u) => new Set(u).add(id));
    const company = companies.find((c) => c.company_id === id);
    if (!company) return;
    try {
      const { onDisk: fresh } = await readiness({ companies: [company] });
      setOnDisk((o) => ({ ...o, ...fresh }));
      const listed = docList((await api.listDocuments(id)) as CompanyDocs, results.find((r) => r.company_id === id)?.documents_found);
      setDocs((d) => ({ ...d, [id]: listed }));
    } catch (err) {
      setError(`Couldn't re-check documents: ${(err as Error).message}`);
    }
  }

  async function carryOn() {
    setBusy(true);
    setError(null);
    try {
      const keep = new Set(rows.filter(isTicked).map((r) => r.companyId));
      const kept = companies.filter((c) => keep.has(c.company_id));
      if (kept.length === 0) {
        setError("No company is ticked. Tick the companies to keep in the Review view, or upload a document for them.");
        return;
      }
      const res = await api.universeFromCompanies(kept, "documents_ready");
      dispatch({ type: "handedOver", stage: "documents", output: { path: res.path, count: res.company_count, companies: kept } });
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
          <button onClick={carryOn} disabled={busy}>
            {busy ? "Handing over…" : `Continue with ${rows.filter(isTicked).length} of ${rows.length} →`}
          </button>
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
        <button onClick={start} disabled={busy || !source?.path || !source.count || stage.state === "running"}>
          Search for documents across {source?.count ? `${source.count} companies` : "your companies (upload them first)"}
        </button>
      )}
      {runId && !skipped && (
        <>
          <RunProgress runId={runId} runType="discovery" />
          {companies.length > 0 && <DocumentUpload companies={companies} onUploaded={onUploaded} />}
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
                      <td>{docs[r.companyId]?.length ?? r.onFile}</td>
                      <td>{r.flagged ? <span className="await-text">{flagReason(r)}</span> : marker(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {runId && !skipped && rows.length > 0 && (
        <>
          <h3>Documents found</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Document</th>
                  <th>Type</th>
                  <th>Format</th>
                  <th>Source</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {rows.flatMap((r) => {
                  const list = docs[r.companyId];
                  if (!list) return [<tr key={r.companyId}><td>{r.name}</td><td colSpan={5} className="muted">Loading…</td></tr>];
                  if (!list.length) return [<tr key={r.companyId}><td>{r.name}</td><td colSpan={5} className="await-text">No documents</td></tr>];
                  return list.map((d, i) => (
                    <tr key={`${r.companyId}/${d.key}`}>
                      <td>{i === 0 ? r.name : ""}</td>
                      <td>
                        {d.url ? (
                          <a href={d.url} target="_blank" rel="noreferrer">{d.title}</a>
                        ) : d.filename ? (
                          <a href={api.documentRawUrl(r.companyId, d.docType, d.filename)} target="_blank" rel="noreferrer">{d.title}</a>
                        ) : (
                          d.title
                        )}
                      </td>
                      <td>{d.docType.replaceAll("_", " ")}</td>
                      <td className="mono">{d.format}</td>
                      <td>{d.source}</td>
                      <td className="mono">{d.date ? d.date.slice(0, 10) : "—"}</td>
                    </tr>
                  ));
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {stage.state === "stale" && stage.output && (
        <div className="toolbar">
          <span className="await-text">Inputs changed since this stage ran.</span>
          <button className="secondary" onClick={() => dispatch({ type: "useAnyway", stage: "documents" })}>Use anyway</button>
        </div>
      )}
      {footer}
    </div>
  );
}
