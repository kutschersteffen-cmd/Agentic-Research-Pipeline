import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { ExtractionResultsTable, FieldDetail, FinancialsResultsTable, SegmentDetail, SpendDetail } from "../components/ExtractionResults";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type {
  CachedDocumentDetail,
  CachedDocumentRow,
  CompanyDirectoryEntry,
  CompanyDocumentRow,
  CompanyFinancialsRecord,
  ExtractionRecord,
  ReviewDecision,
  RunManifest,
} from "../types";
import { DATA_LIBRARY_TABS as SUB_TABS } from "../nav";
import { useSubTab } from "../router";
import { Button, Field, PageHeader, StateBlock, TabPanel, Tabs } from "../ui";

export function DataLibrary() {
  const [sub, setSub] = useSubTab(SUB_TABS, "results");

  return (
    <div className="page">
      <PageHeader
        title="Data Library"
        description={
          <>
            Browse everything already stored: results from any past extraction or financials run, and every parsed
            document text this instance has cached -- across all companies and runs, not just the last one you looked at.
          </>
        }
      />
      <Tabs
        id="library"
        tabs={SUB_TABS}
        active={sub}
        onChange={(id) => setSub(id as typeof sub)}
        label="Data library view"
      />
      <TabPanel id="library" active={sub}>
        {sub === "results" && <RunResultsView />}
        {sub === "by_company" && <CompanyResultsView />}
        {sub === "parsed" && <ParsedDocumentsView />}
      </TabPanel>
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
        <Field label="Run type">
          <select value={kind} onChange={(e) => setKind(e.target.value as RunKind)}>
            <option value="extraction">Data-point extraction</option>
            <option value="financials">Company financials</option>
          </select>
        </Field>
        <Field label="Run">
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
        </Field>
        {runs.length === 0 && <StateBlock kind="empty" message={<>No {kind} runs recorded yet.</>} />}
        {runId && (
          <div className="toolbar">
            <Button onClick={() => loadResults()}>Refresh</Button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
            <Field label="Reviewing as" className="field-inline field-push">
              <input placeholder="your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </Field>
          </div>
        )}
        {error && <StateBlock kind="error" message={error} />}
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

// --- By company: every result this one company has ever had, across
// every run of a type (not just the latest) -- read-only (review actions
// stay on Run results / Review Queue, which are already scoped to one run
// each; a single company's rows here can span several runs at once) ------

function CompanyResultsView() {
  const [kind, setKind] = useState<RunKind>("extraction");
  const [companies, setCompanies] = useState<CompanyDirectoryEntry[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [extractionRecords, setExtractionRecords] = useState<ExtractionRecord[]>([]);
  const [financialsRecords, setFinancialsRecords] = useState<CompanyFinancialsRecord[]>([]);
  const [documents, setDocuments] = useState<CompanyDocumentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  useEffect(() => {
    (async () => {
      const res = (await api.listKnownCompanies(kind)) as { companies: CompanyDirectoryEntry[] };
      setCompanies(res.companies);
      setCompanyId("");
      setExtractionRecords([]);
      setFinancialsRecords([]);
      setDocuments([]);
      setActiveSource(null);
    })();
  }, [kind]);

  async function load(id: string) {
    if (!id) return;
    setError(null);
    try {
      if (kind === "extraction") {
        const res = (await api.getExtractionResultsForCompany(id)) as { results: ExtractionRecord[] };
        setExtractionRecords(res.results);
      } else {
        const res = (await api.getFinancialsResultsForCompany(id)) as { results: CompanyFinancialsRecord[] };
        setFinancialsRecords(res.results);
      }
      const docsRes = (await api.listDocuments(id)) as { documents: CompanyDocumentRow[] };
      setDocuments(docsRes.documents);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div>
      <section className="card">
        <Field label="Run type">
          <select value={kind} onChange={(e) => setKind(e.target.value as RunKind)}>
            <option value="extraction">Data-point extraction</option>
            <option value="financials">Company financials</option>
          </select>
        </Field>
        <Field label="Company">
          <select
            value={companyId}
            onChange={(e) => {
              setCompanyId(e.target.value);
              load(e.target.value);
            }}
          >
            <option value="">Select a company...</option>
            {companies.map((c) => (
              <option key={c.company_id} value={c.company_id}>
                {c.name ?? c.company_id}{c.ticker ? ` (${c.ticker})` : ""} -- {c.company_id}
              </option>
            ))}
          </select>
        </Field>
        {companies.length === 0 && <StateBlock kind="empty" message={<>No {kind} results recorded for any company yet.</>} />}
        {error && <StateBlock kind="error" message={error} />}
      </section>

      {companyId && documents.length > 0 && (
        <section className="card">
          <h3>Source documents on file</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Doc type</th>
                  <th>File</th>
                  <th>Size</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d, i) => (
                  <tr key={i}>
                    <td>{d.doc_type}</td>
                    <td>
                      <a href={api.documentRawUrl(companyId, d.doc_type, d.filename)} target="_blank" rel="noreferrer">
                        {d.filename}
                      </a>
                    </td>
                    <td>{Math.round(d.size_bytes / 1024)} KB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {companyId && kind === "extraction" && extractionRecords.length === 0 && (
        <StateBlock kind="empty" message="No extraction results recorded for this company yet." />
      )}
      {companyId && (extractionRecords.length > 0 || financialsRecords.length > 0) && (
        <div className="split-review">
          <div className="split-review-main">
            {kind === "extraction" &&
              extractionRecords.map((r) => (
                <section className="card" key={r.run_id}>
                  <h3>Run {r.run_id} -- {new Date(r.generated_at).toLocaleString()}</h3>
                  <p>
                    <ConfidenceBadge value={r.overall_confidence} /> {r.needs_review && <span className="badge badge-low">needs review</span>}
                  </p>
                  {r.fields.map((f) => (
                    <FieldDetail key={f.field_id} field={f} onOpenSource={setActiveSource} />
                  ))}
                </section>
              ))}

            {kind === "financials" &&
              financialsRecords.map((r) => (
                <section className="card" key={r.run_id}>
                  <h3>Run {r.run_id} -- {new Date(r.generated_at).toLocaleString()}</h3>
                  <p>
                    <ConfidenceBadge value={r.overall_confidence} /> {r.needs_review && <span className="badge badge-low">needs review</span>}
                  </p>
                  <h4>Business Segments</h4>
                  {r.segments.length === 0 && <StateBlock kind="empty" message="No segment reporting evidence found." />}
                  {r.segments.map((s, si) => (
                    <SegmentDetail key={si} segment={s} onOpenSource={setActiveSource} />
                  ))}
                  <h4>CapEx</h4>
                  <SpendDetail label="CapEx" spend={r.capex} onOpenSource={setActiveSource} />
                  <h4>R&amp;D</h4>
                  <SpendDetail label="R&D" spend={r.rnd} onOpenSource={setActiveSource} />
                </section>
              ))}
          </div>
          <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
        </div>
      )}

      {companyId && kind === "financials" && financialsRecords.length === 0 && (
        <StateBlock kind="empty" message="No financials results recorded for this company yet." />
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
        {error && <StateBlock kind="error" message={error} />}
      </section>

      <section className="card">
        <div className="table-wrap">
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
                          <StateBlock kind="loading" />
                        ) : (
                          <pre className="review-json scroll-box">
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
        </div>
        {rows.length === 0 && <StateBlock kind="empty" message="No cached documents yet." />}
        <div className="toolbar">
          <Button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0}>
            Prev
          </Button>
          <span className="muted">
            {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <Button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total}>
            Next
          </Button>
        </div>
      </section>
    </div>
  );
}
