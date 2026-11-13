import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { FileLink } from "../components/FileLink";
import { ReviewControls, decisionLabel } from "../components/ReviewControls";
import { RunScoringPanel } from "../components/RunScoring";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { WalkthroughLink } from "../components/WalkthroughLink";
import { TRANSITION_PLAN_TEMPLATE, keptRuns, notInRun, onlyNeedsYou, periodText, resultRows, walkTalkLine, type ResultRow } from "../lib/argusFlow";
import { errorDetail } from "../lib/barrier";
import type { ArgusFlow as Flow, DataPointSchema, ExtractionRecord, ReviewDecision, ReviewItem, TransitionPlanIndicatorDef } from "../types";

const VALUE_LABELS = { approve: "Approve", correct: "Edit", reject: "Reject" } as const;
// A not-found value is either right (approve: confirmed not disclosed) or wrong (correct: the value the source gives).
const NOT_FOUND_LABELS = { approve: "Confirm not disclosed", correct: "Enter value" } as const;
const CONFLICT_LABELS = { reject: "Keep accepted", approve: "Accept new" } as const;
const PAGE = 500;

/** A result row and the run it is reviewed in; `kept` is the date of the earlier run a skipped company's values come from. */
type Row = ResultRow & { runId: string; kept?: string };

