import { useEffect, useId, useState } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import {
  TAXONOMIES,
  ariaSort,
  formatFactValue,
  nextSort,
  periodLabel,
  rangeLabel,
  secFilingUrl,
  type SortState,
} from "../lib/xbrlTags";
import type { XbrlFact, XbrlPivot } from "../types";
import { StepTabs } from "./StepTabs";

const PAGE = 50; // the API caps a page at 500
const FORMS = ["10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F", "8-K", "ESEF"];
const VIEWS = [
  { id: "flat", label: "Flat" },
  { id: "year", label: "By year" },
];
const SORT_LABEL: Record<string, string> = { concept: "tag", period_end: "period end", value: "value", form: "form", filed: "filing date" };
const msg = (err: unknown) => (err as Error).message;

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** "21–40 of 1,234" with Previous and Next; the buttons only appear when there is more than one page. */
export function Pager(p: { offset: number; count: number; total: number; limit: number; noun: string; onPage: (offset: number) => void }) {
  return (
    <div className="toolbar xbrl-pager">
      <span className="mono" aria-label={`Showing ${rangeLabel(p.offset, p.count, p.total)} ${p.noun}`}>
        {rangeLabel(p.offset, p.count, p.total)}
      </span>
      {p.total > p.limit && (
        <>
          <button type="button" className="secondary" disabled={p.offset === 0} onClick={() => p.onPage(Math.max(0, p.offset - p.limit))}>
            Previous
          </button>
          <button type="button" className="secondary" disabled={p.offset + p.count >= p.total} onClick={() => p.onPage(p.offset + p.limit)}>
            Next
          </button>
        </>
      )}
    </div>
  );
}

function SortIcon({ dir }: { dir: "ascending" | "descending" | "none" }) {
  return (
    <svg className="xbrl-sort-icon" width="10" height="12" viewBox="0 0 10 12" aria-hidden="true">
      <path d="M1 4.5 5 1l4 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" opacity={dir === "descending" ? 0.3 : 1} />
      <path d="M1 7.5 5 11l4-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" opacity={dir === "ascending" ? 0.3 : 1} />
    </svg>
  );
}

/** A tag id that may only break after the colon and between the words of the concept, never mid-word. */
export function TagId({ id }: { id: string }) {
  const [prefix, concept = ""] = id.split(/:(.*)/s);
  return (
    <>
      <span className="xbrl-nowrap">{prefix}:</span>
      {concept.split(/(?=[A-Z][a-z])/).map((part, i) => (
        <span key={i}>
          <wbr />
          {part}
        </span>
      ))}
    </>
  );
}

function TagCell({ label, tagId, unit }: { label: string | null; tagId: string; unit?: string }) {
  return (
    <th scope="row" className="xbrl-tag-cell">
      <span className="xbrl-name">{label || tagId}</span>
      <span className="xbrl-sub mono">
        <TagId id={tagId} />
        {unit && <span className="xbrl-unit">{unit}</span>}
      </span>
    </th>
  );
}

