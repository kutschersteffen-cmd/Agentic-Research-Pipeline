import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { ExtractionResultsTable, FinancialsResultsTable } from "../components/ExtractionResults";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { CachedDocumentDetail, CachedDocumentRow, CompanyFinancialsRecord, ExtractionRecord, ReviewDecision, RunManifest } from "../types";

const SUB_TABS = [
  { id: "results", label: "Run results" },
  { id: "parsed", label: "Parsed documents" },
] as const;

export function DataLibrary() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("results");

  return (
    <div className="page">
      <h2>Data Library</h2>
      <p className="help-text">
        Browse everything already stored: results from any past extraction or financials run, and every parsed
        document text this instance has cached -- across all companies and runs, not just the last one you looked at.
      </p>
      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      {sub === "results" && <RunResultsView />}
      {sub === "parsed" && <ParsedDocumentsView />}
    </div>
  );
}

// --- Run results: pick any past extraction/financials run and view it,
// exactly as Extraction.tsx shows a run it just started ---------------------

type RunKind = "extraction" | "financials";

function RunResultsView() {
  const [kind, setKind] = useState<RunKind>("extraction");
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [runId, setRunId] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  const [extractionResults, setExtractionResults] = useState<ExtractionRecord[]>([]);
  const [extractionReviewDecisions, setExtractionReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [financialsResults, setFinancialsResults] = useState<CompanyFinancialsRecord[]>([]);
  const [financialsReviewDecisions, setFinancialsReviewDecisions] = useState<Record<string, ReviewDecision>>({});

  useEffect(() => {
    (async () => {
      const res = (await api.listRuns(kind)) as { runs: RunManifest[] };
      setRuns(res.runs);
      setRunId("");
      setExpanded(null);
      setActiveSource(null);
    })();
  }, [kind]);

  async function loadResults(id: string = runId) {
    if (!id) return;
    setError(null);
    setExpanded(null);
    try {
      if (kind === "extraction") {
        const res = (await api.getExtractionResults(id)) as { results: ExtractionRecord[] };
        setExtractionResults(res.results);
        const decisionsRes = (await api.getExtractionReviewDecisions(id)) as { decisions: Record<string, ReviewDecision> };
        setExtractionReviewDecisions(decisionsRes.decisions);
      } else {
        const res = (await api.getFinancialsResults(id)) as { results: CompanyFinancialsRecord[] };
        setFinancialsResults(res.results);
        const decisionsRes = (await api.getFinancialsReviewDecisions(id)) as { decisions: Record<string, ReviewDecision> };
        setFinancialsReviewDecisions(decisionsRes.decisions);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div>
      <section className="card">
        <label className="field-label">Run type</label>
        <select value={kind} onChange={(e) => setKind(e.target.value as RunKind)}>
          <option value="extraction">Data-point extraction</option>
          <option value="financials">Company financials</option>
        </select>
        <label className="field-label">Run</label>
        <select
          value={runId}
          onChange={(e) => {
            setRunId(e.target.value);
            loadResults(e.target.value);
          }}
        >
          <option value="">Select a run...</option>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id} -- {new Date(r.created_at).toLocaleString()} ({r.completed_count}/{r.company_count} companies)
            </option>
          ))}
        </select>
        {runs.length === 0 && <p className="muted">No {kind} runs recorded yet.</p>}
        {runId && (
          <div className="toolbar">
            <button onClick={() => loadResults()}>Refresh</button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
            <label className="field-label" style={{ marginLeft: "auto" }}>
              Reviewing as
            </label>
            <input
              placeholder="your name"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              style={{ maxWidth: 160 }}
            />
          </div>
        )}
        {error && <p className="error-text">{error}</p>}
      </section>

      {runId && ((kind === "extraction" && extractionResults.length > 0) || (kind === "financials" && financialsResults.length > 0)) && (
        <div className="split-review">
          <div className="split-review-main">
            {kind === "extraction" && (
              <ExtractionResultsTable
                results={extractionResults}
                runId={runId}
                expanded={expanded}
                onToggleExpanded={(companyId) => setExpanded(expanded === companyId ? null : companyId)}
                reviewDecisions={extractionReviewDecisions}
                reviewer={reviewer}
                onReviewDone={() => loadResults()}
                onOpenSource={setActiveSource}
              />
            )}
            {kind === "financials" && (
              <FinancialsResultsTable
                results={financialsResults}
                runId={runId}
                expanded={expanded}
                onToggleExpanded={(companyId) => setExpanded(expanded === companyId ? null : companyId)}
                reviewDecisions={financialsReviewDecisions}
                reviewer={reviewer}
                onReviewDone={() => loadResults()}
                onOpenSource={setActiveSource}
              />
            )}
          </div>
          <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
        </div>
      )}
    </div>
  );
}

// --- Parsed documents: every cached Docling parse this instance holds,
// enriched with company/doc_type/title when the source document is
// registered, with a link back to the original file --------------------

const PAGE_SIZE = 25;

function ParsedDocumentsView() {
  const [rows, setRows] = useState<CachedDocumentRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CachedDocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const res = (await api.listCachedDocuments(offset, PAGE_SIZE)) as { total: number; documents: CachedDocumentRow[] };
      setRows(res.documents);
      setTotal(res.total);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  async function toggleExpand(row: CachedDocumentRow) {
    if (expandedId === row.id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(row.id);
    setDetail(null);
    const res = (await api.getCachedDocumentText(row.id)) as CachedDocumentDetail;
    setDetail(res);
  }

  return (
    <div>
      <section className="card">
        <p className="muted">
          {total} parsed document{total === 1 ? "" : "s"} cached
        </p>
        {error && <p className="error-text">{error}</p>}
      </section>

      <section className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Doc type</th>
              <th>Title</th>
              <th>Size</th>
              <th>Parser</th>
              <th>Cached at</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Fragment key={row.id}>
                <tr className="clickable-row" onClick={() => toggleExpand(row)}>
                  <td>{row.company_id ?? <span className="muted">unregistered</span>}</td>
                  <td>{row.doc_type ?? "—"}</td>
                  <td>{row.title ?? "—"}</td>
                  <td>{row.char_len.toLocaleString()} chars</td>
                  <td>{row.parser_version}</td>
                  <td>{new Date(row.created_at).toLocaleString()}</td>
                </tr>
                {expandedId === row.id && (
                  <tr>
                    <td colSpan={6} className="detail-cell">
                      {row.company_id && row.doc_type && row.filename ? (
                        <p>
                          <a
                            href={api.documentRawUrl(row.company_id, row.doc_type, row.filename)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            view original document
                          </a>
                        </p>
                      ) : (
                        <p className="muted">Source document not separately registered -- showing cached text only.</p>
                      )}
                      {detail === null ? (
                        <p className="muted">Loading...</p>
                      ) : (
                        <pre className="review-json" style={{ maxHeight: 400, overflow: "auto" }}>
                          {detail.full_text}
                        </pre>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="muted">No cached documents yet.</p>}
        <div className="toolbar">
          <button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0}>
            Prev
          </button>
          <span className="muted">
            {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total}>
            Next
          </button>
        </div>
      </section>
    </div>
  );
}
