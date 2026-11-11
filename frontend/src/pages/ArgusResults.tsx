import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { FileLink } from "../components/FileLink";
import { ReviewControls, decisionLabel } from "../components/ReviewControls";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { onlyNeedsYou, resultRows, type ResultRow } from "../lib/argusFlow";
import type { ArgusFlow as Flow, ExtractionRecord, ReviewDecision, ReviewItem } from "../types";

const VALUE_LABELS = { approve: "Approve", correct: "Edit", reject: "Reject" } as const;
// A not-found value is either right (approve: confirmed not disclosed) or wrong (correct: the value the source gives).
const NOT_FOUND_LABELS = { approve: "Confirm not disclosed", correct: "Enter value" } as const;
const CONFLICT_LABELS = { reject: "Keep accepted", approve: "Accept new" } as const;
const PAGE = 500;

/** Every result of the run: the endpoint returns at most a page at a time, and a flow may hold thousands of companies. */
async function allResults(runId: string): Promise<ExtractionRecord[]> {
  const out: ExtractionRecord[] = [];
  for (;;) {
    const page = (await api.getExtractionResults(runId, out.length, PAGE)) as { total: number; results: ExtractionRecord[] };
    out.push(...page.results);
    if (page.results.length === 0 || out.length >= page.total) return out;
  }
}

/** Step 5: every value of the flow's run with its decision; what needs a person first, decided in place. */
export function ArgusResults({ flow }: { flow: Flow }) {
  const runId = flow.run_id!;
  const [rows, setRows] = useState<ResultRow[] | null>(null);
  const [decisions, setDecisions] = useState<Record<string, ReviewDecision>>({});
  const [mineOnly, setMineOnly] = useState(false);
  const [source, setSource] = useState<ActiveSource | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [results, open, review] = await Promise.all([
        allResults(runId),
        api.listReviewItems(runId),
        api.getExtractionReviewDecisions(runId) as Promise<{ decisions: Record<string, ReviewDecision> }>,
      ]);
      // shortcut: Financials and TNFD records have no per-field rows here; their values are reviewed in the Review Queue until a later slice
      setRows(resultRows(results.filter((r) => Array.isArray(r.fields)), open.items as ReviewItem[]));
      setDecisions(review.decisions);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [runId]);
  useEffect(() => {
    void load();
  }, [load]);

  if (!rows) return error ? <p className="error-text" role="alert">{error}</p> : <p className="muted" role="status">Loading…</p>;
  const shown = mineOnly ? onlyNeedsYou(rows) : rows;
  const open = (r: ResultRow) => {
    const c = r.citation!;
    setSource({
      title: `${c.source_filename}${c.page ? ` — p. ${c.page}` : ""}`,
      src: `${api.documentRawUrl(c.company_id!, c.doc_type, c.source_filename!)}${c.page ? `#page=${c.page}` : ""}`,
      quote: c.quote,
      page: c.page, // the cited page as an image, the quote boxed on it
    });
  };

  return (
    <section className="argus-results" aria-label="Results">
      <div className="argus-results-head">
        <label className="argus-mine">
          <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} /> Only what needs me
        </label>
        <FileLink className="button-link" url={api.exportRunCsvUrl(runId)} name={`${runId}.csv`}>Download CSV</FileLink>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data-table stack-on-phone" aria-label="Extracted values">
          <thead>
            <tr>
              <th scope="col">Company</th>
              <th scope="col">Field</th>
              <th scope="col">Value</th>
              <th scope="col">Source</th>
              <th scope="col">Decision</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.key} className={r.item ? "argus-row-await" : undefined}>
                <td data-label="Company">{r.company}</td>
                <td data-label="Field">{r.field}</td>
                <td data-label="Value">
                  {r.accepted !== undefined ? <>Accepted: {r.accepted}<br />New: {r.value}</> : r.value}
                </td>
                <td data-label="Source">
                  {r.citation?.company_id && r.citation.source_filename ? (
                    <button type="button" className="link-button" onClick={() => open(r)}>
                      {r.citation.page ? `p. ${r.citation.page}` : r.citation.source_filename}
                    </button>
                  ) : "—"}
                </td>
                <td data-label="Decision">
                  {r.item ? (
                    <ReviewControls
                      runId={runId}
                      itemKey={r.key}
                      item={r.item}
                      onDone={() => void load()}
                      onOpenSource={setSource}
                      labels={r.companyLevel ? undefined : r.accepted !== undefined ? CONFLICT_LABELS : r.notFound ? NOT_FOUND_LABELS : VALUE_LABELS}
                      choices={r.companyLevel ? undefined : r.accepted !== undefined ? ["reject", "approve"]
                        : r.notFound ? ["approve", "correct"] : ["approve", "correct", "reject"]}
                    />
                  ) : decisions[r.key] ? decisionLabel(decisions[r.key]) : "No review needed"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <p className="muted">{mineOnly ? "Nothing waits on you in this run." : "This run has no values yet."}</p>}
      {source && <SourcePanel source={source} onClose={() => setSource(null)} />}
    </section>
  );
}