/** One company's facts: a flat table of every fact, or annual values by period-end year. Filters, sorting and paging run on the server. */
export function XbrlFactsTable({ cik }: { cik: string }) {
  const id = useId();
  const [view, setView] = useState("flat");
  const [q, setQ] = useState("");
  const [taxonomy, setTaxonomy] = useState("");
  const [form, setForm] = useState("");
  const [year, setYear] = useState("");
  const [annual, setAnnual] = useState(false);
  const [sort, setSort] = useState<SortState>({ key: "period_end", order: "desc" });
  const [flat, setFlat] = useState<{ items: XbrlFact[]; total: number } | null>(null);
  const [pivot, setPivot] = useState<XbrlPivot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const dq = useDebounced(q.trim());
  const dform = useDebounced(form.trim().toUpperCase());
  const dyear = useDebounced(year.trim());
  const yearValid = dyear === "" || /^\d{4}$/.test(dyear);

  // Any filter, sort or view change starts again at the first page, without an extra request.
  const filterKey = JSON.stringify([view, dq, taxonomy, dform, dyear, annual, sort]);
  const [page, setPage] = useState({ key: filterKey, offset: 0 });
  const offset = page.key === filterKey ? page.offset : 0;
  const goTo = (o: number) => setPage({ key: filterKey, offset: o });

  useEffect(() => {
    let live = true; // only the newest request may write results
    setLoading(true);
    const common = { q: dq || undefined, taxonomy: taxonomy || undefined, offset, limit: PAGE };
    const done = (total: number, count: number, noun: string) => {
      setError(null);
      announce(total ? `${noun} ${rangeLabel(offset, count, total)}` : `No ${noun.toLowerCase()} match these filters`);
    };
    const req =
      view === "flat"
        ? api
            .getXbrlFacts(cik, {
              ...common,
              form: dform || undefined,
              period_year: yearValid && dyear ? Number(dyear) : undefined,
              annual_only: annual,
              sort: sort.key,
              order: sort.order,
            })
            .then((res) => live && (setFlat(res), done(res.total, res.items.length, "Facts")))
        : api.getXbrlPivot(cik, common).then((res) => live && (setPivot(res), done(res.total, res.rows.length, "Rows")));
    req
      .catch((err) => {
        if (!live) return;
        setError(msg(err));
        announce("Facts could not be loaded");
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [cik, view, dq, taxonomy, dform, dyear, yearValid, annual, sort, offset, retry]);

  const sortHeader = (key: string, label: string, className?: string) => (
    <th scope="col" aria-sort={ariaSort(sort, key)} className={className}>
      <button type="button" className="xbrl-sort" onClick={() => setSort(nextSort(sort, key))}>
        {label}
        <SortIcon dir={ariaSort(sort, key)} />
      </button>
    </th>
  );
  const status = loading ? <p className="muted xbrl-status">Loading…</p> : null;
  const failed = error && (
    <p className="error-text">
      Facts could not be loaded ({error}).{" "}
      <button type="button" className="link-button" onClick={() => setRetry((n) => n + 1)}>
        Try again
      </button>
    </p>
  );

  return (
    <div className="xbrl-facts">
      <StepTabs label="Facts view" tabs={VIEWS} active={view} onSelect={setView} />
      <div role="tabpanel" aria-label={view === "flat" ? "Flat table" : "By-year table"}>
        <div className="xbrl-filters">
          <label className="field-label xbrl-filter-wide">
            Search label or tag
            <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. revenue" />
          </label>
          <label className="field-label">
            Taxonomy
            <select value={taxonomy} onChange={(e) => setTaxonomy(e.target.value)}>
              <option value="">All taxonomies</option>
              {TAXONOMIES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          {view === "flat" && (
            <>
              <label className="field-label">
                Form
                <input type="text" list={`${id}-forms`} value={form} onChange={(e) => setForm(e.target.value)} placeholder="Any form" />
                <datalist id={`${id}-forms`}>
                  {FORMS.map((f) => (
                    <option key={f} value={f} />
                  ))}
                </datalist>
              </label>
              <label className="field-label">
                Period-end year
                <input
                  type="text"
                  inputMode="numeric"
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  placeholder="Any year"
                  aria-invalid={!yearValid || undefined}
                  aria-describedby={yearValid ? undefined : `${id}-year-error`}
                />
                {!yearValid && (
                  <span className="error-text xbrl-field-error" id={`${id}-year-error`}>
                    Enter a four-digit year, e.g. 2024.
                  </span>
                )}
              </label>
              <label className="checkbox-label xbrl-filter-check">
                <input type="checkbox" checked={annual} onChange={(e) => setAnnual(e.target.checked)} />
                Annual facts only
              </label>
            </>
          )}
        </div>
        {failed}

        {view === "flat" && flat && (
          <>
            <p className="help-text xbrl-note" id={`${id}-flat-note`}>
              Every fact as filed, sorted by {SORT_LABEL[sort.key]}, {sort.order === "asc" ? "ascending" : "descending"}. Values are
              shown as filed, with their unit.
            </p>
            <div className="table-wrap xbrl-table-wrap" tabIndex={0} role="region" aria-label="Facts, flat table">
              <table className="data-table xbrl-table" aria-busy={loading} aria-describedby={`${id}-flat-note`}>
                <caption className="visually-hidden">Facts, one row per fact</caption>
                <thead>
                  <tr>
                    {sortHeader("concept", "Tag")}
                    {sortHeader("period_end", "Period")}
                    <th scope="col">Fiscal</th>
                    {sortHeader("value", "Value", "num")}
                    <th scope="col">Unit</th>
                    {sortHeader("form", "Form")}
                    {sortHeader("filed", "Filed")}
                    <th scope="col">Accession</th>
                  </tr>
                </thead>
                <tbody>
                  {flat.items.length === 0 && (
                    <tr>
                      <td colSpan={8} className="muted">No facts match these filters.</td>
                    </tr>
                  )}
                  {flat.items.map((f, i) => (
                    <tr key={`${f.taxonomy}:${f.concept}|${f.unit}|${f.period_start}|${f.period_end}|${f.accession}|${i}`}>
                      <TagCell label={f.label} tagId={`${f.taxonomy}:${f.concept}`} />
                      <td className="mono">{periodLabel(f.period_start, f.period_end)}</td>
                      <td className="mono">{[f.fiscal_year, f.fiscal_period].filter(Boolean).join(" ") || "–"}</td>
                      <td className="num mono">{formatFactValue(f.value, f.unit)}</td>
                      <td className="mono xbrl-unit-col">{f.unit}</td>
                      <td className="mono">{f.form}</td>
                      <td className="mono">{f.filed ?? "–"}</td>
                      <td className="mono">
                        {f.accession && f.market === "esef" ? (
                          f.accession
                        ) : f.accession ? (
                          <a href={secFilingUrl(f.cik, f.accession)} target="_blank" rel="noopener noreferrer">
                            {f.accession}
                            <span className="visually-hidden"> (filing on SEC.gov, opens in a new tab)</span>
                          </a>
                        ) : (
                          "–"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {status}
            <Pager offset={offset} count={flat.items.length} total={flat.total} limit={PAGE} noun="facts" onPage={goTo} />
          </>
        )}

        {view === "year" && pivot && (
          <>
            <p className="help-text xbrl-note" id={`${id}-year-note`}>
              Annual facts only. Columns are the calendar year in which each period ends, newest first. Where a period was
              reported more than once, the latest filed value is shown.
            </p>
            <div className="table-wrap xbrl-table-wrap" tabIndex={0} role="region" aria-label="Facts by year, scrolls sideways">
              <table className="data-table xbrl-table xbrl-pivot" aria-busy={loading} aria-describedby={`${id}-year-note`}>
                <caption className="visually-hidden">Annual facts by period-end year, one row per tag and unit</caption>
                <thead>
                  <tr>
                    <th scope="col">Tag and unit</th>
                    {pivot.years.map((y) => (
                      <th scope="col" key={y} className="num">
                        {y}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {pivot.rows.length === 0 && (
                    <tr>
                      <td colSpan={pivot.years.length + 1} className="muted">No annual facts match these filters.</td>
                    </tr>
                  )}
                  {pivot.rows.map((r) => (
                    <tr key={`${r.tag_id}|${r.unit}`}>
                      <TagCell label={r.label} tagId={r.tag_id} unit={r.unit} />
                      {pivot.years.map((y) => {
                        const v = r.values[y];
                        return v == null ? (
                          <td key={y} className="num xbrl-gap">
                            <span aria-hidden="true">–</span>
                            <span className="visually-hidden">no value</span>
                          </td>
                        ) : (
                          <td key={y} className="num mono">
                            {formatFactValue(v, r.unit)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {status}
            <Pager offset={offset} count={pivot.rows.length} total={pivot.total} limit={PAGE} noun="rows" onPage={goTo} />
          </>
        )}
        {((view === "flat" && !flat) || (view === "year" && !pivot)) && !error && status}
      </div>
    </div>
  );
}