/** One run's value rows, its records and its decisions. */
async function runRows(runId: string): Promise<{ rows: ResultRow[]; records: ExtractionRecord[]; decisions: Record<string, ReviewDecision> }> {
  const [results, open, review] = await Promise.all([
    allResults(runId),
    api.listReviewItems(runId),
    api.getExtractionReviewDecisions(runId) as Promise<{ decisions: Record<string, ReviewDecision> }>,
  ]);
  // shortcut: Financials and TNFD records have no per-field rows here; their values are reviewed in the Review Queue until a later slice
  return { rows: resultRows(results.filter((r) => Array.isArray(r.fields)), open.items as ReviewItem[]), records: results, decisions: review.decisions };
}

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
  const [rows, setRows] = useState<Row[] | null>(null);
  const [inRun, setInRun] = useState<Set<string>>(new Set());
  const [decisions, setDecisions] = useState<Record<string, Record<string, ReviewDecision>>>({});
  const [mineOnly, setMineOnly] = useState(false);
  const [source, setSource] = useState<ActiveSource | null>(null);
  const [error, setError] = useState("");
  const [records, setRecords] = useState<ExtractionRecord[]>([]);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);
  const [indicators, setIndicators] = useState<TransitionPlanIndicatorDef[] | null>(null);
  const choice = flow.schema_choice;
  const transitionPlan = choice?.kind === "schema" && choice.schema_id === TRANSITION_PLAN_TEMPLATE;

  useEffect(() => {
    if (choice?.kind !== "schema" || !choice.schema_id || !choice.version) return;
    api.getSchema(choice.schema_id, choice.version).then(setSchema, () => setSchema(null));
    if (transitionPlan) api.getTransitionPlanIndicators().then(setIndicators, () => setIndicators(null));
  }, [choice?.kind, choice?.schema_id, choice?.version, transitionPlan]);

  const kept = keptRuns(flow.companies, flow.repeat, flow.repeat_rows);
  const keptKey = JSON.stringify(kept);
  const load = useCallback(async () => {
    try {
      const earlier = JSON.parse(keptKey) as typeof kept;
      // a company set to "Skip, keep earlier results" has its values in its earlier run, and is reviewed there;
      // each earlier run is read once, however many of its companies are kept
      const runs = [...new Set(earlier.map((k) => k.run_id))];
      const [current, ...keptRows] = await Promise.all([runRows(runId), ...runs.map((id) => runRows(id))]);
      const keptFrom = new Map(earlier.map((k) => [`${k.run_id}/${k.company_id}`, k.date]));
      const all: Row[] = [
        ...current.rows.map((r) => ({ ...r, runId })),
        ...keptRows.flatMap((k, i) => k.rows.flatMap((r) => {
          const date = keptFrom.get(`${runs[i]}/${r.companyId}`);
          return date ? [{ ...r, runId: runs[i], kept: date }] : [];
        })),
      ];
      setRows([...all.filter((r) => r.item), ...all.filter((r) => !r.item)]);
      setInRun(new Set(current.records.map((r) => r.company_id)));
      setRecords(current.records.filter((r) => Array.isArray(r.fields)));
      setDecisions(Object.fromEntries([[runId, current.decisions], ...keptRows.map((k, i) => [runs[i], k.decisions])]));
    } catch (e) {
      setError(errorDetail(e as Error));
    }
  }, [runId, keptKey]);
  useEffect(() => {
    void load();
  }, [load]);
  // the viewer opens below the table: bring it into view, or the click looks like it did nothing
  useEffect(() => {
    if (source) document.querySelector(".argus-results .source-panel")?.scrollIntoView({ block: "nearest" });
  }, [source]);

  if (!rows) return error ? <p className="error-text" role="alert">{error}</p> : <p className="muted" role="status">Loading…</p>;
  const shown = mineOnly ? onlyNeedsYou(rows) : rows;
  // the transition-plan template's field names are indicator ids: its question says what was asked
  const question = new Map(transitionPlan ? (schema?.fields ?? []).map((f) => [f.name, f.description]) : []);
  const missing = notInRun(flow.companies, inRun, flow.repeat, flow.repeat_rows);
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
      {missing.length > 0 && (
        <p className="muted" role="note">
          This run covers {flow.companies.length - missing.length} of {flow.companies.length} companies. Not in it:{" "}
          {missing.map((m, i) => (
            <span key={m.name}>
              {i > 0 && ", "}
              {m.name}
              {m.earlier && (
                <>
                  {" "}(kept from the extraction of {m.earlier.date}, <a href={`#/review/extraction/${m.earlier.run_id}`}>open</a>)
                </>
              )}
            </span>
          ))}
          . To extract a missing company, go back to step 3; a draft schema runs on one company until it is released.
        </p>
      )}
      {transitionPlan && indicators && records.length > 0 && (
        <ul className="argus-walk-talk" aria-label="Indicators by company">
          {records.map((r) => (
            <li key={r.company_id}>
              {r.name}: {walkTalkLine(r, indicators)}
            </li>
          ))}
        </ul>
      )}
      <div className="table-wrap">
        <table className="data-table stack-on-phone" aria-label="Extracted values">
          <thead>
            <tr>
              <th scope="col">Company</th>
              <th scope="col">Field</th>
              <th scope="col">Period</th>
              <th scope="col">Value</th>
              <th scope="col">Source</th>
              <th scope="col">Decision</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={`${r.runId}/${r.key}`} className={r.item ? "argus-row-await" : undefined}>
                <td data-label="Company">
                  {r.company}
                  {r.kept && <span className="xbrl-sub">kept from the extraction of {r.kept}</span>}
                </td>
                <td data-label="Field">
                  {question.get(r.field) ? <span>{question.get(r.field)} <span className="mono muted">{r.field}</span></span> : r.field}
                </td>
                <td data-label="Period" className="argus-period">{periodText(r.period)}</td>
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
                      runId={r.runId}
                      itemKey={r.key}
                      item={r.item}
                      onDone={() => void load()}
                      onOpenSource={setSource}
                      labels={r.companyLevel ? undefined : r.accepted !== undefined ? CONFLICT_LABELS : r.notFound ? NOT_FOUND_LABELS : VALUE_LABELS}
                      choices={r.companyLevel ? undefined : r.accepted !== undefined ? ["reject", "approve"]
                        : r.notFound ? ["approve", "correct"] : ["approve", "correct", "reject"]}
                    />
                  ) : decisions[r.runId]?.[r.key] ? decisionLabel(decisions[r.runId][r.key]) : "No review needed"}
                  {r.walkthrough && <WalkthroughLink href={r.walkthrough} label={`How was ${r.field}${r.period ? ` ${r.period}` : ""} for ${r.company} found?`} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && (flow.schema_choice?.kind === "profile" ? (
        <p className="muted">
          This profile's values are not listed here. <a href={`#/review/${flow.schema_choice.profile}/${runId}`}>Open them in the Review Queue</a> or download the CSV.
        </p>
      ) : (
        <p className="muted">{mineOnly ? "Nothing waits on you in this run." : "This run has no values yet."}</p>
      ))}
      {source && <SourcePanel source={source} onClose={() => setSource(null)} />}
      {choice?.kind === "schema" && <RunScoringPanel runId={runId} runType="extraction" fieldNames={schema?.fields.map((f) => f.name)} />}
    </section>
  );
}
